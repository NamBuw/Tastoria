"""Read-only real sample asset loaders and deterministic Pillow boundary builders for Tastoria E2E."""

from __future__ import annotations

import io
import struct
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FOOD_DIR = REPO_ROOT / "app" / "assets" / "food"
LANDING_IMG_DIR = REPO_ROOT / "landing" / "img"
YOLO_V4_DIR = REPO_ROOT / "data" / "processed" / "cv" / "yolo_v4"

MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # 3,145,728 bytes
MAX_PIXELS = 4096 * 4096


def get_app_food_asset(filename: str) -> bytes:
    """Load a real dish WEBP asset read-only from app/assets/food/ (deterministic fallback if absent)."""
    path = APP_FOOD_DIR / filename
    if path.is_file():
        return path.read_bytes()
    return make_dish_jpeg()


def get_landing_img_asset(filename: str) -> bytes:
    """Load a real landing image read-only from landing/img/ (deterministic fallback if absent)."""
    path = LANDING_IMG_DIR / filename
    if path.is_file():
        return path.read_bytes()
    return make_dish_jpeg()


def _find_nam_class_id() -> int:
    data_yaml = YOLO_V4_DIR / "data.yaml"
    if not data_yaml.is_file():
        return 21
    parsed = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    names = parsed.get("names", {})
    if isinstance(names, dict):
        for k, v in names.items():
            if str(v).strip() == "nam":
                return int(k)
    elif isinstance(names, list):
        for idx, v in enumerate(names):
            if str(v).strip() == "nam":
                return idx
    return 21


def discover_nam_test_jpegs(limit: int = 10, max_bytes: int = 1_500_000) -> list[Path]:
    """Discover real `nam` test JPEGs read-only via yolo_v4/data.yaml + labels/test/*.txt."""
    images_dir = YOLO_V4_DIR / "images" / "test"
    labels_dir = YOLO_V4_DIR / "labels" / "test"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        return []

    nam_id = _find_nam_class_id()
    prefix = f"{nam_id} "
    found: list[Path] = []
    for lbl in sorted(labels_dir.glob("*.txt")):
        try:
            lines = lbl.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if any(line.startswith(prefix) for line in lines):
            img_path = images_dir / f"{lbl.stem}.jpg"
            if img_path.is_file() and img_path.stat().st_size <= max_bytes:
                found.append(img_path)
                if len(found) >= limit:
                    break
    return found


def get_nam_sample_jpeg(index: int = 0) -> bytes:
    """Return a real mushroom (`nam`) test JPEG from yolo_v4, or deterministic Pillow fallback if dataset absent."""
    paths = discover_nam_test_jpegs(limit=max(5, index + 1))
    if paths:
        return paths[index % len(paths)].read_bytes()
    return make_mushroom_fallback_jpeg()


def get_produce_scan_jpeg() -> bytes:
    """Return a real produce test JPEG from yolo_v4/images/test/ or deterministic produce fallback."""
    images_dir = YOLO_V4_DIR / "images" / "test"
    if images_dir.is_dir():
        for p in sorted(images_dir.glob("*.jpg")):
            if 10_000 <= p.stat().st_size <= 500_000:
                return p.read_bytes()
    return make_produce_jpeg()


def make_produce_jpeg(width: int = 640, height: int = 480) -> bytes:
    """Create a deterministic RGB JPEG resembling produce for fallback/synthetic scan tests."""
    img = Image.new("RGB", (width, height), (242, 238, 228))
    draw = ImageDraw.Draw(img)
    draw.ellipse([90, 110, 250, 270], fill=(198, 45, 36), outline=(120, 25, 20), width=3)
    draw.polygon([(165, 108), (180, 92), (195, 110), (175, 120)], fill=(46, 118, 56))
    draw.ellipse([320, 140, 540, 320], fill=(54, 132, 66), outline=(32, 86, 40), width=3)
    draw.ellipse([240, 290, 350, 420], fill=(238, 224, 198), outline=(185, 165, 135), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_mushroom_fallback_jpeg(width: int = 480, height: int = 360) -> bytes:
    """Deterministic fallback mushroom-like image only used when yolo_v4 dataset is absent on remote host."""
    img = Image.new("RGB", (width, height), (235, 230, 220))
    draw = ImageDraw.Draw(img)
    draw.ellipse([140, 90, 340, 210], fill=(175, 150, 122), outline=(110, 90, 70), width=3)
    draw.rectangle([215, 200, 265, 310], fill=(242, 236, 224), outline=(190, 180, 165), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_dish_jpeg(width: int = 400, height: int = 300) -> bytes:
    """Deterministic dish JPEG for synthetic fallback or OOD probes."""
    img = Image.new("RGB", (width, height), (245, 240, 232))
    draw = ImageDraw.Draw(img)
    draw.ellipse([60, 40, 340, 260], fill=(255, 255, 255), outline=(210, 200, 185), width=4)
    draw.ellipse([110, 80, 280, 210], fill=(215, 135, 75))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def make_valid_png_bytes(width: int = 160, height: int = 160) -> bytes:
    """Create a valid PNG image."""
    img = Image.new("RGB", (width, height), (64, 142, 76))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_oversized_jpeg(min_bytes: int = MAX_UPLOAD_BYTES + 4096) -> bytes:
    """Create a valid-header JPEG strictly larger than 3 MB (3,145,728 bytes) -> 413 image_too_large."""
    base = make_produce_jpeg(640, 480)
    pad_needed = max(1, min_bytes - len(base))
    chunks: list[bytes] = [base[:-2]]
    remaining = pad_needed
    while remaining > 0:
        chunk_len = min(remaining, 60_000)
        chunks.append(b"\xff\xfe" + struct.pack(">H", chunk_len + 2) + (b"T" * chunk_len))
        remaining -= chunk_len
    chunks.append(b"\xff\xd9")
    data = b"".join(chunks)
    assert len(data) > MAX_UPLOAD_BYTES
    return data


def make_oversized_pixels_jpeg() -> bytes:
    """Create a 4097x4096 solid-color JPEG (< 3 MB file size, > 4096x4096 pixels) -> 422 image_too_many_pixels."""
    img = Image.new("RGB", (4097, 4096), (240, 236, 224))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=30)
    data = buf.getvalue()
    assert len(data) <= MAX_UPLOAD_BYTES, f"4097x4096 JPEG exceeded MAX_UPLOAD_BYTES: {len(data)}"
    return data


def make_oversized_pixels_png() -> bytes:
    """Create a 4097x4096 solid-color PNG (< 3 MB file size, > 4096x4096 pixels) -> 422 image_too_many_pixels."""
    img = Image.new("RGB", (4097, 4096), (240, 236, 224))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=9)
    data = buf.getvalue()
    assert len(data) <= MAX_UPLOAD_BYTES, f"4097x4096 PNG exceeded MAX_UPLOAD_BYTES: {len(data)}"
    return data


def make_spoofed_pdf_bytes() -> bytes:
    """Create a %PDF-1.7 payload masquerading as an image -> 415 unsupported_media_type."""
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def make_corrupt_jpeg_bytes() -> bytes:
    """Create a truncated/corrupt JPEG magic-header payload -> 415 unsupported_media_type."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdaTRUNCATED"


def make_exif_gps_orientation6_jpeg(width: int = 400, height: int = 240) -> bytes:
    """Create a JPEG with EXIF Orientation=6 and GPS IFD tag (0x8825) to verify sanitization."""
    img = Image.new("RGB", (width, height), (190, 80, 50))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], fill=(55, 135, 70))

    tiff_header = b"II*\x00\x08\x00\x00\x00"
    ifd0_count = struct.pack("<H", 2)
    entry_orient = struct.pack("<HHII", 0x0112, 3, 1, 6)
    entry_gps = struct.pack("<HHII", 0x8825, 4, 1, 38)
    next_ifd0 = struct.pack("<I", 0)
    gps_count = struct.pack("<H", 1)
    gps_entry = struct.pack("<HHII", 0x0001, 2, 2, int.from_bytes(b"N\x00\x00\x00", "little"))
    next_gps = struct.pack("<I", 0)
    exif_payload = (
        b"Exif\x00\x00"
        + tiff_header
        + ifd0_count
        + entry_orient
        + entry_gps
        + next_ifd0
        + gps_count
        + gps_entry
        + next_gps
    )
    app1_seg = b"\xff\xe1" + struct.pack(">H", len(exif_payload) + 2) + exif_payload

    clean_buf = io.BytesIO()
    img.save(clean_buf, format="JPEG", quality=88)
    clean_jpeg = clean_buf.getvalue()
    assert clean_jpeg[:2] == b"\xff\xd8"
    return clean_jpeg[:2] + app1_seg + clean_jpeg[2:]
