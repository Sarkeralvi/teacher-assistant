"""Bounded real-provider smoke for the bulk-supervised production services.

This command is deliberately restricted to its own disposable
``teacher_assistant_bulk_smoke_test`` database.
It performs one synthetic mapping, one synthetic transcription, and one
text-only draft grading path. It never approves a grade.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    FinalGrade,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    User,
)
from app.services.bulk_evaluation_service import BulkEvaluationService


def _database_name() -> str:
    # Operator scripts load local configuration in their own PowerShell
    # process.  This Python smoke must read the same settings object so it
    # cannot accidentally fall back to a shell-global DATABASE_URL.
    return get_settings().database_url.rsplit("/", 1)[-1].split("?", 1)[0]


def _synthetic_archive() -> BytesIO:
    image = Image.new("RGB", (1400, 1900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("arial.ttf", 58)
    draw.text((120, 180), "1(a)", fill="black", font=font)
    draw.text((160, 340), "Paris is the capital of France.", fill="black", font=font)
    page = BytesIO()
    image.save(page, format="PNG")
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic-student/page1.png", page.getvalue())
    archive_bytes.seek(0)
    return archive_bytes


def main() -> int:
    if _database_name() != "teacher_assistant_bulk_smoke_test":
        raise RuntimeError(
            "Live bulk smoke refuses every database except "
            "teacher_assistant_bulk_smoke_test"
        )
    get_settings.cache_clear()
    settings = get_settings()
    unique = uuid4().hex[:10]
    with SessionLocal() as db:
        revision = db.execute(text("select version_num from alembic_version")).scalar_one()
        if revision != "0026_bulk_supervised_evaluation":
            raise RuntimeError("Disposable smoke database is not at migration head 0026")
        teacher = User(
            name="Bulk live smoke teacher",
            email=f"bulk-live-smoke-{unique}@example.invalid",
            password_hash="unused-live-smoke-password-hash",
            role="teacher",
        )
        db.add(teacher)
        db.flush()
        course = Course(
            teacher_id=teacher.id,
            code=f"BULK-{unique}",
            title="Bulk supervised live smoke",
            department="QA",
            semester="Synthetic",
        )
        db.add(course)
        db.flush()
        assessment = Assessment(
            course_id=course.id,
            title="Synthetic bulk smoke assessment",
            assessment_type="quiz",
            total_marks=Decimal("1.00"),
            status="ready",
        )
        db.add(assessment)
        db.flush()
        extraction = ExtractionRun(
            assessment_id=assessment.id,
            artifact_file_path="synthetic/reference.pdf",
            original_filename="synthetic-reference.pdf",
            content_type="application/pdf",
            extraction_type="question_paper",
            provider="mock",
            status="succeeded",
            normalized_output={},
            blockers=[],
        )
        db.add(extraction)
        db.flush()
        question = Question(
            assessment_id=assessment.id,
            question_no="1(a)",
            question_text="State the capital city of France.",
            model_answer="Paris.",
            total_marks=Decimal("1.00"),
        )
        db.add(question)
        db.flush()
        db.add(
            QuestionNode(
                assessment_id=assessment.id,
                extraction_run_id=extraction.id,
                question_number="1(a)",
                label="1(a)",
                text=question.question_text,
                marks=Decimal("1.00"),
                node_type="subquestion",
                source_page=1,
                source_reference={"synthetic": True},
                confidence=Decimal("1.0000"),
                teacher_confirmed=True,
            )
        )
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                is_active=True,
                rubric_json={
                    "total_marks": "1.00",
                    "criteria": [
                        {
                            "id": "capital",
                            "name": "Correct capital",
                            "description": "States Paris as France's capital.",
                            "max_marks": "1.00",
                        }
                    ],
                },
            )
        )
        now = datetime.now(UTC)
        grading_run = GradingRun(
            assessment_id=assessment.id,
            created_by_teacher_id=teacher.id,
            mode="bulk_supervised",
            status="grading_ready",
            marking_policy="general",
            materials_confirmed_at=now,
            questions_confirmed_at=now,
            rubrics_confirmed_at=now,
            reference_extraction_status="succeeded",
            reference_extraction_stage="complete",
            reference_material_hashes={"synthetic": "c" * 64},
        )
        db.add(grading_run)
        db.commit()

        upload = UploadFile(filename="synthetic-bulk-smoke.zip", file=_synthetic_archive())
        service = BulkEvaluationService(db, settings=settings)
        run = service.create_from_zip(
            assessment_id=assessment.id,
            grading_run=grading_run,
            teacher=teacher,
            upload=upload,
            expected_model=settings.local_qwen38_model,
            marking_policy="general",
            maximum_provider_calls=8,
        )
        for _ in range(12):
            if not service.run_next(run.id):
                break
        run = service.get_run(run.id)
        item = run.items[0]
        final_count = db.scalar(
            select(FinalGrade.id).where(
                FinalGrade.answer_region_id == item.answer_region_id
            )
        )
        raw_audits = json.dumps(
            [
                row.payload_json
                for row in db.scalars(
                    select(AuditLog).where(
                        AuditLog.entity_type == "bulk_evaluation_run",
                        AuditLog.entity_id == run.id,
                    )
                ).all()
            ],
            sort_keys=True,
        )
        summary = {
            "run_id": run.id,
            "status": run.status,
            "stage": run.stage,
            "calls_used": run.calls_used,
            "item_status": item.status,
            "mapping_present": item.mapping_id is not None,
            "transcription_present": item.transcription_run_id is not None,
            "draft_grade_present": item.grade_suggestion_id is not None,
            "final_grade_present": final_count is not None,
            "exception_codes": item.exception_codes,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        if "paris" in raw_audits.casefold():
            raise RuntimeError("Raw synthetic answer text leaked into bulk audit payloads")
        if final_count is not None:
            raise RuntimeError("Live smoke created a FinalGrade without teacher approval")
        if not (
            item.mapping_id
            and item.transcription_run_id
            and item.grade_suggestion_id
            and item.status == "graded"
            and run.status == "review_ready"
        ):
            raise RuntimeError("Live bulk smoke did not reach a clean review-required draft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
