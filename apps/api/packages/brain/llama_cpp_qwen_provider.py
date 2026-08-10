from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import (
    GradeSuggestionOutput,
    ModelPolicy,
    RubricBreakdownItem,
)


class QwenRubricBreakdownItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    criterion_status: Literal["met", "partially_met", "not_met"]
    max_marks: Decimal = Field(ge=Decimal("0"))
    awarded_marks: Decimal = Field(ge=Decimal("0"))
    reason: str = Field(min_length=1)
    evidence: str | None = None
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def awarded_marks_must_not_exceed_max(self) -> QwenRubricBreakdownItem:
        if self.awarded_marks > self.max_marks:
            raise ValueError("awarded_marks cannot exceed max_marks")
        return self


class QwenGradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]
    rubric_breakdown: list[QwenRubricBreakdownItem] = Field(min_length=1)
    detected_answer_summary: str = Field(min_length=1)
    major_errors: list[str]
    feedback_to_student: str = Field(min_length=1)
    review_flags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reconcile_score_with_breakdown(self) -> QwenGradePayload:
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        status_reconciled = False
        for item in self.rubric_breakdown:
            if item.criterion_status == "not_met" and item.awarded_marks != 0:
                item.awarded_marks = Decimal("0")
                item.confidence = min(item.confidence, Decimal("0.75"))
                status_reconciled = True
        if status_reconciled:
            self.confidence = min(self.confidence, Decimal("0.75"))
            if "criterion_status_reconciled" not in self.review_flags:
                self.review_flags.append("criterion_status_reconciled")
        total = sum((item.awarded_marks for item in self.rubric_breakdown), Decimal("0"))
        if total != self.score:
            # The criterion-level decisions are the auditable grading result.
            # llama.cpp's JSON grammar cannot express this cross-field sum, so
            # reconcile deterministically instead of issuing a second model
            # call.  Keep the inconsistency visible to the teacher and lower
            # confidence in the draft.
            self.score = total
            self.confidence = min(self.confidence, Decimal("0.75"))
            if "score_reconciled_from_breakdown" not in self.review_flags:
                self.review_flags.append("score_reconciled_from_breakdown")
        return self


class QwenQuestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1, max_length=64)
    parent_question_number: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    node_type: Literal["question", "subquestion", "instruction"]
    source_page: int = Field(ge=1)
    source_text_excerpt: str = Field(min_length=1, max_length=500)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]


class QwenQuestionExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QwenQuestionDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class QwenRubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str | None = Field(default=None, max_length=64)
    criterion_label: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    max_marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    blocker: str | None = None
    needs_review: Literal[True]


class QwenRubricExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[QwenRubricCriterion] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class QwenReferenceCriterionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    max_marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_rubric_pages: list[int] = Field(default_factory=list, max_length=5)
    blocker: str | None = Field(default=None, max_length=400)


class QwenReferenceQuestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1, max_length=32)
    parent_question_number: str | None = Field(default=None, max_length=32)
    node_type: Literal["question", "subquestion"]
    question_text: str = Field(min_length=1, max_length=1800)
    model_answer: str | None = Field(default=None, max_length=1800)
    marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    source_question_pages: list[int] = Field(min_length=1, max_length=5)
    source_solution_pages: list[int] = Field(default_factory=list, max_length=5)
    source_text_excerpt: str = Field(min_length=1, max_length=300)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    # A leaf is not actionable in the review screen without at least one
    # rubric row.  Do not let an omitted optional field silently turn into an
    # empty list: llama.cpp's JSON grammar will require this property and
    # Pydantic will reject an empty response before it reaches persistence.
    criteria: list[QwenReferenceCriterionDraft] = Field(min_length=1, max_length=8)
    blockers: list[str] = Field(default_factory=list, max_length=8)
    needs_review: Literal[True]


class QwenReferenceBundlePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QwenReferenceQuestionDraft] = Field(min_length=1, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def question_numbers_must_be_unique(self) -> QwenReferenceBundlePayload:
        numbers = [item.question_number.strip().casefold() for item in self.questions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("reference question numbers must be unique")
        for item in self.questions:
            criterion_marks = [criterion.max_marks for criterion in item.criteria]
            if not criterion_marks or any(mark is None for mark in criterion_marks):
                continue
            criterion_total = sum(
                (mark for mark in criterion_marks if mark is not None), Decimal("0")
            )
            if item.marks is None:
                # This is a deterministic copy of the complete rubric
                # allocation, not a model inference.  It keeps the editable
                # question draft internally consistent while teacher review is
                # still mandatory.
                item.marks = criterion_total
            elif item.marks != criterion_total:
                raise ValueError("reference question marks must equal the rubric criterion total")
        return self


class QwenAnswerBlockReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_no: int = Field(ge=1)
    block_orders: list[int] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def block_orders_must_be_unique(self) -> QwenAnswerBlockReference:
        if len(self.block_orders) != len(set(self.block_orders)):
            raise ValueError("answer block orders must be unique")
        return self


class QwenSubmissionAnswerMappingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: int = Field(gt=0)
    question_no: str = Field(min_length=1, max_length=32)
    status: Literal["mapped", "uncertain", "not_found"]
    block_references: list[QwenAnswerBlockReference] = Field(default_factory=list)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    warnings: list[str] = Field(default_factory=list, max_length=8)
    needs_review: Literal[True]

    @model_validator(mode="after")
    def mapped_answers_require_blocks(self) -> QwenSubmissionAnswerMappingDraft:
        if self.status in {"mapped", "uncertain"} and not self.block_references:
            raise ValueError("mapped or uncertain answers require OCR block references")
        if self.status == "not_found" and self.block_references:
            raise ValueError("not_found answers cannot contain OCR block references")
        return self


class QwenSubmissionAnswerMappingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[QwenSubmissionAnswerMappingDraft] = Field(min_length=1, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def question_ids_must_be_unique(self) -> QwenSubmissionAnswerMappingPayload:
        question_ids = [item.question_id for item in self.mappings]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("submission answer mapping question IDs must be unique")
        return self


class QwenPreparedStudentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: int = Field(gt=0)
    question_no: str = Field(min_length=1, max_length=32)
    status: Literal["prepared", "uncertain"]
    # Keep the JSON schema unbounded above: llama.cpp's grammar compiler rejects
    # a generated ``char{1,10000}`` repetition. The application validator below
    # still enforces the same storage/safety ceiling after generation.
    prepared_text: str = Field(min_length=1)
    alternative_prepared_texts: list[str] = Field(min_length=0, max_length=3)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    uncertainties: list[str] = Field(default_factory=list, max_length=12)
    source_candidate_ids: list[str] = Field(min_length=1, max_length=40)
    transcription_complete: Literal[True]
    needs_review: Literal[True]

    @model_validator(mode="after")
    def candidate_ids_must_be_unique(self) -> QwenPreparedStudentAnswer:
        if len(self.prepared_text) > 10000:
            raise ValueError("prepared answer text exceeds the application limit")
        if any(len(item) > 10000 for item in self.alternative_prepared_texts):
            raise ValueError("alternative prepared answer text exceeds the application limit")
        normalized_alternatives = [item.strip() for item in self.alternative_prepared_texts]
        if any(not item for item in normalized_alternatives):
            raise ValueError("alternative prepared answer text cannot be empty")
        if len(normalized_alternatives) != len(set(normalized_alternatives)):
            raise ValueError("alternative prepared answer texts must be unique")
        if self.prepared_text.strip() in set(normalized_alternatives):
            raise ValueError("alternative prepared answer text must differ from the primary")
        if len(self.source_candidate_ids) != len(set(self.source_candidate_ids)):
            raise ValueError("prepared answer candidate IDs must be unique")
        return self


class QwenPreparedStudentAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[QwenPreparedStudentAnswer] = Field(min_length=1, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def question_ids_must_be_unique(self) -> QwenPreparedStudentAnswerPayload:
        question_ids = [item.question_id for item in self.answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("prepared answer question IDs must be unique")
        return self


_API_KEY_PATTERN = re.compile(r"(?:sk|key)-[A-Za-z0-9_\-]+", re.IGNORECASE)
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", re.IGNORECASE)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
# A grading suggestion is deliberately concise.  Bound generation so an
# unavailable or rambling local model cannot occupy the single Qwen slot
# indefinitely; the strict schema still requires a complete rubric breakdown.
_GRADE_MAX_TOKENS = 1600


class LlamaCppQwenProvider(BrainProvider):
    """Text-only Qwen provider behind llama.cpp's OpenAI-compatible API."""

    provider_name = "llama_cpp_qwen"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout_seconds: float = 180.0,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("LOCAL_QWEN_API_KEY is required")
        if not model_name:
            raise ValueError("LOCAL_QWEN_MODEL is required")
        parsed_url = urlparse(base_url)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname not in _LOOPBACK_HOSTS
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("LOCAL_QWEN_BASE_URL must use HTTP on a loopback host")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/") + "/"
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            trust_env=False,
        )
        self._model_verified = False

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del answer_image_path, task_name, model_policy, image_data_url, marking_policy
        if not (student_answer_text or "").strip():
            raise ValueError("Teacher-confirmed student answer text is required")
        payload, usage = self._structured_completion(
            messages=messages or [],
            response_model=QwenGradePayload,
            schema_name="grade_suggestion",
            max_tokens=_GRADE_MAX_TOKENS,
        )
        assert isinstance(payload, QwenGradePayload)
        self._remove_unsupported_criterion_credit(payload, student_answer_text)
        self._enforce_rubric_dependencies(payload, rubric_json)
        self._validate_grade_contract(payload, question_total_marks, rubric_json)
        flags = list(payload.review_flags)
        for flag in (
            "teacher_review_required",
            "image_input_disabled",
            "local_provider",
        ):
            if flag not in flags:
                flags.append(flag)
        return GradeSuggestionOutput(
            score=payload.score,
            max_score=payload.max_score,
            confidence=payload.confidence,
            needs_review=True,
            rubric_breakdown=[
                RubricBreakdownItem.model_validate(item.model_dump(exclude={"criterion_status"}))
                for item in payload.rubric_breakdown
            ],
            detected_answer_summary=payload.detected_answer_summary,
            major_errors=payload.major_errors,
            feedback_to_student=payload.feedback_to_student,
            review_flags=flags,
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=Decimal("0"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

    def _remove_unsupported_criterion_credit(
        self, payload: QwenGradePayload, student_answer_text: str
    ) -> None:
        changed = False
        for item in payload.rubric_breakdown:
            if item.awarded_marks <= 0:
                continue
            if _evidence_is_verbatim_student_text(item.evidence, student_answer_text):
                continue
            item.awarded_marks = Decimal("0")
            item.confidence = min(item.confidence, Decimal("0.75"))
            changed = True
        if not changed:
            return
        payload.score = sum((item.awarded_marks for item in payload.rubric_breakdown), Decimal("0"))
        payload.confidence = min(payload.confidence, Decimal("0.75"))
        if "unsupported_criterion_evidence_removed" not in payload.review_flags:
            payload.review_flags.append("unsupported_criterion_evidence_removed")

    def _enforce_rubric_dependencies(
        self, payload: QwenGradePayload, rubric_json: dict[str, Any]
    ) -> None:
        criteria = rubric_json.get("criteria")
        if not isinstance(criteria, list):
            return
        requirements = {
            str(criterion.get("id")): tuple(
                str(dependency_id) for dependency_id in criterion.get("depends_on", [])
            )
            for criterion in criteria
            if isinstance(criterion, dict)
            and criterion.get("id") is not None
            and not bool(criterion.get("allow_follow_through", False))
        }
        breakdown = {item.criterion_id: item for item in payload.rubric_breakdown}
        changed = False
        pending = True
        while pending:
            pending = False
            for criterion_id, dependency_ids in requirements.items():
                item = breakdown.get(criterion_id)
                if item is None or item.awarded_marks <= 0 or not dependency_ids:
                    continue
                prerequisites_met = all(
                    dependency_id in breakdown
                    and breakdown[dependency_id].awarded_marks == breakdown[dependency_id].max_marks
                    for dependency_id in dependency_ids
                )
                if prerequisites_met:
                    continue
                item.awarded_marks = Decimal("0")
                item.confidence = min(item.confidence, Decimal("0.75"))
                changed = True
                pending = True
        if not changed:
            return
        payload.score = sum((item.awarded_marks for item in payload.rubric_breakdown), Decimal("0"))
        payload.confidence = min(payload.confidence, Decimal("0.75"))
        if "dependent_criterion_credit_removed" not in payload.review_flags:
            payload.review_flags.append("dependent_criterion_credit_removed")

    def extract_questions_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        context = self._ocr_context(pages)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract question structure from local OCR text. Use only supplied text. "
                    "Every item is a draft and needs_review must be true. Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract questions, subquestions, marks, model answers when explicitly "
                    "present, source pages, short source excerpts, confidence, and warnings. "
                    "Do not invent missing answers or marks.\n\n" + context
                ),
            },
        ]
        payload, _usage = self._structured_completion(
            messages=messages,
            response_model=QwenQuestionExtractionPayload,
            schema_name="question_extraction",
        )
        assert isinstance(payload, QwenQuestionExtractionPayload)
        return payload.model_dump(mode="json")

    def extract_rubric_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        context = self._ocr_context(pages)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract rubric criteria from local OCR text. Use only supplied text. "
                    "Every item is a draft and needs_review must be true. Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract criterion labels, descriptions, marks, question links, confidence, "
                    "blockers, and warnings. Do not invent missing marks.\n\n" + context
                ),
            },
        ]
        payload, _usage = self._structured_completion(
            messages=messages,
            response_model=QwenRubricExtractionPayload,
            schema_name="rubric_extraction",
        )
        assert isinstance(payload, QwenRubricExtractionPayload)
        return payload.model_dump(mode="json")

    def extract_reference_bundle_from_ocr_documents(
        self, documents: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        context = self._ocr_document_context(documents)
        question_hints = _reference_question_number_hints(documents)
        structure_instruction = ""
        if question_hints:
            structure_instruction = (
                " A deterministic structure scan found these gradable leaf labels: "
                + ", ".join(question_hints)
                + ". Return each label exactly once and return no other question labels."
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "Link a question paper, its worked solution/model answer, and its "
                    "marking rubric from local OCR text. Use only supplied text. Preserve "
                    "question numbering and mathematics. Every output is an editable draft; "
                    "needs_review must be true. Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "For every gradable question or subquestion, extract the exact question "
                    "text, the matching model answer from SOLUTION, total marks, and matching "
                    "rubric criteria from RUBRIC. Include source page numbers and confidence. "
                    "Use blockers for missing, ambiguous, or unmatched material. Every leaf MUST "
                    "contain at least one criterion object. When the rubric wording cannot be "
                    "read or linked, use one explicit draft placeholder with a descriptive "
                    "criterion_label, max_marks null, and a blocker saying that the teacher must "
                    "supply or correct the rubric; do not invent marks. Otherwise extract the "
                    "actual rubric criterion. Create exactly one object per gradable leaf "
                    "part: when a parent has (i), (ii), or similar children, output the children "
                    "and do not also output the parent. Never duplicate a question number. "
                    "When a SOLUTION section names only a parent such as Question 1(a), map its "
                    "successive worked-answer blocks to that parent's leaf parts in question-paper "
                    "order and record the solution page on each leaf. When the RUBRIC includes a "
                    "[RUBRIC HANDWRITING FOCUS] section, prefer that structured reading for exact "
                    "leaf labels and mark allocations; use the full-page reading only as context. "
                    "For a single criterion row, its max_marks must equal the leaf marks. "
                    "Keep model answers and rubric descriptions concise while preserving "
                    "calculations. "
                    "Stop immediately after the last source question; never add filler entries."
                    + structure_instruction
                    + "\n\n"
                    + context
                ),
            },
        ]
        payload, usage = self._structured_completion(
            messages=messages,
            response_model=QwenReferenceBundlePayload,
            schema_name="reference_bundle_extraction",
            max_tokens=3500,
        )
        assert isinstance(payload, QwenReferenceBundlePayload)
        if question_hints:
            actual = [item.question_number.strip().casefold() for item in payload.questions]
            expected = [item.casefold() for item in question_hints]
            if actual != expected:
                raise ValueError(
                    "Local Qwen output did not match the detected source question structure"
                )
        result = payload.model_dump(mode="json")
        result["usage"] = usage
        return result

    def map_submission_answers_from_ocr_pages(
        self,
        *,
        pages: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not questions:
            raise ValueError("Finalized questions are required for answer mapping")
        page_context = _submission_ocr_block_context(pages)
        reference_context = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
        messages = [
            {
                "role": "system",
                "content": (
                    "Map OCR blocks from a student's complete answer script to finalized "
                    "question IDs. Use only supplied block IDs. Do not grade, transcribe, "
                    "rewrite, infer missing answer text, or create coordinates. Return every "
                    "finalized question exactly once. Every mapping needs teacher review."
                ),
            },
            {
                "role": "user",
                "content": (
                    "For each finalized question, select all and only the ordered OCR blocks "
                    "that belong to that student's answer, including continuation blocks on "
                    "later pages. Question labels may help locate boundaries. Use status "
                    "not_found with no blocks when there is no visible answer. Use uncertain "
                    "when a boundary or question link is ambiguous. Preserve exact question_id "
                    "and question_no values.\n\nFINALIZED REFERENCES\n"
                    + reference_context
                    + "\n\nSCRIPT OCR BLOCKS\n"
                    + page_context
                ),
            },
        ]
        payload, usage = self._structured_completion(
            messages=messages,
            response_model=QwenSubmissionAnswerMappingPayload,
            schema_name="submission_answer_mapping",
            max_tokens=2400,
        )
        assert isinstance(payload, QwenSubmissionAnswerMappingPayload)
        expected = {
            (int(question["question_id"]), str(question["question_no"]).strip())
            for question in questions
        }
        actual = {(item.question_id, item.question_no.strip()) for item in payload.mappings}
        if actual != expected:
            raise ValueError("Local Qwen changed or omitted finalized question references")
        result = payload.model_dump(mode="json")
        result["usage"] = usage
        return result

    def prepare_student_answers_from_ocr_candidates(
        self,
        *,
        answers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not answers:
            raise ValueError("OCR answer candidates are required")
        context = json.dumps(answers, ensure_ascii=False, separators=(",", ":"))
        messages = [
            {
                "role": "system",
                "content": (
                    "Prepare a faithful, complete student-answer transcription from multiple "
                    "local PaddleOCR readings. This is evidence preparation, not grading. Use only "
                    "student content supported by at least one supplied OCR candidate. Never "
                    "copy, derive, calculate, or correct an answer from the question. Preserve "
                    "student mistakes and every coherent line of working. Do not summarize an "
                    "answer down to its final value. Every cleaned_whole_segment candidate is "
                    "the required body transcription for that segment: preserve its coherent "
                    "content in segment order and cite every such candidate ID. Remove only page "
                    "headings, answer-number/question labels, HTML image placeholders, and obvious "
                    "marker annotations. Treat "
                    "selected_full_page_layout_blocks as lower-fidelity navigation OCR; it "
                    "must not override numerals, operators, or units visible in focused_final_ocr "
                    "or focused_final_formula. Use the two focused candidates only to clarify a "
                    "coherent final line; ignore them when they contain isolated gibberish, marker "
                    "strokes, or unrelated reverse-page bleed. Prefer cleaned_whole_segment for "
                    "all body text. A trailing coloured check, flourish, circled mark, or "
                    "isolated letter after a numeric result is not student evidence. Do not "
                    "include isolated "
                    "gibberish that is absent from coherent segment-level readings. "
                    "When readings conflict and the intended symbol is not supported clearly, "
                    "retain an explicit [unclear: ...] marker and use status uncertain. Never "
                    "hide uncertainty. Uncertainty notes must discuss transcription only: never "
                    "critique correctness, solve the question, or say what the question asks. "
                    "If an uncertain glyph has one or two plausible readings supported by the "
                    "OCR or by the same written line, put the most likely complete transcription "
                    "in prepared_text and each other complete transcription in "
                    "alternative_prepared_texts. Alternatives may differ only at uncertain "
                    "spans; they are teacher choices, not corrected answers. Set "
                    "transcription_complete=true only after preserving the coherent body. "
                    "Every result requires teacher review."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return exactly one prepared answer for every supplied question_id. "
                    "The question text is navigation context only and is not answer evidence. "
                    "Preserve useful mathematical working in readable plain text or LaTeX. "
                    "List every candidate ID used. Do not mention model answers or rubrics; "
                    "none are supplied.\n\nOCR ANSWER CANDIDATES\n" + context
                ),
            },
        ]
        payload, usage = self._structured_completion(
            messages=messages,
            response_model=QwenPreparedStudentAnswerPayload,
            schema_name="student_answer_ocr_preparation",
            max_tokens=3000,
        )
        assert isinstance(payload, QwenPreparedStudentAnswerPayload)
        expected = {
            (int(answer["question_id"]), str(answer["question_no"]).strip())
            for answer in answers
        }
        actual = {(item.question_id, item.question_no.strip()) for item in payload.answers}
        if actual != expected:
            raise ValueError("Local Qwen changed or omitted prepared answer references")
        candidates_by_question = {
            int(answer["question_id"]): {
                str(candidate["id"])
                for candidate in answer.get("ocr_candidates", [])
                if isinstance(candidate, dict) and candidate.get("id")
            }
            for answer in answers
        }
        for item in payload.answers:
            available = candidates_by_question.get(item.question_id, set())
            if not set(item.source_candidate_ids).issubset(available):
                raise ValueError("Local Qwen cited an unknown OCR candidate")
            source = next(
                answer for answer in answers if int(answer["question_id"]) == item.question_id
            )
            body_candidates = [
                candidate
                for candidate in source.get("ocr_candidates", [])
                if isinstance(candidate, dict)
                and candidate.get("kind") == "cleaned_whole_segment"
                and str(candidate.get("text") or "").strip()
            ]
            required_body_ids = {str(candidate["id"]) for candidate in body_candidates}
            if not required_body_ids.issubset(set(item.source_candidate_ids)):
                raise ValueError(
                    "Local Qwen omitted a required whole-segment transcription source"
                )
            body_character_count = sum(
                len(_normalize_evidence_text(str(candidate.get("text") or "")))
                for candidate in body_candidates
            )
            minimum_prepared_characters = min(
                120,
                max(12, body_character_count // 5),
            )
            if (
                len(_normalize_evidence_text(item.prepared_text))
                < minimum_prepared_characters
            ):
                raise ValueError(
                    "Local Qwen omitted substantive student working from prepared evidence"
                )
            for alternative in item.alternative_prepared_texts:
                if (
                    len(_normalize_evidence_text(alternative))
                    < minimum_prepared_characters
                ):
                    raise ValueError(
                        "Local Qwen returned an incomplete alternative transcription"
                    )
        result = payload.model_dump(mode="json")
        result["usage"] = usage
        return result

    def verify_model(self) -> None:
        if self._model_verified:
            return
        try:
            # llama.cpp intentionally leaves /v1/models readable, even when
            # --api-key is configured. Verify the key against a lightweight
            # protected endpoint before trusting model-alias health.
            auth_response = self.client.get("../props", headers=self._headers())
            if getattr(auth_response, "status_code", None) in {401, 403}:
                raise RuntimeError("Local Qwen API-key authentication failed")
            auth_response.raise_for_status()
            response = self.client.get("models", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Local Qwen model verification failed: {self._sanitize(str(exc))}"
            ) from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("Local Qwen model verification returned an invalid model list")
        model_ids = {
            item.get("id")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if self.model_name not in model_ids:
            raise RuntimeError(
                "Local Qwen model alias mismatch; expected the configured model alias"
            )
        self._model_verified = True

    def verify_available_model(self) -> None:
        self.verify_model()

    def _structured_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        schema_name: str,
        max_tokens: int | None = None,
    ) -> tuple[BaseModel, dict[str, int]]:
        self.verify_model()
        try:
            request_json: dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": _llama_cpp_json_schema(response_model),
                    },
                },
            }
            if max_tokens is not None:
                request_json["max_tokens"] = max_tokens
            response = self.client.post(
                "chat/completions",
                headers=self._headers(),
                json=request_json,
            )
            response.raise_for_status()
            body = response.json()
            content = self._extract_content(body)
            raw = json.loads(content)
            validated = response_model.model_validate(raw)
        except json.JSONDecodeError:
            raise ValueError("Local Qwen returned invalid structured output (JSON)") from None
        except ValidationError as exc:
            first = exc.errors(include_input=False)[0]
            location = ".".join(str(item) for item in first.get("loc", ())) or "root"
            error_type = str(first.get("type") or "validation_error")
            raise ValueError(
                f"Local Qwen returned invalid structured output at {location} ({error_type})"
            ) from None
        except Exception as exc:
            raise RuntimeError(self._sanitize(str(exc))) from exc
        usage_payload = body.get("usage") if isinstance(body, dict) else None
        usage = {
            key: int(value)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage_payload, dict)
            and isinstance((value := usage_payload.get(key)), int)
            and value >= 0
        }
        return validated, usage

    def _validate_grade_contract(
        self,
        payload: QwenGradePayload,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
    ) -> None:
        expected_max = Decimal(str(rubric_json.get("total_marks", question_total_marks)))
        if payload.max_score != expected_max or payload.max_score != question_total_marks:
            raise ValueError("Local Qwen changed the canonical maximum score")
        criteria = rubric_json.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("Active rubric has no criteria")
        expected = {
            str(item.get("id")): Decimal(str(item.get("max_marks")))
            for item in criteria
            if isinstance(item, dict) and item.get("id") is not None
        }
        actual = {item.criterion_id: item.max_marks for item in payload.rubric_breakdown}
        if actual != expected:
            raise ValueError("Local Qwen changed rubric criterion IDs or maximum marks")

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Local Qwen response missing choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Local Qwen response missing message content")
        return content

    def _ocr_context(self, pages: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        for page in pages:
            page_no = page.get("page", page.get("page_no", "?"))
            text = str(page.get("text") or page.get("normalized_text") or "").strip()
            if text:
                chunks.append(f"--- Page {page_no} ---\n{text}")
        if not chunks:
            raise ValueError("Local OCR returned no text to extract")
        return "\n\n".join(chunks)

    def _ocr_document_context(self, documents: dict[str, list[dict[str, Any]]]) -> str:
        chunks: list[str] = []
        labels = {
            "question_paper": "QUESTION PAPER",
            "solution": "SOLUTION / MODEL ANSWER",
            "rubric": "RUBRIC",
        }
        for document_type in ("question_paper", "solution", "rubric"):
            pages = documents.get(document_type, [])
            page_chunks: list[str] = []
            for page in pages:
                page_no = page.get("page", page.get("page_no", "?"))
                # Normalized OCR text contains the same semantic evidence as the
                # rendered Markdown without repeating layout markup and table
                # scaffolding.  Prefer it so one local extraction remains well
                # inside the 32K context and the host job timeout.
                content = str(
                    page.get("text") or page.get("normalized_text") or page.get("markdown") or ""
                ).strip()
                if content:
                    page_chunks.append(f"--- {labels[document_type]} PAGE {page_no} ---\n{content}")
            if not page_chunks:
                raise ValueError(f"Local OCR returned no text for {labels[document_type]}")
            chunks.extend(page_chunks)
        return "\n\n".join(chunks)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _sanitize(self, message: str) -> str:
        sanitized = message.replace(self.api_key, "[REDACTED]")
        sanitized = _API_KEY_PATTERN.sub("[REDACTED]", sanitized)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", sanitized)


def _llama_cpp_json_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Remove Pydantic's regex-backed Decimal string alternative.

    llama.cpp build 10249 cannot translate the ``\\d`` escape emitted in that
    alternative into a grammar. JSON numbers retain the same Decimal precision
    once Pydantic validates the response, while nullable Decimal fields keep
    their null alternative.
    """

    return _prefer_json_numbers(deepcopy(response_model.model_json_schema()))


def _prefer_json_numbers(value: Any) -> Any:
    if isinstance(value, list):
        return [_prefer_json_numbers(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _prefer_json_numbers(item) for key, item in value.items()}
    alternatives = normalized.get("anyOf")
    if not isinstance(alternatives, list):
        return normalized

    has_number = any(
        isinstance(option, dict) and option.get("type") == "number" for option in alternatives
    )
    if not has_number:
        return normalized
    filtered = [
        option
        for option in alternatives
        if not (isinstance(option, dict) and option.get("type") == "string" and "pattern" in option)
    ]
    if len(filtered) == len(alternatives):
        return normalized
    if len(filtered) == 1:
        metadata = {
            key: item
            for key, item in normalized.items()
            if key not in {"anyOf", "type", "minimum", "maximum"}
        }
        return {**filtered[0], **metadata}
    normalized["anyOf"] = filtered
    return normalized


def _evidence_is_verbatim_student_text(evidence: str | None, student_answer_text: str) -> bool:
    if not (evidence or "").strip():
        return False
    candidate = str(evidence).strip()
    candidate = re.sub(
        r"(?i)^\s*(?:student(?:'s)?\s+(?:answer|work)|answer|evidence)\s*:\s*",
        "",
        candidate,
    ).strip()
    candidate = candidate.strip("'\"`“”‘’ ")
    normalized_candidate = _normalize_evidence_text(candidate)
    normalized_answer = _normalize_evidence_text(student_answer_text)
    return bool(normalized_candidate) and normalized_candidate in normalized_answer


def _normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = normalized.replace("×", "x").replace("−", "-")
    return " ".join(normalized.split()).strip(" .;,'\"`“”‘’")


def _submission_ocr_block_context(pages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    seen: set[tuple[int, int]] = set()
    for page in pages:
        page_no = int(page.get("page") or page.get("page_no") or 0)
        if page_no < 1:
            raise ValueError("Submission OCR page number is invalid")
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError("Submission OCR blocks are missing")
        lines: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("Submission OCR block is invalid")
            order = int(block.get("order") or 0)
            block_text = str(block.get("text") or "").strip()
            if order < 1 or not block_text:
                continue
            key = (page_no, order)
            if key in seen:
                raise ValueError("Submission OCR block IDs are not unique")
            seen.add(key)
            lines.append(f"[page={page_no} block={order}] {block_text}")
        chunks.append(f"--- SCRIPT PAGE {page_no} ---\n" + "\n".join(lines))
    if not seen:
        raise ValueError("Local OCR returned no submission text blocks")
    return "\n\n".join(chunks)


def _reference_question_number_hints(
    documents: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Return high-confidence nested leaf labels from the question paper OCR.

    Hints are emitted only when at least two lettered parents contain roman
    children, which avoids constraining less structured papers.
    """

    pages = documents.get("question_paper", [])
    text = "\n".join(str(page.get("text") or page.get("normalized_text") or "") for page in pages)
    current_number: str | None = None
    current_parent: str | None = None
    parent_count = 0
    leaves: list[str] = []
    roman_pattern = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*• ")
        if not line:
            continue
        number_match = re.match(r"^(\d+)\s*[.)]?\s*(.*)$", line)
        remainder = line
        if number_match:
            current_number = number_match.group(1)
            current_parent = None
            remainder = number_match.group(2).lstrip()
        marker_match = re.match(r"^\(([A-Za-z]+)\)", remainder)
        if marker_match is None or current_number is None:
            continue
        marker = marker_match.group(1).lower()
        if len(marker) == 1 and marker in "abcdefgh":
            current_parent = marker
            parent_count += 1
            continue
        if roman_pattern.fullmatch(marker):
            label = (
                f"{current_number}({current_parent})({marker})"
                if current_parent
                else f"{current_number}({marker})"
            )
            if label not in leaves:
                leaves.append(label)

    return leaves if parent_count >= 2 and len(leaves) >= 2 else []
