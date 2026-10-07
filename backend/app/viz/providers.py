"""AI visualisation providers. Output is ALWAYS stamped as illustrative - never a construction drawing."""

from __future__ import annotations

import base64
import io
from typing import Protocol

import httpx
from PIL import Image, ImageDraw

from app.config import Settings
from app.utils.errors import ExternalServiceError, ServiceNotConfigured

DISCLAIMER = "AI visualisation - illustrative only. Not a construction drawing."
SAFE_SUFFIX = ("Photorealistic interior visualisation. Keep the room's layout, windows and doors unchanged. "
               "Do not add text or logos.")


class VisualizationProvider(Protocol):
    name: str

    def generate(self, prompt: str, source_image: bytes | None) -> bytes: ...


class NoVisualization:
    name = "none"

    def generate(self, prompt: str, source_image: bytes | None) -> bytes:
        raise ServiceNotConfigured("No image-generation provider is configured. Set VIZ_PROVIDER=openai_images and OPENAI_API_KEY to enable visualisations.")


class OpenAIImages:
    name = "openai_images"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if settings.openai_api_key is None:
            raise ServiceNotConfigured("OPENAI_API_KEY is required for VIZ_PROVIDER=openai_images")
        self._key = settings.openai_api_key.get_secret_value()
        self._base = settings.openai_base_url.rstrip("/")
        self._model = settings.viz_openai_model
        self._client = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))

    def generate(self, prompt: str, source_image: bytes | None) -> bytes:
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if source_image:
                r = self._client.post(f"{self._base}/images/edits", headers=headers, data={"model": self._model, "prompt": prompt},
                                      files={"image": ("room.png", source_image, "image/png")})
            else:
                r = self._client.post(f"{self._base}/images/generations", headers=headers, json={"model": self._model, "prompt": prompt})
        except httpx.HTTPError as exc:
            raise ExternalServiceError("The image provider is unreachable.") from exc
        if r.status_code >= 400:
            raise ExternalServiceError(f"The image provider rejected the request (HTTP {r.status_code}).")
        b64 = (r.json().get("data") or [{}])[0].get("b64_json")
        if not b64:
            raise ExternalServiceError("The image provider returned no image.")
        return base64.b64decode(b64)


def stamp_disclaimer(png_or_jpeg: bytes) -> bytes:
    with Image.open(io.BytesIO(png_or_jpeg)) as src:
        im = src.convert("RGB")
    draw = ImageDraw.Draw(im)
    band = max(22, im.height // 28)
    draw.rectangle([0, im.height - band, im.width, im.height], fill=(20, 20, 20))
    draw.text((10, im.height - band + band // 4), DISCLAIMER, fill=(240, 240, 240))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def build_prompt(user_prompt: str, *, style: str | None, category: str | None, constraints: list[str]) -> str:
    parts = [user_prompt.strip()[:600]]
    if style:
        parts.append(f"Style: {style}.")
    if category:
        parts.append(f"Project type: {category.replace('_', ' ')}.")
    if constraints:
        parts.append("Respect these constraints: " + "; ".join(constraints[:5]) + ".")
    parts.append(SAFE_SUFFIX)
    return " ".join(parts)


def build_viz_provider(settings: Settings) -> VisualizationProvider:
    return OpenAIImages(settings) if settings.viz_provider == "openai_images" else NoVisualization()
