"""Upload attacks and sanitising (FR-12-02 … FR-12-05): size, magic bytes, pixel bombs, EXIF/GPS stripping."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from tastoria.core.errors import ApiError
from tastoria.modules.scan.images import MAX_BYTES, sanitize, sniff


def jpeg(w: int = 64, h: int = 48, *, exif: bytes | None = None, color=(200, 30, 30), quality: int = 90) -> bytes:  # noqa: ANN001
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=quality, **kw)
    return buf.getvalue()


def gps_exif(orientation: int = 6) -> bytes:
    ex = Image.Exif()
    ex[0x0112] = orientation  # Orientation: 6 = rotate 90° CW to display
    ex[0x010F] = "TestCam"  # Make
    gps = {1: "N", 2: (21.0, 1.0, 30.0), 3: "E", 4: (105.0, 51.0, 0.0)}  # Hà Nội
    ex[0x8825] = gps
    return ex.tobytes()


def _code(exc: pytest.ExceptionInfo[ApiError]) -> tuple[int, str]:
    return exc.value.status, exc.value.code.value


def test_exif_orientation_applied_and_every_metadata_block_dropped() -> None:
    raw = jpeg(64, 48, exif=gps_exif(6))
    assert b"Exif" in raw and b"TestCam" in raw
    out = sanitize(raw)
    assert (out.width, out.height) == (48, 64)  # rotated per Orientation = 6 (FR-12-05)
    with Image.open(io.BytesIO(out.jpeg)) as im:
        assert im.format == "JPEG"
        assert im.size == (48, 64)
        assert not im.getexif()  # no EXIF at all, so no GPS IFD
        assert "exif" not in im.info and "icc_profile" not in im.info
    assert b"Exif" not in out.jpeg and b"TestCam" not in out.jpeg
    assert b"\xff\xe1" not in out.jpeg  # no APP1 segment (EXIF / XMP)


def test_png_and_webp_are_reencoded_as_jpeg() -> None:
    for fmt in ("PNG", "WEBP"):
        buf = io.BytesIO()
        Image.new("RGBA", (30, 20), (1, 2, 3, 128)).save(buf, fmt)
        out = sanitize(buf.getvalue())
        assert out.jpeg[:3] == b"\xff\xd8\xff" and (out.width, out.height) == (30, 20)


def test_fake_extension_pdf_is_415() -> None:
    pdf = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
    with pytest.raises(ApiError) as e:
        sanitize(pdf)
    assert _code(e) == (415, "unsupported_media_type")


def test_jpeg_magic_with_garbage_body_is_415() -> None:
    with pytest.raises(ApiError) as e:
        sanitize(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    assert _code(e) == (415, "unsupported_media_type")


def test_svg_or_html_disguised_is_415() -> None:
    assert sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    with pytest.raises(ApiError) as e:
        sanitize(b"<html><script>alert(1)</script></html>")
    assert _code(e) == (415, "unsupported_media_type")


def test_size_limit_is_3_mb_exactly() -> None:
    small = jpeg()
    with pytest.raises(ApiError) as e:
        sanitize(small + b"\x00" * (MAX_BYTES + 1 - len(small)))
    assert _code(e) == (413, "image_too_large")
    padded = small + b"\x00" * (MAX_BYTES - len(small))  # trailing bytes after EOI are ignored by decoders
    assert sanitize(padded).width == 64


def test_pixel_bomb_is_refused_before_decoding() -> None:
    raw = jpeg(4097, 4096, quality=10)  # 16 781 312 px > 4096², a few hundred kB
    with pytest.raises(ApiError) as e:
        sanitize(raw)
    assert _code(e) == (422, "image_too_many_pixels")


def test_header_claiming_huge_size_is_refused() -> None:
    # a tiny PNG whose IHDR says 30000 x 30000: refused from the header, nothing allocated
    buf = io.BytesIO()
    Image.new("L", (1, 1)).save(buf, "PNG")
    data = bytearray(buf.getvalue())
    data[16:24] = (30000).to_bytes(4, "big") * 2  # IHDR width, height (CRC now wrong; header read is enough)
    with pytest.raises(ApiError) as e:
        sanitize(bytes(data))
    assert _code(e)[0] in (415, 422)


def test_4096_square_is_accepted() -> None:
    out = sanitize(jpeg(4096, 4096, quality=10))
    assert (out.width, out.height) == (4096, 4096)
