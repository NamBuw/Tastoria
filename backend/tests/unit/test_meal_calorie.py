"""Unit tests for the decoupled meal_calorie module (M17)."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tastoria.app import create_app
from tastoria.core.auth import AuthUser, current_user
from tastoria.core.config import Settings
from tastoria.core.errors import ProblemCode
from tastoria.modules.meal_calorie.estimator import (
    MAX_BYTES,
    MAX_CARB_G,
    MAX_FAT_G,
    MAX_KCAL,
    MAX_MASS_G,
    MAX_PROTEIN_G,
    ArtifactIntegrityError,
    MealCalorieEstimator,
    load_meal_calorie_estimator,
    make_cpu_session,
    sanitize_meal_image,
)
from tastoria.modules.meal_calorie.kb_lookup import PORTION_MULTIPLIERS, KBDishCatalog, KBDishNutrition
from tastoria.modules.meal_calorie.service import MealCalorieDeps, estimate_meal_calories

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIR = REPO_ROOT / "deploy" / "models" / "meal_calorie"


# ---------------------------------------------------------------- minimal pure-Python ONNX builder


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


def _vi(field: int, val: int) -> bytes:
    return _tag(field, 0) + _varint(val)


def _tensor_type_proto(elem_type: int, dims: list[int | str]) -> bytes:
    shape_dims = b""
    for d in dims:
        if isinstance(d, int):
            shape_dims += _ld(1, _vi(1, d))
        else:
            shape_dims += _ld(1, _ld(2, d.encode()))
    tensor_type = _vi(1, elem_type) + _ld(2, shape_dims)
    return _ld(1, tensor_type)


def _value_info(name: str, dims: list[int | str]) -> bytes:
    return _ld(1, name.encode()) + _ld(2, _tensor_type_proto(1, dims))


def _attr_ints(name: str, vals: list[int]) -> bytes:
    return _ld(1, name.encode()) + _vi(20, 7) + b"".join(_vi(8, v) for v in vals)


def _attr_int(name: str, val: int) -> bytes:
    return _ld(1, name.encode()) + _vi(20, 2) + _vi(3, val)


def _node(op_type: str, inputs: list[str], outputs: list[str], attrs: list[bytes]) -> bytes:
    return (
        b"".join(_ld(1, i.encode()) for i in inputs)
        + b"".join(_ld(2, o.encode()) for o in outputs)
        + _ld(4, op_type.encode())
        + b"".join(_ld(5, a) for a in attrs)
    )


def build_synthetic_calorie_onnx(path: Path) -> Path:
    """Build valid opset-13 ONNX: image ['n',3,224,224] -> ReduceMean(axes=[2]) ['n',3,224] -> Slice/Reshape?
    Simpler: ReduceMean over [3] -> ['n', 3, 224], Slice [0..5] on axis 2 -> ['n', 3, 5], ReduceMean over [1] -> ['n', 5].
    Actually Pad ['n',3] on [2,3] ReduceMean output is even simpler: ReduceMean(axes=[2,3]) -> ['n',3], Concat(x, x[:,:2])!
    Let's use Reshape after Tile/Concat? Wait: Slice(axes=[2], starts=[0], ends=[5]) on ReduceMean(axes=[3]) gives ['n',3,5] -> ReduceMean(axes=[1]) -> ['n',5]!
    """
    # Even simpler: GlobalAveragePool -> ['n',3,1,1] -> Squeeze? Wait: ReduceMean(axes=[2,3], keepdims=0) -> ['n', 3].
    # Concat ['n',3] and ['n',3] along axis=1 -> ['n', 6] -> ReduceMean? No, Gather/Slice 0..5!
    # Actually Pad or Concat on constant? No constant tensor needed:
    # 1) ReduceMean(image, axes=[3], keepdims=0) -> tmp1 ['n', 3, 224]
    # 2) ReduceMean(tmp1, axes=[1], keepdims=0) -> tmp2 ['n', 224]
    # Wait, Slice needs tensor inputs in opset 13! Instead:
    # ReduceMean(image, axes=[2,3], keepdims=0) -> a ['n', 3]
    # Concat(a, a, axis=1) -> b ['n', 6]
    # Shape? Still need Slice for 5. What if we just use ReduceSum/ReduceMean to [n, 5]?
    # In opset 13, Reshape/Slice take tensor inputs; or we can make a 1-tensor Constant!
    # Wait: Constant node has attribute `value` (TensorProto, field 5, type=4)!
    # Easier: ReduceMean(image, axes=[2,3], keepdims=0) -> ['n', 3]
    #Wait: test can just check 3 or 5? No, MealCalorieEstimator checks len(vec) >= 5!
    # Let's include a tiny TensorProto Constant for Pad or Slice, OR Concat 2x ['n', 3] -> ['n', 6] which has len >= 5!
    nodes = [
        _node("ReduceMean", ["image"], ["rgb_mean"], [_attr_ints("axes", [2, 3]), _attr_int("keepdims", 0)]),
        _node("Concat", ["rgb_mean", "rgb_mean"], ["pred"], [_attr_int("axis", 1)]),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"meal_calorie_test")
        + _ld(11, _value_info("image", ["n", 3, 224, 224]))
        + _ld(12, _value_info("pred", ["n", 6]))
    )
    opset = _ld(1, b"") + _vi(2, 13)
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, opset)
    path.write_bytes(model)
    return path


def _write_synthetic_bundle(model_dir: Path) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = build_synthetic_calorie_onnx(model_dir / "model.onnx")
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    serving = {
        "schema_version": "meal_calorie.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "input": {"name": "image", "shape": [1, 3, 224, 224], "pad_value": 128},
        "portion_multipliers": dict(PORTION_MULTIPLIERS),
        "domain_shift_note": "synthetic test domain shift note",
    }
    (model_dir / "serving.json").write_text(json.dumps(serving), encoding="utf-8")
    return model_dir


def _jpeg_bytes(size: tuple[int, int] = (320, 240), color: tuple[int, int, int] = (180, 120, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- unit tests


def test_sha256_verification_and_tamper_rejection(tmp_path: Path) -> None:
    mdir = _write_synthetic_bundle(tmp_path / "good_model")
    est = load_meal_calorie_estimator(mdir, verify_sha256=True)
    pred = est.predict(Image.new("RGB", (320, 240), (100, 150, 200)))
    assert pred.kcal >= 0.0
    assert pred.latency_ms >= 0.0

    # Tamper ONNX bytes -> must raise ArtifactIntegrityError
    bad_dir = _write_synthetic_bundle(tmp_path / "tampered_model")
    with (bad_dir / "model.onnx").open("ab") as fh:
        fh.write(b"\x00")
    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        load_meal_calorie_estimator(bad_dir, verify_sha256=True)

    # Missing serving.json -> must raise ArtifactIntegrityError
    empty_dir = tmp_path / "missing"
    empty_dir.mkdir()
    with pytest.raises(ArtifactIntegrityError, match="Missing serving.json"):
        load_meal_calorie_estimator(empty_dir, verify_sha256=True)


def test_kb_catalog_lookup_and_portion_scaling() -> None:
    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")
    assert len(cat.dishes) == 569
    assert cat.calibrated is True
    assert 0.05 < cat.half_width_rel < 0.25

    vua = cat.estimate(dish_slug="thit-kho-tau", portion="vua")
    nho = cat.estimate(dish_slug="thit-kho-tau", portion="nho")
    lon = cat.estimate(dish_slug="thit-kho-tau", portion="lon")
    assert vua is not None and nho is not None and lon is not None
    assert nho.portion_multiplier == 0.75
    assert lon.portion_multiplier == 1.35
    assert nho.estimated_kcal < vua.estimated_kcal < lon.estimated_kcal
    assert vua.kcal_low < vua.estimated_kcal < vua.kcal_high


def test_service_modes_and_image_error_codes(tmp_path: Path) -> None:
    mdir = _write_synthetic_bundle(tmp_path / "bundle")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )

    # 1. KB calibrated mode
    kb_res = estimate_meal_calories(deps, dish_slug="thit-kho-tau", portion="lon")
    assert kb_res.source == "kb_calibrated"
    assert kb_res.calibrated is True
    assert kb_res.kb_slug == "thit-kho-tau"

    # 2. ONNX visual mode
    vis_res = estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), portion="nho")
    assert vis_res.source == "onnx_nutrition5k"
    assert vis_res.calibrated is False
    assert vis_res.portion_multiplier == 0.75
    assert vis_res.domain_shift_note is not None

    # 3. Hybrid mode
    hyb_res = estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), dish_name="Thịt kho tàu", portion="vua")
    assert hyb_res.source == "hybrid"
    assert hyb_res.kb_slug == "thit-kho-tau"
    assert hyb_res.visual_kcal is not None

    # 4. Malformed / oversized / missing input errors
    from tastoria.core.errors import ApiError

    with pytest.raises(ApiError) as exc_empty:
        estimate_meal_calories(deps)
    assert exc_empty.value.code == ProblemCode.validation_error

    with pytest.raises(ApiError) as exc_bad_img:
        estimate_meal_calories(deps, image_bytes=b"not an image")
    assert exc_bad_img.value.code == ProblemCode.unsupported_media_type
    assert exc_bad_img.value.status == 415

    with pytest.raises(ApiError) as exc_big:
        estimate_meal_calories(deps, image_bytes=b"\xff\xd8\xff" + b"0" * MAX_BYTES)
    assert exc_big.value.code == ProblemCode.image_too_large
    assert exc_big.value.status == 413

    with pytest.raises(ApiError) as exc_404:
        estimate_meal_calories(deps, dish_slug="mon-khong-ton-tai")
    assert exc_404.value.code == ProblemCode.not_found
    assert exc_404.value.status == 404


def test_http_endpoints_and_oversized_pixel_bomb(tmp_path: Path) -> None:
    mdir = _write_synthetic_bundle(tmp_path / "http_bundle")
    app = create_app(Settings(login_throttle_backend="memory", meal_calorie_model_dir=str(mdir)))
    fake_user = AuthUser(id=uuid.uuid4(), email="u@tastoria.local", role="user")
    app.dependency_overrides[current_user] = lambda: fake_user

    client = TestClient(app)
    r_list = client.get("/api/v1/meal-calorie/dishes")
    assert r_list.status_code == 200
    body = r_list.json()
    assert len(body["dishes"]) == 569
    assert body["calibrated"] is True

    r_kb = client.post("/api/v1/meal-calorie/estimate", data={"dish_slug": "canh-chua-ca-loc", "portion": "vua"})
    assert r_kb.status_code == 200
    assert r_kb.json()["source"] == "kb_calibrated"

    r_img = client.post(
        "/api/v1/meal-calorie/estimate",
        data={"portion": "lon"},
        files={"image": ("plate.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert r_img.status_code == 200
    assert r_img.json()["source"] == "onnx_nutrition5k"
    assert r_img.json()["portion_multiplier"] == 1.35

    # Invalid file -> 415 unsupported_media_type
    r_bad = client.post(
        "/api/v1/meal-calorie/estimate",
        files={"image": ("bad.txt", b"hello world", "text/plain")},
    )
    assert r_bad.status_code == 415
    assert r_bad.json()["code"] == "unsupported_media_type"

    # Pixel bomb (> 4096 x 4096) in compact PNG -> 422 image_too_many_pixels
    bomb_buf = io.BytesIO()
    Image.new("RGB", (4100, 4100), (0, 0, 0)).save(bomb_buf, format="PNG")
    assert len(bomb_buf.getvalue()) < MAX_BYTES
    r_bomb = client.post(
        "/api/v1/meal-calorie/estimate",
        files={"image": ("bomb.png", bomb_buf.getvalue(), "image/png")},
    )
    assert r_bomb.status_code == 422
    assert r_bomb.json()["code"] == "image_too_many_pixels"

    # Missing model dir -> 503 model_unavailable on image upload
    deps_missing = MealCalorieDeps.from_paths(
        model_dir=tmp_path / "nonexistent",
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    from tastoria.core.errors import ApiError

    with pytest.raises(ApiError) as exc_503:
        estimate_meal_calories(deps_missing, image_bytes=_jpeg_bytes())
    assert exc_503.value.status == 503
    assert exc_503.value.code == ProblemCode.model_unavailable

    # Short 1-2 char dish_name returns 404 (not Gà luộc), even with image
    r_short = client.post("/api/v1/meal-calorie/estimate", data={"dish_name": "a"})
    assert r_short.status_code == 404
    assert r_short.json()["code"] == "not_found"

    r_short_img = client.post(
        "/api/v1/meal-calorie/estimate",
        data={"dish_name": "a"},
        files={"image": ("plate.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert r_short_img.status_code == 404
    assert r_short_img.json()["code"] == "not_found"

    # Explicit unknown dish_slug + image returns 404 (never silently drops to onnx_nutrition5k)
    r_miss_hybrid = client.post(
        "/api/v1/meal-calorie/estimate",
        data={"dish_slug": "mon-gia-khong-co", "portion": "vua"},
        files={"image": ("plate.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert r_miss_hybrid.status_code == 404
    assert r_miss_hybrid.json()["code"] == "not_found"


def test_kb_short_substring_guard() -> None:
    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")
    assert cat.lookup(dish_name="a") is None
    assert cat.lookup(dish_name="ga") is None
    assert cat.lookup(dish_name="  a  ") is None
    assert cat.lookup(dish_name="ga luoc") is not None

    # Exact folded name match still works for <= 2 char dish names
    tiny_cat = KBDishCatalog(
        [
            KBDishNutrition(
                slug="oc",
                name_vi="Ốc",
                slot="man",
                servings=1,
                kcal_per_serving=120.0,
                protein_g=14.0,
                lipid_g=2.0,
                glucid_g=6.0,
                fiber_g=0.0,
                data_version="test",
            )
        ],
        half_width_rel=0.12,
        calibrated=True,
        data_version="test",
    )
    assert tiny_cat.lookup(dish_name="oc") is not None
    assert tiny_cat.lookup(dish_name="o") is None


def test_explicit_dish_miss_with_image_raises_404(tmp_path: Path) -> None:
    from tastoria.core.errors import ApiError

    mdir = _write_synthetic_bundle(tmp_path / "bundle_miss")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    with pytest.raises(ApiError) as exc_slug:
        estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), dish_slug="mon-gia-khong-co")
    assert exc_slug.value.status == 404
    assert exc_slug.value.code == ProblemCode.not_found

    with pytest.raises(ApiError) as exc_name:
        estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), dish_name="a")
    assert exc_name.value.status == 404
    assert exc_name.value.code == ProblemCode.not_found

    # Whitespace-only dish_slug/dish_name still routes to pure visual estimation
    vis = estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), dish_slug="  ", dish_name=" ")
    assert vis.source == "onnx_nutrition5k"


def _build_exploding_calorie_onnx(path: Path) -> Path:
    """Synthetic opset-13 ONNX: sq(ReduceMean(image)) -> [65025, 0, 0, ...] on pure red, [0, 65025, 0, ...] on pure green."""
    nodes = [
        _node("ReduceMean", ["image"], ["rgb_mean"], [_attr_ints("axes", [2, 3]), _attr_int("keepdims", 0)]),
        _node("Mul", ["rgb_mean", "rgb_mean"], ["sq"], []),
        _node("Concat", ["sq", "sq"], ["pred"], [_attr_int("axis", 1)]),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"meal_calorie_exploding_test")
        + _ld(11, _value_info("image", ["n", 3, 224, 224]))
        + _ld(12, _value_info("pred", ["n", 6]))
    )
    opset = _ld(1, b"") + _vi(2, 13)
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, opset)
    path.write_bytes(model)
    return path


def test_ood_upper_bound_clamping_and_macro_reconciliation(tmp_path: Path) -> None:
    mdir = tmp_path / "exploding_model"
    mdir.mkdir(parents=True, exist_ok=True)
    onnx_path = _build_exploding_calorie_onnx(mdir / "model.onnx")
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    serving = {
        "schema_version": "meal_calorie.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "input": {"name": "image", "shape": [1, 3, 224, 224], "pad_value": 128},
        "portion_multipliers": dict(PORTION_MULTIPLIERS),
        "domain_shift_note": "synthetic domain shift note",
    }
    (mdir / "serving.json").write_text(json.dumps(serving), encoding="utf-8")

    est = load_meal_calorie_estimator(mdir, verify_sha256=True)
    # Red image -> raw kcal=65025, carb_g=65025 -> clamped to 3500 kcal & 400 g carb
    pred_red = est.predict(Image.new("RGB", (224, 224), (255, 0, 0)))
    assert pred_red.kcal == MAX_KCAL
    assert pred_red.carb_g == MAX_CARB_G
    assert pred_red.ood_clamped is True

    # Green image -> raw kcal=0.0, mass=65025, protein=65025 -> clamped + Atwater kcal reconciled (4*250=1000)
    pred_green = est.predict(Image.new("RGB", (224, 224), (0, 255, 0)))
    assert pred_green.mass_g == MAX_MASS_G
    assert pred_green.protein_g == MAX_PROTEIN_G
    assert pred_green.kcal == 1000.0
    assert pred_green.ood_clamped is True

    # Black image -> 0,0,0 -> not clamped
    pred_black = est.predict(Image.new("RGB", (224, 224), (0, 0, 0)))
    assert pred_black.kcal == 0.0
    assert pred_black.ood_clamped is False

    # End-to-end service with portion="lon" (1.35) also stays within physical bounds
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    res_lon = estimate_meal_calories(deps, image_bytes=_jpeg_bytes((224, 224), (255, 0, 0)), portion="lon")
    assert res_lon.estimated_kcal <= MAX_KCAL
    assert res_lon.kcal_high <= MAX_KCAL
    assert res_lon.carbs_g <= MAX_CARB_G
    assert res_lon.protein_g <= MAX_PROTEIN_G
    assert res_lon.fat_g <= MAX_FAT_G
    assert res_lon.ood_clamped is True
    assert res_lon.domain_shift_note is not None and "OOD" in res_lon.domain_shift_note


def test_real_deployed_meal_calorie_artifact_if_present() -> None:
    if not (DEPLOY_DIR / "model.onnx").exists():
        pytest.skip("deploy/models/meal_calorie/model.onnx not exported yet")
    est = load_meal_calorie_estimator(DEPLOY_DIR, verify_sha256=True)
    pred = est.predict(Image.new("RGB", (640, 480), (140, 120, 90)))
    assert pred.kcal >= 0.0
    assert pred.latency_ms <= 50.0

    # Challenger 1 OOD probes: 4-quadrant saturated RGB, solid red, CMYK JPEG, checkerboard
    q = Image.new("RGB", (240, 160))
    px = q.load()
    for y in range(160):
        for x in range(240):
            if x < 120 and y < 80:
                px[x, y] = (255, 0, 0)
            elif x >= 120 and y < 80:
                px[x, y] = (0, 255, 0)
            elif x < 120 and y >= 80:
                px[x, y] = (0, 0, 255)
            else:
                px[x, y] = (255, 255, 0)

    cmyk_buf = io.BytesIO()
    Image.new("CMYK", (240, 160), (0, 255, 255, 0)).save(cmyk_buf, format="JPEG")
    cmyk_img = sanitize_meal_image(cmyk_buf.getvalue())

    checker = np.zeros((224, 224, 3), dtype=np.uint8)
    for y in range(0, 224, 16):
        for x in range(0, 224, 16):
            checker[y : y + 16, x : x + 16] = (255, 0, 255) if ((x // 16 + y // 16) % 2 == 0) else (0, 255, 255)

    for probe_img in (q, Image.new("RGB", (240, 160), (255, 0, 0)), cmyk_img, Image.fromarray(checker)):
        p = est.predict(probe_img)
        assert 0.0 <= p.kcal <= MAX_KCAL
        assert 0.0 <= p.mass_g <= MAX_MASS_G
        assert 0.0 <= p.fat_g <= MAX_FAT_G
        assert 0.0 <= p.carb_g <= MAX_CARB_G
        assert 0.0 <= p.protein_g <= MAX_PROTEIN_G
        assert p.ood_clamped is True

    # Real food photo should not trigger OOD clamping
    pho_path = REPO_ROOT / "app" / "assets" / "food" / "pho.webp"
    if pho_path.exists():
        pho_pred = est.predict(sanitize_meal_image(pho_path.read_bytes()))
        assert pho_pred.ood_clamped is False
        assert 0.0 < pho_pred.kcal <= MAX_KCAL


def test_architectural_isolation_untouched() -> None:
    detector_src = (REPO_ROOT / "backend/src/tastoria/modules/scan/detector.py").read_text(encoding="utf-8")
    mlops_src = (REPO_ROOT / "backend/src/tastoria/modules/mlops/service.py").read_text(encoding="utf-8")
    assert "meal_calorie" not in detector_src
    assert "modules.meal_calorie" not in mlops_src
    assert "import meal_calorie" not in mlops_src
    assert "nutrition5k" not in detector_src.lower()
    assert "nutrition5k" not in mlops_src.lower()


def test_deps_thread_safe_preload_and_concurrent_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import concurrent.futures
    import threading
    from tastoria.modules.meal_calorie import service as svc

    mdir = _write_synthetic_bundle(tmp_path / "thread_bundle")
    counts = {"kb": 0, "est": 0, "bc": 0}
    cnt_lock = threading.Lock()

    orig_kb = svc.KBDishCatalog.from_dirs
    orig_est = svc.load_meal_calorie_estimator
    orig_bc = svc.BarcodeCatalog.from_kb_dir

    def tracked_kb(*a, **kw):
        with cnt_lock:
            counts["kb"] += 1
        return orig_kb(*a, **kw)

    def tracked_est(*a, **kw):
        with cnt_lock:
            counts["est"] += 1
        return orig_est(*a, **kw)

    def tracked_bc(*a, **kw):
        with cnt_lock:
            counts["bc"] += 1
        return orig_bc(*a, **kw)

    monkeypatch.setattr(svc.KBDishCatalog, "from_dirs", staticmethod(tracked_kb))
    monkeypatch.setattr(svc, "load_meal_calorie_estimator", tracked_est)
    monkeypatch.setattr(svc.BarcodeCatalog, "from_kb_dir", staticmethod(tracked_bc))

    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        preload=False,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for _ in range(16):
            futs.append(ex.submit(deps.get_kb))
            futs.append(ex.submit(deps.get_estimator))
            futs.append(ex.submit(deps.get_barcode_catalog))
        for f in futs:
            assert f.result() is not None
    assert counts == {"kb": 1, "est": 1, "bc": 1}

    pre = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        preload=True,
    )
    assert pre.kb_catalog is not None
    assert pre.estimator is not None
    assert pre.barcode_catalog is not None


def test_customer_facing_strings_free_of_jargon(tmp_path: Path) -> None:
    from tastoria.modules.meal_calorie.estimator import DEFAULT_DOMAIN_SHIFT_NOTE, OOD_WARNING_NOTE

    for txt in (OOD_WARNING_NOTE, DEFAULT_DOMAIN_SHIFT_NOTE):
        assert "nutrition5k" not in txt.lower()
        assert "yuka" not in txt.lower()

    if (DEPLOY_DIR / "serving.json").is_file():
        serving = json.loads((DEPLOY_DIR / "serving.json").read_text(encoding="utf-8"))
        note = str(serving.get("domain_shift_note") or "")
        assert "nutrition5k" not in note.lower()
        assert "yuka" not in note.lower()

    mdir = _write_synthetic_bundle(tmp_path / "jargon_bundle")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    for out in (
        estimate_meal_calories(deps, dish_slug="bo-kho", portion="vua"),
        estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), portion="vua"),
        estimate_meal_calories(deps, image_bytes=_jpeg_bytes(), dish_slug="bo-kho", portion="vua"),
    ):
        for s in (out.domain_shift_note or "", out.provenance_label_vi):
            assert "nutrition5k" not in s.lower()
            assert "yuka" not in s.lower()


def test_inverse_variance_fusion_ood_and_disagreement_interval() -> None:
    from tastoria.modules.meal_calorie.service import inverse_variance_fuse

    # OOD visual prediction must be ignored (w_vis == 0)
    k_ood, lo_ood, hi_ood, *_ , w_kb_ood, w_vis_ood = inverse_variance_fuse(
        kcal_kb=255.0,
        prot_kb=15.5,
        carb_kb=2.5,
        fat_kb=20.0,
        fib_kb=0.4,
        kb_mass_g=170.0,
        hw_kb=0.20,
        vis_kcal=3200.0,
        vis_mass_g=2500.0,
        vis_prot_g=50.0,
        vis_carb_g=100.0,
        vis_fat_g=80.0,
        food_area_ratio=0.5,
        multi_dish_score=0.1,
        ood_clamped=True,
        top1_conf=0.95,
        top_margin=0.90,
        portion="vua",
    )
    assert k_ood == 255.0
    assert w_kb_ood == 1.0 and w_vis_ood == 0.0
    assert lo_ood < k_ood < hi_ood

    # Agreement tightens relative interval compared to strong disagreement
    _, lo_agree, hi_agree, hw_agree, *_ = inverse_variance_fuse(
        kcal_kb=300.0,
        prot_kb=20.0,
        carb_kb=30.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=300.0,
        hw_kb=0.16,
        vis_kcal=305.0,
        vis_mass_g=310.0,
        vis_prot_g=19.0,
        vis_carb_g=32.0,
        vis_fat_g=11.0,
        food_area_ratio=0.55,
        multi_dish_score=0.15,
        ood_clamped=False,
        top1_conf=0.88,
        top_margin=0.75,
        portion="vua",
    )
    k_dis, lo_dis, hi_dis, hw_dis, *_ = inverse_variance_fuse(
        kcal_kb=300.0,
        prot_kb=20.0,
        carb_kb=30.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=300.0,
        hw_kb=0.16,
        vis_kcal=650.0,
        vis_mass_g=520.0,
        vis_prot_g=30.0,
        vis_carb_g=60.0,
        vis_fat_g=28.0,
        food_area_ratio=0.55,
        multi_dish_score=0.15,
        ood_clamped=False,
        top1_conf=0.52,
        top_margin=0.05,
        portion="vua",
    )
    assert hw_dis > hw_agree
    assert lo_agree < 305.0 < hi_agree
    assert 300.0 < k_dis < 650.0
    assert lo_dis < k_dis < hi_dis

    # Standard 26mm EXIF focal length increases visual weight vs ultrawide, and tightens CI when masses align
    k_26, lo_26, hi_26, hw_26, *_, wvis_26 = inverse_variance_fuse(
        kcal_kb=300.0,
        prot_kb=20.0,
        carb_kb=30.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=300.0,
        hw_kb=0.16,
        vis_kcal=305.0,
        vis_mass_g=305.0,
        vis_prot_g=20.0,
        vis_carb_g=31.0,
        vis_fat_g=10.5,
        food_area_ratio=0.50,
        multi_dish_score=0.20,
        ood_clamped=False,
        top1_conf=0.80,
        top_margin=0.60,
        portion="vua",
        focal_length_35mm=26.0,
    )
    k_uw, lo_uw, hi_uw, hw_uw, *_, wvis_uw = inverse_variance_fuse(
        kcal_kb=300.0,
        prot_kb=20.0,
        carb_kb=30.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=300.0,
        hw_kb=0.16,
        vis_kcal=305.0,
        vis_mass_g=305.0,
        vis_prot_g=20.0,
        vis_carb_g=31.0,
        vis_fat_g=10.5,
        food_area_ratio=0.50,
        multi_dish_score=0.20,
        ood_clamped=False,
        top1_conf=0.80,
        top_margin=0.60,
        portion="vua",
        focal_length_35mm=14.0,
    )
    assert wvis_26 > wvis_uw
    assert hw_26 <= hw_uw and (hi_26 - lo_26) <= (hi_uw - lo_uw)
    assert lo_26 < k_26 < hi_26 and lo_uw < k_uw < hi_uw

    # High RAPS conformal set size (>3) shifts posterior weight toward visual prior
    k_r1, *_, wkb_r1, wvis_r1 = inverse_variance_fuse(
        kcal_kb=250.0,
        prot_kb=15.0,
        carb_kb=25.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=250.0,
        hw_kb=0.16,
        vis_kcal=600.0,
        vis_mass_g=500.0,
        vis_prot_g=30.0,
        vis_carb_g=60.0,
        vis_fat_g=25.0,
        food_area_ratio=0.55,
        multi_dish_score=0.20,
        ood_clamped=False,
        top1_conf=0.80,
        top_margin=0.60,
        portion="vua",
        raps_set_size=1,
    )
    k_r12, *_, wkb_r12, wvis_r12 = inverse_variance_fuse(
        kcal_kb=250.0,
        prot_kb=15.0,
        carb_kb=25.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=250.0,
        hw_kb=0.16,
        vis_kcal=600.0,
        vis_mass_g=500.0,
        vis_prot_g=30.0,
        vis_carb_g=60.0,
        vis_fat_g=25.0,
        food_area_ratio=0.55,
        multi_dish_score=0.20,
        ood_clamped=False,
        top1_conf=0.52,
        top_margin=0.05,
        portion="vua",
        raps_set_size=12,
    )
    assert wkb_r1 > 0.70 and wvis_r12 > 0.70 and k_r12 > k_r1


def test_exif_focal_length_preserved_while_gps_stripped(tmp_path: Path) -> None:
    from PIL import ExifTags

    im = Image.new("RGB", (240, 180), (140, 110, 90))
    exif = im.getexif()
    exif[41989] = 26  # FocalLengthIn35mmFilm
    exif[ExifTags.Base.Make] = "SecretPhone"
    exif[ExifTags.Base.GPSInfo] = {1: "N", 2: (10.0, 20.0, 30.0)}
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)

    clean = sanitize_meal_image(buf.getvalue())
    assert clean.info.get("focal_length_35mm") == 26.0
    assert len(clean.getexif()) == 0  # raw EXIF/GPS/Make stripped

    mdir = _write_synthetic_bundle(tmp_path / "exif_model")
    est = load_meal_calorie_estimator(mdir, verify_sha256=True)
    pred = est.predict(clean)
    assert pred.focal_length_35mm == 26.0


def test_sanitize_highres_caps_edge_and_fusion_dampens_clear_margin_raps() -> None:
    from PIL import ExifTags
    from tastoria.modules.meal_calorie.estimator import MAX_INFER_EDGE
    from tastoria.modules.meal_calorie.service import inverse_variance_fuse

    big = Image.new("RGB", (3024, 4032), (160, 120, 80))
    exif = big.getexif()
    exif[41989] = 28
    exif[ExifTags.Base.GPSInfo] = {1: "N"}
    buf = io.BytesIO()
    big.save(buf, format="JPEG", exif=exif, quality=60)
    clean = sanitize_meal_image(buf.getvalue())
    assert max(clean.size) <= MAX_INFER_EDGE
    assert clean.info.get("focal_length_35mm") == 28.0
    assert len(clean.getexif()) == 0

    # Clear margin (>=0.20) & top1>=0.42 retains strong KB weight even with RAPS=11 (e.g., pho/bun_thit_nuong)
    k_clear, *_, wkb_clear, _ = inverse_variance_fuse(
        kcal_kb=444.0,
        prot_kb=22.0,
        carb_kb=62.0,
        fat_kb=10.0,
        fib_kb=2.0,
        kb_mass_g=520.0,
        hw_kb=0.16,
        vis_kcal=160.7,
        vis_mass_g=292.0,
        vis_prot_g=8.0,
        vis_carb_g=20.0,
        vis_fat_g=5.0,
        food_area_ratio=0.25,
        multi_dish_score=0.26,
        ood_clamped=False,
        top1_conf=0.451,
        top_margin=0.248,
        portion="vua",
        raps_set_size=11,
    )
    assert wkb_clear > 0.70
    assert 370.0 < k_clear <= 444.0

    # Monotonic bound: opposing density vs mass differences must not overshoot both KB and visual kcal
    k_mono, *_ = inverse_variance_fuse(
        kcal_kb=586.6,
        prot_kb=24.0,
        carb_kb=10.0,
        fat_kb=45.0,
        fib_kb=0.5,
        kb_mass_g=220.0,
        hw_kb=0.16,
        vis_kcal=436.8,
        vis_mass_g=352.7,
        vis_prot_g=20.0,
        vis_carb_g=35.0,
        vis_fat_g=22.0,
        food_area_ratio=0.60,
        multi_dish_score=0.40,
        ood_clamped=False,
        top1_conf=0.524,
        top_margin=0.155,
        portion="vua",
        raps_set_size=6,
    )
    assert 436.8 <= k_mono <= 586.6


def test_kb_whole_word_prefix_lookup_and_negative_cases(tmp_path: Path) -> None:
    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # Whole-word prefix fallback in lookup_recognized: "Phở bò" -> "pho" ("Phở", 444.0 kcal)
    pho_rec = cat.lookup_recognized(dish_name="Phở bò")
    assert pho_rec is not None
    assert pho_rec.dish_id == "pho"
    assert pho_rec.name_vi == "Phở"

    pho_est = cat.estimate_recognized(dish_name="Phở bò", portion="vua")
    assert pho_est is not None
    assert pho_est.estimated_kcal == 444.0

    # Whole-word prefix fallback picks longest match: "Cơm tấm sườn" -> "com tam"
    com_tam_rec = cat.lookup_recognized(dish_name="Cơm tấm sườn")
    assert com_tam_rec is not None
    assert "com" in com_tam_rec.dish_id

    # Negative cases still return None
    assert cat.lookup_recognized(dish_name="mon-khong-ton-tai") is None
    assert cat.lookup(dish_name="mon-khong-ton-tai") is None
    assert cat.lookup_recognized(dish_name="ga") is None
    assert cat.lookup(dish_name="ga") is None

    # End-to-end service estimate_meal_calories for "Phở bò" succeeds across portions
    mdir = _write_synthetic_bundle(tmp_path / "pho_bundle")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    res_nho = estimate_meal_calories(deps, dish_name="Phở bò", portion="nho")
    res_vua = estimate_meal_calories(deps, dish_name="Phở bò", portion="vua")
    res_lon = estimate_meal_calories(deps, dish_name="Phở bò", portion="lon")
    assert res_vua.dish_name_vi == "Phở"
    assert res_vua.estimated_kcal == 444.0
    assert res_nho.estimated_kcal < res_vua.estimated_kcal < res_lon.estimated_kcal

    # Whole-word prefix fallback in KBDishCatalog.lookup() directly (picks longest prefix key >= 3 chars)
    prefix_cat = KBDishCatalog(
        [
            KBDishNutrition(
                slug="com",
                name_vi="Cơm",
                slot="com",
                servings=1,
                kcal_per_serving=200.0,
                protein_g=4.0,
                lipid_g=0.5,
                glucid_g=44.0,
                fiber_g=0.5,
                data_version="test",
            ),
            KBDishNutrition(
                slug="com-tam",
                name_vi="Cơm tấm",
                slot="man",
                servings=1,
                kcal_per_serving=550.0,
                protein_g=24.0,
                lipid_g=18.0,
                glucid_g=70.0,
                fiber_g=2.0,
                data_version="test",
            ),
        ],
        half_width_rel=0.15,
        calibrated=True,
        data_version="test",
    )
    matched = prefix_cat.lookup(dish_name="Cơm tấm sườn")
    assert matched is not None and matched.slug == "com-tam"
    assert prefix_cat.lookup(dish_name="Cơm tấm") is not None
    assert prefix_cat.lookup(dish_name="Cơmpact") is None  # requires word boundary (" ")
    assert prefix_cat.lookup(dish_name="mon-khong-ton-tai") is None


def test_kb_exact_before_fuzzy_and_word_boundary_no_substring_hijack(tmp_path: Path) -> None:
    """T5-1 regression: exact match across dish_list + recognized runs before fuzzy, and word-boundary prevents hijack."""
    from tastoria.core.errors import ApiError

    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # Direct KBDishCatalog.lookup must NOT substring-hijack "Phở", "Phởn", or "Bún"
    assert cat.lookup(dish_name="Phở") is None
    assert cat.lookup(dish_name="Pho") is None
    assert cat.lookup(dish_name="Phởn") is None
    assert cat.lookup(dish_name="Bún") is None
    assert cat.lookup_recognized(dish_name="Phởn") is None

    mdir = _write_synthetic_bundle(tmp_path / "t5_1_bundle")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )

    for q in ("Phở", "Pho", "Phở bò"):
        res = estimate_meal_calories(deps, dish_name=q, portion="vua")
        assert res.dish_name_vi == "Phở"
        assert res.recognized_dish_id == "pho"
        assert res.kb_slug is None
        assert res.estimated_kcal == 444.0

    with pytest.raises(ApiError) as exc_phon:
        estimate_meal_calories(deps, dish_name="Phởn", portion="vua")
    assert exc_phon.value.status == 404
    assert exc_phon.value.code == ProblemCode.not_found

    com_res = estimate_meal_calories(deps, dish_name="Cơm", portion="vua")
    assert com_res.dish_name_vi != "Cá cơm rim mặn ngọt"
    assert com_res.dish_name_vi != "Cốm"
    assert com_res.dish_name_vi.startswith("Cơm")

    com_vong_res = estimate_meal_calories(deps, dish_name="Cốm", portion="vua")
    assert com_vong_res.dish_name_vi == "Cốm"
    assert com_vong_res.recognized_dish_id == "com_vong"

    bun_res = estimate_meal_calories(deps, dish_name="Bún", portion="vua")
    assert bun_res.dish_name_vi != "Cà bung"
    assert bun_res.dish_name_vi.startswith("Bún")

    com_tam = estimate_meal_calories(deps, dish_name="Cơm tấm", portion="vua")
    assert com_tam.dish_name_vi == "Cơm tấm"
    assert com_tam.estimated_kcal == 591.0

    hao_hao = estimate_meal_calories(deps, dish_name="Mì Hảo Hảo", portion="vua")
    assert "Hảo Hảo" in hao_hao.dish_name_vi
    assert hao_hao.estimated_kcal == pytest.approx(350.2, abs=0.5)

    bun_tn = estimate_meal_calories(deps, dish_name="Bún thịt nướng", portion="vua")
    assert bun_tn.dish_name_vi == "Bún thịt nướng"
    assert bun_tn.estimated_kcal == 467.0

    tra_sua = estimate_meal_calories(deps, dish_name="Trà sữa", portion="vua")
    assert "Trà sữa" in tra_sua.dish_name_vi
    assert tra_sua.estimated_kcal == pytest.approx(376.0, abs=0.5)

    # Decoupled dau_phu_non / omelette vs dish_list recipes
    dau_plain = estimate_meal_calories(deps, dish_slug="dau_phu_non", portion="vua")
    dau_sauce = estimate_meal_calories(deps, dish_slug="dau-phu-non-sot-nam", portion="vua")
    assert dau_plain.dish_name_vi == "Đậu phụ non chần hành gừng"
    assert dau_plain.estimated_kcal < 130.0
    assert dau_sauce.dish_name_vi == "Đậu phụ non sốt nấm"
    assert dau_sauce.estimated_kcal > dau_plain.estimated_kcal + 40.0

    om = estimate_meal_calories(deps, dish_slug="omelette", portion="vua")
    trung = estimate_meal_calories(deps, dish_slug="trung-chien-hanh", portion="vua")
    assert om.dish_name_vi == "Trứng rán cuộn Omelette"
    assert om.estimated_kcal == 255.0
    assert trung.dish_name_vi == "Trứng chiên hành lá"
    assert trung.estimated_kcal < om.estimated_kcal - 30.0



def test_zero_cal_nutrition_split_fused_mass_semaphore_503_and_copy_purge(tmp_path: Path) -> None:
    from tastoria.core.errors import ApiError
    from tastoria.modules.meal_calorie import estimator as mc_est
    from tastoria.modules.meal_calorie import service as mc_svc
    from tastoria.modules.meal_calorie.barcode import BarcodeCatalog, BarcodeProduct

    # 1. P1-13: 0 kcal beverage must return (0, 0, 0) split and MUST NOT suffer fat penalty (Grade D)
    score, grade, split = mc_svc._compute_nutrition_intelligence(
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0, fiber_g=0.0, is_packaged=True
    )
    assert (split.protein_pct, split.carbs_pct, split.fat_pct) == (0, 0, 0)
    assert grade in ("A", "B", "C") and score >= 50

    # 2. P1-13: inverse_variance_fuse returns bounded positive est_mass_g
    est_kcal, lo, hi, _, _, _, _, _, mass_g, _, _ = mc_svc.inverse_variance_fuse(
        kcal_kb=450.0,
        prot_kb=20.0,
        carb_kb=50.0,
        fat_kb=15.0,
        fib_kb=3.0,
        kb_mass_g=380.0,
        hw_kb=0.15,
        vis_kcal=520.0,
        vis_mass_g=430.0,
        vis_prot_g=22.0,
        vis_carb_g=58.0,
        vis_fat_g=18.0,
        food_area_ratio=0.45,
        multi_dish_score=0.1,
        ood_clamped=False,
        top1_conf=0.85,
        top_margin=0.4,
        portion="vua",
    )
    assert est_kcal > 0 and lo <= est_kcal <= hi
    assert mass_g is not None and 50.0 <= mass_g <= 5000.0

    # 3. P0-7: ONNX_INFER_SEMAPHORE returns 503 + Retry-After: 2 on contention timeout
    acquired = [mc_est.ONNX_INFER_SEMAPHORE.acquire(timeout=0.5) for _ in range(2)]
    assert all(acquired)
    try:
        old_to = mc_est.INFER_ACQUIRE_TIMEOUT_S
        mc_est.INFER_ACQUIRE_TIMEOUT_S = 0.05
        with pytest.raises(ApiError) as exc_503:
            with mc_est.onnx_infer_slot("meal_calorie"):
                pass
        assert exc_503.value.status == 503
        assert exc_503.value.code == ProblemCode.temporarily_unavailable
        assert exc_503.value.headers.get("Retry-After") == "2"
    finally:
        mc_est.INFER_ACQUIRE_TIMEOUT_S = old_to
        for _ in acquired:
            mc_est.ONNX_INFER_SEMAPHORE.release()

    # 4. Track 5 Section 3 ML Copy Purge across meal_calorie & barcode responses
    mdir = _write_synthetic_bundle(tmp_path / "copy_bundle")
    deps = MealCalorieDeps.from_paths(
        model_dir=mdir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    deps.barcode_catalog = BarcodeCatalog({
        "8930000000099": BarcodeProduct(
            barcode="8930000000099",
            product_name="Trà xanh không đường",
            brand="Demo",
            serving_size="350 ml",
            serving_g=350.0,
            kcal_per_serving=0.0,
            protein_g_per_serving=0.0,
            carbs_g_per_serving=0.0,
            fat_g_per_serving=0.0,
            fiber_g_per_serving=0.0,
            kcal_per_100g=0.0,
            protein_g_per_100g=0.0,
            carbs_g_per_100g=0.0,
            fat_g_per_100g=0.0,
            fiber_g_per_100g=0.0,
            source="Danh mục nhãn thực phẩm Mỹ Vị",
        )
    })
    res_dish = estimate_meal_calories(deps, dish_name="Cơm tấm", portion="vua")
    res_bc = mc_svc.lookup_barcode(deps, barcode="8930000000099")
    assert res_bc.macro_kcal_split is not None
    assert (res_bc.macro_kcal_split.protein_pct, res_bc.macro_kcal_split.carbs_pct, res_bc.macro_kcal_split.fat_pct) == (0, 0, 0)
    for text_field in (
        res_dish.provenance_label_vi,
        res_dish.domain_shift_note or "",
        res_dish.source_ref or "",
        res_bc.source,
    ):
        assert "Tastoria" not in text_field
        assert "Kho món ăn chuẩn" not in text_field
        assert "cân bằng phương sai" not in text_field
        assert "—" not in text_field and "·" not in text_field
