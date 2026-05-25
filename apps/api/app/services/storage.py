from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings


@dataclass(frozen=True)
class StoredFile:
    absolute_path: Path
    relative_path: str


class LocalStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.root = Path(settings.local_storage_root).resolve()
        self.uploads_dir = Path(settings.uploads_dir).resolve()
        self.artifacts_dir = Path(settings.artifacts_dir).resolve()
        for directory in (self.root, self.uploads_dir, self.artifacts_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def relative_to_root(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stored path escaped storage root",
            ) from exc
        return relative.as_posix()

    def resolve_relative(self, relative_path: str) -> Path:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        resolved = (self.root / relative_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found",
            ) from exc
        return resolved

    def save_upload(self, upload: UploadFile, submission_id: int, suffix: str) -> StoredFile:
        safe_suffix = suffix.lower()
        filename = f"original-{uuid4().hex}{safe_suffix}"
        target_dir = self.uploads_dir / "submissions" / str(submission_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        return StoredFile(target, self.relative_to_root(target))

    def page_image_path(self, submission_id: int, page_no: int) -> StoredFile:
        target_dir = self.artifacts_dir / "pages" / f"submission_{submission_id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"page_{page_no:04d}.png"
        return StoredFile(target, self.relative_to_root(target))
