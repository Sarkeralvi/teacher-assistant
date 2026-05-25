from decimal import Decimal

from fastapi import HTTPException, status
from PIL import Image

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
