from decimal import Decimal

import pytest
from PIL import Image

from app.core.config import get_settings
from app.services.answer_region_processing import (
    crop_answer_region_image,
    crop_grading_context_image,
)
from app.services.storage import LocalStorage


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        yield LocalStorage()
    finally:
        get_settings.cache_clear()


def make_source_page(storage: LocalStorage, submission_id: int, size: tuple[int, int]) -> str:
    stored = storage.page_image_path(submission_id, 1)
    Image.new("RGB", size, color="white").save(stored.absolute_path, format="PNG")
    return stored.relative_path


def test_grading_context_crop_padding_clamps_to_page_bounds(storage: LocalStorage) -> None:
    source_path = make_source_page(storage, submission_id=1, size=(100, 80))

    padded_relative_path = crop_grading_context_image(
        storage=storage,
        source_image_path=source_path,
        submission_id=1,
        x=Decimal("0"),
        y=Decimal("0"),
        width=Decimal("20"),
        height=Decimal("20"),
        padding_ratio=0.50,
    )

    padded_path = storage.resolve_relative(padded_relative_path)
    with Image.open(padded_path) as padded_image:
        assert padded_image.size == (30, 30)


def test_original_answer_region_crop_remains_unpadded(storage: LocalStorage) -> None:
    source_path = make_source_page(storage, submission_id=2, size=(100, 80))

    cropped_relative_path = crop_answer_region_image(
        storage=storage,
        source_image_path=source_path,
        submission_id=2,
        x=Decimal("10"),
        y=Decimal("10"),
        width=Decimal("20"),
        height=Decimal("20"),
    )

    cropped_path = storage.resolve_relative(cropped_relative_path)
    with Image.open(cropped_path) as cropped_image:
        assert cropped_image.size == (20, 20)
