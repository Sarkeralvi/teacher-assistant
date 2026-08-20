from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    AuditLog,
    ExtractionRun,
    GradingDispatchRun,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    RubricExtractionCriterion,
)
from app.schemas import ReferenceExtractionConfirmationRequest
from app.services.document_extraction import (
    ExtractionProviderResult,
    apply_extraction_result,
    mark_extraction_run_failed,
)
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_reference_extraction import (
    LOCAL_REFERENCE_PROVIDER,
    LocalReferenceExtractor,
)

_ACTIVE_REFERENCE_STATUSES = {"queued", "running"}
_API_KEY_PATTERN = re.compile(r"(?i)(?:sk|key)-[A-Za-z0-9_-]+")


class ReferenceExtractionError(RuntimeError):
    pass


class ReferenceExtractionService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        phase_manager: LocalAiPhaseManager | None = None,
        extractor_factory: Any | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.phase_manager = phase_manager or LocalAiPhaseManager(settings=self.settings)
        self.extractor_factory = extractor_factory or (
            lambda: LocalReferenceExtractor(settings=self.settings)
        )

    def create(
        self,
        grading_run: GradingRun,
        *,
        teacher_id: int,
        expected_model: str,
    ) -> dict[str, Any]:
        self._assert_enabled(expected_model)
        if grading_run.mode != "custom_controlled":
            raise ReferenceExtractionError(
                "Bundled local extraction is available only for Custom Controlled runs"
            )
        if grading_run.reference_extraction_status in _ACTIVE_REFERENCE_STATUSES:
            raise ReferenceExtractionError("Reference extraction is already in progress")
        if not all(
            (
                grading_run.question_pdf_path,
                grading_run.solution_pdf_path,
                grading_run.rubric_pdf_path,
            )
        ):
            raise ReferenceExtractionError(
                "Upload the question, solution/model answer, and rubric PDFs first"
            )
        active_dispatch = self.db.scalar(
            select(GradingDispatchRun.id).where(
                GradingDispatchRun.status.in_(["queued", "running", "stopping"])
            )
        )
        if active_dispatch is not None:
            raise ReferenceExtractionError(
                "Wait for the active local grading dispatch to stop before extracting references"
            )

        paths = self._material_paths(grading_run)
        hashes = {name: _sha256(path) for name, path in paths.items()}
        question_run = ExtractionRun(
            assessment_id=grading_run.assessment_id,
            artifact_file_path=grading_run.question_pdf_path,
            original_filename=grading_run.question_pdf_name or "question.pdf",
            content_type="application/pdf",
            extraction_type="question_paper",
            provider=LOCAL_REFERENCE_PROVIDER,
            status="pending",
            blockers=[],
        )
        rubric_run = ExtractionRun(
            assessment_id=grading_run.assessment_id,
            artifact_file_path=grading_run.rubric_pdf_path,
            original_filename=grading_run.rubric_pdf_name or "rubric.pdf",
            content_type="application/pdf",
            extraction_type="rubric",
            provider=LOCAL_REFERENCE_PROVIDER,
            status="pending",
            blockers=[],
        )
        self.db.add_all((question_run, rubric_run))
        self.db.flush()

        grading_run.materials_confirmed_at = datetime.now(UTC)
        grading_run.questions_confirmed_at = None
        grading_run.rubrics_confirmed_at = None
        grading_run.reference_extraction_status = "queued"
        grading_run.reference_extraction_stage = "queued"
        grading_run.reference_extraction_error = None
        grading_run.reference_extraction_warnings = []
        grading_run.reference_material_hashes = hashes
        grading_run.reference_question_run_id = question_run.id
        grading_run.reference_rubric_run_id = rubric_run.id
        grading_run.reference_ocr_call_count = 0
        grading_run.reference_qwen_call_count = 0
        grading_run.reference_extraction_started_at = None
        grading_run.reference_extraction_completed_at = None
        self._audit(
            grading_run,
            "reference_extraction_requested",
            actor_type="teacher",
            actor_id=teacher_id,
            payload={"material_hashes": hashes, "draft_only": True},
        )
        self.db.commit()
        self.db.refresh(grading_run)
        return self.serialize(grading_run)

    def mark_enqueue_failed(self, grading_run_id: int) -> None:
        grading_run = self.db.get(GradingRun, grading_run_id)
        if grading_run is None or grading_run.reference_extraction_status != "queued":
            return
        self._mark_failed(grading_run, "Reference extraction could not be queued")
        self.db.commit()

    def run(self, grading_run_id: int) -> None:
        grading_run = self.db.get(GradingRun, grading_run_id)
        if grading_run is None or grading_run.reference_extraction_status != "queued":
            return
        grading_run.reference_extraction_status = "running"
        grading_run.reference_extraction_stage = "validating_materials"
        grading_run.reference_extraction_started_at = datetime.now(UTC)
        self._audit(
            grading_run,
            "reference_extraction_started",
            actor_type="worker",
            payload={"material_hashes": grading_run.reference_material_hashes},
        )
        self.db.commit()

        try:
            self._assert_enabled(self.settings.local_qwen38_model)
            paths = self._material_paths(grading_run)
            self._assert_material_hashes(grading_run, paths)
            self._set_stage(grading_run, "rendering_reference_pages")
            extractor = self.extractor_factory()
            documents: dict[str, list[tuple[bytes, str, int]]] = {}
            name_map = {"question_paper": "QUESTION", "solution": "SOLUTION", "rubric": "RUBRIC"}
            total_pages = 0
            for source_name, document_name in name_map.items():
                rendered = extractor.render_pages(paths[source_name], "application/pdf")
                total_pages += len(rendered)
                if total_pages > self.settings.local_qwen38_max_visual_calls:
                    raise ReferenceExtractionError(
                        "Reference pages exceed the authorized visual call limit"
                    )
                documents[document_name] = [
                    (image_bytes, mime_type, page_no)
                    for page_no, image_bytes, mime_type in rendered
                ]
            grading_run.reference_ocr_call_count = total_pages
            self._set_stage(grading_run, "qwen38_visual_reference_extraction")
            if self.settings.local_ai_phase_switch_enabled:
                self.phase_manager.switch("Qwen38")
            provider_result = extractor.extract_reference_bundle(documents)
            grading_run.reference_qwen_call_count = 1
            self._assert_material_hashes(grading_run, paths)
            self._apply_provider_result(grading_run, provider_result)
            grading_run.reference_extraction_status = "succeeded"
            grading_run.reference_extraction_stage = "teacher_review_required"
            grading_run.reference_extraction_warnings = list(provider_result.get("warnings") or [])
            grading_run.reference_extraction_completed_at = datetime.now(UTC)
            self._audit(
                grading_run,
                "reference_extraction_succeeded",
                actor_type="worker",
                payload={"visual_page_count": total_pages, "qwen_call_count": 1},
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            grading_run = self.db.get(GradingRun, grading_run_id)
            if grading_run is not None:
                self._mark_failed(grading_run, str(exc))
                self.db.commit()

    def confirm(
        self,
        grading_run: GradingRun,
        *,
        teacher_id: int,
        request: ReferenceExtractionConfirmationRequest,
    ) -> None:
        if grading_run.reference_extraction_status != "succeeded":
            raise ReferenceExtractionError(
                "Reference drafts must finish successfully before teacher confirmation"
            )
        paths = self._material_paths(grading_run)
        self._assert_material_hashes(grading_run, paths)
        if (
            grading_run.reference_question_run_id is None
            or grading_run.reference_rubric_run_id is None
        ):
            raise ReferenceExtractionError("Reference extraction records are incomplete")

        nodes = list(
            self.db.scalars(
                select(QuestionNode)
                .where(QuestionNode.extraction_run_id == grading_run.reference_question_run_id)
                .where(QuestionNode.node_type.in_(["question", "subquestion"]))
                .order_by(QuestionNode.id)
            ).all()
        )
        criteria = list(
            self.db.scalars(
                select(RubricExtractionCriterion)
                .where(
                    RubricExtractionCriterion.extraction_run_id
                    == grading_run.reference_rubric_run_id
                )
                .order_by(RubricExtractionCriterion.id)
            ).all()
        )
        if {node.id for node in nodes} != {item.id for item in request.questions}:
            raise ReferenceExtractionError("Confirm every extracted question draft exactly once")
        requested_criterion_ids = {
            criterion.id for item in request.questions for criterion in item.criteria
        }
        if {criterion.id for criterion in criteria} != requested_criterion_ids:
            raise ReferenceExtractionError("Confirm every extracted rubric criterion exactly once")

        nodes_by_id = {node.id: node for node in nodes}
        criteria_by_id = {criterion.id: criterion for criterion in criteria}
        for draft in request.questions:
            node = nodes_by_id[draft.id]
            question_no = draft.question_number.strip()
            node.question_number = question_no
            node.label = question_no
            node.text = draft.question_text.strip()
            node.marks = draft.total_marks
            node.teacher_confirmed = True
            source_reference = dict(node.source_reference or {})
            source_reference["model_answer_draft"] = draft.model_answer.strip()
            source_reference["teacher_confirmed"] = True
            node.source_reference = source_reference

            question = self.db.scalar(
                select(Question).where(
                    Question.assessment_id == grading_run.assessment_id,
                    Question.question_no == question_no,
                )
            )
            if question is None:
                question = Question(
                    assessment_id=grading_run.assessment_id,
                    question_no=question_no,
                    question_text=draft.question_text.strip(),
                    model_answer=draft.model_answer.strip(),
                    total_marks=draft.total_marks,
                )
                self.db.add(question)
                self.db.flush()
            else:
                question.question_text = draft.question_text.strip()
                question.model_answer = draft.model_answer.strip()
                question.total_marks = draft.total_marks

            existing_rubrics = list(
                self.db.scalars(select(Rubric).where(Rubric.question_id == question.id)).all()
            )
            for existing in existing_rubrics:
                existing.is_active = False
            next_version = max((item.version for item in existing_rubrics), default=0) + 1
            rubric_json = {
                "total_marks": str(draft.total_marks),
                "criteria": [
                    {
                        "id": f"criterion-{index}",
                        "name": criterion.criterion_label.strip(),
                        "description": criterion.description.strip(),
                        "max_marks": str(criterion.max_marks),
                    }
                    for index, criterion in enumerate(draft.criteria, start=1)
                ],
            }
            self.db.add(
                Rubric(
                    question_id=question.id,
                    version=next_version,
                    rubric_json=rubric_json,
                    is_active=True,
                )
            )
            for confirmed_criterion in draft.criteria:
                criterion = criteria_by_id[confirmed_criterion.id]
                criterion.question_number = question_no
                criterion.criterion_label = confirmed_criterion.criterion_label.strip()
                criterion.description = confirmed_criterion.description.strip()
                criterion.max_marks = confirmed_criterion.max_marks
                criterion.blocker = None
                criterion.teacher_confirmed = True

        question_run = self.db.get(ExtractionRun, grading_run.reference_question_run_id)
        rubric_run = self.db.get(ExtractionRun, grading_run.reference_rubric_run_id)
        if question_run is not None:
            question_run.blockers = []
        if rubric_run is not None:
            rubric_run.blockers = []
        now = datetime.now(UTC)
        grading_run.questions_confirmed_at = now
        grading_run.rubrics_confirmed_at = now
        grading_run.status = "questions_ready"
        grading_run.reference_extraction_stage = "teacher_confirmed"
        self._audit(
            grading_run,
            "reference_extraction_teacher_confirmed",
            actor_type="teacher",
            actor_id=teacher_id,
            payload={
                "question_count": len(request.questions),
                "criterion_count": len(requested_criterion_ids),
                "material_hashes": grading_run.reference_material_hashes,
            },
        )
        self.db.commit()

    def serialize(self, grading_run: GradingRun) -> dict[str, Any]:
        nodes: list[QuestionNode] = []
        criteria: list[RubricExtractionCriterion] = []
        if grading_run.reference_question_run_id is not None:
            nodes = list(
                self.db.scalars(
                    select(QuestionNode)
                    .where(QuestionNode.extraction_run_id == grading_run.reference_question_run_id)
                    .where(QuestionNode.node_type.in_(["question", "subquestion"]))
                    .order_by(QuestionNode.id)
                ).all()
            )
        if grading_run.reference_rubric_run_id is not None:
            criteria = list(
                self.db.scalars(
                    select(RubricExtractionCriterion)
                    .where(
                        RubricExtractionCriterion.extraction_run_id
                        == grading_run.reference_rubric_run_id
                    )
                    .order_by(RubricExtractionCriterion.id)
                ).all()
            )
        grouped: dict[str, list[RubricExtractionCriterion]] = defaultdict(list)
        for criterion in criteria:
            if criterion.question_number:
                grouped[criterion.question_number].append(criterion)
        questions: list[dict[str, Any]] = []
        for node in nodes:
            source_reference = node.source_reference or {}
            questions.append(
                {
                    "id": node.id,
                    "question_number": node.question_number,
                    "question_text": node.text,
                    "model_answer": source_reference.get("model_answer_draft"),
                    "total_marks": node.marks,
                    "confidence": node.confidence,
                    "source_page": node.source_page,
                    "criteria": [
                        {
                            "id": criterion.id,
                            "question_number": criterion.question_number,
                            "criterion_label": criterion.criterion_label,
                            "description": criterion.description,
                            "max_marks": criterion.max_marks,
                            "confidence": criterion.confidence,
                            "blocker": criterion.blocker,
                        }
                        for criterion in grouped.get(node.question_number, [])
                    ],
                }
            )
        return {
            "grading_run_id": grading_run.id,
            "status": grading_run.reference_extraction_status,
            "stage": grading_run.reference_extraction_stage,
            "provider": LOCAL_REFERENCE_PROVIDER,
            "model": self.settings.local_qwen38_model,
            "ocr_device": "qwen38_gpu_single_slot",
            "question_run_id": grading_run.reference_question_run_id,
            "rubric_run_id": grading_run.reference_rubric_run_id,
            "ocr_call_count": grading_run.reference_ocr_call_count,
            "qwen_call_count": grading_run.reference_qwen_call_count,
            "warnings": grading_run.reference_extraction_warnings,
            "error": grading_run.reference_extraction_error,
            "questions": questions,
            "started_at": grading_run.reference_extraction_started_at,
            "completed_at": grading_run.reference_extraction_completed_at,
        }

    def _apply_provider_result(
        self, grading_run: GradingRun, provider_result: dict[str, Any]
    ) -> None:
        questions = provider_result.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ReferenceExtractionError("Local Qwen extracted no gradable questions")
        question_nodes: list[dict[str, Any]] = []
        rubric_criteria: list[dict[str, Any]] = []
        blockers: list[str] = []
        for item in questions:
            if not isinstance(item, dict):
                raise ReferenceExtractionError("Local Qwen returned an invalid question draft")
            question_number = str(item.get("question_number", "")).strip()
            item_blockers = [str(value) for value in item.get("blockers", [])]
            if item.get("marks") is None:
                item_blockers.append(f"{question_number}: total marks require teacher input")
            if not str(item.get("model_answer") or "").strip():
                item_blockers.append(f"{question_number}: model answer requires teacher input")
            criteria = item.get("criteria")
            if not isinstance(criteria, list) or not criteria:
                item_blockers.append(f"{question_number}: rubric criteria require teacher input")
                criteria = []
            blockers.extend(item_blockers)
            source_question_pages = item.get("source_question_pages") or []
            question_nodes.append(
                {
                    "question_number": question_number,
                    "parent_question_number": item.get("parent_question_number"),
                    "label": question_number,
                    "text": item.get("question_text"),
                    "marks": item.get("marks"),
                    "node_type": item.get("node_type", "question"),
                    "source_page": source_question_pages[0] if source_question_pages else None,
                    "source_reference": {
                        "source_text_excerpt": item.get("source_text_excerpt"),
                        "source_question_pages": source_question_pages,
                        "source_solution_pages": item.get("source_solution_pages", []),
                        "model_answer_draft": item.get("model_answer"),
                        "provider": LOCAL_REFERENCE_PROVIDER,
                        "teacher_review_required": True,
                    },
                    "confidence": item.get("confidence"),
                    "teacher_confirmed": False,
                }
            )
            for criterion in criteria:
                rubric_criteria.append(
                    {
                        "question_number": question_number,
                        "criterion_label": criterion.get("criterion_label"),
                        "description": criterion.get("description"),
                        "max_marks": criterion.get("max_marks"),
                        "confidence": criterion.get("confidence"),
                        "blocker": criterion.get("blocker"),
                        "teacher_confirmed": False,
                    }
                )
        if not rubric_criteria:
            raise ReferenceExtractionError("Local Qwen extracted no rubric criteria")

        question_run = self.db.get(ExtractionRun, grading_run.reference_question_run_id)
        rubric_run = self.db.get(ExtractionRun, grading_run.reference_rubric_run_id)
        if question_run is None or rubric_run is None:
            raise ReferenceExtractionError("Reference extraction records disappeared")
        raw = json.dumps(provider_result, ensure_ascii=False)
        apply_extraction_result(
            self.db,
            question_run,
            ExtractionProviderResult(
                raw_output=raw,
                normalized_output={
                    "question_nodes": question_nodes,
                    "blockers": list(dict.fromkeys(blockers)),
                },
                blockers=list(dict.fromkeys(blockers)),
            ),
        )
        apply_extraction_result(
            self.db,
            rubric_run,
            ExtractionProviderResult(
                raw_output=raw,
                normalized_output={"criteria": rubric_criteria, "blockers": []},
                blockers=[],
            ),
        )

    def _assert_enabled(self, expected_model: str) -> None:
        if not self.settings.brain_allow_real_providers:
            raise ReferenceExtractionError("Real local providers are safety-disabled")
        if not (
            self.settings.local_reference_extraction_enabled
            and self.settings.local_qwen38_visual_preparation_enabled
        ):
            raise ReferenceExtractionError("Qwen3.8 reference extraction is disabled")
        if not self.settings.local_qwen38_enabled:
            raise ReferenceExtractionError("Qwen3.8 must be enabled")
        if expected_model != self.settings.local_qwen38_model:
            raise ReferenceExtractionError("Expected Qwen model alias does not match configuration")

    def _material_paths(self, grading_run: GradingRun) -> dict[str, Path]:
        storage_root = Path(self.settings.local_storage_root).resolve()
        values = {
            "question_paper": grading_run.question_pdf_path,
            "solution": grading_run.solution_pdf_path,
            "rubric": grading_run.rubric_pdf_path,
        }
        paths: dict[str, Path] = {}
        for name, relative_path in values.items():
            if not relative_path:
                raise ReferenceExtractionError("A required reference PDF is missing")
            relative = Path(relative_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ReferenceExtractionError("A required reference PDF is unavailable")
            path = (storage_root / relative).resolve()
            if path != storage_root and storage_root not in path.parents:
                raise ReferenceExtractionError("A required reference PDF is unavailable")
            if not path.is_file():
                raise ReferenceExtractionError("A required reference PDF is unavailable")
            paths[name] = path
        return paths

    def _assert_material_hashes(self, grading_run: GradingRun, paths: dict[str, Path]) -> None:
        current = {name: _sha256(path) for name, path in paths.items()}
        if current != grading_run.reference_material_hashes:
            raise ReferenceExtractionError(
                "Reference materials changed after teacher authorization"
            )

    def _set_stage(self, grading_run: GradingRun, stage: str) -> None:
        grading_run.reference_extraction_stage = stage
        self.db.commit()

    def _mark_failed(self, grading_run: GradingRun, message: str) -> None:
        grading_run.reference_extraction_status = "failed"
        grading_run.reference_extraction_stage = "failed"
        grading_run.reference_extraction_error = message
        grading_run.reference_extraction_completed_at = datetime.now(UTC)
        for run_id in (
            grading_run.reference_question_run_id,
            grading_run.reference_rubric_run_id,
        ):
            extraction_run = self.db.get(ExtractionRun, run_id) if run_id else None
            if extraction_run is not None and extraction_run.status == "pending":
                mark_extraction_run_failed(extraction_run, message)
        self._audit(
            grading_run,
            "reference_extraction_failed",
            actor_type="worker",
            payload={
                "ocr_calls": grading_run.reference_ocr_call_count,
                "qwen_calls": grading_run.reference_qwen_call_count,
                "error_code": "reference_extraction_failed",
            },
        )

    def _audit(
        self,
        grading_run: GradingRun,
        event_type: str,
        *,
        actor_type: str,
        actor_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        safe_payload: dict[str, Any] = {
            "assessment_id": grading_run.assessment_id,
            "provider": LOCAL_REFERENCE_PROVIDER,
            "model": self.settings.local_qwen38_model,
        }
        if payload:
            safe_payload.update(payload)
        self.db.add(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=event_type,
                entity_type="grading_run",
                entity_id=grading_run.id,
                payload_json=safe_payload,
            )
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_error(error: Exception) -> str:
    if isinstance(error, ReferenceExtractionError):
        message = str(error)
    else:
        message = str(error) or "Reference extraction failed"
    message = _API_KEY_PATTERN.sub("[REDACTED]", message)
    if len(message) > 500:
        message = message[:500]
    return message
