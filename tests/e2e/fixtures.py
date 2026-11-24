"""Programmatic image & payload fixtures + real CV test sample discovery for Tastoria E2E."""

from __future__ import annotations

import io
import os
import struct
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_YOLO_TEST_DIR = REPO_ROOT / "data" / "processed" / "cv" / "yolo" / "images" / "test"

MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # 3,145,728 bytes (backend/modules/scan/images.py)
MAX_PIXELS = 4096 * 4096


def get_real_scan_image_path(max_bytes: int = 400_000) -> Path | None:
    """Return a real produce test image from data/processed/cv/yolo/images/test/ if present."""
    if not REAL_YOLO_TEST_DIR.is_dir():
        return None
    candidates = sorted(REAL_YOLO_TEST_DIR.glob("*.jpg"))
    for pattern in ("openimages_", "mendeley_bd__test__"):
        for p in candidates:
            if p.name.startswith(pattern) and p.stat().st_size <= max_bytes:
                return p
    for p in candidates:
        if p.stat().st_size <= MAX_UPLOAD_BYTES:
            return p
    return None


def make_produce_jpeg(width: int = 640, height: int = 480) -> bytes:
    """Create a valid RGB JPEG resembling produce (tomato/leaf shapes) for deterministic scan tests."""
    img = Image.new("RGB", (width, height), (242, 238, 228))
    draw = ImageDraw.Draw(img)
    # Red tomato-like circle
    draw.ellipse([90, 110, 250, 270], fill=(198, 45, 36), outline=(120, 25, 20), width=3)
    draw.polygon([(165, 108), (180, 92), (195, 110), (175, 120)], fill=(46, 118, 56))
    # Green leafy bundle
    draw.ellipse([320, 140, 540, 320], fill=(54, 132, 66), outline=(32, 86, 40), width=3)
    # Egg oval
    draw.ellipse([240, 290, 350, 420], fill=(238, 224, 198), outline=(185, 165, 135), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def get_scan_sample_jpeg() -> bytes:
    """Return real produce test JPEG if synced, otherwise programmatic produce JPEG."""
    real = get_real_scan_image_path()
    if real is not None:
        return real.read_bytes()
    return make_produce_jpeg()


def make_exif_gps_orientation6_jpeg(width: int = 400, height: int = 240) -> bytes:
    """Create a JPEG with EXIF Orientation=6 (rotated) and GPS IFD tag (0x8825) to verify sanitization."""
    img = Image.new("RGB", (width, height), (190, 80, 50))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], fill=(55, 135, 70))

    # Build a minimal valid TIFF/EXIF APP1 containing IFD0 with Orientation=6 and GPSInfoIFDPointer (0x8825)
    tiff_header = b"II*\x00\x08\x00\x00\x00"  # Little-endian TIFF, IFD0 at offset 8
    # IFD0: 2 entries (Orientation 0x0112 = 6, GPSInfo 0x8825 -> offset 38)
    ifd0_count = struct.pack("<H", 2)
    entry_orient = struct.pack("<HHII", 0x0112, 3, 1, 6)
    entry_gps = struct.pack("<HHII", 0x8825, 4, 1, 38)
    next_ifd0 = struct.pack("<I", 0)
    # GPS IFD at offset 38: 1 entry (GPSLatitudeRef 0x0001 = 'N\x00\x00\x00')
    gps_count = struct.pack("<H", 1)
    gps_entry = struct.pack("<HHII", 0x0001, 2, 2, int.from_bytes(b"N\x00\x00\x00", "little"))
    next_gps = struct.pack("<I", 0)
    exif_payload = b"Exif\x00\x00" + tiff_header + ifd0_count + entry_orient + entry_gps + next_ifd0 + gps_count + gps_entry + next_gps
    app1_seg = b"\xff\xe1" + struct.pack(">H", len(exif_payload) + 2) + exif_payload

    # Re-save clean JPEG without exif, then insert APP1 right after SOI (FF D8)
    clean_buf = io.BytesIO()
    img.save(clean_buf, format="JPEG", quality=88)
    clean_jpeg = clean_buf.getvalue()
    assert clean_jpeg[:2] == b"\xff\xd8"
    return clean_jpeg[:2] + app1_seg + clean_jpeg[2:]


def make_oversized_jpeg(min_bytes: int = MAX_UPLOAD_BYTES + 1024) -> bytes:
    """Create a valid-header JPEG strictly larger than 3 MB (3,145,728 bytes) -> 413 image_too_large."""
    base = make_produce_jpeg(640, 480)
    # Append JPEG-valid padding inside a COM (0xFFFE) segment before EOI so it's structurally valid JPEG > 3MB
    pad_needed = max(1, min_bytes - len(base))
    chunks: list[bytes] = [base[:-2]]
    remaining = pad_needed
    while remaining > 0:
        chunk_len = min(remaining, 60000)
        chunks.append(b"\xff\xfe" + struct.pack(">H", chunk_len + 2) + (b"T" * chunk_len))
        remaining -= chunk_len
    chunks.append(b"\xff\xd9")
    data = b"".join(chunks)
    assert len(data) > MAX_UPLOAD_BYTES
    return data


def make_oversized_pixels_jpeg() -> bytes:
    """Create a 4097x4096 solid-color JPEG (< 3 MB file size, > 4096*4096 pixels) -> 422 image_too_many_pixels."""
    img = Image.new("RGB", (4097, 4096), (240, 236, 224))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=30)
    data = buf.getvalue()
    assert len(data) <= MAX_UPLOAD_BYTES, f"4097x4096 JPEG exceeded MAX_BYTES: {len(data)}"
    return data


def make_valid_png_bytes(width: int = 128, height: int = 128) -> bytes:
    """Create a valid PNG image (accepted by backend scan sanitize & converted to JPEG)."""
    img = Image.new("RGB", (width, height), (60, 140, 75))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_spoofed_pdf_bytes() -> bytes:
    """Create a %PDF-1.7 payload masquerading as a .jpg -> 415 unsupported_media_type."""
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def make_corrupt_jpeg_bytes() -> bytes:
    """Create a truncated/corrupt JPEG magic header payload -> 415 unsupported_media_type."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdaTRUNCATED"


def write_temp_scan_file(tmp_dir: Path, filename: str = "scan_produce.jpg", data: bytes | None = None) -> Path:
    """Write a JPEG fixture to tmp_dir for Playwright file-chooser upload."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / filename
    target.write_bytes(data if data is not None else get_scan_sample_jpeg())
    return target
