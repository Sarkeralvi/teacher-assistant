from decimal import Decimal

from fastapi import HTTPException, status
from PIL import Image, ImageDraw

from app.services.storage import LocalStorage


def crop_answer_region_image(
    storage: LocalStorage,
    source_image_path: str,
    submission_id: int,
    x: Decimal,
    y: Decimal,
    width: Decimal,
    height: Decimal,
) -> str:
    source_path = storage.resolve_relative(source_image_path)
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )

    with Image.open(source_path) as image:
        left = float(x)
        top = float(y)
        right = left + float(width)
        bottom = top + float(height)
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Crop rectangle must fit within source image bounds",
            )
        cropped = image.crop((left, top, right, bottom))
        stored = storage.answer_region_image_path(submission_id)
        cropped.save(stored.absolute_path, format="PNG")
        return stored.relative_path


def crop_grading_context_image(
    storage: LocalStorage,
    source_image_path: str,
    submission_id: int,
    x: Decimal,
    y: Decimal,
    width: Decimal,
    height: Decimal,
    padding_ratio: float,
) -> str:
    """Create an AI-grading-only padded crop while preserving original region data."""
    source_path = storage.resolve_relative(source_image_path)
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )

    safe_padding_ratio = max(0.0, min(float(padding_ratio), 0.5))
    with Image.open(source_path) as image:
        left = float(x)
        top = float(y)
        right = left + float(width)
        bottom = top + float(height)
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Crop rectangle must fit within source image bounds",
            )
        pad_x = float(width) * safe_padding_ratio
        pad_y = float(height) * safe_padding_ratio
        padded_left = max(0.0, left - pad_x)
        padded_top = max(0.0, top - pad_y)
        padded_right = min(float(image.width), right + pad_x)
        padded_bottom = min(float(image.height), bottom + pad_y)
        cropped = image.crop((padded_left, padded_top, padded_right, padded_bottom))
        stored = storage.grading_context_image_path(submission_id)
        cropped.save(stored.absolute_path, format="PNG")
        return stored.relative_path


def create_composite_grading_context_image(
    storage: LocalStorage,
    submission_id: int,
    segments: list[dict[str, object]],
) -> str:
    """Stack confirmed answer segment crops into one auditable grading context image."""
    if not segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one answer segment is required",
        )
    opened: list[tuple[str, Image.Image]] = []
    try:
        for segment in segments:
            image_path = str(segment["image_path"])
            path = storage.resolve_relative(image_path)
            if not path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Answer segment image is missing",
                )
            label = str(segment.get("label") or "Segment")
            opened.append((label, Image.open(path).convert("RGB")))

        label_height = 32
        gap = 12
        padding = 12
        width = max(image.width for _label, image in opened) + padding * 2
        height = padding + sum(label_height + image.height + gap for _label, image in opened)
        composite = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(composite)
        y = padding
        for label, image in opened:
            draw.text((padding, y), label, fill="black")
            y += label_height
            composite.paste(image, (padding, y))
            y += image.height + gap
        stored = storage.grading_context_image_path(submission_id)
        composite.save(stored.absolute_path, format="PNG")
        return stored.relative_path
    finally:
        for _label, image in opened:
            image.close()
