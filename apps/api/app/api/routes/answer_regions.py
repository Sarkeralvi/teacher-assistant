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
from app.models import AnswerRegion, AnswerRegionSegment, Question, Submission, SubmissionPage
from app.schemas import (
    AnswerRegionCreate,
    AnswerRegionFullAnswerConfirmation,
    AnswerRegionMappingSuggestionRequest,
    AnswerRegionRead,
    AnswerRegionSegmentCreate,
    AnswerRegionSegmentRead,
    AnswerRegionSuggestionAcceptRequest,
    AnswerRegionSuggestionGroupResponse,
    AnswerRegionSuggestionRequest,
    AnswerRegionSuggestionResponse,
    DraftAnswerRegionSuggestion,
    DraftAnswerRegionSuggestionGroup,
    DraftAnswerRegionSuggestionSegment,
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


def get_questions_for_submission_mapping(
    submission: Submission,
    db: Session,
    question_ids: list[int] | None = None,
    question_nos: list[str] | None = None,
) -> list[Question]:
    page = submission.pages[0] if submission.pages else None
    if page is None:
        return []
    return get_questions_for_suggestion(page, db, question_ids, question_nos)


def get_pages_for_submission_mapping(
    submission: Submission,
    page_ids: list[int] | None = None,
) -> list[SubmissionPage]:
    pages = sorted(submission.pages, key=lambda item: item.page_no)
    if not page_ids:
        return pages
    by_id = {page.id: page for page in pages}
    selected: list[SubmissionPage] = []
    seen_page_ids: set[int] = set()
    for page_id in page_ids:
        page = by_id.get(page_id)
        if page is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Mapping page must belong to the same submission",
            )
        if page.id not in seen_page_ids:
            selected.append(page)
            seen_page_ids.add(page.id)
    return selected


def validate_page_box(
    page: SubmissionPage, x: Decimal, y: Decimal, width: Decimal, height: Decimal
) -> None:
    path = LocalStorage().resolve_relative(page.image_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )
    with Image.open(path) as image:
        if x + width > image.width or y + height > image.height:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Mapping segment box must fit inside its submission page",
            )


def build_mock_mapping_suggestion_groups(
    submission: Submission,
    questions: Sequence[Question],
    pages: Sequence[SubmissionPage],
    deterministic_case: str,
) -> AnswerRegionSuggestionGroupResponse:
    if not questions or not pages:
        return AnswerRegionSuggestionGroupResponse(
            submission_id=submission.id,
            provider="mock",
            source="mock",
            needs_review=True,
            message="No confirmed questions or pages available for draft mapping suggestions.",
            suggestion_groups=[],
        )
    question = questions[0]
    first_page = pages[0]
    second_page = pages[1] if len(pages) > 1 else None
    validate_page_box(first_page, Decimal("20"), Decimal("30"), Decimal("200"), Decimal("180"))

    warnings = [
        "Draft mapping suggestion only.",
        "Teacher/founder must accept and confirm full answer evidence before grading.",
    ]
    segments = [
        DraftAnswerRegionSuggestionSegment(
            page_id=first_page.id,
            order_index=1,
            x=Decimal("20"),
            y=Decimal("30"),
            width=Decimal("200"),
            height=Decimal("180"),
            is_primary=True,
            source="suggestion",
            confidence=Decimal("0.70"),
            continuation_risk="none",
            warnings=[],
            notes="Mock deterministic first answer segment.",
        )
    ]
    continuation_risk = "none"
    reason = "Mock deterministic single-segment mapping suggestion."
    group_warnings = list(warnings)
    if deterministic_case == "multi_segment_continuation" and second_page is not None:
        validate_page_box(second_page, Decimal("20"), Decimal("30"), Decimal("200"), Decimal("180"))
        segments.append(
            DraftAnswerRegionSuggestionSegment(
                page_id=second_page.id,
                order_index=2,
                x=Decimal("20"),
                y=Decimal("30"),
                width=Decimal("200"),
                height=Decimal("180"),
                is_primary=False,
                source="suggestion",
                confidence=Decimal("0.70"),
                continuation_risk="continuation_included",
                warnings=[],
                notes="Mock deterministic continuation segment on the next page.",
            )
        )
        continuation_risk = "continuation_included"
        reason = "Mock deterministic multi-segment mapping includes next-page continuation."
    elif deterministic_case == "possible_continuation":
        warning = (
            "Possible continuation on the next page; teacher/founder must confirm full "
            "answer before grading."
        )
        group_warnings.append(warning)
        segments[0].continuation_risk = "possible_continuation"
        segments[0].warnings.append(warning)
        continuation_risk = "possible_continuation"
        reason = "Mock deterministic bottom-near segment with possible continuation."

    return AnswerRegionSuggestionGroupResponse(
        submission_id=submission.id,
        provider="mock",
        source="mock",
        needs_review=True,
        message="Mock deterministic mapping suggestion groups generated.",
        provider_warnings=[],
        suggestion_groups=[
            DraftAnswerRegionSuggestionGroup(
                draft_id=f"submission-{submission.id}-question-{question.id}-{deterministic_case}",
                suggested_question_id=question.id,
                suggested_question_no=question.question_no,
                provider="mock",
                source="mock",
                confidence=Decimal("0.70"),
                continuation_risk=continuation_risk,
                segments=segments,
                warnings=group_warnings,
                reason=reason,
                needs_review=True,
                needs_teacher_confirmation=True,
                requires_full_answer_confirmation=True,
            )
        ],
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
    db.flush()
    db.add(
        AnswerRegionSegment(
            answer_region_id=region.id,
            submission_page_id=page.id,
            order_index=1,
            x=payload.x,
            y=payload.y,
            width=payload.width,
            height=payload.height,
            image_path=image_path,
            source="manual",
            confirmed=True,
            is_primary=True,
        )
    )
    db.commit()
    db.refresh(region)
    return region


@router.post(
    "/submissions/{submission_id}/answer-region-mapping-suggestions",
    response_model=AnswerRegionSuggestionGroupResponse,
)
def suggest_answer_region_mapping_groups(
    submission_id: int,
    db: DbSession,
    payload: AnswerRegionMappingSuggestionRequest | None = None,
) -> AnswerRegionSuggestionGroupResponse:
    submission = get_submission_or_404(submission_id, db)
    request = payload or AnswerRegionMappingSuggestionRequest()
    provider_name = (request.provider or "mock").strip().lower()
    if provider_name != "mock":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the mock deterministic mapping provider is implemented for TA-MAP-002",
        )
    questions = get_questions_for_submission_mapping(
        submission, db, request.question_ids, request.question_nos
    )
    pages = get_pages_for_submission_mapping(submission, request.page_ids)
    return build_mock_mapping_suggestion_groups(
        submission, questions, pages, request.deterministic_case
    )


@router.post(
    "/submissions/{submission_id}/answer-region-mapping-suggestions/accept",
    response_model=AnswerRegionRead,
    status_code=status.HTTP_201_CREATED,
)
def accept_answer_region_mapping_suggestion(
    submission_id: int,
    payload: AnswerRegionSuggestionAcceptRequest,
    db: DbSession,
) -> AnswerRegion:
    submission = get_submission_or_404(submission_id, db)
    question = get_question_or_404(payload.question_id, db)
    if question.assessment_id != submission.assessment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Question assessment must match submission assessment",
        )
    pages_by_id = {page.id: page for page in submission.pages}
    ordered_segments = sorted(payload.segments, key=lambda segment: segment.order_index)
    expected_order = list(range(1, len(ordered_segments) + 1))
    if [segment.order_index for segment in ordered_segments] != expected_order:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Accepted mapping segment order must be contiguous starting at 1",
        )
    primary_count = sum(1 for segment in ordered_segments if segment.is_primary)
    if primary_count != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Accepted mapping suggestion must have exactly one primary segment",
        )
    for segment in ordered_segments:
        page = pages_by_id.get(segment.page_id)
        if page is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Mapping page must belong to the same submission",
            )
        validate_page_box(page, segment.x, segment.y, segment.width, segment.height)

    primary = next(segment for segment in ordered_segments if segment.is_primary)
    primary_page = pages_by_id[primary.page_id]
    primary_image_path = crop_answer_region_image(
        storage=LocalStorage(),
        source_image_path=primary_page.image_path,
        submission_id=submission.id,
        x=primary.x,
        y=primary.y,
        width=primary.width,
        height=primary.height,
    )
    region = AnswerRegion(
        submission_id=submission.id,
        question_id=question.id,
        page_id=primary_page.id,
        x=primary.x,
        y=primary.y,
        width=primary.width,
        height=primary.height,
        image_path=primary_image_path,
        full_answer_confirmed=payload.full_answer_confirmed,
    )
    db.add(region)
    db.flush()
    for segment in ordered_segments:
        page = pages_by_id[segment.page_id]
        segment_image_path = primary_image_path if segment.is_primary else crop_answer_region_image(
            storage=LocalStorage(),
            source_image_path=page.image_path,
            submission_id=submission.id,
            x=segment.x,
            y=segment.y,
            width=segment.width,
            height=segment.height,
        )
        db.add(
            AnswerRegionSegment(
                answer_region_id=region.id,
                submission_page_id=page.id,
                order_index=segment.order_index,
                x=segment.x,
                y=segment.y,
                width=segment.width,
                height=segment.height,
                image_path=segment_image_path,
                source="suggestion",
                confirmed=payload.full_answer_confirmed,
                is_primary=segment.is_primary,
            )
        )
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


@router.post(
    "/answer-regions/{answer_region_id}/segments",
    response_model=AnswerRegionSegmentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_answer_region_segment(
    answer_region_id: int, payload: AnswerRegionSegmentCreate, db: DbSession
) -> AnswerRegionSegment:
    region = get_answer_region_or_404(answer_region_id, db)
    page = get_submission_page_or_404(payload.page_id, db)
    if page.submission_id != region.submission_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Segment page must belong to the same submission",
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
    segment = AnswerRegionSegment(
        answer_region_id=region.id,
        submission_page_id=page.id,
        order_index=payload.order_index,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        image_path=image_path,
        source=payload.source,
        confirmed=payload.confirmed,
        is_primary=False,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


@router.patch(
    "/answer-regions/{answer_region_id}/full-answer-confirmation",
    response_model=AnswerRegionRead,
)
def update_answer_region_full_answer_confirmation(
    answer_region_id: int, payload: AnswerRegionFullAnswerConfirmation, db: DbSession
) -> AnswerRegion:
    region = get_answer_region_or_404(answer_region_id, db)
    region.full_answer_confirmed = payload.full_answer_confirmed
    db.commit()
    db.refresh(region)
    return region


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
