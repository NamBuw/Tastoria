"""Unit tests for the 131-class dish recognition & expanded meal_calorie integration."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from tastoria.modules.meal_calorie.dish_classifier import DishClassifier, load_dish_classifier
from tastoria.modules.meal_calorie.estimator import ArtifactIntegrityError
from tastoria.modules.meal_calorie.kb_lookup import KBDishCatalog
from tastoria.modules.meal_calorie.service import MealCalorieDeps, estimate_meal_calories

from unit.test_meal_calorie import (
    REPO_ROOT,
    _attr_int,
    _attr_ints,
    _jpeg_bytes,
    _ld,
    _node,
    _tensor_type_proto,
    _value_info,
    _vi,
    _write_synthetic_bundle,
)


def _tensor_proto_float(name: str, dims: list[int], vals: np.ndarray) -> bytes:
    raw = np.asarray(vals, dtype="<f4").tobytes()
    return b"".join(_vi(1, d) for d in dims) + _vi(2, 1) + _ld(8, name.encode()) + _ld(9, raw)


def _textured_jpeg_bytes(size: tuple[int, int] = (320, 240)) -> bytes:
    """Smooth spatial RGB gradient so per-channel spatial std is well above OOD flat-frame threshold."""
    w, h = size
    xs = np.linspace(40, 220, w, dtype=np.uint8)[None, :]
    ys = np.linspace(30, 200, h, dtype=np.uint8)[:, None]
    rgb = np.stack(
        [
            np.broadcast_to(xs, (h, w)),
            np.broadcast_to(ys, (h, w)),
            np.broadcast_to(((xs.astype(np.int32) + ys.astype(np.int32)) // 2).astype(np.uint8), (h, w)),
        ],
        axis=-1,
    )
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _build_synthetic_classifier_onnx(path: Path, n_classes: int, hot_idx: int, hot_logit: float) -> Path:
    logits = np.zeros((1, n_classes), dtype=np.float32)
    logits[0, hot_idx] = hot_logit
    nodes = [
        _node("GlobalAveragePool", ["image"], ["g"], []),
        _node("Flatten", ["g"], ["f"], []),
        _node("MatMul", ["f", "w_zero"], ["z"], []),
        _node("Add", ["z", "bias"], ["logits"], []),
    ]
    inits = [
        _tensor_proto_float("w_zero", [3, 1], np.zeros((3, 1), dtype=np.float32)),
        _tensor_proto_float("bias", [1, n_classes], logits),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"dish_classifier_test")
        + b"".join(_ld(5, i) for i in inits)
        + _ld(11, _value_info("image", [1, 3, 224, 224]))
        + _ld(12, _value_info("logits", [1, n_classes]))
    )
    opset = _ld(1, b"") + _vi(2, 13)
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, opset)
    path.write_bytes(model)
    return path


def _write_synthetic_classifier_bundle(model_dir: Path, *, hot_idx: int = 0, hot_logit: float = 12.0) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    rec = yaml.safe_load((REPO_ROOT / "data" / "kb" / "recognized_dishes_nutrition.yaml").read_text(encoding="utf-8"))
    dishes = rec["dishes"]
    onnx_path = _build_synthetic_classifier_onnx(model_dir / "model.onnx", len(dishes), hot_idx, hot_logit)
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    serving = {
        "schema_version": "dish_classifier.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "input": {"name": "image", "shape": [1, 3, 224, 224], "crop": "center"},
        "temperature": 1.0,
        "conf_threshold": 0.45,
        "n_classes": len(dishes),
        "classes": [
            {
                "id": d["dish_id"],
                "name_vi": d["name_vi"],
                "name_en": d["name_en"],
                "category": d["category"],
                "kb_slug": d.get("kb_slug"),
                "slot": d.get("slot"),
            }
            for d in dishes
        ],
    }
    (model_dir / "serving.json").write_text(json.dumps(serving, ensure_ascii=False), encoding="utf-8")
    return model_dir


def test_recognized_dishes_nutrition_catalog_atwater_and_lookup() -> None:
    path = REPO_ROOT / "data" / "kb" / "recognized_dishes_nutrition.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["n_dishes"] == len(doc["dishes"]) >= 216
    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")
    assert len(cat.dishes) == 180
    assert len(cat.recognized) >= 250
    for d in doc["dishes"]:
        p, c, f, kcal = d["protein_g"], d["glucid_g"], d["lipid_g"], d["kcal_per_serving"]
        if d.get("kb_slug"):
            assert d["kb_slug"] in cat.by_slug
        else:
            atwater = 4.0 * p + 4.0 * c + 9.0 * f
            assert abs(atwater - kcal) / max(1.0, atwater) <= 0.12, d["dish_id"]

    pkg_doc = yaml.safe_load((REPO_ROOT / "data" / "kb" / "everyday_packaged_foods.yaml").read_text(encoding="utf-8"))
    for it in pkg_doc["items"]:
        atwater = 4.0 * it["protein_g"] + 4.0 * it["glucid_g"] + 9.0 * it["lipid_g"]
        assert atwater > 0, it["id"]

    pho = cat.estimate_recognized(dish_id="pho", portion="vua")
    assert pho is not None and pho.name_vi == "Phở" and pho.estimated_kcal > 300.0
    ca = cat.estimate_recognized(dish_id="ca_kho_to", portion="vua")
    assert ca is not None and ca.calibrated is True
    mitom = cat.estimate_recognized(dish_name="mì tôm", portion="vua")
    assert mitom is not None and mitom.estimated_kcal > 300.0


def test_barcode_lookup_and_extended_dish_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tastoria.core.errors import ApiError, ProblemCode
    from tastoria.modules.meal_calorie.barcode import BarcodeProduct
    from tastoria.modules.meal_calorie.service import list_dishes, lookup_barcode

    cal_dir = _write_synthetic_bundle(tmp_path / "cal_bc")
    deps = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )

    base = list_dishes(deps, include_extended=False)
    ext = list_dishes(deps, include_extended=True)
    assert len(base.dishes) == 180
    assert len(ext.dishes) > 400
    assert any("Hảo Hảo" in d.name_vi for d in ext.dishes)

    # Local VN barcode hit (no network call)
    hh = lookup_barcode(deps, barcode="8934563138165", allow_remote=False)
    assert "Hảo Hảo" in hh.product_name
    assert hh.kcal_per_serving == 350.0
    assert hh.kcal_per_100g is not None and hh.kcal_per_100g > 400.0

    # Invalid barcode -> 422
    with pytest.raises(ApiError) as exc_bad:
        lookup_barcode(deps, barcode="abc123", allow_remote=False)
    assert exc_bad.value.code == ProblemCode.validation_error and exc_bad.value.status == 422

    # Mocked Open Food Facts hit & 404 miss
    cat = deps.get_barcode_catalog()
    monkeypatch.setattr(
        cat,
        "_fetch_openfoodfacts",
        lambda bc, timeout=4.0: BarcodeProduct(
            barcode=bc,
            product_name="Demo Product",
            brand="BrandX",
            serving_size="1 pack (50g)",
            serving_g=50.0,
            kcal_per_serving=200.0,
            protein_g_per_serving=5.0,
            carbs_g_per_serving=25.0,
            fat_g_per_serving=8.0,
            fiber_g_per_serving=1.0,
            kcal_per_100g=400.0,
            protein_g_per_100g=10.0,
            carbs_g_per_100g=50.0,
            fat_g_per_100g=16.0,
            fiber_g_per_100g=2.0,
            source="Open Food Facts",
        )
        if bc == "1234567890123"
        else None,
    )
    ok = lookup_barcode(deps, barcode="1234567890123", allow_remote=True)
    assert ok.product_name == "Demo Product" and ok.kcal_per_serving == 200.0
    with pytest.raises(ApiError) as exc_404:
        lookup_barcode(deps, barcode="9999999999999", allow_remote=True)
    assert exc_404.value.code == ProblemCode.not_found and exc_404.value.status == 404


def test_dish_classifier_sha256_and_photo_auto_recognition(tmp_path: Path) -> None:
    cal_dir = _write_synthetic_bundle(tmp_path / "cal")
    cls_high = _write_synthetic_classifier_bundle(tmp_path / "cls_high", hot_idx=31, hot_logit=12.0)  # pho

    loaded = load_dish_classifier(cls_high, verify_sha256=True)
    assert isinstance(loaded, DishClassifier)

    # Tamper detection
    tampered = _write_synthetic_classifier_bundle(tmp_path / "cls_bad", hot_idx=0, hot_logit=10.0)
    with (tampered / "model.onnx").open("ab") as fh:
        fh.write(b"\x01")
    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        load_dish_classifier(tampered, verify_sha256=True)

    deps = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_high,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    out = estimate_meal_calories(deps, image_bytes=_textured_jpeg_bytes(), portion="vua")
    assert out.source == "hybrid"
    assert out.recognized_dish_id == "pho"
    assert out.dish_name_vi == "Phở"
    assert out.recognized_confidence is not None and out.recognized_confidence > 0.9
    assert len(out.top_candidates) == 3
    assert out.top_candidates[0].dish_id == "pho"
    assert out.visual_kcal is not None

    # Low-confidence photo falls back cleanly to onnx_nutrition5k while still surfacing top_candidates
    cls_low = _write_synthetic_classifier_bundle(tmp_path / "cls_low", hot_idx=31, hot_logit=0.5)
    deps_low = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_low,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    low_out = estimate_meal_calories(deps_low, image_bytes=_textured_jpeg_bytes(), portion="vua")
    assert low_out.source == "onnx_nutrition5k"
    assert low_out.dish_name_vi is None
    assert len(low_out.top_candidates) == 3
    assert low_out.fusion_mode == "visual_fallback"
    assert low_out.disambiguation_required is True
    assert len(low_out.suggested_modifiers) >= 3


def test_kb_hijack_fixes_and_structured_serving_g() -> None:
    cat = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    tofu_rec = cat.lookup_recognized(dish_id="dau_phu_non")
    assert tofu_rec is not None
    assert tofu_rec.kb_slug is None
    assert tofu_rec.serving_g == 150.0
    tofu_vua = cat.estimate_recognized(dish_id="dau_phu_non", portion="vua")
    tofu_lon = cat.estimate_recognized(dish_id="dau_phu_non", portion="lon")
    assert tofu_vua is not None and tofu_lon is not None
    assert tofu_vua.estimated_kcal == 95.0
    assert tofu_vua.serving_g == 150.0
    assert tofu_lon.serving_g == pytest.approx(202.5, abs=0.1)

    omelette_rec = cat.lookup_recognized(dish_id="omelette")
    assert omelette_rec is not None
    assert omelette_rec.kb_slug is None
    assert omelette_rec.serving_g == 170.0
    omelette_vua = cat.estimate_recognized(dish_id="omelette", portion="vua")
    assert omelette_vua is not None and omelette_vua.estimated_kcal == 255.0

    chicken_rice = cat.lookup_recognized(dish_id="com_ga_hai_nam")
    assert chicken_rice is not None
    assert chicken_rice.kb_slug is None
    assert chicken_rice.glucid_g == 64.0
    assert chicken_rice.kcal_per_serving == 545.0
    assert chicken_rice.serving_g == 380.0

    # All 40 everyday packaged foods must have realistic structured serving_g (never None or regex '1' bug)
    pkg_doc = yaml.safe_load((REPO_ROOT / "data" / "kb" / "everyday_packaged_foods.yaml").read_text(encoding="utf-8"))
    for it in pkg_doc["items"]:
        est = cat.estimate_recognized(dish_id=it["id"], portion="vua")
        assert est is not None
        assert est.serving_g is not None and est.serving_g >= 50.0, it["id"]
    assert cat.estimate_recognized(dish_id="mi_omachi_bo_ham", portion="vua").serving_g == 80.0  # type: ignore[union-attr]
    assert cat.estimate_recognized(dish_id="mi_hao_hao_tom_chua_cay", portion="vua").serving_g == 350.0  # type: ignore[union-attr]


def test_disambiguation_contract_low_margin_and_modifiers(tmp_path: Path) -> None:
    cal_dir = _write_synthetic_bundle(tmp_path / "cal_d")
    cls_high = _write_synthetic_classifier_bundle(tmp_path / "cls_hi", hot_idx=31, hot_logit=12.0)  # pho
    cls_mid = _write_synthetic_classifier_bundle(tmp_path / "cls_mid", hot_idx=31, hot_logit=4.8)  # ~0.28 prob -> <0.45

    deps_hi = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_high,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    out_hi = estimate_meal_calories(deps_hi, image_bytes=_textured_jpeg_bytes(), portion="vua")
    assert out_hi.fusion_mode == "variance_weighted"
    assert out_hi.disambiguation_required is False
    assert out_hi.top_margin is not None and out_hi.top_margin > 0.8
    assert "Viện Dinh Dưỡng" in out_hi.provenance_label_vi
    assert len(out_hi.suggested_modifiers) >= 3

    # Build a synthetic classifier with conf_threshold=0.25 and moderate top1=0.50 (margin < 0.12)
    cls_tie_dir = tmp_path / "cls_tie"
    cls_tie_dir.mkdir(parents=True, exist_ok=True)
    rec = yaml.safe_load((REPO_ROOT / "data" / "kb" / "recognized_dishes_nutrition.yaml").read_text(encoding="utf-8"))
    dishes = rec["dishes"]
    logits = np.full((1, len(dishes)), -10.0, dtype=np.float32)
    logits[0, 31] = 2.0   # pho ~0.52
    logits[0, 28] = 1.85  # hu_tieu ~0.45 -> margin ~0.07 < 0.12
    nodes = [
        _node("GlobalAveragePool", ["image"], ["g"], []),
        _node("Flatten", ["g"], ["f"], []),
        _node("MatMul", ["f", "w_zero"], ["z"], []),
        _node("Add", ["z", "bias"], ["logits"], []),
    ]
    inits = [
        _tensor_proto_float("w_zero", [3, 1], np.zeros((3, 1), dtype=np.float32)),
        _tensor_proto_float("bias", [1, len(dishes)], logits),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"dish_tie_test")
        + b"".join(_ld(5, i) for i in inits)
        + _ld(11, _value_info("image", [1, 3, 224, 224]))
        + _ld(12, _value_info("logits", [1, len(dishes)]))
    )
    onnx_path = cls_tie_dir / "model.onnx"
    onnx_path.write_bytes(_vi(1, 8) + _ld(7, graph) + _ld(8, _ld(1, b"") + _vi(2, 13)))
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    serving = {
        "schema_version": "dish_classifier.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "input": {"name": "image", "shape": [1, 3, 224, 224], "crop": "center"},
        "temperature": 1.0,
        "conf_threshold": 0.25,
        "n_classes": len(dishes),
        "classes": [
            {
                "id": d["dish_id"],
                "name_vi": d["name_vi"],
                "name_en": d["name_en"],
                "category": d["category"],
                "kb_slug": d.get("kb_slug"),
                "slot": d.get("slot"),
            }
            for d in dishes
        ],
    }
    (cls_tie_dir / "serving.json").write_text(json.dumps(serving, ensure_ascii=False), encoding="utf-8")

    deps_tie = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_tie_dir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    out_tie = estimate_meal_calories(deps_tie, image_bytes=_textured_jpeg_bytes(), portion="vua")
    assert out_tie.fusion_mode == "variance_weighted"
    assert out_tie.disambiguation_required is True
    assert out_tie.top_margin is not None and out_tie.top_margin < 0.12

    # Explicit dish query never requires disambiguation and uses kb_exact
    out_exp = estimate_meal_calories(deps_tie, image_bytes=_textured_jpeg_bytes(), dish_slug="bo-kho", portion="vua")
    assert out_exp.fusion_mode == "kb_exact"
    assert out_exp.disambiguation_required is False

    # Stage 2 top3_blend when top1 < conf_threshold (0.45) and top-k sum >= 0.50
    cls_s2_dir = tmp_path / "cls_s2"
    cls_s2_dir.mkdir(parents=True, exist_ok=True)
    logits_s2 = np.full((1, len(dishes)), -10.0, dtype=np.float32)
    logits_s2[0, 31] = 2.0  # ~0.36
    logits_s2[0, 28] = 1.9  # ~0.33
    logits_s2[0, 15] = 1.8  # ~0.30 -> top3 sum ~0.99 >= 0.50, top1 < 0.45
    graph_s2 = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"dish_s2_test")
        + b"".join(_ld(5, i) for i in [_tensor_proto_float("w_zero", [3, 1], np.zeros((3, 1), dtype=np.float32)), _tensor_proto_float("bias", [1, len(dishes)], logits_s2)])
        + _ld(11, _value_info("image", [1, 3, 224, 224]))
        + _ld(12, _value_info("logits", [1, len(dishes)]))
    )
    onnx_s2 = cls_s2_dir / "model.onnx"
    onnx_s2.write_bytes(_vi(1, 8) + _ld(7, graph_s2) + _ld(8, _ld(1, b"") + _vi(2, 13)))
    serving_s2 = dict(serving, artifact_sha256=hashlib.sha256(onnx_s2.read_bytes()).hexdigest(), conf_threshold=0.45)
    (cls_s2_dir / "serving.json").write_text(json.dumps(serving_s2, ensure_ascii=False), encoding="utf-8")
    deps_s2 = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_s2_dir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    out_s2 = estimate_meal_calories(deps_s2, image_bytes=_textured_jpeg_bytes(), portion="vua")
    assert out_s2.fusion_mode == "top3_blend"
    assert out_s2.disambiguation_required is True
    assert out_s2.dish_name_vi is None
    _ = cls_mid


def test_p0_energy_maxlogit_raps_ood_gate(tmp_path: Path) -> None:
    from tastoria.modules.meal_calorie.estimator import sanitize_meal_image

    # Synthetic classifier with OOD gate enabled
    cls_ood_dir = _write_synthetic_classifier_bundle(tmp_path / "cls_ood", hot_idx=31, hot_logit=3.0)
    srv_path = cls_ood_dir / "serving.json"
    srv = json.loads(srv_path.read_text(encoding="utf-8"))
    srv.update({"ood_energy_max": -6.8, "ood_max_logit_min": 5.2, "raps_tau": 0.95, "raps_k_reg": 3, "raps_lambda": 0.01})
    srv_path.write_text(json.dumps(srv, ensure_ascii=False), encoding="utf-8")

    clf = load_dish_classifier(cls_ood_dir, verify_sha256=True)
    res_ood = clf.predict(Image.new("RGB", (224, 224), (200, 100, 50)), top_k=3)
    assert res_ood.is_ood is True
    assert res_ood.confident is False
    assert res_ood.max_logit == pytest.approx(3.0, abs=0.1)
    assert res_ood.energy_score > -6.8
    assert res_ood.raps_set_size > 3

    # Real deployed SigLIP2 v3 P0 gate check (if staged locally)
    deploy_cls = REPO_ROOT / "deploy" / "models" / "dish_classifier"
    pho_path = REPO_ROOT / "app" / "assets" / "food" / "pho.webp"
    if (deploy_cls / "model.onnx").is_file() and pho_path.is_file():
        real_clf = load_dish_classifier(deploy_cls, verify_sha256=True)
        pho_res = real_clf.predict(sanitize_meal_image(pho_path.read_bytes()), top_k=3)
        assert pho_res.is_ood is False
        assert pho_res.max_logit >= 5.2
        assert pho_res.energy_score <= -6.8

        rng = np.random.default_rng(7)
        noise_img = Image.fromarray(rng.integers(0, 256, (224, 224, 3), dtype=np.uint8))
        noise_res = real_clf.predict(noise_img, top_k=3)
        assert noise_res.is_ood is True
        assert noise_res.confident is False
        assert noise_res.raps_set_size > 3


def test_vn_home_dishes_category_and_platter_backoff() -> None:
    from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
    from tastoria.modules.meal_calorie.estimator import VisualPrediction
    from tastoria.modules.meal_calorie.service import fuse_photo_estimate

    rec = yaml.safe_load((REPO_ROOT / "data" / "kb" / "recognized_dishes_nutrition.yaml").read_text(encoding="utf-8"))
    by_id = {d["dish_id"]: d for d in rec["dishes"]}
    for did in ("rau_cai_xao", "trung_xao_ca_chua", "ca_hap_xi_dau"):
        assert by_id[did]["category"] == "vn"

    srv_path = REPO_ROOT / "deploy" / "models" / "dish_classifier" / "serving.json"
    if srv_path.is_file():
        srv = json.loads(srv_path.read_text(encoding="utf-8"))
        cls_map = {c["id"]: c for c in srv["classes"]}
        for did in ("rau_cai_xao", "trung_xao_ca_chua", "ca_hap_xi_dau"):
            assert cls_map[did]["category"] == "vn"

    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # Confident non-VN global dish (pizza) stays in variance_weighted with KB fusion & disambiguation_required=False
    cls_pizza = DishClassification(
        top_k=[DishCandidate("pizza", "Pizza", "Pizza", 0.96, None, "man")],
        top1_id="pizza",
        top1_name_vi="Pizza",
        top1_confidence=0.96,
        confident=True,
        conf_threshold=0.42,
        latency_ms=10.0,
        top_margin=0.92,
        raps_set_size=1,
        is_ood=False,
    )
    vis_pizza = VisualPrediction(kcal=720.0, mass_g=420.0, fat_g=28.0, carb_g=82.0, protein_g=32.0, latency_ms=5.0)
    out_pizza = fuse_photo_estimate(kb=kb, vis=vis_pizza, cls_res=cls_pizza, portion="vua")
    assert out_pizza.fusion_mode == "variance_weighted"
    assert out_pizza.disambiguation_required is False
    assert out_pizza.dish_name_vi is not None
    assert 442.0 <= out_pizza.estimated_kcal < 720.0
    assert out_pizza.estimated_mass_g is not None and 220.0 < out_pizza.estimated_mass_g < 420.0

    # Large multi-person seafood feast platter backs off cleanly to visual_fallback (without forcing disambiguation)
    cls_fish = DishClassification(
        top_k=[DishCandidate("ca_hap_xi_dau", "Cá hấp xì dầu", "Steamed Fish", 0.98, "ca-dieu-hong-hap-xi-dau", "man")],
        top1_id="ca_hap_xi_dau",
        top1_name_vi="Cá hấp xì dầu",
        top1_confidence=0.98,
        confident=True,
        conf_threshold=0.42,
        latency_ms=10.0,
        top_margin=0.96,
        raps_set_size=1,
        is_ood=False,
    )
    vis_feast = VisualPrediction(kcal=1098.5, mass_g=789.0, fat_g=35.0, carb_g=40.0, protein_g=110.0, latency_ms=5.0)
    out_feast = fuse_photo_estimate(kb=kb, vis=vis_feast, cls_res=cls_fish, portion="vua")
    assert out_feast.fusion_mode == "visual_fallback"
    assert out_feast.estimated_kcal == 1098.5
    assert out_feast.disambiguation_required is False

    # Single-serving VN dish with high RAPS=11 but clear margin>=0.24 stays in variance_weighted
    cls_pho = DishClassification(
        top_k=[
            DishCandidate("pho", "Phở", "Pho", 0.451, None, "man"),
            DishCandidate("hu_tieu", "Hủ tiếu", "Hu tieu", 0.203, None, "man"),
        ],
        top1_id="pho",
        top1_name_vi="Phở",
        top1_confidence=0.451,
        confident=True,
        conf_threshold=0.42,
        latency_ms=10.0,
        top_margin=0.248,
        raps_set_size=11,
        is_ood=False,
    )
    vis_pho = VisualPrediction(
        kcal=160.7, mass_g=292.0, fat_g=5.0, carb_g=20.0, protein_g=8.0, latency_ms=5.0, food_area_ratio=0.20, multi_dish_score=0.26
    )
    out_pho = fuse_photo_estimate(kb=kb, vis=vis_pho, cls_res=cls_pho, portion="vua")
    assert out_pho.fusion_mode == "variance_weighted"
    assert 370.0 < out_pho.estimated_kcal <= 444.0


def test_ood_gate_propagation_on_flat_and_noise_frames(tmp_path: Path) -> None:
    from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
    from tastoria.modules.meal_calorie.estimator import OOD_WARNING_NOTE, VisualPrediction
    from tastoria.modules.meal_calorie.service import fuse_photo_estimate

    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # 1. Mocked cls_res.is_ood=True must propagate into ood_clamped, note, disambiguation, and widened CI
    cls_ood = DishClassification(
        top_k=[DishCandidate("pho", "Phở", "Pho", 0.15, None, "man")],
        top1_id="pho",
        top1_name_vi="Phở",
        top1_confidence=0.15,
        confident=False,
        conf_threshold=0.42,
        latency_ms=8.0,
        top_margin=0.02,
        energy_score=-6.0,
        max_logit=3.1,
        raps_set_size=25,
        is_ood=True,
    )
    vis_norm = VisualPrediction(kcal=320.0, mass_g=280.0, fat_g=10.0, carb_g=40.0, protein_g=15.0, latency_ms=5.0)
    out_ood = fuse_photo_estimate(kb=kb, vis=vis_norm, cls_res=cls_ood, portion="vua")
    assert out_ood.ood_clamped is True
    assert out_ood.fusion_mode == "visual_fallback"
    assert out_ood.disambiguation_required is True
    assert out_ood.domain_shift_note is not None and OOD_WARNING_NOTE in out_ood.domain_shift_note
    assert out_ood.half_width_rel > 0.35
    assert out_ood.kcal_low < 320.0 * 0.65
    assert out_ood.kcal_high > 320.0 * 1.35

    # 2. Zero-variance flat frames trigger is_ood even on a classifier without energy thresholds
    cls_dir = _write_synthetic_classifier_bundle(tmp_path / "cls_flat_check", hot_idx=31, hot_logit=12.0)
    cal_dir = _write_synthetic_bundle(tmp_path / "cal_flat_check")
    deps_flat = MealCalorieDeps.from_paths(
        model_dir=cal_dir,
        dish_classifier_model_dir=cls_dir,
        kb_dir=REPO_ROOT / "data" / "kb",
        kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
    )
    for size, rgb in [((1, 1), (0, 0, 0)), ((224, 224), (0, 0, 0)), ((224, 224), (128, 128, 128)), ((224, 224), (255, 255, 255))]:
        buf = io.BytesIO()
        Image.new("RGB", size, rgb).save(buf, format="PNG")
        res = estimate_meal_calories(deps_flat, image_bytes=buf.getvalue(), portion="vua")
        assert res.ood_clamped is True
        assert res.disambiguation_required is True
        assert res.domain_shift_note is not None and OOD_WARNING_NOTE in res.domain_shift_note
        assert res.half_width_rel > 0.35

    # 3. Real deployed models: all 5 degenerate images must propagate OOD cleanly
    deploy_cal = REPO_ROOT / "deploy" / "models" / "meal_calorie"
    deploy_cls = REPO_ROOT / "deploy" / "models" / "dish_classifier"
    if (deploy_cal / "model.onnx").is_file() and (deploy_cls / "model.onnx").is_file():
        deps_real = MealCalorieDeps.from_paths(
            model_dir=deploy_cal,
            dish_classifier_model_dir=deploy_cls,
            kb_dir=REPO_ROOT / "data" / "kb",
            kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        )
        rng = np.random.default_rng(123)
        probes = [
            Image.new("RGB", (1, 1), (0, 0, 0)),
            Image.new("RGB", (224, 224), (0, 0, 0)),
            Image.new("RGB", (224, 224), (128, 128, 128)),
            Image.new("RGB", (224, 224), (255, 255, 255)),
            Image.fromarray(rng.integers(0, 256, (224, 224, 3), dtype=np.uint8)),
        ]
        for im in probes:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            out = estimate_meal_calories(deps_real, image_bytes=buf.getvalue(), portion="vua")
            assert out.ood_clamped is True
            assert out.disambiguation_required is True
            assert out.domain_shift_note is not None and OOD_WARNING_NOTE in out.domain_shift_note
            assert out.half_width_rel > 0.35


def test_confident_asian_global_dishes_and_zero_vis_safety() -> None:
    from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
    from tastoria.modules.meal_calorie.estimator import VisualPrediction
    from tastoria.modules.meal_calorie.service import fuse_photo_estimate

    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    for did, vk, vm in [
        ("omelette", 246.2, 217.8),
        ("dau_phu_non", 280.0, 260.0),
        ("rau_cu_xao_thap_cam", 568.8, 619.0),
    ]:
        meta = kb.lookup_recognized(dish_id=did)
        assert meta is not None
        cls_ok = DishClassification(
            top_k=[DishCandidate(did, meta.name_vi, meta.name_en, 0.99, meta.kb_slug, meta.slot)],
            top1_id=did,
            top1_name_vi=meta.name_vi,
            top1_confidence=0.99,
            confident=True,
            conf_threshold=0.42,
            latency_ms=10.0,
            top_margin=0.98,
            raps_set_size=1,
            is_ood=False,
        )
        vis_ok = VisualPrediction(kcal=vk, mass_g=vm, fat_g=10.0, carb_g=15.0, protein_g=12.0, latency_ms=5.0)
        out = fuse_photo_estimate(kb=kb, vis=vis_ok, cls_res=cls_ok, portion="vua")
        assert out.fusion_mode == "variance_weighted", did
        assert out.disambiguation_required is False, did
        assert out.dish_name_vi is not None and len(out.dish_name_vi) > 0, did
        assert out.estimated_mass_g is not None and out.estimated_mass_g != vm, did

        # vis.kcal == 0 safety guard: must fall back to kb_exact (never 0.0 kcal visual_fallback)
        vis_zero = VisualPrediction(kcal=0.0, mass_g=0.0, fat_g=0.0, carb_g=0.0, protein_g=0.0, latency_ms=5.0)
        out_z = fuse_photo_estimate(kb=kb, vis=vis_zero, cls_res=cls_ok, portion="vua")
        assert out_z.fusion_mode == "kb_exact", did
        assert out_z.estimated_kcal == meta.kcal_per_serving
        assert out_z.estimated_mass_g == meta.serving_g
        assert out_z.disambiguation_required is False

    # Verify real deployed omelette.webp & tofu-greens.webp if models staged locally
    deploy_cal = REPO_ROOT / "deploy" / "models" / "meal_calorie"
    deploy_cls = REPO_ROOT / "deploy" / "models" / "dish_classifier"
    if (deploy_cal / "model.onnx").is_file() and (deploy_cls / "model.onnx").is_file():
        deps_real = MealCalorieDeps.from_paths(
            model_dir=deploy_cal,
            dish_classifier_model_dir=deploy_cls,
            kb_dir=REPO_ROOT / "data" / "kb",
            kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        )
        for fname in ("omelette.webp", "tofu-greens.webp"):
            fp = REPO_ROOT / "app" / "assets" / "food" / fname
            if fp.is_file():
                res = estimate_meal_calories(deps_real, image_bytes=fp.read_bytes(), portion="vua")
                assert res.fusion_mode == "variance_weighted", fname
                assert res.disambiguation_required is False, fname
                assert res.dish_name_vi is not None, fname
                assert res.estimated_kcal < 300.0, fname


def test_smooth_continuity_fused_mass_and_brand_strings() -> None:
    from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
    from tastoria.modules.meal_calorie.estimator import VisualPrediction
    from tastoria.modules.meal_calorie.service import _provenance_label_vi, fuse_photo_estimate

    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # 1. Smooth continuity across former mass cliffs & margin cliff
    cls_pho = DishClassification(
        top_k=[
            DishCandidate("pho", "Phở", "Pho", 0.85, None, "man"),
            DishCandidate("hu_tieu", "Hủ tiếu", "Hu tieu", 0.10, None, "man"),
        ],
        top1_id="pho",
        top1_name_vi="Phở",
        top1_confidence=0.85,
        confident=True,
        conf_threshold=0.42,
        latency_ms=8.0,
        top_margin=0.75,
        raps_set_size=2,
        is_ood=False,
    )
    for m_lo, m_hi, vk in [(394.9, 395.0, 1080.0), (434.9, 435.0, 950.0), (539.9, 540.0, 560.0)]:
        k1 = fuse_photo_estimate(
            kb=kb, vis=VisualPrediction(kcal=vk, mass_g=m_lo, fat_g=20, carb_g=50, protein_g=20, latency_ms=5), cls_res=cls_pho
        ).estimated_kcal
        k2 = fuse_photo_estimate(
            kb=kb, vis=VisualPrediction(kcal=vk, mass_g=m_hi, fat_g=20, carb_g=50, protein_g=20, latency_ms=5), cls_res=cls_pho
        ).estimated_kcal
        assert abs(k2 - k1) < 2.0, f"Discontinuous mass cliff at {m_lo}->{m_hi}: {k1} -> {k2}"

    cls_m1 = DishClassification(
        top_k=[DishCandidate("pho", "Phở", "Pho", 0.50, None, "man"), DishCandidate("hu_tieu", "Hủ tiếu", "Hu tieu", 0.301, None, "man")],
        top1_id="pho", top1_name_vi="Phở", top1_confidence=0.50, confident=True, conf_threshold=0.42, latency_ms=5.0,
        top_margin=0.199, raps_set_size=8, is_ood=False,
    )
    cls_m2 = DishClassification(
        top_k=[DishCandidate("pho", "Phở", "Pho", 0.50, None, "man"), DishCandidate("hu_tieu", "Hủ tiếu", "Hu tieu", 0.300, None, "man")],
        top1_id="pho", top1_name_vi="Phở", top1_confidence=0.50, confident=True, conf_threshold=0.42, latency_ms=5.0,
        top_margin=0.200, raps_set_size=8, is_ood=False,
    )
    vis_m = VisualPrediction(kcal=320.0, mass_g=300.0, fat_g=10.0, carb_g=40.0, protein_g=15.0, latency_ms=5.0)
    km1 = fuse_photo_estimate(kb=kb, vis=vis_m, cls_res=cls_m1).estimated_kcal
    km2 = fuse_photo_estimate(kb=kb, vis=vis_m, cls_res=cls_m2).estimated_kcal
    assert abs(km2 - km1) < 3.0

    # 2. Fused mass returned in variance_weighted & top3_blend + Mỹ Vị brand cleanup
    out_vw = fuse_photo_estimate(
        kb=kb, vis=VisualPrediction(kcal=565.8, mass_g=372.5, fat_g=15, carb_g=40, protein_g=25, latency_ms=5),
        cls_res=DishClassification(
            top_k=[DishCandidate("ca_hap_xi_dau", "Cá hấp xì dầu", "Steamed Fish", 0.89, None, "man")],
            top1_id="ca_hap_xi_dau", top1_name_vi="Cá hấp xì dầu", top1_confidence=0.89,
            confident=True, conf_threshold=0.42, latency_ms=5.0, top_margin=0.81, raps_set_size=2, is_ood=False,
        ),
    )
    assert out_vw.fusion_mode == "variance_weighted"
    assert out_vw.estimated_mass_g is not None and 240.0 < out_vw.estimated_mass_g < 372.5

    out_t3 = fuse_photo_estimate(
        kb=kb, vis=VisualPrediction(kcal=320.0, mass_g=600.0, fat_g=10, carb_g=40, protein_g=15, latency_ms=5),
        cls_res=DishClassification(
            top_k=[
                DishCandidate("pho", "Phở", "Pho", 0.36, None, "man"),
                DishCandidate("hu_tieu", "Hủ tiếu", "Hu tieu", 0.33, None, "man"),
            ],
            top1_id="pho", top1_name_vi="Phở", top1_confidence=0.36,
            confident=False, conf_threshold=0.42, latency_ms=5.0, top_margin=0.03, raps_set_size=4, is_ood=False,
        ),
    )
    assert out_t3.fusion_mode == "top3_blend"
    assert out_t3.estimated_mass_g is not None and out_t3.estimated_mass_g != 600.0
    assert "Tastoria" not in out_t3.provenance_label_vi
    assert "Mỹ Vị" in out_t3.provenance_label_vi
    assert "Mỹ Vị" in _provenance_label_vi("custom", with_image=False)
    assert "Tastoria" not in _provenance_label_vi("custom", with_image=False)


def test_dish_classifier_nonfinite_logits_and_solid_color_ood_fail_closed(tmp_path: Path) -> None:
    class _FakeInput:
        name = "image"
        shape = [1, 3, 224, 224]

    class _FakeSession:
        def __init__(self, logits: np.ndarray) -> None:
            self._logits = logits

        def get_inputs(self) -> list[_FakeInput]:
            return [_FakeInput()]

        def run(self, *_args: object, **_kwargs: object) -> list[np.ndarray]:
            return [self._logits]

    serving = {
        "conf_threshold": 0.42,
        "classes": [
            {"id": "pho", "name_vi": "Phở", "name_en": "Pho", "category": "vn"},
            {"id": "com_tam", "name_vi": "Cơm tấm", "name_en": "Broken Rice", "category": "vn"},
        ],
    }
    textured_img = Image.open(io.BytesIO(_textured_jpeg_bytes()))
    for bad_row in (
        np.array([[np.nan, 10.0]], dtype=np.float32),
        np.array([[np.inf, -np.inf]], dtype=np.float32),
    ):
        clf_bad = DishClassifier(_FakeSession(bad_row), serving=serving)  # type: ignore[arg-type]
        res_bad = clf_bad.predict(textured_img, top_k=2)
        assert res_bad.is_ood is True
        assert res_bad.confident is False
        assert res_bad.top1_id is None
        assert res_bad.top_k == []

    # Solid colored (120, 90, 60) frame has cross-channel std ~24.5 but spatial per-channel std == 0.0 -> must fail OOD
    cls_dir = _write_synthetic_classifier_bundle(tmp_path / "cls_solid_color", hot_idx=31, hot_logit=12.0)
    clf_solid = load_dish_classifier(cls_dir, verify_sha256=True)
    res_solid = clf_solid.predict(Image.new("RGB", (224, 224), (120, 90, 60)), top_k=3)
    assert res_solid.is_ood is True
    assert res_solid.confident is False

    res_tex = clf_solid.predict(textured_img, top_k=3)
    assert res_tex.is_ood is False
    assert res_tex.confident is True
    assert res_tex.top1_id == "pho"


def test_stage1_margin_and_stage2_conf_smooth_continuity() -> None:
    from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
    from tastoria.modules.meal_calorie.estimator import VisualPrediction
    from tastoria.modules.meal_calorie.service import fuse_photo_estimate

    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")

    # Stage 1 top_margin continuity across 0.149 -> 0.151 (contrasting rau_muong_xao vs com_tam)
    vis_s1 = VisualPrediction(kcal=350.0, mass_g=280.0, fat_g=12.0, carb_g=35.0, protein_g=15.0, latency_ms=5.0)
    for raps in (2, 8):
        k_vals = []
        for c2 in (0.351, 0.349):  # top1=0.50 -> margin=0.149 vs 0.151
            cls_s1 = DishClassification(
                top_k=[
                    DishCandidate("rau_muong_xao", "Rau muống xào", "Morning Glory", 0.50, None, "rau"),
                    DishCandidate("com_tam", "Cơm tấm", "Broken Rice", c2, None, "man"),
                ],
                top1_id="rau_muong_xao",
                top1_name_vi="Rau muống xào",
                top1_confidence=0.50,
                confident=True,
                conf_threshold=0.42,
                latency_ms=5.0,
                top_margin=round(0.50 - c2, 4),
                raps_set_size=raps,
                is_ood=False,
            )
            k_vals.append(fuse_photo_estimate(kb=kb, vis=vis_s1, cls_res=cls_s1, portion="vua").estimated_kcal)
        assert abs(k_vals[1] - k_vals[0]) < 10.0, f"Stage 1 margin cliff at raps={raps}: {k_vals}"

    # Stage 2 confidence entry continuity across 0.299 -> 0.301
    vis_s2 = VisualPrediction(kcal=400.0, mass_g=300.0, fat_g=12.0, carb_g=45.0, protein_g=18.0, latency_ms=5.0)
    k_s2 = []
    for c1 in (0.299, 0.301):
        cls_s2 = DishClassification(
            top_k=[
                DishCandidate("rau_muong_xao", "Rau muống xào", "Morning Glory", c1, None, "rau"),
                DishCandidate("com_tam", "Cơm tấm", "Broken Rice", 0.25, None, "man"),
            ],
            top1_id="rau_muong_xao",
            top1_name_vi="Rau muống xào",
            top1_confidence=c1,
            confident=False,
            conf_threshold=0.42,
            latency_ms=5.0,
            top_margin=round(c1 - 0.25, 4),
            raps_set_size=4,
            is_ood=False,
        )
        k_s2.append(fuse_photo_estimate(kb=kb, vis=vis_s2, cls_res=cls_s2, portion="vua").estimated_kcal)
    assert abs(k_s2[1] - k_s2[0]) < 10.0, f"Stage 2 conf cliff: {k_s2}"
