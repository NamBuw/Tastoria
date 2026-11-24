"""Unit tests for Direction 1 8-class FungiCLEF safety-gated mushroom sub-classifier (`G-11`, Contract #3)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from tastoria.modules.catalog.schemas import IngredientView, VisionClassView
from tastoria.modules.mlops.schemas import ModelVersionView
from tastoria.modules.scan import service as scan_service
from tastoria.modules.scan import worker as scan_worker
from tastoria.modules.scan.detector import Box
from tastoria.modules.scan.models import Detection, Scan, ScanImage, ScanItem
from tastoria.modules.scan.schemas import DetectionOut, ScanItemOut
from tastoria.modules.scan.worker import (
    MUSHROOM_SLUGS,
    MushroomClassifier,
    MushroomPrediction,
    WorkerContext,
    load_mushroom_classifier,
    resolve_mushroom_model_dir,
)


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
        shape_dims += _ld(1, _vi(1, d)) if isinstance(d, int) else _ld(1, _ld(2, d.encode()))
    return _ld(1, _vi(1, elem_type) + _ld(2, shape_dims))


def _value_info(name: str, dims: list[int | str]) -> bytes:
    return _ld(1, name.encode()) + _ld(2, _tensor_type_proto(1, dims))


def _node(op_type: str, inputs: list[str], outputs: list[str], attrs: list[bytes]) -> bytes:
    return (
        b"".join(_ld(1, i.encode()) for i in inputs)
        + b"".join(_ld(2, o.encode()) for o in outputs)
        + _ld(4, op_type.encode())
        + b"".join(_ld(5, a) for a in attrs)
    )


def _build_mushroom_test_onnx(path: Path) -> Path:
    """Build an 8-class ONNX model mapping RGB [N,3,224,224] -> raw logits [N,8].

    - Pure Red (255,0,0) -> strong class 0 (nam-rom), very negative energy
    - Pure Green (0,255,0) -> strong class 2 (nam-kim-cham), very negative energy
    - Pure Blue (0,0,255) -> class 6 (other_mushroom, deadly lookalike) -> safety_abstained=True
    - Yellowish (255,255,0) -> class 7 (not_mushroom, e.g. garlic/potato/tofu) -> suppressed!
    - Mid-gray (128,128,128) -> low flat logits -> fails P>=0.85 & high energy -> safety_abstained=True
    """
    # Input rgb_mean is in [0, 255].
    # R channel -> +0.05 to class 0, -0.02 to class 7
    # G channel -> +0.05 to class 2, -0.02 to class 7
    # B channel -> +0.05 to class 6, -0.02 to class 7
    # Wait: make R+G (255,255,0) strongly trigger class 7 (not_mushroom) via +0.06 each to class 7 vs +0.03 to 0,2!
    # Let's use clean orthogonal color encoding:
    # W shape [3, 8]:
    # R=[0.06, 0, -0.02, 0, 0, 0, 0, 0.01]  -> Pure R=(255,0,0): logit0=15.3, logit7=2.55 (class 0 wins!)
    # G=[0, 0, 0.06, 0, 0, 0, 0, 0.01]   -> Pure G=(0,255,0): logit2=15.3, logit7=2.55 (class 2 wins!)
    # B=[-0.02, -0.02, -0.02, 0, 0, 0, 0.08, 0.01] -> Pure B=(0,0,255): class 6 (other_mushroom) wins!
    # Wait for not_mushroom: make (0, 255, 255) Cyan -> G+B -> logit7 = 0.04*255 + 0.04*255 = 20.4, while logit2=10.2, logit6=10.2!
    w = np.array(
        [
            [0.06, 0.0, -0.02, 0.0, 0.0, 0.0, -0.02, 0.01],  # R
            [-0.02, 0.0, 0.04, 0.0, 0.0, 0.0, -0.02, 0.04],  # G -> pure G: logit2=10.2, logit7=10.2? Make G[2]=0.06, G[7]=0.01
            [-0.02, 0.0, -0.02, 0.0, 0.0, 0.0, 0.05, 0.02],  # B
        ],
        dtype=np.float32,
    )
    # Adjust cleanly:
    # Pure R (255,0,0): c0 = 15.3, others <= 0 -> P(c0)~1.0, P(other)~0, E~-15.3
    # Pure G (0,255,0): c2 = 15.3, others <= 0 -> P(c2)~1.0, P(other)~0, E~-15.3
    # Pure B (0,0,255): c6 = 15.3 -> other_mushroom wins!
    # White (255,255,255): c7 = (0.04+0.04+0.04)*255 = 30.6 -> not_mushroom wins!
    # Wait: with R+G+B = 255 each on c0: 0.06 - 0.02 - 0.02 = 0.02*255 = 5.1 << 30.6!
    # And mid-gray (128,128,128): c7 = 0.12*128 = 15.36 -> wait, gray shouldn't be not_mushroom, gray should be ambiguous!
    # Let's make R+G (255, 255, 0) Yellow -> not_mushroom, and Gray (128,128,128) balanced!
    # Actually simplest:
    # R = [0.06, 0, -0.04, 0, 0, 0, 0, 0.02]  -> pure R (255,0,0): c0=15.3, c7=5.1
    # G = [-0.04, 0, 0.06, 0, 0, 0, 0, 0.02] -> pure G (0,255,0): c2=15.3, c7=5.1
    # B = [0, 0, 0, 0, 0, 0, 0.06, -0.04]    -> pure B (0,0,255): c6=15.3
    # Wait: Yellow (255,255,0): c0=5.1, c2=5.1, c7=10.2! -> not_mushroom wins cleanly!
    # And for low-confidence / high-energy ambiguous: (10, 10, 10) dark image -> all logits near 0 -> E = -ln(8) = -2.08 > -8.0 AND max_prob < 0.85!
    w = np.array(
        [
            [0.06, 0.0, -0.04, 0.0, 0.0, 0.0, 0.0, 0.02],
            [-0.04, 0.0, 0.06, 0.0, 0.0, 0.0, 0.0, 0.02],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.06, -0.04],
        ],
        dtype=np.float32,
    )
    tensor_w = _vi(1, 3) + _vi(1, 8) + _vi(2, 1) + _ld(8, b"W") + _ld(9, w.tobytes())

    attr_axes = _ld(1, b"axes") + _vi(20, 7) + _vi(8, 2) + _vi(8, 3)
    attr_keep = _ld(1, b"keepdims") + _vi(20, 2) + _vi(3, 0)
    nodes = [
        _node("ReduceMean", ["image"], ["rgb_mean"], [attr_axes, attr_keep]),
        _node("MatMul", ["rgb_mean", "W"], ["logits"], []),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"mushroom_8cls_test")
        + _ld(5, tensor_w)
        + _ld(11, _value_info("image", ["n", 3, 224, 224]))
        + _ld(12, _value_info("logits", ["n", 8]))
    )
    opset = _ld(1, b"") + _vi(2, 13)
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, opset)
    path.write_bytes(model)
    return path


def _write_serving_dir(
    model_dir: Path,
    *,
    tau: float = 0.85,
    other_max: float = 0.03,
    energy_threshold: float | None = -8.0,
    tamper_sha: bool = False,
) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = _build_mushroom_test_onnx(model_dir / "model.onnx")
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    if tamper_sha:
        sha = "0" * 64
    serving = {
        "schema_version": "mushroom_classifier.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "input": {"name": "image", "shape": [1, 3, 224, 224], "pad_value": 128, "crop": "letterbox"},
        "calibration": {"temperature": 1.0},
        "safety": {
            "culinary_prob_min": tau,
            "other_mushroom_prob_max": other_max,
            "energy_threshold": energy_threshold,
            "c_psc": 100,
        },
        "abstention": {
            "tau": tau,
            "other_mushroom_max": other_max,
            "energy_threshold": energy_threshold,
            "ood_class": "other_mushroom",
            "not_mushroom_class": "not_mushroom",
        },
        "output": {"name": "logits", "calibration_applied_in_onnx": False},
        "classes": [{"id": s} for s in [*MUSHROOM_SLUGS, "other_mushroom", "not_mushroom"]],
    }
    (model_dir / "serving.json").write_text(json.dumps(serving), encoding="utf-8")
    return model_dir


def test_fungiclef_safety_gates_and_not_mushroom_suppression(tmp_path: Path) -> None:
    good_dir = _write_serving_dir(tmp_path / "good", tau=0.85, other_max=0.03, energy_threshold=-8.0)
    clf = load_mushroom_classifier(good_dir, verify_sha256=True)
    assert isinstance(clf, MushroomClassifier)

    crops = [
        Image.new("RGB", (224, 224), (255, 0, 0)),    # class 0 (nam-rom), passes all 3 gates
        Image.new("RGB", (224, 224), (0, 255, 0)),    # class 2 (nam-kim-cham), passes all 3 gates
        Image.new("RGB", (224, 224), (0, 0, 255)),    # class 6 (other_mushroom deadly lookalike) -> abstain
        Image.new("RGB", (224, 224), (255, 255, 0)),  # class 7 (not_mushroom) -> suppress
        Image.new("RGB", (224, 224), (10, 10, 10)),   # ambiguous / high energy -> abstain
    ]
    preds = clf.predict_crops(crops)
    assert len(preds) == 5
    assert preds[0].sub_species_slug == "nam-rom" and not preds[0].safety_abstained and not preds[0].suppress_not_mushroom
    assert preds[1].sub_species_slug == "nam-kim-cham" and not preds[1].safety_abstained
    assert preds[2] == MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
    assert preds[3] == MushroomPrediction(None, None, safety_abstained=False, suppress_not_mushroom=True)
    assert preds[4] == MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
    assert clf.predict_crops([]) == []

    # Test Energy OOD gate strictly: even if softmax prob >= 0.85, failing energy_threshold abstains
    strict_dir = _write_serving_dir(tmp_path / "strict_energy", tau=0.85, other_max=0.03, energy_threshold=-25.0)
    strict_clf = load_mushroom_classifier(strict_dir, verify_sha256=True)
    assert strict_clf.predict_crops([Image.new("RGB", (224, 224), (0, 255, 0))])[0].safety_abstained is True

    # Test P(other_mushroom) < 0.03 gate strictly using direct _postprocess_row
    probs_high_cul_but_risky_other = np.array([0.0, 0.0, 0.95, 0.0, 0.0, 0.0, 0.04, 0.01])
    res_risky = clf._postprocess_row(probs_high_cul_but_risky_other, energy=-15.0)
    assert res_risky == MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)

    bad_dir = _write_serving_dir(tmp_path / "tampered", tamper_sha=True)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_mushroom_classifier(bad_dir, verify_sha256=True)


def test_resolve_mushroom_model_dir_env_and_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good_dir = _write_serving_dir(tmp_path / "mush")
    monkeypatch.setenv("TASTORIA_MUSHROOM_CLASSIFIER_MODEL_DIR", str(good_dir))
    assert resolve_mushroom_model_dir() == good_dir

    monkeypatch.setenv("TASTORIA_MUSHROOM_CLASSIFIER_MODEL_DIR", str(tmp_path / "missing"))
    assert resolve_mushroom_model_dir() is None

    monkeypatch.setenv("TASTORIA_MUSHROOM_CLASSIFIER_MODEL_DIR", "disabled")
    assert resolve_mushroom_model_dir() is None


def test_schemas_backward_compatible_defaults() -> None:
    now = datetime.now(timezone.utc)
    det = DetectionOut(
        id=1,
        image_ordinal=1,
        vision_class_code="nam",
        x1=0.1,
        y1=0.1,
        x2=0.5,
        y2=0.5,
        confidence=0.9,
        p_tuoi=None,
        p_dung_som=None,
        p_dung_ngay=None,
        p_kiem_tra=None,
    )
    assert det.sub_species_slug is None and det.sub_species_conf is None and det.safety_abstained is False

    item = ScanItemOut(
        id=uuid.uuid4(),
        ingredient_id=uuid.uuid4(),
        ingredient_name_vi="nấm rơm",
        origin="model",
        model_count=None,
        final_count=None,
        qty_level=None,
        user_action="kept",
        original_ingredient_id=None,
        predicted_freshness=None,
        user_freshness=None,
        needs_check=False,
        detections=[det],
        created_at=now,
        updated_at=now,
    )
    assert item.sub_species_slug is None and item.sub_species_conf is None and item.safety_abstained is False


class _FakeResult:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = rows

    def first(self):  # noqa: ANN201
        return self._rows[0] if self._rows else None

    def one_or_none(self):  # noqa: ANN201
        return self._rows[0] if self._rows else None

    def all(self):  # noqa: ANN201
        return list(self._rows)

    def scalars(self):  # noqa: ANN201
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, scan: Scan, photos: list[ScanImage]) -> None:
        self.scan = scan
        self.photos = photos
        self.added_items: list[ScanItem] = []
        self.added_detections: list[Detection] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):  # noqa: ANN002
        return False

    def execute(self, stmt):  # noqa: ANN001
        s = str(stmt)
        if "UPDATE scans" in s:
            self.scan.status = "processing"
            return _FakeResult([SimpleNamespace(attempts=1, enqueued_at=self.scan.created_at)])
        return _FakeResult([])

    def scalars(self, stmt):  # noqa: ANN001
        s = str(stmt)
        if "FROM scan_images" in s:
            return _FakeResult(self.photos)
        if "FROM scans" in s:
            return _FakeResult([self.scan])
        return _FakeResult([])

    def add(self, obj) -> None:  # noqa: ANN001
        if isinstance(obj, ScanItem):
            self.added_items.append(obj)
        elif isinstance(obj, Detection):
            self.added_detections.append(obj)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


def _ing(name_vi: str, shelf_days: float) -> IngredientView:
    return IngredientView(
        id=uuid.uuid4(),
        name_vi=name_vi,
        food_group_code="nam",
        is_staple=False,
        countable=False,
        shelf_life_days=shelf_days,
        is_active=True,
        allergen_codes=frozenset(),
        units={},
    )


def test_worker_routes_safe_species_abstains_ood_and_suppresses_not_mushroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nam_vid = 22
    tomato_vid = 8
    ing_rom = _ing("nấm rơm", 2.0)
    ing_kim = _ing("nấm kim châm", 7.0)
    ing_tomato = IngredientView(
        id=uuid.uuid4(),
        name_vi="cà chua",
        food_group_code="rau_cu",
        is_staple=False,
        countable=True,
        shelf_life_days=7.0,
        is_active=True,
        allergen_codes=frozenset(),
        units={"qua": 100.0},
    )
    ing_map = {ing_rom.id: ing_rom, ing_kim.id: ing_kim, ing_tomato.id: ing_tomato}

    monkeypatch.setattr(scan_worker.catalog, "vision_class_ids_by_code", lambda s: {"nam": nam_vid, "ca_chua": tomato_vid})
    monkeypatch.setattr(
        scan_worker.catalog,
        "vision_classes",
        lambda s: {
            nam_vid: VisionClassView(nam_vid, "nam", "nấm", False, False, ing_rom.id),
            tomato_vid: VisionClassView(tomato_vid, "ca_chua", "cà chua", True, False, ing_tomato.id),
        },
    )
    monkeypatch.setattr(scan_worker.catalog, "active_ingredients", lambda s, food_group_code=None: {ing_rom.id: ing_rom, ing_kim.id: ing_kim})
    monkeypatch.setattr(
        scan_worker.catalog, "ingredients_by_ids", lambda s, ids: {iid: ing_map[iid] for iid in ids}
    )

    # 4 vertical bands (224x224 each): green (nam-kim-cham), blue (other_mushroom -> abstain), yellow (not_mushroom -> suppressed!), green (nam-kim-cham)
    img_path = tmp_path / "scan.jpg"
    im = Image.new("RGB", (896, 224), (0, 255, 0))
    im.paste(Image.new("RGB", (224, 224), (0, 0, 255)), (224, 0))
    im.paste(Image.new("RGB", (224, 224), (255, 255, 0)), (448, 0))
    im.save(img_path, "JPEG", quality=95)

    class _FakeDetector:
        def detect(self, _rgb):  # noqa: ANN001
            return [
                Box(0, 0.91, 0.00, 0.0, 0.25, 1.0),  # nam: green -> nam-kim-cham
                Box(0, 0.85, 0.25, 0.0, 0.50, 1.0),  # nam: blue -> other_mushroom -> abstain to nấm rơm
                Box(0, 0.45, 0.50, 0.0, 0.75, 1.0),  # nam: yellow -> not_mushroom -> SUPPRESSED!
                Box(0, 0.80, 0.75, 0.0, 1.00, 1.0),  # nam: green -> nam-kim-cham
                Box(1, 0.88, 0.05, 0.1, 0.20, 0.5),  # ca_chua -> preserved!
            ]

    class _FakeQueue:
        def publish(self, *_a, **_kw) -> None:
            pass

    now = datetime.now(timezone.utc)
    scan_id = uuid.uuid4()
    scan = Scan(id=scan_id, user_id=uuid.uuid4(), mode="fridge", status="queued", attempts=0, created_at=now)
    photo = ScanImage(id=uuid.uuid4(), scan_id=scan_id, ordinal=1, shelf_group=1, storage_key="scan.jpg", width=896, height=224)
    fake_session = _FakeSession(scan, [photo])
    det_ver = ModelVersionView(
        id=uuid.uuid4(),
        name="detector",
        version="v1",
        artifact_key="k",
        sha256="0" * 64,
        preprocess_version="none",
        metrics={},
        status="validated",
        created_at=now,
        class_map={0: nam_vid, 1: tomato_vid},
        is_active=True,
    )

    mdir = _write_serving_dir(tmp_path / "mush_model")
    clf = load_mushroom_classifier(mdir, verify_sha256=True)

    ctx = WorkerContext(
        sessionmaker=lambda: fake_session,  # type: ignore[arg-type]
        storage_dir=tmp_path,
        queue=_FakeQueue(),  # type: ignore[arg-type]
        detector=_FakeDetector(),  # type: ignore[arg-type]
        detector_version=det_ver,
        mushroom_classifier=clf,
    )
    assert scan_worker.run_job(ctx, scan_id) == "done"
    assert len(fake_session.added_items) == 3
    by_ing = {it.ingredient_id: it for it in fake_session.added_items}
    assert set(by_ing) == {ing_kim.id, ing_rom.id, ing_tomato.id}
    # Box 2 (not_mushroom) was suppressed -> only 4 detections emitted instead of 5!
    assert len(fake_session.added_detections) == 4
    assert fake_session.added_detections[0].scan_item_id == by_ing[ing_kim.id].id
    assert fake_session.added_detections[0].sub_species_slug == "nam-kim-cham"
    assert fake_session.added_detections[0].sub_species_conf is not None
    assert fake_session.added_detections[0].safety_abstained is False

    assert fake_session.added_detections[1].scan_item_id == by_ing[ing_rom.id].id
    assert fake_session.added_detections[1].sub_species_slug is None
    assert fake_session.added_detections[1].sub_species_conf is None
    assert fake_session.added_detections[1].safety_abstained is True

    assert fake_session.added_detections[2].scan_item_id == by_ing[ing_kim.id].id
    assert fake_session.added_detections[2].sub_species_slug == "nam-kim-cham"
    assert fake_session.added_detections[2].sub_species_conf is not None
    assert fake_session.added_detections[2].safety_abstained is False

    assert fake_session.added_detections[3].scan_item_id == by_ing[ing_tomato.id].id
    assert fake_session.added_detections[3].sub_species_slug is None
    assert fake_session.added_detections[3].sub_species_conf is None
    assert fake_session.added_detections[3].safety_abstained is False

    # Backward compatibility when mushroom_classifier=None and model dir is disabled -> all nam fall back to nấm rơm
    monkeypatch.setenv("TASTORIA_MUSHROOM_CLASSIFIER_MODEL_DIR", "disabled")
    scan2 = Scan(id=scan_id, user_id=scan.user_id, mode="fridge", status="queued", attempts=0, created_at=now)
    fake_session2 = _FakeSession(scan2, [photo])
    ctx_none = WorkerContext(
        sessionmaker=lambda: fake_session2,  # type: ignore[arg-type]
        storage_dir=tmp_path,
        queue=_FakeQueue(),  # type: ignore[arg-type]
        detector=_FakeDetector(),  # type: ignore[arg-type]
        detector_version=det_ver,
        mushroom_classifier=None,
    )
    assert scan_worker.run_job(ctx_none, scan_id) == "done"
    assert len(fake_session2.added_items) == 2
    assert len(fake_session2.added_detections) == 5


def test_service_items_out_populates_sub_species_and_safety_abstained(monkeypatch: pytest.MonkeyPatch) -> None:
    nam_vid = 22
    ing_rom = _ing("nấm rơm", 2.0)
    ing_kim = _ing("nấm kim châm", 7.0)
    ing_map = {ing_rom.id: ing_rom, ing_kim.id: ing_kim}

    now = datetime.now(timezone.utc)
    scan_id = uuid.uuid4()
    scan = Scan(id=scan_id, user_id=uuid.uuid4(), mode="fridge", status="done", attempts=1, created_at=now)
    it_kim = ScanItem(
        id=uuid.uuid4(),
        scan_id=scan_id,
        ingredient_id=ing_kim.id,
        origin="model",
        model_count=None,
        final_count=None,
        qty_level=None,
        user_action="kept",
        original_ingredient_id=None,
        created_at=now,
        updated_at=now,
    )
    it_rom = ScanItem(
        id=uuid.uuid4(),
        scan_id=scan_id,
        ingredient_id=ing_rom.id,
        origin="model",
        model_count=None,
        final_count=None,
        qty_level=None,
        user_action="kept",
        original_ingredient_id=None,
        created_at=now,
        updated_at=now,
    )
    d1 = Detection(
        id=1,
        scan_image_id=uuid.uuid4(),
        scan_item_id=it_kim.id,
        vision_class_id=nam_vid,
        x1=0.1,
        y1=0.1,
        x2=0.4,
        y2=0.8,
        confidence=0.92,
        p_tuoi=None,
        p_dung_som=None,
        p_dung_ngay=None,
        p_kiem_tra=None,
    )
    d2 = Detection(
        id=2,
        scan_image_id=uuid.uuid4(),
        scan_item_id=it_rom.id,
        vision_class_id=nam_vid,
        x1=0.5,
        y1=0.1,
        x2=0.9,
        y2=0.8,
        confidence=0.85,
        p_tuoi=None,
        p_dung_som=None,
        p_dung_ngay=None,
        p_kiem_tra=None,
    )

    class _ReadSession:
        def scalars(self, _stmt):  # noqa: ANN001
            return [it_kim, it_rom]

        def execute(self, _stmt):  # noqa: ANN001
            return _FakeResult([(d1, 1), (d2, 1)])

    monkeypatch.setattr(
        scan_service.catalog,
        "vision_classes",
        lambda s: {nam_vid: VisionClassView(nam_vid, "nam", "nấm", False, False, ing_rom.id)},
    )
    monkeypatch.setattr(scan_service.catalog, "ingredients_by_ids", lambda s, ids: {i: ing_map[i] for i in ids})

    items_out = scan_service._items_out(_ReadSession(), scan)  # type: ignore[arg-type]
    assert len(items_out) == 2
    assert items_out[0].ingredient_name_vi == "nấm kim châm"
    assert items_out[0].sub_species_slug == "nam-kim-cham"
    assert items_out[0].safety_abstained is False
    assert items_out[0].detections[0].sub_species_slug == "nam-kim-cham"
    assert items_out[0].detections[0].safety_abstained is False

    assert items_out[1].ingredient_name_vi == scan_service.MUSHROOM_ABSTAINED_LABEL_VI
    assert items_out[1].sub_species_slug is None
    assert items_out[1].safety_abstained is True
    assert items_out[1].detections[0].sub_species_slug is None
    assert items_out[1].detections[0].safety_abstained is True

    # Persisted Detection with sub_species_slug="nam-rom" & sub_species_conf=0.94 reads back as non-abstained
    d_rom_ok = Detection(
        id=3,
        scan_image_id=uuid.uuid4(),
        scan_item_id=it_rom.id,
        vision_class_id=nam_vid,
        x1=0.5,
        y1=0.1,
        x2=0.9,
        y2=0.8,
        confidence=0.89,
        p_tuoi=None,
        p_dung_som=None,
        p_dung_ngay=None,
        p_kiem_tra=None,
        sub_species_slug="nam-rom",
        sub_species_conf=0.94,
        safety_abstained=False,
    )
    d_kim_ok = Detection(
        id=4,
        scan_image_id=uuid.uuid4(),
        scan_item_id=it_kim.id,
        vision_class_id=nam_vid,
        x1=0.1,
        y1=0.1,
        x2=0.4,
        y2=0.8,
        confidence=0.92,
        p_tuoi=None,
        p_dung_som=None,
        p_dung_ngay=None,
        p_kiem_tra=None,
        sub_species_slug="nam-kim-cham",
        sub_species_conf=0.97,
        safety_abstained=False,
    )

    class _PersistedReadSession:
        def scalars(self, _stmt):  # noqa: ANN001
            return [it_kim, it_rom]

        def execute(self, _stmt):  # noqa: ANN001
            return _FakeResult([(d_kim_ok, 1), (d_rom_ok, 1)])

    persisted_out = scan_service._items_out(_PersistedReadSession(), scan)  # type: ignore[arg-type]
    assert persisted_out[0].sub_species_slug == "nam-kim-cham"
    assert persisted_out[0].sub_species_conf == 0.97
    assert persisted_out[0].safety_abstained is False
    assert persisted_out[0].detections[0].sub_species_conf == 0.97

    assert persisted_out[1].ingredient_name_vi == "nấm rơm"
    assert persisted_out[1].sub_species_slug == "nam-rom"
    assert persisted_out[1].sub_species_conf == 0.94
    assert persisted_out[1].safety_abstained is False
    assert persisted_out[1].detections[0].sub_species_slug == "nam-rom"
    assert persisted_out[1].detections[0].sub_species_conf == 0.94
    assert persisted_out[1].detections[0].safety_abstained is False


def _fake_classifier_with_outputs(outputs: np.ndarray, *, cal_in_onnx: bool = False) -> MushroomClassifier:
    out_name = "probs" if cal_in_onnx else "logits"

    class _FakeSess:
        def get_inputs(self):  # noqa: ANN201
            return [SimpleNamespace(name="image", shape=[1, 3, 224, 224])]

        def get_outputs(self):  # noqa: ANN201
            return [SimpleNamespace(name=out_name)]

        def run(self, _output_names, feed):  # noqa: ANN001, ANN201
            n = int(feed["image"].shape[0])
            return [outputs[:n]]

    serving = {
        "input": {"pad_value": 128},
        "calibration": {"temperature": 1.0},
        "safety": {"culinary_prob_min": 0.85, "other_mushroom_prob_max": 0.03, "energy_threshold": -3.127},
        "abstention": {
            "tau": 0.85,
            "other_mushroom_max": 0.03,
            "energy_threshold": -3.127,
            "ood_class": "other_mushroom",
            "not_mushroom_class": "not_mushroom",
        },
        "output": {"name": out_name, "calibration_applied_in_onnx": cal_in_onnx},
        "classes": [{"id": s} for s in [*MUSHROOM_SLUGS, "other_mushroom", "not_mushroom"]],
    }
    return MushroomClassifier(_FakeSess(), serving=serving)


def test_non_finite_mushroom_logits_fail_closed() -> None:
    nan = float("nan")
    inf = float("inf")
    ninf = float("-inf")
    logits = np.array(
        [
            [nan, inf, ninf, 0.0, 0.0, 0.0, 0.0, 0.0],
            [12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # valid nam-rom in same batch
            [0.0, nan, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, inf, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, ninf, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    clf = _fake_classifier_with_outputs(logits, cal_in_onnx=False)
    crops = [Image.new("RGB", (64, 64), (128, 128, 128)) for _ in range(5)]
    preds = clf.predict_crops(crops)
    abstained = MushroomPrediction(sub_species_slug=None, sub_species_conf=None, safety_abstained=True, suppress_not_mushroom=False)
    assert preds[0] == abstained
    assert preds[1].sub_species_slug == "nam-rom" and preds[1].safety_abstained is False
    assert preds[2] == abstained
    assert preds[3] == abstained
    assert preds[4] == abstained

    # Non-finite probs in cal_in_onnx=True mode or direct _postprocess_row also fail closed
    probs_clf = _fake_classifier_with_outputs(
        np.array([[nan, inf, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]], dtype=np.float32), cal_in_onnx=True
    )
    assert probs_clf.predict_crops([Image.new("RGB", (64, 64), (0, 0, 0))]) == [abstained]
    assert clf._postprocess_row(np.array([0.0, inf, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]), energy=-5.0) == abstained
    assert clf._postprocess_row(np.array([0.99, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01]), energy=nan) == abstained


def test_not_mushroom_suppression_guard_blocks_ambiguous_deadly_lookalike_ties() -> None:
    # Ambiguous tie: P(nam-rom)=0.30, P(other_mushroom)=0.34, P(not_mushroom)=0.36 at E=-2.0
    # Construct logits = log(probs) + 2.0 - log(sum) -> sum(exp(logits)) = exp(2.0) -> E = -2.0
    probs_ambig = np.array([0.30, 1e-9, 1e-9, 1e-9, 1e-9, 1e-9, 0.34, 0.36], dtype=np.float64)
    probs_ambig = probs_ambig / probs_ambig.sum()
    logits_ambig = (np.log(probs_ambig) + 2.0).astype(np.float32)

    # Clear not_mushroom: P(not_mushroom)=0.85, P(other_mushroom)=0.04 < 0.05
    probs_clear = np.array([0.11, 1e-9, 1e-9, 1e-9, 1e-9, 1e-9, 0.04, 0.85], dtype=np.float64)
    probs_clear = probs_clear / probs_clear.sum()
    logits_clear = (np.log(probs_clear) + 2.0).astype(np.float32)

    clf = _fake_classifier_with_outputs(np.stack([logits_ambig, logits_clear]), cal_in_onnx=False)
    crops = [Image.new("RGB", (64, 64), (100, 100, 100)) for _ in range(2)]
    preds = clf.predict_crops(crops)

    assert preds[0] == MushroomPrediction(
        sub_species_slug=None, sub_species_conf=None, safety_abstained=True, suppress_not_mushroom=False
    )
    assert preds[1] == MushroomPrediction(
        sub_species_slug=None, sub_species_conf=None, safety_abstained=False, suppress_not_mushroom=True
    )

    # Boundary checks on _postprocess_row
    abstained = MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
    suppressed = MushroomPrediction(None, None, safety_abstained=False, suppress_not_mushroom=True)
    # p_not < 0.50 -> abstain even if p_other == 0
    assert clf._postprocess_row(np.array([0.48, 0.0, 0.0, 0.0, 0.0, 0.0, 0.03, 0.49]), energy=-2.0) == abstained
    # p_other >= 0.15 -> abstain even if p_not == 0.50
    assert clf._postprocess_row(np.array([0.35, 0.0, 0.0, 0.0, 0.0, 0.0, 0.15, 0.50]), energy=-2.0) == abstained
    # p_not == 0.50, p_other == 0.14 (< 0.15), margin == 0.36 (>= 0.15) -> suppress
    assert clf._postprocess_row(np.array([0.36, 0.0, 0.0, 0.0, 0.0, 0.0, 0.14, 0.50]), energy=-2.0) == suppressed


def test_out_of_range_or_negative_mushroom_probs_fail_closed() -> None:
    abstained = MushroomPrediction(
        sub_species_slug=None, sub_species_conf=None, safety_abstained=True, suppress_not_mushroom=False
    )
    bad_rows = [
        np.array([-0.5, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
        np.array([1.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
        np.array([-0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.5], dtype=np.float32),
        np.array([-0.1, 0.9, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
    ]
    probs_clf = _fake_classifier_with_outputs(np.stack(bad_rows), cal_in_onnx=True)
    crops = [Image.new("RGB", (64, 64), (100, 100, 100)) for _ in bad_rows]
    preds = probs_clf.predict_crops(crops)
    assert preds == [abstained] * len(bad_rows)

    for row in bad_rows:
        assert probs_clf._postprocess_row(row, energy=-5.0) == abstained

    # Valid probability distribution in [0, 1] still classifies normally
    valid_row = np.array([0.95, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    valid_pred = probs_clf._postprocess_row(valid_row, energy=-5.0)
    assert valid_pred == MushroomPrediction(
        sub_species_slug="nam-rom", sub_species_conf=0.95, safety_abstained=False, suppress_not_mushroom=False
    )



def test_mushroom_micro_batch_16_count_clamp_and_confirm_safety_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import io
    from types import SimpleNamespace as _NS

    from tastoria.core.auth import AuthUser
    from tastoria.core.errors import ApiError, ProblemCode
    from tastoria.modules.catalog.schemas import IngredientView as _IngView

    # 1. MushroomClassifier chunks crops into micro-batches of 16
    batch_sizes: list[int] = []

    class _BatchMushSess:
        def get_inputs(self):  # noqa: ANN201
            return [_NS(name="image", shape=[1, 3, 224, 224])]

        def get_outputs(self):  # noqa: ANN201
            return [_NS(name="logits")]

        def run(self, _out, feed):  # noqa: ANN001, ANN201
            x = next(iter(feed.values()))
            batch_sizes.append(int(x.shape[0]))
            row = np.array([12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
            return [np.tile(row, (int(x.shape[0]), 1))]

    bclf = MushroomClassifier(
        _BatchMushSess(),
        serving={"temperature": 1.0, "confidence_threshold": 0.85, "energy_threshold": -1.5, "output": {"calibration_applied_in_onnx": False}},
    )
    crops = [Image.new("RGB", (64, 64), (100, 50, 50)) for _ in range(20)]
    preds = bclf.predict_crops(crops)
    assert len(preds) == 20 and batch_sizes == [16, 4]
    assert all(p.sub_species_slug == "nam-rom" and not p.safety_abstained for p in preds)

    # 2. run_job catches mclf.predict_crops failures (falls back to safety_abstained=True),
    # caps detections at <= 64, and clamps final_count to <= 99 (P0-8 + P0-9)
    class _ExplodingMushClf:
        def predict_crops(self, _crops):  # noqa: ANN001, ANN201
            raise RuntimeError("ONNX runtime OOM")

    egg_id = uuid.uuid4()
    nam_id = uuid.uuid4()
    scan_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    img_path = tmp_path / "photo.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), (220, 120, 80)).save(buf, format="JPEG")
    img_path.write_bytes(buf.getvalue())

    boxes = [Box(1, 0.9, 0.05, 0.05, 0.2, 0.2)] + [
        Box(0, 0.9 - i * 1e-4, 0.01, 0.01, 0.1, 0.1) for i in range(120)
    ]

    class _Det:
        def detect(self, _im):  # noqa: ANN001, ANN201
            return boxes

    scan_row = Scan(id=scan_id, user_id=user_id, mode="fridge", status="queued", attempts=0, created_at=now)
    img_row = ScanImage(id=uuid.uuid4(), scan_id=scan_id, ordinal=1, shelf_group=1, storage_key="photo.jpg", width=128, height=128)
    fake_session = _FakeSession(scan_row, [img_row])

    monkeypatch.setattr(scan_worker.catalog, "vision_class_ids_by_code", lambda _s: {"trung": 10, "nam": 20})
    monkeypatch.setattr(
        scan_worker.catalog,
        "vision_classes",
        lambda _s: {
            10: VisionClassView(10, "trung", "trứng gà", True, True, egg_id),
            20: VisionClassView(20, "nam", "nấm", False, False, nam_id),
        },
    )
    monkeypatch.setattr(
        scan_worker.catalog,
        "ingredients_by_ids",
        lambda _s, _ids: {
            egg_id: _IngView(egg_id, "trứng gà", "trung", False, True, 14.0, True, frozenset(), {"quả": 55.0}),
            nam_id: _IngView(nam_id, "nấm rơm", "nam", False, False, 3.0, True, frozenset(), {}),
        },
    )
    monkeypatch.setattr(scan_worker.catalog, "active_ingredients", lambda _s, food_group_code="nam": {})
    det_ver = ModelVersionView(
        id=uuid.uuid4(),
        name="detector",
        version="d1",
        artifact_key="models/detector/d1/d.onnx",
        sha256="0" * 64,
        preprocess_version="none",
        metrics={},
        status="active",
        created_at=now,
        class_map={0: 10, 1: 20},
        is_active=True,
    )
    ctx = WorkerContext(lambda: fake_session, tmp_path, _NS(publish=lambda *a: None), _Det(), det_ver, mushroom_classifier=_ExplodingMushClf())  # type: ignore[arg-type]
    assert scan_worker.run_job(ctx, scan_id) == "done"
    added_dets = fake_session.added_detections
    added_items = fake_session.added_items
    assert len(added_dets) == 64
    egg_item = next(i for i in added_items if i.ingredient_id == egg_id)
    assert egg_item.final_count == 63
    nam_det = next(d for d in added_dets if d.vision_class_id == 20)
    assert nam_det.safety_abstained is True

    # Explicit >99 count clamping check via _write
    many_egg_boxes = [(_NS(ordinal=1, shelf_group=1, id=img_row.id), Box(0, 0.9, 0.1, 0.1, 0.2, 0.2), None, None) for _ in range(110)]
    fake_session.added_items.clear()
    fake_session.added_detections.clear()
    scan_row.status = "processing"
    assert scan_worker._write(ctx, scan_id, many_egg_boxes) is True  # type: ignore[arg-type]
    egg_item_110 = next(o for o in fake_session.added_items if o.ingredient_id == egg_id)
    assert egg_item_110.model_count == 110 and egg_item_110.final_count == 99

    # 3. confirm() blocks unresolved safety_abstained mushroom chip with 409 freshness_check_required
    m_item = ScanItem(
        id=uuid.uuid4(), scan_id=scan_id, ingredient_id=nam_id, origin="model", model_count=None, final_count=None,
        qty_level="vua", user_action="kept", original_ingredient_id=None, user_freshness=None, created_at=now, updated_at=now,
    )
    ab_det = Detection(id=1, scan_image_id=img_row.id, scan_item_id=m_item.id, vision_class_id=20, x1=0.1, y1=0.1, x2=0.2, y2=0.2, confidence=0.9, safety_abstained=True)
    scan_done = Scan(id=scan_id, user_id=user_id, mode="fridge", status="done", attempts=1, created_at=now)
    call_n = {"n": 0}

    class _ConfirmSess:
        def scalars(self, _stmt):  # noqa: ANN001, ANN201
            call_n["n"] += 1
            if call_n["n"] == 1:
                return _NS(one_or_none=lambda: scan_done)
            if call_n["n"] == 2:
                return [m_item]
            if call_n["n"] == 3:
                return []
            return [ab_det]

    monkeypatch.setattr(scan_service.catalog, "vision_classes", lambda _s: {20: VisionClassView(20, "nam", "nấm", False, False, nam_id)})
    monkeypatch.setattr(scan_service.catalog, "ingredients_by_ids", lambda _s, _ids: {nam_id: _ing("nấm rơm", 3.0)})
    with pytest.raises(ApiError) as exc:
        scan_service.confirm(_ConfirmSess(), _NS(settings=_NS()), AuthUser(user_id, "user", "u@t.local"), scan_id, None)  # type: ignore[arg-type]
    assert exc.value.status == 409 and exc.value.code == ProblemCode.freshness_check_required
    assert exc.value.extra["item_ids"] == [str(m_item.id)]
