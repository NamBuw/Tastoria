"""Private ONNXRuntime CPU meal-calorie estimator (pure numpy + PIL + onnxruntime)."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.health import metrics

MAX_BYTES = 3 * 1024 * 1024  # 3 MB
MAX_PIXELS = 4096 * 4096
MAX_INFER_EDGE = 640
DEFAULT_SIZE = 224
DEFAULT_PAD = 128
VISUAL_HALF_WIDTH_REL = 0.35

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)

ONNX_INFER_SEMAPHORE = threading.BoundedSemaphore(2)
INFER_ACQUIRE_TIMEOUT_S = 3.0


@contextmanager
def onnx_infer_slot(model_name: str, *, timeout_s: float | None = None) -> Iterator[None]:
    """Bound concurrent CPU ONNX executions (max 2) and fail fast with 503 on contention."""
    limit = INFER_ACQUIRE_TIMEOUT_S if timeout_s is None else timeout_s
    if not ONNX_INFER_SEMAPHORE.acquire(timeout=limit):
        metrics.inc_onnx_contention(model_name)
        raise ApiError(
            503,
            ProblemCode.temporarily_unavailable,
            "Hệ thống đang bận ước lượng dinh dưỡng, vui lòng thử lại sau.",
            headers={"Retry-After": "2"},
        )
    t0 = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        metrics.observe_onnx(model_name, time.perf_counter() - t0, outcome=outcome)
        ONNX_INFER_SEMAPHORE.release()

# Physically plausible single-meal upper bounds matching [kcal, mass_g, fat_g, carb_g, protein_g].
# Nutrition5k train max kcal is 1324.1 and test max is 1050.5, so valid meals are unaffected.
MAX_KCAL = 3500.0
MAX_MASS_G = 3000.0
MAX_FAT_G = 250.0
MAX_CARB_G = 400.0
MAX_PROTEIN_G = 250.0
PHYSICAL_UPPER_BOUNDS = np.array([MAX_KCAL, MAX_MASS_G, MAX_FAT_G, MAX_CARB_G, MAX_PROTEIN_G], dtype=np.float64)

OOD_WARNING_NOTE = (
    "Cảnh báo OOD: ảnh đầu vào có đặc trưng ngoài phân phối ảnh món ăn đã học; "
    "giá trị ước lượng đã được giới hạn trong ngưỡng vật lý an toàn và có thể không chính xác."
)

_MAGIC = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
)

DEFAULT_DOMAIN_SHIFT_NOTE = (
    "Ước lượng trực quan theo khẩu phần ảnh; "
    "món Việt dạng bát/canh/nước có sai số quy mô và dầu ẩn cao hơn, nên chọn tên món từ kho KB nếu biết."
)


class ArtifactIntegrityError(RuntimeError):
    """Raised when meal_calorie model artifact is missing or fails SHA-256 verification."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sniff(data: bytes) -> str | None:
    for sig, fmt in _MAGIC:
        if data.startswith(sig):
            return fmt
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _img_err() -> list[dict[str, str]]:
    return [{"pointer": "/image", "code": "image", "message": "ảnh bữa ăn không hợp lệ"}]


def _extract_focal_length_35mm(im: Image.Image) -> float | None:
    """Safely extract sanitized FocalLengthIn35mmFilm (tag 0xA405 / 41989) before EXIF stripping."""
    try:
        exif = im.getexif()
        if not exif:
            return None
        raw = None
        try:
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            if exif_ifd:
                raw = exif_ifd.get(41989)
        except Exception:
            raw = None
        if raw is None:
            raw = exif.get(41989)
        if raw is None:
            return None
        val = float(raw[0]) / float(raw[1]) if isinstance(raw, tuple) and len(raw) == 2 and raw[1] else float(raw)
        if 10.0 <= val <= 300.0:
            return round(val, 1)
    except Exception:
        return None
    return None


def sanitize_meal_image(data: bytes) -> Image.Image:
    """Validate upload bytes (size <= 3 MB, magic JPEG/PNG/WebP, <= 4096x4096) and return upright RGB Image."""
    if len(data) > MAX_BYTES:
        raise ApiError(413, ProblemCode.image_too_large, f"Ảnh lớn hơn {MAX_BYTES} byte.", errors=_img_err())
    fmt = _sniff(data)
    if fmt is None:
        raise ApiError(
            415, ProblemCode.unsupported_media_type, "Tệp không phải ảnh JPEG/PNG/WebP.", errors=_img_err()
        )
    focal_35mm: float | None = None
    try:
        with Image.open(io.BytesIO(data), formats=[fmt]) as im:
            w, h = im.size
            if w <= 0 or h <= 0:
                raise ApiError(415, ProblemCode.unsupported_media_type, "Không giải mã được ảnh.", errors=_img_err())
            if w * h > MAX_PIXELS:
                raise ApiError(
                    422,
                    ProblemCode.image_too_many_pixels,
                    f"Ảnh {w}×{h} vượt 4096×4096 điểm ảnh.",
                    errors=_img_err(),
                )
            focal_35mm = _extract_focal_length_35mm(im)
            orientation = im.getexif().get(0x0112, 1)
            if fmt == "JPEG":
                im.draft("RGB", (MAX_INFER_EDGE, MAX_INFER_EDGE))
            im.load()
            upright = ImageOps.exif_transpose(im) if orientation != 1 else im
            rgb = upright if upright.mode == "RGB" else upright.convert("RGB")
            if max(rgb.size) > MAX_INFER_EDGE:
                rgb = rgb.copy() if rgb is im else rgb
                rgb.thumbnail((MAX_INFER_EDGE, MAX_INFER_EDGE), Image.Resampling.BILINEAR)
            raw_bytes = rgb.tobytes()
            final_size = rgb.size
    except ApiError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ApiError(422, ProblemCode.image_too_many_pixels, str(exc), errors=_img_err()) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ApiError(
            415, ProblemCode.unsupported_media_type, "Không giải mã được ảnh.", errors=_img_err()
        ) from exc
    clean = Image.frombytes("RGB", final_size, raw_bytes)
    if focal_35mm is not None:
        clean.info["focal_length_35mm"] = focal_35mm
    return clean


def letterbox_rgb(img: Image.Image, size: int = DEFAULT_SIZE, pad_value: int = DEFAULT_PAD) -> np.ndarray:
    """Letterbox RGB image to ``(1, 3, size, size)`` float32 in ``[0.0, 255.0]``."""
    rgb = img.convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.BILINEAR)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    w, h = rgb.size
    px, py = (size - w) // 2, (size - h) // 2
    canvas[py : py + h, px : px + w] = np.asarray(rgb, dtype=np.uint8)
    return canvas.transpose(2, 0, 1).astype(np.float32)[None, ...]


@dataclass(frozen=True)
class VisualPrediction:
    kcal: float
    mass_g: float
    fat_g: float
    carb_g: float
    protein_g: float
    latency_ms: float
    ood_clamped: bool = False
    food_area_ratio: float | None = None
    multi_dish_score: float | None = None
    focal_length_35mm: float | None = None


def _synthetic_input(img: Image.Image, min_colors: int = 24) -> bool:
    """Input-side OOD gate: flat/graphic images (few distinct colours) are not food photos.

    Model-output heuristics alone depend on the regressor's quirks; a real photo of a dish has hundreds
    of distinct 5-bit colours in a 64x64 thumbnail, whereas solid fills, checkerboards and quadrant
    test cards have fewer than ten.
    """
    small = np.asarray(img.convert("RGB").resize((64, 64), Image.Resampling.NEAREST), dtype=np.uint8)
    chroma = small.max(axis=2).astype(np.int16) - small.min(axis=2).astype(np.int16)
    if float((chroma > 128).mean()) < 0.25:
        return False  # dark/grey flat frames (e.g. lens cap) are handled by the output-side checks
    small = small >> 3
    codes = (small[..., 0].astype(np.int32) << 10) | (small[..., 1].astype(np.int32) << 5) | small[..., 2]
    return int(np.unique(codes).size) < min_colors


class MealCalorieEstimator:
    """CPU ONNXRuntime wrapper for 5-target meal nutrition regression."""

    def __init__(self, session: ort.InferenceSession, *, serving: dict[str, Any] | None = None) -> None:
        self.session = session
        self.serving = serving or {}
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if len(inp.shape) == 4 and isinstance(inp.shape[2], int) else DEFAULT_SIZE
        inp_cfg = self.serving.get("input") or {}
        self.pad_value = int(inp_cfg.get("pad_value", DEFAULT_PAD))
        self.domain_shift_note = str(self.serving.get("domain_shift_note") or DEFAULT_DOMAIN_SHIFT_NOTE)

    def predict(self, img: Image.Image) -> VisualPrediction:
        x = letterbox_rgb(img, size=self.size, pad_value=self.pad_value)
        with onnx_infer_slot("meal_calorie"):
            t0 = time.perf_counter()
            raw = self.session.run(None, {self.input_name: x})[0]
            latency_ms = (time.perf_counter() - t0) * 1000.0
        raw_vec = np.asarray(raw, dtype=np.float64).reshape(-1)
        if len(raw_vec) < 5:
            raise ValueError(f"Expected 5 outputs [kcal, mass_g, fat_g, carb_g, protein_g], got {len(raw_vec)}")
        raw5 = raw_vec[:5]
        non_finite = bool(not np.all(np.isfinite(raw5)))
        sanitized = np.nan_to_num(raw5, nan=0.0, posinf=PHYSICAL_UPPER_BOUNDS, neginf=0.0)
        upper_clamped = bool(np.any(sanitized > PHYSICAL_UPPER_BOUNDS))
        vec = np.clip(sanitized, 0.0, PHYSICAL_UPPER_BOUNDS)

        kcal, mass_g, fat_g, carb_g, protein_g = (float(vec[i]) for i in range(5))
        atwater_kcal = 4.0 * protein_g + 4.0 * carb_g + 9.0 * fat_g
        macro_contradiction = (kcal <= 1e-6 and atwater_kcal > 50.0) or (
            atwater_kcal > 100.0 and kcal < 0.25 * atwater_kcal
        )
        if kcal <= 1e-6 and atwater_kcal > 50.0:
            kcal = min(MAX_KCAL, round(atwater_kcal, 1))
        ood_clamped = non_finite or upper_clamped or macro_contradiction or _synthetic_input(img)
        food_area_ratio: float | None = None
        multi_dish_score: float | None = None
        if len(raw_vec) >= 7:
            a_val = float(np.nan_to_num(raw_vec[5], nan=0.5, posinf=1.0, neginf=0.0))
            m_val = float(np.nan_to_num(raw_vec[6], nan=0.25, posinf=1.0, neginf=0.0))
            food_area_ratio = round(float(np.clip(a_val, 0.0, 1.0)), 4)
            multi_dish_score = round(float(np.clip(m_val, 0.0, 1.0)), 4)

        raw_focal = img.info.get("focal_length_35mm")
        focal_35mm = float(raw_focal) if isinstance(raw_focal, int | float) and 10.0 <= float(raw_focal) <= 300.0 else None

        return VisualPrediction(
            kcal=kcal,
            mass_g=mass_g,
            fat_g=fat_g,
            carb_g=carb_g,
            protein_g=protein_g,
            latency_ms=round(latency_ms, 3),
            ood_clamped=ood_clamped,
            food_area_ratio=food_area_ratio,
            multi_dish_score=multi_dish_score,
            focal_length_35mm=focal_35mm,
        )


def make_cpu_session(onnx_path: Path, *, intra_threads: int = 2) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = intra_threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])


def load_meal_calorie_estimator(model_dir: Path, *, verify_sha256: bool = True) -> MealCalorieEstimator:
    model_dir = Path(model_dir)
    serving_path = model_dir / "serving.json"
    if not serving_path.exists():
        raise ArtifactIntegrityError(f"Missing serving.json in {model_dir}")
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    artifact_name = str(serving.get("artifact_file") or "model.onnx")
    onnx_path = model_dir / artifact_name
    if not onnx_path.exists():
        raise ArtifactIntegrityError(f"Missing ONNX artifact {onnx_path}")
    if verify_sha256:
        expected = serving.get("artifact_sha256")
        if not expected:
            raise ArtifactIntegrityError(f"Missing artifact_sha256 in {serving_path}")
        actual = sha256_file(onnx_path)
        if actual != expected:
            raise ArtifactIntegrityError(f"SHA-256 mismatch for {onnx_path}: expected {expected}, got {actual}")
    sess = make_cpu_session(onnx_path, intra_threads=2)
    inp = sess.get_inputs()[0]
    sz = int(inp.shape[2]) if len(inp.shape) == 4 and isinstance(inp.shape[2], int) else DEFAULT_SIZE
    warm = np.full((1, 3, sz, sz), DEFAULT_PAD, dtype=np.float32)
    for _ in range(2):
        sess.run(None, {inp.name: warm})
    return MealCalorieEstimator(sess, serving=serving)
