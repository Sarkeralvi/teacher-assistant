import base64
import mimetypes
from pathlib import Path


class BrainImageInputError(RuntimeError):
    """Raised when cropped answer image input cannot be prepared safely."""


_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg"}


def build_image_data_url(*, image_path: str, storage_root: str) -> str:
    root = Path(storage_root).resolve()
    candidate = Path(image_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrainImageInputError("Image input path escaped storage root") from exc
    if not resolved.is_file():
        raise BrainImageInputError(
            "Image input enabled but cropped answer image is missing"
        )
    mime_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    if mime_type not in _ALLOWED_MIME_TYPES:
        raise BrainImageInputError("Image input must be PNG or JPEG")
    image_bytes = resolved.read_bytes()
    if not _looks_like_supported_image(image_bytes, mime_type):
        raise BrainImageInputError("Image input is not a readable PNG/JPEG file")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"{mime_type};base64,{encoded}".join(("data:", ""))


def _looks_like_supported_image(image_bytes: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return image_bytes.startswith(b"\xff\xd8") and image_bytes.endswith(b"\xff\xd9")
    return False
