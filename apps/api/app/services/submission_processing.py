from pathlib import Path

import fitz
from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.services.storage import LocalStorage

_ALLOWED_SUFFIXES = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}
_ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
}


def classify_upload(upload: UploadFile) -> tuple[str, str]:
    suffix = Path(upload.filename or "").suffix.lower()
    suffix_kind = _ALLOWED_SUFFIXES.get(suffix)
    content_kind = _ALLOWED_CONTENT_TYPES.get(upload.content_type or "")
    kind = suffix_kind or content_kind
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported submission file type",
        )
    if suffix not in _ALLOWED_SUFFIXES:
        suffix = ".pdf" if kind == "pdf" else ".png"
    return kind, suffix


def extract_page_images(
    *,
    storage: LocalStorage,
    submission_id: int,
    uploaded_path: Path,
    kind: str,
) -> list[str]:
    if kind == "image":
        return [_store_image_page(storage, submission_id, uploaded_path, 1)]
    if kind == "pdf":
        return _store_pdf_pages(storage, submission_id, uploaded_path)
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported submission file type",
    )


def _store_image_page(
    storage: LocalStorage, submission_id: int, uploaded_path: Path, page_no: int
) -> str:
    output = storage.page_image_path(submission_id, page_no)
    try:
        with Image.open(uploaded_path) as image:
            image.convert("RGB").save(output.absolute_path, format="PNG")
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image could not be decoded",
        ) from exc
    return output.relative_path


def _store_pdf_pages(storage: LocalStorage, submission_id: int, uploaded_path: Path) -> list[str]:
    try:
        doc = fitz.open(uploaded_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF could not be decoded",
        ) from exc
    try:
        if len(doc) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded PDF has no pages",
            )
        paths: list[str] = []
        for index in range(len(doc)):
            page_no = index + 1
            page = doc.load_page(index)
            output = storage.page_image_path(submission_id, page_no)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(output.absolute_path)
            paths.append(output.relative_path)
        return paths
    finally:
        doc.close()
