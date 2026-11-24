"""Tier 1: Backend ONNX/serving, Detector->build_chips, KB/NIN calibration, and meal_calorie isolation contracts."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from kb_helpers import API, key, q, user
from PIL import Image

from tastoria.modules.catalog.bundle import load_bundle
from tastoria.modules.catalog.nutrition import compute
from tastoria.modules.scan import worker as job
from tastoria.modules.scan.aggregate import ClassRule, FoundBox, build_chips

pytestmark = pytest.mark.tier1

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data/kb"
PROCESSED_DIR = REPO_ROOT / "data/processed"


def _load_37_ids() -> list[str]:
    raw = yaml.safe_load((KB_DIR / "vision_classes.yaml").read_text(encoding="utf-8"))
    return [str(r["id"]) for r in list(raw["classes"]) + list(raw.get("proposed_classes") or [])]


def _load_37_countable() -> dict[str, bool]:
    raw = yaml.safe_load((KB_DIR / "vision_classes.yaml").read_text(encoding="utf-8"))
    return {str(r["id"]): bool(r["countable"]) for r in list(raw["classes"]) + list(raw.get("proposed_classes") or [])}


def test_detector_onnx_and_serving_contract(e2e_cfg, e2e_detector) -> None:
    inp = e2e_detector.session.get_inputs()[0]
    out = e2e_detector.session.get_outputs()[0]
    c = len(e2e_detector.classes)
    assert len(inp.shape) == 4 and inp.shape[0] == 1 and inp.shape[1] == 3 and inp.shape[2] == inp.shape[3]
    assert tuple(out.shape) == (1, 4 + c, 8400)

    meta = e2e_detector.session.get_modelmeta().custom_metadata_map
    assert meta.get("end2end") == "False"

    expected_37 = _load_37_ids()
    assert len(expected_37) == 37
    if "classes" in e2e_detector.manifest:
        assert e2e_detector.manifest["classes"] == e2e_detector.classes
    if "classes" in e2e_detector.serving:
        assert e2e_detector.serving["classes"] == e2e_detector.classes
    if e2e_cfg.strict:
        assert c == 37 and e2e_detector.classes == expected_37
    else:
        assert set(e2e_detector.classes) <= set(expected_37)

    digest = hashlib.sha256(e2e_detector.onnx_path.read_bytes()).hexdigest()
    assert e2e_detector.manifest["sha256"] == digest
    assert 0.0 < float(e2e_detector.serving["conf"]) < 1.0
    assert 0.0 < float(e2e_detector.serving["iou"]) < 1.0
    if e2e_detector.serving.get("agnostic_iou") is not None:
        assert 0.0 < float(e2e_detector.serving["agnostic_iou"]) < 1.0
    if e2e_detector.serving.get("class_conf") is not None:
        cc = e2e_detector.serving["class_conf"]
        assert set(cc) <= set(e2e_detector.classes)
        assert all(0.0 < float(v) <= 1.0 for v in cc.values())


def test_detector_detect_to_build_chips_invariants(e2e_detector, real_produce_images: list[Path]) -> None:
    countable_by_code = _load_37_countable()
    rules = {
        vid: ClassRule(
            countable=countable_by_code[code],
            ingredient_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"e2e.ing.{code}"),
        )
        for vid, code in e2e_detector.code_by_vid.items()
    }

    found: list[FoundBox] = []
    for idx, img_path in enumerate(real_produce_images[:6]):
        with Image.open(img_path) as im:
            boxes = e2e_detector.detector.detect(im.convert("RGB"))
        confs = [b.confidence for b in boxes]
        assert confs == sorted(confs, reverse=True)
        for b in boxes:
            assert 0.0 <= b.x1 < b.x2 <= 1.0
            assert 0.0 <= b.y1 < b.y2 <= 1.0
            found.append(
                FoundBox(
                    image=idx,
                    shelf_group=1 if idx < 3 else 2,
                    vision_class_id=e2e_detector.class_map[b.class_index],
                    confidence=b.confidence,
                )
            )
    assert len(found) > 0, "Expected at least one detection across real produce images"

    chips = build_chips(found, rules)
    assert len(chips) > 0
    assert [c.best_confidence for c in chips] == sorted((c.best_confidence for c in chips), reverse=True)
    for ch in chips:
        box_vids = {found[i].vision_class_id for i in ch.boxes}
        if any(rules[vid].countable for vid in box_vids):
            assert isinstance(ch.model_count, int) and ch.model_count >= 1
        else:
            assert ch.model_count is None


@pytest.mark.parametrize(
    "rule_case",
    ["same_shelf_max", "cross_shelf_sum", "uncountable_none", "cautious_u_img"],
)
def test_build_chips_shelf_aggregation_and_freshness_contract(rule_case: str) -> None:
    ing_egg = uuid.uuid4()
    ing_spinach = uuid.uuid4()
    rules = {
        1: ClassRule(True, ing_egg),
        2: ClassRule(False, ing_spinach),
        3: ClassRule(True, None),
    }

    if rule_case == "same_shelf_max":
        found = [FoundBox(0, 1, 1, 0.8)] * 4 + [FoundBox(1, 1, 1, 0.7)] * 3 + [FoundBox(0, 1, 3, 0.9)]
        chips = build_chips(found, rules)
        assert len(chips) == 1 and chips[0].model_count == 4 and len(chips[0].boxes) == 7
    elif rule_case == "cross_shelf_sum":
        found = [FoundBox(0, 1, 1, 0.8)] * 4 + [FoundBox(1, 2, 1, 0.7)] * 3
        chips = build_chips(found, rules)
        assert len(chips) == 1 and chips[0].model_count == 7
    elif rule_case == "uncountable_none":
        found = [FoundBox(0, 1, 2, 0.85), FoundBox(1, 2, 2, 0.65)]
        chips = build_chips(found, rules)
        assert len(chips) == 1 and chips[0].model_count is None
    else:
        low_u = (0.9, 0.1, 0.0, 0.0)
        high_u = (0.1, 0.1, 0.3, 0.5)
        found = [FoundBox(0, 1, 2, 0.95, low_u), FoundBox(1, 1, 2, 0.55, high_u)]
        chips = build_chips(found, rules)
        assert chips[0].probs == high_u and chips[0].best_confidence == pytest.approx(0.95)


def test_kb_bundle_and_nutrition_compute_contract() -> None:
    b = load_bundle(KB_DIR, PROCESSED_DIR)
    assert b.ok, f"Catalog bundle errors: {b.errors[:5]}"
    assert len(b.recipes) == 180
    assert len(b.ingredients) >= 232

    nut = compute(b, PROCESSED_DIR)
    assert nut.engine == "tastoria_ml"
    assert len(nut.per_serving) == 180
    assert nut.rice_bowl_kcal == pytest.approx(173.2, abs=0.5)


def test_nin_dishes_calibration_and_recipe_nutrition_csv_contract(e2e_cfg) -> None:
    b = load_bundle(KB_DIR, PROCESSED_DIR)
    nut = compute(b, PROCESSED_DIR)

    nin_doc = yaml.safe_load((KB_DIR / "validation/nin_dishes.yaml").read_text(encoding="utf-8"))
    dishes = nin_doc["dishes"]
    summary = nin_doc["summary"]
    assert len(dishes) >= e2e_cfg.min_nin_dishes
    assert int(summary["n"]) >= 30
    assert summary["data_version"] == nut.data_version
    assert float(summary["p80_abs_rel_error"]) <= 0.25

    dish_list = yaml.safe_load((KB_DIR / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]
    expected_slugs = {str(d["slug"]) for d in dish_list}
    assert len(expected_slugs) == 180

    with (PROCESSED_DIR / "kb/recipe_nutrition.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    csv_slugs = {r["slug"] for r in rows}
    assert csv_slugs == expected_slugs
    for r in rows:
        kcal = float(r["kcal_per_serving"])
        assert np.isfinite(kcal) and kcal > 0.0
    if e2e_cfg.strict:
        assert {r["data_version"] for r in rows} == {nut.data_version}


@pytest.mark.parametrize("scan_file", ["detector.py", "service.py"])
def test_meal_calorie_ast_and_class_isolation(scan_file: str) -> None:
    src_path = REPO_ROOT / "backend/src/tastoria/modules/scan" / scan_file
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for mod in imported:
        assert "meal_calorie" not in mod and "tastoria_ml.calorie" not in mod, (
            f"Hard isolation violation: {scan_file} imports {mod}"
        )

    dish_slugs = {str(d["slug"]) for d in yaml.safe_load((KB_DIR / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]}
    vision_ids = set(_load_37_ids())
    assert not (vision_ids & dish_slugs), f"Cooked dish slugs leaked into vision_classes: {vision_ids & dish_slugs}"


def test_meal_calorie_service_or_api_contract(e2e_cfg, meal_calorie_probe: dict[str, Any] | None) -> None:
    if meal_calorie_probe is None:
        assert not e2e_cfg.strict
        from tastoria.modules.scan import detector as scan_det
        from tastoria.modules.scan import service as scan_svc

        assert not hasattr(scan_det, "estimate_meal_calories")
        assert not hasattr(scan_svc, "estimate_meal_calories")
        return

    svc = meal_calorie_probe["service"]
    deps = meal_calorie_probe["deps"]
    dish_list = svc.list_dishes(deps)
    assert len(dish_list.dishes) == 180

    # KB-calibrated portion estimation works in both baseline & strict modes
    kb_kcals: list[float] = []
    for portion in ("nho", "vua", "lon"):
        res = svc.estimate_meal_calories(deps, dish_slug="bo-kho", portion=portion)
        assert res.source == "kb_calibrated"
        assert np.isfinite(res.estimated_kcal) and res.estimated_kcal > 0.0
        assert res.kcal_low <= res.estimated_kcal <= res.kcal_high
        kb_kcals.append(res.estimated_kcal)
    assert kb_kcals[0] < kb_kcals[1] < kb_kcals[2]

    # ONNX photo estimation (mandatory under STRICT_V4=1, executed when artifact staged)
    if meal_calorie_probe["has_onnx"] or e2e_cfg.strict:
        pho_bytes = (REPO_ROOT / "app/assets/food/pho.webp").read_bytes()
        vis_kcals: list[float] = []
        for portion in ("nho", "vua", "lon"):
            res = svc.estimate_meal_calories(deps, image_bytes=pho_bytes, portion=portion)
            assert res.source in {"onnx_nutrition5k", "hybrid"}
            assert np.isfinite(res.estimated_kcal) and res.estimated_kcal > 0.0
            vis_kcals.append(res.estimated_kcal)
        assert vis_kcals[0] < vis_kcals[1] < vis_kcals[2]


# ---------------------------------------------------------------- EF5 additional Tier 1 contracts


def test_rice_bowl_and_kb_catalog_portion_scaling_contract() -> None:
    """Verify rice_bowl.json (173.2 kcal / 150.0 g) & KBDishCatalog nho < vua < lon scaling."""
    from tastoria.modules.meal_calorie.kb_lookup import KBDishCatalog

    rice = json.loads((PROCESSED_DIR / "kb/rice_bowl.json").read_text(encoding="utf-8"))
    assert float(rice["energy_kcal"]) == pytest.approx(173.2, abs=0.5)
    assert float(rice["cooked_g"]) == pytest.approx(150.0, abs=0.5)

    cat = KBDishCatalog.from_dirs(KB_DIR, PROCESSED_DIR / "kb")
    assert len(cat.dishes) == 180
    assert cat.calibrated is True
    assert 0.0 < cat.half_width_rel <= 0.25

    for slug in ("bo-kho", "canh-chua-ca-loc", "dau-phu-sot-ca-chua"):
        nho = cat.estimate(dish_slug=slug, portion="nho")
        vua = cat.estimate(dish_slug=slug, portion="vua")
        lon = cat.estimate(dish_slug=slug, portion="lon")
        assert nho is not None and vua is not None and lon is not None
        assert nho.portion_multiplier == 0.75
        assert vua.portion_multiplier == 1.0
        assert lon.portion_multiplier == 1.35
        assert nho.estimated_kcal < vua.estimated_kcal < lon.estimated_kcal
        assert vua.kcal_low <= vua.estimated_kcal <= vua.kcal_high


def test_meal_calorie_catalog_and_kb_alignment_contract(
    e2e_cfg, meal_calorie_probe: dict[str, Any] | None
) -> None:
    """Verify meal_calorie.list_dishes aligns 1:1 with dish_list.yaml and recipe_nutrition.csv."""
    from tastoria.modules.meal_calorie.kb_lookup import KBDishCatalog

    dish_yaml = yaml.safe_load((KB_DIR / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]
    yaml_by_slug = {str(d["slug"]): d for d in dish_yaml}
    assert len(yaml_by_slug) == 180

    cat = KBDishCatalog.from_dirs(KB_DIR, PROCESSED_DIR / "kb")
    assert {d.slug for d in cat.dishes} == set(yaml_by_slug)
    for d in cat.dishes:
        assert d.slot in {"man", "rau", "canh"}
        assert d.kcal_per_serving > 0.0
        assert d.name_vi == yaml_by_slug[d.slug]["name_vi"]

    if meal_calorie_probe is not None:
        svc = meal_calorie_probe["service"]
        deps = meal_calorie_probe["deps"]
        listed = svc.list_dishes(deps)
        assert len(listed.dishes) == 180
        assert listed.calibrated is True
        assert {d.slug for d in listed.dishes} == set(yaml_by_slug)
    else:
        assert not e2e_cfg.strict


@pytest.mark.integration
def test_meal_calorie_http_endpoints_contract(kb_client, e2e_cfg) -> None:
    """EF5 HTTP contract: GET /api/v1/meal-calorie/dishes & POST /api/v1/meal-calorie/estimate via kb_client."""
    h = user(kb_client)
    r_list = kb_client.get(f"{API}/meal-calorie/dishes", headers=h)
    assert r_list.status_code == 200, r_list.text
    list_body = r_list.json()
    assert len(list_body["dishes"]) == 180
    assert list_body["calibrated"] is True
    assert list_body["data_version"]

    kcals: list[float] = []
    for portion in ("nho", "vua", "lon"):
        r_est = kb_client.post(
            f"{API}/meal-calorie/estimate",
            data={"dish_slug": "bo-kho", "portion": portion},
            headers=h,
        )
        assert r_est.status_code == 200, r_est.text
        body = r_est.json()
        assert body["source"] == "kb_calibrated"
        assert body["kb_slug"] == "bo-kho"
        assert body["kcal_low"] <= body["estimated_kcal"] <= body["kcal_high"]
        kcals.append(float(body["estimated_kcal"]))
    assert kcals[0] < kcals[1] < kcals[2]

    r_name = kb_client.post(
        f"{API}/meal-calorie/estimate",
        data={"dish_name": "Thịt kho tàu", "portion": "vua"},
        headers=h,
    )
    assert r_name.status_code == 200, r_name.text
    assert r_name.json()["kb_slug"] == "thit-kho-tau"

    if (REPO_ROOT / "deploy/models/meal_calorie/serving.json").is_file() or e2e_cfg.strict:
        pho_bytes = (REPO_ROOT / "app/assets/food/pho.webp").read_bytes()
        r_img = kb_client.post(
            f"{API}/meal-calorie/estimate",
            data={"portion": "vua"},
            files={"image": ("pho.webp", pho_bytes, "image/webp")},
            headers=h,
        )
        assert r_img.status_code == 200, r_img.text
        img_body = r_img.json()
        assert img_body["source"] in {"onnx_nutrition5k", "hybrid"}
        assert img_body["estimated_kcal"] > 0.0


# ---------------------------------------------------------------- EF3 DB-backed MLOps lifecycle


@pytest.mark.integration
def test_mlops_register_gate_deploy_db_workflow(
    kb_app, kb_engine, kb_clean, storage_dir: Path, e2e_detector
) -> None:
    """EF3 DB contract: real tastoria.modules.admin.mlops.register -> gate -> deploy -> active_version."""
    from sqlalchemy.orm import Session

    from tastoria.modules.admin import mlops as admin_mlops
    from tastoria.modules.mlops import service as mlops_svc

    sm = kb_app.state.sessionmaker
    ver = f"e2e-mlops-{uuid.uuid4().hex[:8]}"
    art_dir = storage_dir / "models" / "detector" / ver
    try:
        view, created = admin_mlops.register(
            sm,
            storage_dir,
            name="detector",
            version=ver,
            artifact=e2e_detector.onnx_path,
            metrics={"serving": dict(e2e_detector.serving)},
            preprocess_version=e2e_detector.manifest.get("preprocess_version") or "none",
            class_codes=None,
        )
        assert created is True
        assert view.status == "candidate"
        assert len(view.class_map) == len(e2e_detector.classes)

        ok, reasons = admin_mlops.gate(sm, storage_dir, name="detector", version=ver)
        assert ok is True, f"MLOps gate rejected valid detector ONNX: {reasons}"
        assert reasons == []
        assert (art_dir / "gate.json").is_file()

        dep = admin_mlops.deploy(sm, name="detector", version=ver)
        assert dep["changed"] is True
        assert dep["active_version_id"] == str(view.id)

        with kb_engine.connect() as conn, Session(bind=conn) as s:
            active = mlops_svc.active_version(s, "detector")
            assert active is not None and active.id == view.id and active.status == "validated"
            sess = mlops_svc.load_onnx(storage_dir, active, intra_op_threads=2)
            assert sess.get_providers() == ["CPUExecutionProvider"]
    finally:
        with kb_engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM model_deployments WHERE name = 'detector'")
            conn.exec_driver_sql(
                "DELETE FROM model_version_classes WHERE model_version_id IN "
                "(SELECT id FROM model_versions WHERE name = 'detector' AND version = %s)",
                (ver,),
            )
            conn.exec_driver_sql("DELETE FROM model_versions WHERE name = 'detector' AND version = %s", (ver,))
        shutil.rmtree(art_dir, ignore_errors=True)


# ---------------------------------------------------------------- EF6 additional isolation & CPU contracts


def test_meal_calorie_modules_never_import_scan_or_pantry_models() -> None:
    """EF6 bidirectional AST isolation: meal_calorie & tastoria_ml.calorie never import scan/pantry."""
    scan_dirs = [REPO_ROOT / "backend/src/tastoria/modules/meal_calorie"]
    ml_cal_dir = REPO_ROOT / "ml/src/tastoria_ml/calorie"
    if ml_cal_dir.is_dir():
        scan_dirs.append(ml_cal_dir)

    forbidden_modules = ("tastoria.modules.scan", "tastoria.modules.pantry")
    forbidden_tokens = ("pantry_lots", "scan_jobs", "scan_boxes")
    py_files = [p for d in scan_dirs for p in sorted(d.glob("*.py"))]
    assert len(py_files) > 0

    for py_file in py_files:
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_file))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for mod in imported:
            assert not any(mod.startswith(f) for f in forbidden_modules), (
                f"Bidirectional isolation violation: {py_file.name} imports {mod}"
            )
        for tok in forbidden_tokens:
            assert tok not in src, f"Forbidden scan/pantry table/symbol {tok!r} referenced in {py_file.name}"


def test_vision_classes_zero_cooked_dish_slugs_or_names() -> None:
    """EF6 class isolation: vision_classes.yaml shares zero slugs or Vietnamese dish names with cooked KB/NIN."""
    import unicodedata

    def _fold(s: str) -> str:
        nfkd = unicodedata.normalize("NFKD", s.strip().casefold())
        return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("đ", "d")

    raw_vc = yaml.safe_load((KB_DIR / "vision_classes.yaml").read_text(encoding="utf-8"))
    vc_rows = list(raw_vc["classes"]) + list(raw_vc.get("proposed_classes") or [])
    vc_ids = {str(r["id"]) for r in vc_rows}
    vc_names_vi = {_fold(str(r["name_vi"])) for r in vc_rows if r.get("name_vi")}

    dish_list = yaml.safe_load((KB_DIR / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]
    dish_slugs = {str(d["slug"]) for d in dish_list}
    dish_names_vi = {_fold(str(d["name_vi"])) for d in dish_list}

    nin_dishes = yaml.safe_load((KB_DIR / "validation/nin_dishes.yaml").read_text(encoding="utf-8"))["dishes"]
    nin_names_vi = {_fold(str(d["name_vi"])) for d in nin_dishes if d.get("name_vi")}

    assert not (vc_ids & dish_slugs)
    assert not (vc_names_vi & dish_names_vi)
    assert not (vc_names_vi & nin_names_vi)


def test_cpu_execution_provider_and_threads_enforcement(e2e_detector) -> None:
    """EF6 CPU runtime contract: CPUExecutionProvider & intra_op_num_threads == 2 in detector & mlops.load_onnx."""
    import inspect
    from datetime import UTC, datetime

    from tastoria.modules.mlops import service as mlops_svc
    from tastoria.modules.mlops.schemas import ModelVersionView

    assert e2e_detector.session.get_providers() == ["CPUExecutionProvider"]

    sig = inspect.signature(mlops_svc.load_onnx)
    assert sig.parameters["intra_op_threads"].default == 2
    load_src = inspect.getsource(mlops_svc.load_onnx)
    assert "CPUExecutionProvider" in load_src
    assert "so.intra_op_num_threads = intra_op_threads" in load_src
    assert "session.intra_op.allow_spinning" in load_src

    # Exercise real mlops.load_onnx end-to-end against detector ONNX artifact
    digest = hashlib.sha256(e2e_detector.onnx_path.read_bytes()).hexdigest()
    view = ModelVersionView(
        id=uuid.uuid4(),
        name="detector",
        version="e2e-cpu-check",
        artifact_key=e2e_detector.onnx_path.name,
        sha256=digest,
        preprocess_version=e2e_detector.manifest.get("preprocess_version"),
        metrics={},
        status="validated",
        created_at=datetime.now(UTC),
        class_map={i: i for i in range(len(e2e_detector.classes))},
        is_active=True,
        gate_report_key=None,
        mlflow_run_id=None,
    )
    loaded_sess = mlops_svc.load_onnx(e2e_detector.onnx_path.parent, view)
    assert loaded_sess.get_providers() == ["CPUExecutionProvider"]

    from tastoria.modules.meal_calorie import estimator as mc_est

    mc_sig = inspect.signature(mc_est.make_cpu_session)
    assert mc_sig.parameters["intra_threads"].default == 2
    mc_src = inspect.getsource(mc_est.make_cpu_session)
    assert "CPUExecutionProvider" in mc_src
    assert "so.intra_op_num_threads = intra_threads" in mc_src


def test_scan_and_meal_calorie_http_routes_disjoint() -> None:
    """EF6 router isolation: /scans/* and /meal-calorie/* routes and schemas remain strictly disjoint."""
    from tastoria.modules.meal_calorie.router import router as mc_router
    from tastoria.modules.scan.router import router as scan_router

    mc_paths = {r.path for r in mc_router.routes}
    scan_paths = {r.path for r in scan_router.routes}
    assert mc_paths and scan_paths
    assert all(p.startswith("/meal-calorie") for p in mc_paths)
    assert all(p.startswith("/scans") for p in scan_paths)
    assert not (mc_paths & scan_paths)


@pytest.mark.integration
def test_scan_pre_confirm_cooked_upload_pantry_zero(kb_client, kb_db, e2e_worker_ctx) -> None:
    """EF6 scan isolation: uploading cooked meal to /api/v1/scans leaves pantry_lots == 0 pre-confirm."""
    h = user(kb_client)
    buf = io.BytesIO()
    with Image.open(REPO_ROOT / "app/assets/food/caramel-pork.webp") as im:
        im.convert("RGB").save(buf, "JPEG", quality=90)

    r = kb_client.post(
        f"{API}/scans",
        data={"mode": "fridge"},
        files=[("images", ("cooked.jpg", buf.getvalue(), "image/jpeg"))],
        headers=h | key(),
    )
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    assert job.run_job(e2e_worker_ctx, uuid.UUID(sid)) == "done"
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0


@pytest.mark.integration
def test_meal_calorie_estimate_never_mutates_pantry_lots(kb_client, kb_db) -> None:
    """EF6 isolation: calling meal-calorie endpoints never creates pantry_lots or scans rows."""
    h = user(kb_client)
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0
    assert q(kb_db, "SELECT count(*) FROM scans").scalar() == 0

    r_dishes = kb_client.get(f"{API}/meal-calorie/dishes", headers=h)
    assert r_dishes.status_code == 200
    r_est = kb_client.post(
        f"{API}/meal-calorie/estimate",
        data={"dish_slug": "bo-kho", "portion": "vua"},
        headers=h,
    )
    assert r_est.status_code == 200

    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0
    assert q(kb_db, "SELECT count(*) FROM scans").scalar() == 0
