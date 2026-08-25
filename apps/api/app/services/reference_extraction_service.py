from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    ReferencePageOcrRun,
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
from app.services.local_model_lease_service import LocalModelLeaseService
from app.services.local_ocr_client import LocalOcrClient
from app.services.local_reference_extraction import (
    LOCAL_REFERENCE_PROVIDER,
    LocalReferenceExtractor,
)
from packages.brain.adapter import BrainAdapter

_ACTIVE_REFERENCE_STATUSES = {"queued", "running"}
# A whole page needs more room than a single answer crop, but not dramatically:
# measured, the densest reference page (71 detected lines) transcribes in ~620
# tokens. This is headroom, not a workaround.
#
# An earlier value of 6000 was chosen for the wrong reason. The pipeline was
# failing with "cut off at the token cap", which looked like too small a budget
# but was actually the model looping on an ambiguous page. A repetition penalty
# fixed that at the provider; raising the budget would only have bought more
# looping before the same failure.
REFERENCE_PAGE_TRANSCRIBE_MAX_TOKENS = 3000
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
        ocr_client_factory: Any | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.phase_manager = phase_manager or LocalAiPhaseManager(
            settings=self.settings, db=self.db
        )
        self.extractor_factory = extractor_factory or (
            lambda: LocalReferenceExtractor(settings=self.settings)
        )
        self.ocr_client_factory = ocr_client_factory or (
            lambda: LocalOcrClient.from_settings(self.settings)
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
            self._assert_enabled(self.settings.local_qwen_model)
            paths = self._material_paths(grading_run)
            self._assert_material_hashes(grading_run, paths)
            self._set_stage(grading_run, "rendering_reference_pages")
            extractor = self.extractor_factory()
            documents: dict[str, list[tuple[bytes, str, int]]] = {}
            name_map = {"question_paper": "QUESTION", "solution": "SOLUTION", "rubric": "RUBRIC"}
            total_pages = 0
            # The rescued primary workflow always uses native PaddleOCR. Its
            # configured render DPI must not depend on the dormant RapidOCR
            # diagnostic flag; doing so silently reduced real Paddle input to
            # the legacy vision default whenever LOCAL_OCR_ENABLED was false.
            render_dpi = self.settings.local_ocr_render_dpi
            for source_name, document_name in name_map.items():
                rendered = extractor.render_pages(
                    paths[source_name], "application/pdf", target_dpi=render_dpi
                )
                total_pages += len(rendered)
                if total_pages > self.settings.local_reference_max_ocr_calls:
                    raise ReferenceExtractionError(
                        "Reference pages exceed the authorized PaddleOCR call limit"
                    )
                documents[document_name] = [
                    (image_bytes, mime_type, page_no)
                    for page_no, image_bytes, mime_type in rendered
                ]
            grading_run.reference_ocr_call_count = total_pages

            lease_holder_id = self._lease_holder_id(grading_run.id)
            provider_result = self._run_paddle_qwen36_extraction(
                grading_run,
                documents,
                render_dpi=render_dpi,
                lease_holder_id=lease_holder_id,
            )

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
                payload={
                    "paddle_ocr_page_count": total_pages,
                    "qwen_call_count": grading_run.reference_qwen_call_count,
                    "provider": "local_paddle_qwen",
                },
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            grading_run = self.db.get(GradingRun, grading_run_id)
            if grading_run is not None:
                self._mark_failed(grading_run, str(exc))
                self.db.commit()

    def _run_paddle_qwen36_extraction(
        self,
        grading_run: GradingRun,
        documents: dict[str, list[tuple[bytes, str, int]]],
        *,
        render_dpi: int,
        lease_holder_id: str,
    ) -> dict[str, Any]:
        """Read every reference page with Paddle, then correlate once with Qwen3.6."""

        role_by_document = {
            "QUESTION": "question_paper",
            "SOLUTION": "solution",
            "RUBRIC": "rubric",
        }
        text_documents: dict[str, list[dict[str, Any]]] = {
            "question_paper": [],
            "solution": [],
            "rubric": [],
        }
        self._set_stage(grading_run, "paddle_ocr_reference_pages")
        lease = LocalModelLeaseService(self.db)
        with lease.hold(
            model_phase="PaddleOcr",
            holder_kind="reference_extraction",
            holder_id=lease_holder_id,
        ):
            self._switch_phase("PaddleOcr", lease_holder_id=lease_holder_id)
            client = self.ocr_client_factory()
            client.health()
            call_count = 0
            for document_name, pages in documents.items():
                role = role_by_document[document_name]
                for image_bytes, mime_type, page_no in pages:
                    lease.heartbeat(holder_id=lease_holder_id)
                    result = client.ocr_image(
                        image_bytes=image_bytes,
                        content_type=mime_type,
                        request_id=f"reference-{grading_run.id}-{role}-{page_no}",
                        mode="document",
                    )
                    call_count += 1
                    lease.heartbeat(holder_id=lease_holder_id)
                    text_documents[role].append(
                        {
                            "page": page_no,
                            "text": result.normalized_text,
                            "markdown": result.markdown,
                            "blocks": [block.model_dump(mode="json") for block in result.blocks],
                        }
                    )
                    self._record_paddle_page_evidence(
                        grading_run,
                        document_role=role,
                        page_no=page_no,
                        image_bytes=image_bytes,
                        result=result,
                        render_dpi=render_dpi,
                    )
                    grading_run.reference_ocr_call_count = call_count
                    self.db.commit()

        self._set_stage(grading_run, "qwen36_reference_correlation")
        with lease.hold(
            model_phase="Qwen",
            holder_kind="reference_extraction",
            holder_id=lease_holder_id,
        ):
            self._switch_phase("Qwen", lease_holder_id=lease_holder_id)
            adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen")
            adapter.verify_available_model()
            lease.heartbeat(holder_id=lease_holder_id)
            result = adapter.provider.extract_reference_bundle_from_ocr_documents(
                documents=text_documents
            )
            lease.heartbeat(holder_id=lease_holder_id)
        grading_run.reference_qwen_call_count = 1
        result["warnings"] = list(result.get("warnings") or []) + [
            "Draft references were read by local PaddleOCR and correlated by Qwen3.6; "
            "teacher confirmation is required."
        ]
        return result

    def _record_paddle_page_evidence(
        self,
        grading_run: GradingRun,
        *,
        document_role: str,
        page_no: int,
        image_bytes: bytes,
        result: Any,
        render_dpi: int,
    ) -> None:
        existing = self.db.scalar(
            select(ReferencePageOcrRun).where(
                ReferencePageOcrRun.grading_run_id == grading_run.id,
                ReferencePageOcrRun.document_role == document_role,
                ReferencePageOcrRun.page_no == page_no,
            )
        )
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
        text = result.normalized_text
        self.db.add(
            ReferencePageOcrRun(
                grading_run_id=grading_run.id,
                document_role=document_role,
                page_no=page_no,
                render_dpi=render_dpi,
                page_image_sha256=hashlib.sha256(image_bytes).hexdigest(),
                engine="paddleocr_vl",
                engine_version=result.version,
                decision="tier1_accepted",
                reason_codes=["primary_local_paddle_workflow"],
                lines=[
                    {
                        "text": block.text,
                        "bbox": block.bbox,
                        "label": block.label,
                        "order": block.order,
                    }
                    for block in result.blocks
                ],
                escalated=False,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                latency_ms=result.latency_ms,
            )
        )
        self.db.flush()

    def _run_tiered_extraction(
        self,
        grading_run: GradingRun,
        documents: dict[str, list[tuple[bytes, str, int]]],
        *,
        render_dpi: int,
        lease_holder_id: str,
    ) -> dict[str, Any]:
        """Read cheaply first, spend the vision model only where OCR is unsure.

        Structured collect-then-execute so batching is enforced by shape rather
        than by convention: every page is read by tier-1 and every escalation
        decision is made BEFORE any model is loaded. Interleaving would cost a
        30-90 second model reload per page.
        """
        from packages.ocr.escalation import EscalationPolicy, evaluate_page
        from packages.ocr.rapidocr_engine import RapidOcrEngine

        self._set_stage(grading_run, "tier1_ocr")
        policy = EscalationPolicy(
            line_confidence_escalate_below=self.settings.local_ocr_confidence_escalate_below,
            uncovered_ink_escalate_above=self.settings.local_ocr_uncovered_ink_escalate_above,
        )
        engine = RapidOcrEngine()
        role_by_document = {
            "QUESTION": "question_paper",
            "SOLUTION": "solution",
            "RUBRIC": "rubric",
        }

        readings: dict[tuple[str, int], Any] = {}
        escalations: list[tuple[str, int]] = []
        for document_name, pages in documents.items():
            for image_bytes, _mime, page_no in pages:
                reading = engine.read_page(
                    image_bytes,
                    render_dpi=render_dpi,
                    page_width=0,
                    page_height=0,
                )
                # Declared, not inferred: a human marking a document hard is
                # auditable where a model inferring it is not. Rubric format
                # varies by teacher, so this is configurable rather than assumed.
                decision = evaluate_page(
                    reading,
                    policy=policy,
                    expect_handwritten=(
                        document_name == "RUBRIC"
                        and self.settings.local_ocr_treat_rubric_as_handwritten
                    ),
                )
                readings[(document_name, page_no)] = (reading, decision)
                self._record_page_evidence(
                    grading_run,
                    document_role=role_by_document[document_name],
                    page_no=page_no,
                    reading=reading,
                    decision=decision,
                    render_dpi=render_dpi,
                )
                if decision.escalated:
                    escalations.append((document_name, page_no))

        self._set_stage(grading_run, "evaluating_escalation")
        if len(escalations) > self.settings.local_reference_max_escalations:
            # A hard stop, never a silent degrade: exceeding the pre-authorized
            # budget means the teacher authorized less work than this needs.
            raise ReferenceExtractionError(
                f"{len(escalations)} reference pages need the vision model but only "
                f"{self.settings.local_reference_max_escalations} escalations were "
                "authorized. Re-run with a higher budget, or supply clearer pages."
            )

        text_documents: dict[str, list[dict[str, Any]]] = {
            "question_paper": [],
            "solution": [],
            "rubric": [],
        }
        lease = LocalModelLeaseService(self.db)
        lease_held = False
        try:
            if escalations:
                self._set_stage(grading_run, "qwen38_visual_escalation")
                lease.acquire(
                    model_phase="Qwen38",
                    holder_kind="reference_extraction",
                    holder_id=lease_holder_id,
                )
                lease_held = True
                self._switch_phase("Qwen38", lease_holder_id=lease_holder_id)
                adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen38")
                adapter.verify_available_model()
                provider = adapter.provider
                for document_name, page_no in escalations:
                    image_bytes = next(
                        data
                        for data, _mime, number in documents[document_name]
                        if number == page_no
                    )
                    transcribe = getattr(provider, "transcribe_image", None)
                    if transcribe is None:
                        raise ReferenceExtractionError(
                            "The configured vision provider cannot transcribe an escalated page"
                        )
                    lease.heartbeat(holder_id=lease_holder_id)
                    # A whole reference page carries far more text than the one
                    # answer crop the default budget was sized for. A real run
                    # hit that 2048-token cap and was cut off mid-JSON.
                    output = transcribe(
                        image_bytes=image_bytes,
                        mime_type="image/png",
                        label=f"{document_name} page {page_no}",
                        max_tokens=REFERENCE_PAGE_TRANSCRIBE_MAX_TOKENS,
                    )
                    lease.heartbeat(holder_id=lease_holder_id)
                    readings[(document_name, page_no)] = (output.draft_text, None)

            for document_name, pages in documents.items():
                role = role_by_document[document_name]
                for _image_bytes, _mime, page_no in pages:
                    value = readings[(document_name, page_no)]
                    text = value[0] if isinstance(value[0], str) else value[0].text
                    text_documents[role].append({"page": page_no, "text": text})

            self._set_stage(grading_run, "qwen36_reference_mapping")
            lease.acquire(
                model_phase="Qwen",
                holder_kind="reference_extraction",
                holder_id=lease_holder_id,
            )
            lease_held = True
            self._switch_phase("Qwen", lease_holder_id=lease_holder_id)
            text_adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen")
            text_adapter.verify_available_model()
            lease.heartbeat(holder_id=lease_holder_id)
            result = text_adapter.provider.extract_reference_bundle_from_ocr_documents(
                documents=text_documents
            )
            lease.heartbeat(holder_id=lease_holder_id)
            grading_run.reference_qwen_call_count = 1
            warnings = list(result.get("warnings") or [])
            if escalations:
                warnings.append(
                    f"{len(escalations)} page(s) were read by the vision model because the "
                    "first-pass reader was not confident; check those drafts most closely."
                )
            result["warnings"] = warnings
            return result
        finally:
            if lease_held:
                lease.release(holder_id=lease_holder_id)

    def _switch_phase(self, phase: str, *, lease_holder_id: str) -> None:
        if self.settings.local_ai_phase_switch_enabled:
            self.phase_manager.switch(phase, lease_holder_id=lease_holder_id)

    @staticmethod
    def _lease_holder_id(grading_run_id: int) -> str:
        return f"reference_extraction:{grading_run_id}:{uuid4().hex}"

    def _record_page_evidence(
        self,
        grading_run: GradingRun,
        *,
        document_role: str,
        page_no: int,
        reading: Any,
        decision: Any,
        render_dpi: int,
    ) -> None:
        """Persist why this page was trusted or escalated.

        A confidence-gated decision is only auditable if the inputs to it are
        recorded, so this stores the engine, the exact image, the per-line
        scores and which triggers fired - not merely the outcome.
        """
        confidences = reading.confidences
        existing = self.db.scalar(
            select(ReferencePageOcrRun).where(
                ReferencePageOcrRun.grading_run_id == grading_run.id,
                ReferencePageOcrRun.document_role == document_role,
                ReferencePageOcrRun.page_no == page_no,
            )
        )
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
        self.db.add(
            ReferencePageOcrRun(
                grading_run_id=grading_run.id,
                document_role=document_role,
                page_no=page_no,
                render_dpi=render_dpi,
                page_image_sha256=reading.page_image_sha256,
                engine=reading.engine,
                engine_version=reading.engine_version,
                decision=decision.decision,
                reason_codes=list(decision.reason_codes),
                lines=[
                    {
                        "text": line.text,
                        "confidence": str(line.confidence) if line.confidence else None,
                        "bbox": list(line.bbox.as_tuple()) if line.bbox else None,
                    }
                    for line in reading.lines
                ],
                min_confidence=min(confidences) if confidences else None,
                mean_confidence=(
                    (sum(confidences) / len(confidences)) if confidences else None
                ),
                uncovered_ink_ratio=reading.uncovered_ink_ratio,
                escalated=decision.escalated,
                latency_ms=reading.latency_ms,
            )
        )
        self.db.flush()

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
            "model": self.settings.local_qwen_model,
            "ocr_device": "paddleocr_gpu_exclusive_phase",
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
        if not self.settings.local_reference_extraction_enabled:
            raise ReferenceExtractionError("Local reference extraction is disabled")
        if not self.settings.local_paddle_ocr_enabled:
            raise ReferenceExtractionError("Local PaddleOCR must be enabled")
        if not self.settings.local_qwen_enabled:
            raise ReferenceExtractionError("Local Qwen3.6 must be enabled")
        if expected_model != self.settings.local_qwen_model:
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
