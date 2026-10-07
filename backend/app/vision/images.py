"""Secure image intake: validate by decoding (not by trusting headers), strip metadata by re-encoding."""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.utils.errors import ValidationFailed

ALLOWED = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
MAX_SIDE = 3000


@dataclass
class ProcessedImage:
    data: bytes
    content_type: str
    ext: str
    width: int
    height: int
    sha256: str


def safe_display_name(filename: str | None) -> str:
    """Filename for display only; never used to build storage paths."""
    base = (filename or "image").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._\- ]", "_", base)[:120].strip(" .")
    return base or "image"


def new_storage_key(project_id: str, ext: str) -> str:
    return f"projects/{project_id}/{uuid.uuid4().hex}.{ext}"


def process_upload(data: bytes, settings: Settings) -> ProcessedImage:
    if not data:
        raise ValidationFailed("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise ValidationFailed(f"Image is larger than {settings.max_upload_mb} MB. Compress it and try again.")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img: Image.Image = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise ValidationFailed("The file is not a valid image. Upload a JPEG, PNG or WebP photo.") from exc
    if fmt not in ALLOWED:
        raise ValidationFailed(f"Unsupported image format '{fmt or 'unknown'}'. Upload a JPEG, PNG or WebP photo.")
    content_type, ext = ALLOWED[fmt]
    img = ImageOps.exif_transpose(img)  # honour orientation, then drop all metadata on re-encode
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    elif fmt == "PNG":
        img.save(out, "PNG", optimize=True)
    else:
        img.save(out, "WEBP", quality=90)
    clean = out.getvalue()
    return ProcessedImage(clean, content_type, ext, img.width, img.height, hashlib.sha256(clean).hexdigest())


def to_llm_image(data: bytes, max_side: int = 1568) -> dict[str, str]:
    """Downscale to a model-friendly JPEG and return a base64 image part."""
    import base64

    with Image.open(io.BytesIO(data)) as src:
        rgb = src.convert("RGB")
    if max(rgb.size) > max_side:
        rgb.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=85)
    return {"media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}
