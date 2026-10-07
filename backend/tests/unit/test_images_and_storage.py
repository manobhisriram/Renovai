from __future__ import annotations

import io

import pytest
from PIL import Image

from app.storage.local import LocalStorage
from app.utils.errors import ValidationFailed
from app.vision.cv import analyze_image_bytes
from app.vision.images import process_upload, safe_display_name
from tests.conftest import jpeg_bytes, make_settings


def test_valid_jpeg_is_reencoded_and_metadata_stripped(tmp_path):
    img = Image.new("RGB", (900, 700), (100, 120, 140))
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    exif[0x8825] = {1: "N"}  # GPS IFD marker
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    out = process_upload(buf.getvalue(), make_settings(tmp_path))
    assert out.content_type == "image/jpeg" and out.width == 900
    assert b"SecretCameraMaker" not in out.data and Image.open(io.BytesIO(out.data)).getexif().get(0x010F) is None


@pytest.mark.parametrize("payload,why", [
    (b"", "empty"),
    (b"<?php system($_GET['c']); ?>", "script"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "svg"),
    (b"GIF89a" + b"\x00" * 20, "truncated gif"),
    (b"\xff\xd8\xff\xe0" + b"garbage", "fake jpeg header"),
])
def test_non_images_are_rejected(tmp_path, payload, why):
    with pytest.raises(ValidationFailed):
        process_upload(payload, make_settings(tmp_path))


def test_gif_even_if_valid_is_rejected_by_format_allowlist(tmp_path):
    buf = io.BytesIO()
    Image.new("P", (10, 10)).save(buf, "GIF")
    with pytest.raises(ValidationFailed, match="Unsupported image format"):
        process_upload(buf.getvalue(), make_settings(tmp_path))


def test_size_and_pixel_limits(tmp_path):
    with pytest.raises(ValidationFailed, match="larger than"):
        process_upload(jpeg_bytes(size=(1600, 1200)) * 1, make_settings(tmp_path, max_upload_mb=0))
    with pytest.raises(ValidationFailed):
        process_upload(jpeg_bytes(size=(2000, 2000)), make_settings(tmp_path, max_image_pixels=1000))


def test_large_images_are_downscaled(tmp_path):
    out = process_upload(jpeg_bytes(size=(4000, 3000)), make_settings(tmp_path))
    assert max(out.width, out.height) == 3000


@pytest.mark.parametrize("name,expected", [("../../etc/passwd", "passwd"), ("a b<script>.jpg", "a b_script_.jpg"), ("", "image"), ("C:\\x\\y.png", "y.png")])
def test_display_filename_sanitised(name, expected):
    assert safe_display_name(name) == expected


def test_local_storage_blocks_traversal_and_roundtrips(tmp_path):
    st = LocalStorage(str(tmp_path / "root"))
    st.put("projects/p1/a.jpg", b"data", "image/jpeg")
    assert st.get("projects/p1/a.jpg") == b"data" and st.healthy()
    for bad in ("../escape.jpg", "/abs/path.jpg", "projects/../../x", "a//b", "bad key.jpg", "x\\y"):
        with pytest.raises(ValueError):
            st.put(bad, b"x", "image/jpeg")
    st.delete("projects/p1/a.jpg")
    assert not (tmp_path / "root" / "projects" / "p1" / "a.jpg").exists()


def test_cv_layer_measures_real_properties():
    dark = analyze_image_bytes(jpeg_bytes(color=(15, 15, 15)))
    bright = analyze_image_bytes(jpeg_bytes(color=(240, 230, 220)))
    assert "too_dark" in dark.quality_flags and dark.brightness < bright.brightness
    warm = analyze_image_bytes(jpeg_bytes(color=(220, 150, 90)))
    cool = analyze_image_bytes(jpeg_bytes(color=(90, 150, 220)))
    assert warm.color_temperature == "warm" and cool.color_temperature == "cool"
    small = analyze_image_bytes(jpeg_bytes(size=(320, 240)))
    assert "low_resolution" in small.quality_flags and small.detector == "none" and small.detections == []
    assert len(warm.palette) >= 1 and abs(sum(c["share"] for c in warm.palette) - 1) < 0.05
