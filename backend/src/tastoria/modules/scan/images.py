"""Upload checks and sanitising of scan photos (spec v2 §8, FR-12-02 … FR-12-05).

Order: size (413) → magic bytes (415) → header pixel count (422, before any pixel is decoded) → full decode with
Pillow's decompression-bomb guard turned into an error → `ImageOps.exif_transpose` → re-encode as baseline JPEG
from a fresh RGB buffer, so no EXIF (GPS, orientation, maker notes), ICC, XMP or comment survives.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from tastoria.core.errors import ApiError, ProblemCode

MAX_BYTES = 3 * 1024 * 1024  # 3 MB = 3 145 728 bytes (FR-12-02)
MAX_PIXELS = 4096 * 4096  # FR-12-04
JPEG_QUALITY = 90

Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # above it Pillow warns; the warning is raised as an error in `sanitize`

# magic bytes -> Pillow format; the app sends JPEG, PNG/WebP from a gallery are accepted and converted
_MAGIC = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
)


def sniff(data: bytes) -> str | None:
    for sig, fmt in _MAGIC:
        if data.startswith(sig):
            return fmt
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


@dataclass(frozen=True)
class CleanImage:
    jpeg: bytes
    width: int
    height: int


def _field(index: int) -> list[dict[str, str]]:
    return [{"pointer": f"/images/{index}", "code": "image", "message": f"ảnh thứ {index + 1}"}]


def sanitize(data: bytes, index: int = 0) -> CleanImage:
    if len(data) > MAX_BYTES:
        raise ApiError(413, ProblemCode.image_too_large, f"Ảnh lớn hơn {MAX_BYTES} byte.", errors=_field(index))
    fmt = sniff(data)
    if fmt is None:
        raise ApiError(
            415, ProblemCode.unsupported_media_type, "Tệp không phải ảnh JPEG/PNG/WebP.", errors=_field(index)
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[fmt]) as im:
                w, h = im.size
                if w * h > MAX_PIXELS:
                    raise ApiError(
                        422,
                        ProblemCode.image_too_many_pixels,
                        f"Ảnh {w}×{h} vượt 4096×4096 điểm ảnh.",
                        errors=_field(index),
                    )
                im.load()
                upright = ImageOps.exif_transpose(im)
                rgb = upright.convert("RGB")
    except ApiError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ApiError(422, ProblemCode.image_too_many_pixels, str(exc), errors=_field(index)) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:  # truncated / corrupt payload
        raise ApiError(
            415, ProblemCode.unsupported_media_type, "Không giải mã được ảnh.", errors=_field(index)
        ) from exc
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())  # fresh buffer: no info dict, no metadata
    buf = io.BytesIO()
    clean.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return CleanImage(buf.getvalue(), clean.width, clean.height)
