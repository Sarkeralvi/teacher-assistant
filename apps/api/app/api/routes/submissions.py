import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import Headers

from app.api.routes.assessments import get_owned_assessment_or_404
from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    AuditLog,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import SubmissionRead, SubmissionZipUploadResponse
from app.services.storage import LocalStorage
from app.services.submission_processing import classify_upload, extract_page_images

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["submissions"])

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_ZIP_FILES = 100
MAX_ZIP_MEMBER_BYTES = 25 * 1024 * 1024
SUPPORTED_ZIP_SUFFIX_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
IdentifierStrategy = Literal["basename", "sequential"]


def get_submission_or_404(submission_id: int, db: Session) -> Submission:
    statement = (
        select(Submission)
        .options(selectinload(Submission.pages))
        .where(Submission.id == submission_id)
    )
    submission = db.scalars(statement).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    submission.pages.sort(key=lambda page: page.page_no)
    return submission


def get_owned_submission_or_404(submission_id: int, db: Session, teacher: User) -> Submission:
    statement = (
        select(Submission)
        .join(Assessment, Assessment.id == Submission.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .options(selectinload(Submission.pages))
        .where(Submission.id == submission_id, Course.teacher_id == teacher.id)
    )
    submission = db.scalars(statement).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    submission.pages.sort(key=lambda page: page.page_no)
    return submission


def get_owned_submission_page_or_404(
    page_id: int, db: Session, teacher: User
) -> SubmissionPage:
    statement = (
        select(SubmissionPage)
        .join(Submission, Submission.id == SubmissionPage.submission_id)
        .join(Assessment, Assessment.id == Submission.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(SubmissionPage.id == page_id, Course.teacher_id == teacher.id)
    )
    page = db.scalars(statement).first()
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page not found",
        )
    return page


def create_submission_from_upload(
    *,
    assessment_id: int,
    db: Session,
    student_identifier: str,
    file: UploadFile,
    student_name: str | None = None,
) -> Submission:
    kind, suffix = classify_upload(file)
    storage = LocalStorage()

    submission = Submission(
        assessment_id=assessment_id,
        student_identifier=student_identifier,
        student_name=student_name or None,
        status="uploaded",
    )
    db.add(submission)
    db.flush()

    stored_upload = storage.save_upload(file, submission.id, suffix)
    page_paths = extract_page_images(
        storage=storage,
        submission_id=submission.id,
        uploaded_path=stored_upload.absolute_path,
        kind=kind,
    )
    for page_no, image_path in enumerate(page_paths, start=1):
        db.add(
            SubmissionPage(
                submission_id=submission.id,
                page_no=page_no,
                image_path=image_path,
                quality_score=None,
            )
        )

    db.commit()
    db.refresh(submission)
    submission.pages.sort(key=lambda page: page.page_no)
    return submission


def is_safe_zip_member_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    if any(":" in part for part in path.parts):
        return False
    return True


def zip_entry_identifier(name: str, strategy: IdentifierStrategy, index: int) -> str:
    if strategy == "sequential":
        return f"S-{index:03d}"
    return PurePosixPath(name.replace("\\", "/")).stem[:128] or f"S-{index:03d}"


def zip_entry_student_name(prefix: str | None, index: int) -> str | None:
    if not prefix:
        return None
    return f"{prefix} {index:03d}"


def zip_entry_upload(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=PurePosixPath(name.replace("\\", "/")).name,
        headers=Headers({"content-type": content_type}),
    )


@router.post(
    "/assessments/{assessment_id}/submissions/upload",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_submission(
    assessment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    student_identifier: Annotated[str, Form(min_length=1, max_length=128)],
    file: Annotated[UploadFile, File()],
    student_name: Annotated[str | None, Form(max_length=255)] = None,
) -> Submission:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return create_submission_from_upload(
        assessment_id=assessment_id,
        db=db,
        student_identifier=student_identifier,
        student_name=student_name,
        file=file,
    )


@router.post(
    "/assessments/{assessment_id}/submissions/upload-zip",
    response_model=SubmissionZipUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_submission_zip(
    assessment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    student_identifier_strategy: Annotated[IdentifierStrategy, Form()] = "basename",
    student_name_prefix: Annotated[str | None, Form(max_length=64)] = None,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    suffix = PurePosixPath(file.filename or "").suffix.lower()
    if suffix != ".zip" and file.content_type not in {
        "application/zip",
        "application/x-zip-compressed",
        "multipart/x-zip",
    }:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a ZIP archive for batch script ingestion",
        )

    zip_bytes = file.file.read(MAX_ZIP_BYTES + 1)
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="ZIP file is too large"
        )

    try:
        archive = zipfile.ZipFile(BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid ZIP archive",
        ) from exc

    submissions_created: list[Submission] = []
    errors: list[str] = []
    warnings: list[str] = []
    imported_count = 0
    skipped_count = 0
    failed_count = 0

    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        requested_file_count = len(entries)
        if requested_file_count > MAX_ZIP_FILES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"ZIP contains too many files; maximum is {MAX_ZIP_FILES}",
            )

        for info in entries:
            name = info.filename
            if not is_safe_zip_member_path(name):
                failed_count += 1
                errors.append(f"Unsafe ZIP path rejected: {name}")
                continue
            suffix = PurePosixPath(name).suffix.lower()
            content_type = SUPPORTED_ZIP_SUFFIX_CONTENT_TYPES.get(suffix)
            if content_type is None:
                skipped_count += 1
                warnings.append(f"Unsupported file type skipped: {name}")
                continue
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                failed_count += 1
                errors.append(f"ZIP entry too large: {name}")
                continue

            try:
                content = archive.read(info)
                upload = zip_entry_upload(name, content, content_type)
                submission = create_submission_from_upload(
                    assessment_id=assessment_id,
                    db=db,
                    student_identifier=zip_entry_identifier(
                        name, student_identifier_strategy, imported_count + 1
                    ),
                    student_name=zip_entry_student_name(student_name_prefix, imported_count + 1),
                    file=upload,
                )
            except HTTPException as exc:
                db.rollback()
                failed_count += 1
                errors.append(f"{name}: {exc.detail}")
                continue
            except Exception as exc:
                db.rollback()
                failed_count += 1
                errors.append(f"{name}: {type(exc).__name__}")
                continue

            imported_count += 1
            submissions_created.append(submission)

    return {
        "assessment_id": assessment_id,
        "requested_file_count": requested_file_count,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "submissions_created": submissions_created,
        "errors": errors,
        "warnings": warnings,
    }


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
def get_submission(submission_id: int, db: DbSession, current_user: CurrentUser) -> Submission:
    return get_owned_submission_or_404(submission_id, db, current_user)


@router.get("/assessments/{assessment_id}/submissions", response_model=list[SubmissionRead])
def list_assessment_submissions(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> Sequence[Submission]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    statement = (
        select(Submission)
        .options(selectinload(Submission.pages))
        .where(Submission.assessment_id == assessment_id)
        .order_by(Submission.id)
    )
    submissions = db.scalars(statement).all()
    for submission in submissions:
        submission.pages.sort(key=lambda page: page.page_no)
    return submissions


@router.delete(
    "/assessments/{assessment_id}/submissions/{submission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_assessment_submission(
    assessment_id: int, submission_id: int, db: DbSession, current_user: CurrentUser
) -> Response:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    statement = (
        select(Submission)
        .options(
            selectinload(Submission.pages),
            selectinload(Submission.answer_regions),
        )
        .where(Submission.id == submission_id, Submission.assessment_id == assessment_id)
    )
    submission = db.scalars(statement).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    answer_region_ids = [region.id for region in submission.answer_regions]
    relative_paths = [page.image_path for page in submission.pages]
    relative_paths.extend(region.image_path for region in submission.answer_regions)

    if answer_region_ids:
        grade_suggestion_ids = db.scalars(
            select(GradeSuggestion.id).where(
                GradeSuggestion.answer_region_id.in_(answer_region_ids)
            )
        ).all()
        db.execute(delete(FinalGrade).where(FinalGrade.answer_region_id.in_(answer_region_ids)))
        if grade_suggestion_ids:
            db.execute(delete(FinalGrade).where(FinalGrade.suggestion_id.in_(grade_suggestion_ids)))
        db.execute(
            delete(GradeSuggestion).where(GradeSuggestion.answer_region_id.in_(answer_region_ids))
        )
        db.execute(delete(GradingJob).where(GradingJob.answer_region_id.in_(answer_region_ids)))
        db.execute(delete(AnswerRegion).where(AnswerRegion.id.in_(answer_region_ids)))

    db.execute(delete(SubmissionPage).where(SubmissionPage.submission_id == submission_id))
    db.execute(delete(Submission).where(Submission.id == submission_id))
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="submission.deleted",
            entity_type="submission",
            entity_id=submission_id,
            payload_json={
                "assessment_id": assessment_id,
                "submission_id": submission_id,
                "answer_region_ids": answer_region_ids,
                "artifact_paths_deleted": relative_paths,
            },
        )
    )
    db.commit()

    LocalStorage().delete_submission_files(submission_id, relative_paths)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/submission-pages/{page_id}/image")
def get_submission_page_image(
    page_id: int, db: DbSession, current_user: CurrentUser
) -> FileResponse:
    page = get_owned_submission_page_or_404(page_id, db, current_user)
    path = LocalStorage().resolve_relative(page.image_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )
    return FileResponse(path, media_type="image/png")
