from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.routes.assessments import get_assessment_or_404
from app.api.routes.questions import get_question_or_404
from app.api.routes.submissions import get_submission_or_404
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AnswerRegion, Question, Submission, SubmissionPage
from app.schemas import (
    AnswerRegionCreate,
    AnswerRegionRead,
    AnswerRegionSuggestionRequest,
    AnswerRegionSuggestionResponse,
    DraftAnswerRegionSuggestion,
)
from app.services.answer_region_processing import crop_answer_region_image
from app.services.storage import LocalStorage
from packages.brain.answer_region_suggestion_codex_provider import (
    CodexAnswerRegionSuggestionProvider,
    CodexAnswerRegionSuggestionProviderError,
)

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["answer-regions"])


def get_submission_page_or_404(page_id: int, db: Session) -> SubmissionPage:
    statement = (
        select(SubmissionPage)
        .options(joinedload(SubmissionPage.submission))
        .where(SubmissionPage.id == page_id)
    )
    page = db.scalars(statement).first()
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page not found",
        )
    return page


def get_answer_region_or_404(answer_region_id: int, db: Session) -> AnswerRegion:
    region = db.get(AnswerRegion, answer_region_id)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found")
    return region


def get_questions_for_suggestion(
    page: SubmissionPage,
    db: Session,
    question_ids: list[int] | None = None,
    question_nos: list[str] | None = None,
) -> list[Question]:
    statement = (
        select(Question)
        .where(Question.assessment_id == page.submission.assessment_id)
        .order_by(Question.id)
    )
    assessment_questions = list(db.scalars(statement).all())
    by_id = {question.id: question for question in assessment_questions}
    by_no = {question.question_no: question for question in assessment_questions}

    if not question_ids and not question_nos:
        return assessment_questions

    selected: list[Question] = []
    seen_question_ids: set[int] = set()

    for question_id in question_ids or []:
        question = by_id.get(question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Question must belong to the same assessment as the submission page",
            )
        if question.id not in seen_question_ids:
            selected.append(question)
            seen_question_ids.add(question.id)

    for question_no in question_nos or []:
        question = by_no.get(question_no)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Question must belong to the same assessment as the submission page",
            )
        if question.id not in seen_question_ids:
            selected.append(question)
            seen_question_ids.add(question.id)

    return selected


def build_mock_answer_region_suggestions(
    page: SubmissionPage,
    questions: Sequence[Question],
) -> AnswerRegionSuggestionResponse:
    image_path = LocalStorage().resolve_relative(page.image_path)
    if not image_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )

    with Image.open(image_path) as image:
        if not questions:
            return AnswerRegionSuggestionResponse(
                page_id=page.id,
                provider="mock",
                source="mock",
                needs_review=True,
                message="No confirmed questions available for draft suggestions.",
                suggestions=[],
            )
        if image.width < 160 or image.height < 120:
            return AnswerRegionSuggestionResponse(
                page_id=page.id,
                provider="mock",
                source="mock",
                needs_review=True,
                message="Page is too small for draft answer-region suggestions.",
                suggestions=[],
            )

        margin_x = max(int(image.width * 0.08), 12)
        box_width = max(image.width - (margin_x * 2), 1)
        band_height = image.height / max(len(questions), 1)
        if band_height < 24:
            return AnswerRegionSuggestionResponse(
                page_id=page.id,
                provider="mock",
                source="mock",
                needs_review=True,
                message="Page is too small for draft answer-region suggestions.",
                suggestions=[],
            )

        suggestions: list[DraftAnswerRegionSuggestion] = []
        warnings = [
            "Draft suggestion only.",
            "Teacher must confirm before grading.",
        ]
        for index, question in enumerate(questions):
            slot_top = int(round(index * band_height))
            slot_bottom = int(round((index + 1) * band_height))
            slot_height = max(slot_bottom - slot_top, 1)
            margin_y = max(int(min(slot_height * 0.15, image.height * 0.08)), 8)
            y = min(slot_top + margin_y, image.height - 1)
            usable_height = max(slot_bottom - margin_y - y, 1)
            height = min(max(int(round(slot_height * 0.6)), 1), usable_height)
            if y + height > image.height:
                height = max(image.height - y, 1)
            if height <= 0:
                continue
            suggestions.append(
                DraftAnswerRegionSuggestion(
                    draft_id=f"page-{page.id}-question-{question.id}-draft",
                    page_id=page.id,
                    suggested_question_id=question.id,
                    suggested_question_no=question.question_no,
                    x=Decimal(margin_x),
                    y=Decimal(y),
                    width=Decimal(box_width),
                    height=Decimal(height),
                    confidence=Decimal("0.35" if len(questions) == 1 else "0.30"),
                    provider="mock",
                    source="mock",
                    warnings=warnings,
                    reason="Mock deterministic layout based on confirmed questions.",
                    notes="Mock deterministic layout based on confirmed questions.",
                    needs_review=True,
                    needs_teacher_confirmation=True,
                )
            )
        message = "Mock deterministic suggestions generated from confirmed questions."
        return AnswerRegionSuggestionResponse(
            page_id=page.id,
            provider="mock",
            source="mock",
            needs_review=True,
            message=message,
            provider_warnings=[],
            suggestions=suggestions,
        )


def normalize_answer_region_suggestion_provider(
    provider: str | None, default_provider: str
) -> str:
    value = (provider or default_provider or "mock").strip().lower()
    if value == "codex_cli":
        return "codex_cli_answer_region_suggester"
    if value in {"mock", "codex_cli_answer_region_suggester"}:
        return value
    return value


def build_codex_answer_region_suggestions(
    page: SubmissionPage,
    questions: Sequence[Question],
    provider_output: object,
) -> AnswerRegionSuggestionResponse:
    question_by_id = {question.id: question for question in questions}
    question_by_no = {question.question_no: question for question in questions}
    seen_question_ids: set[int] = set()
    draft_suggestions: list[DraftAnswerRegionSuggestion] = []

    output_suggestions = getattr(provider_output, "suggestions", [])
    provider_warnings = list(getattr(provider_output, "provider_warnings", []) or [])
    for index, item in enumerate(output_suggestions):
        question = None
        item_question_id = getattr(item, "question_id", None)
        item_question_no = getattr(item, "question_no", None)
        if item_question_id is not None:
            question = question_by_id.get(item_question_id)
        if question is None and item_question_no is not None:
            question = question_by_no.get(item_question_no)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Codex suggestion must reference a confirmed question from the same "
                    "assessment"
                ),
            )
        if item_question_id is not None and question.id != item_question_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Codex suggestion question_id must belong to the same assessment",
            )
        if item_question_no is not None and question.question_no != item_question_no:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Codex suggestion question_no must belong to the same assessment",
            )
        if question.id in seen_question_ids:
            continue
        seen_question_ids.add(question.id)
        draft_suggestions.append(
            DraftAnswerRegionSuggestion(
                draft_id=f"page-{page.id}-question-{question.id}-codex-{index + 1}",
                page_id=page.id,
                suggested_question_id=question.id,
                suggested_question_no=question.question_no,
                x=item.x,
                y=item.y,
                width=item.width,
                height=item.height,
                confidence=item.confidence,
                provider="codex_cli_answer_region_suggester",
                source="codex_cli_answer_region_suggester",
                reason=item.notes,
                warnings=list(getattr(item, "warnings", []) or []),
                notes=item.notes,
                needs_review=True,
                needs_teacher_confirmation=True,
            )
        )

    message = (
        "Codex-backed draft suggestions generated from confirmed questions."
        if draft_suggestions
        else "Codex-backed provider returned no answer-region suggestions."
    )
    return AnswerRegionSuggestionResponse(
        page_id=page.id,
        provider="codex_cli_answer_region_suggester",
        source="codex_cli_answer_region_suggester",
        needs_review=True,
        message=message,
        provider_warnings=provider_warnings,
        suggestions=draft_suggestions,
    )


def get_codex_answer_region_suggestion_provider(settings) -> CodexAnswerRegionSuggestionProvider:
    return CodexAnswerRegionSuggestionProvider(
        command=settings.codex_cli_command,
        model_name=settings.codex_cli_model,
        timeout_seconds=settings.codex_cli_timeout_seconds,
        sandbox=settings.codex_cli_sandbox,
        use_json=settings.codex_cli_use_json,
        output_last_message=settings.codex_cli_output_last_message,
        image_input_enabled=settings.codex_cli_image_input_enabled,
        workdir=settings.codex_cli_workdir,
        skip_git_repo_check=settings.codex_cli_skip_git_repo_check,
    )


@router.post(
    "/submission-pages/{page_id}/answer-regions",
    response_model=AnswerRegionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_answer_region(
    page_id: int, payload: AnswerRegionCreate, db: DbSession
) -> AnswerRegion:
    page = get_submission_page_or_404(page_id, db)
    question = get_question_or_404(payload.question_id, db)
    if question.assessment_id != page.submission.assessment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Question assessment must match submission assessment",
        )

    image_path = crop_answer_region_image(
        storage=LocalStorage(),
        source_image_path=page.image_path,
        submission_id=page.submission_id,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
    )
    region = AnswerRegion(
        submission_id=page.submission_id,
        question_id=payload.question_id,
        page_id=page.id,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        image_path=image_path,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.post(
    "/submission-pages/{page_id}/answer-region-suggestions",
    response_model=AnswerRegionSuggestionResponse,
)
@router.post(
    "/submission-pages/{page_id}/answer-regions/suggest",
    response_model=AnswerRegionSuggestionResponse,
)
def suggest_answer_regions(
    page_id: int, db: DbSession, payload: AnswerRegionSuggestionRequest | None = None
) -> AnswerRegionSuggestionResponse:
    page = get_submission_page_or_404(page_id, db)
    settings = get_settings()
    request = payload or AnswerRegionSuggestionRequest()
    provider_name = normalize_answer_region_suggestion_provider(
        request.provider, settings.answer_region_suggestion_provider
    )
    questions = get_questions_for_suggestion(
        page,
        db,
        question_ids=request.question_ids,
        question_nos=request.question_nos,
    )
    if provider_name == "mock":
        return build_mock_answer_region_suggestions(page, questions)
    if provider_name == "codex_cli_answer_region_suggester":
        if not settings.codex_answer_region_suggestions_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Codex-backed answer-region suggestions are disabled. "
                    "Set CODEX_ANSWER_REGION_SUGGESTIONS_ENABLED=true to enable them."
                ),
            )
        if not settings.codex_cli_image_input_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Codex answer-region suggestions require CODEX_CLI_IMAGE_INPUT_ENABLED=true."
                ),
            )
        provider = get_codex_answer_region_suggestion_provider(settings)
        try:
            with Image.open(LocalStorage().resolve_relative(page.image_path)) as image:
                provider_output = provider.suggest(
                    page_image_path=LocalStorage().resolve_relative(page.image_path).as_posix(),
                    page_width=image.width,
                    page_height=image.height,
                    questions=[
                        {
                            "id": question.id,
                            "question_no": question.question_no,
                            "question_text": question.question_text,
                        }
                        for question in questions
                    ],
                )
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission page image not found",
            ) from None
        except CodexAnswerRegionSuggestionProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Codex answer-region suggestion provider failed: {exc}",
            ) from exc
        return build_codex_answer_region_suggestions(page, questions, provider_output)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported answer-region suggestion provider: {provider_name}",
    )


@router.get("/submissions/{submission_id}/answer-regions", response_model=list[AnswerRegionRead])
def list_submission_answer_regions(submission_id: int, db: DbSession) -> Sequence[AnswerRegion]:
    get_submission_or_404(submission_id, db)
    statement = (
        select(AnswerRegion)
        .where(AnswerRegion.submission_id == submission_id)
        .order_by(AnswerRegion.id)
    )
    return db.scalars(statement).all()


@router.get("/assessments/{assessment_id}/answer-regions", response_model=list[AnswerRegionRead])
def list_assessment_answer_regions(
    assessment_id: int, db: DbSession, question_id: int | None = None
) -> Sequence[AnswerRegion]:
    get_assessment_or_404(assessment_id, db)
    statement = (
        select(AnswerRegion)
        .join(Submission, Submission.id == AnswerRegion.submission_id)
        .where(Submission.assessment_id == assessment_id)
        .order_by(AnswerRegion.id)
    )
    if question_id is not None:
        statement = statement.where(AnswerRegion.question_id == question_id)
    return db.scalars(statement).all()


@router.get("/answer-regions/{answer_region_id}", response_model=AnswerRegionRead)
def get_answer_region(answer_region_id: int, db: DbSession) -> AnswerRegion:
    return get_answer_region_or_404(answer_region_id, db)


@router.get("/answer-regions/{answer_region_id}/image")
def get_answer_region_image(answer_region_id: int, db: DbSession) -> FileResponse:
    region = get_answer_region_or_404(answer_region_id, db)
    path = LocalStorage().resolve_relative(region.image_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer region image not found",
        )
    return FileResponse(path, media_type="image/png")


@router.delete("/answer-regions/{answer_region_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer_region(answer_region_id: int, db: DbSession) -> Response:
    region = get_answer_region_or_404(answer_region_id, db)
    db.delete(region)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Answer region has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
