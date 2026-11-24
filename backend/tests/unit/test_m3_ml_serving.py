"""Unit tests for M3 ML serving components (NumpyRanker, Composer Params, FreshnessClassifier, Config)."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
from PIL import Image

from tastoria.core.config import Settings
from tastoria.modules.catalog.schemas import IngredientView, RecipeLine, RecipeView, StepView
from tastoria.modules.events.schemas import RecipeSignal
from tastoria.modules.meal import composer as cmp
from tastoria.modules.meal.ranker import NumpyRanker, RankContext, load_ranker
from tastoria.modules.scan.detector import Box
from tastoria.modules.scan.freshness import FreshnessClassifier, crop_box_pixels, letterbox_crop

REPO_ROOT = Path(__file__).resolve().parents[3]
RANKER_NPZ = REPO_ROOT / "deploy/models/ranker/model.npz"
RANKER_SERVING = REPO_ROOT / "deploy/models/ranker/serving.json"
COMPOSER_SERVING = REPO_ROOT / "deploy/models/composer/serving.json"


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


def build_freshness_onnx(path: Path, *, two_outputs: bool) -> Path:
    """Build a valid opset-13 ONNX model taking image ['n',3,224,224] -> logits ['n',3] (or probs, logits)."""
    nodes = [
        _node(
            "ReduceMean",
            ["image"],
            ["logits"],
            [_attr_ints("axes", [2, 3]), _attr_int("keepdims", 0)],
        )
    ]
    outputs = []
    if two_outputs:
        nodes.append(_node("Softmax", ["logits"], ["probs"], [_attr_int("axis", 1)]))
        outputs.append(_value_info("probs", ["n", 3]))
    outputs.append(_value_info("logits", ["n", 3]))
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"freshness_test")
        + _ld(11, _value_info("image", ["n", 3, 224, 224]))
        + b"".join(_ld(12, o) for o in outputs)
    )
    opset = _ld(1, b"") + _vi(2, 13)
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, opset)
    path.write_bytes(model)
    return path


# ---------------------------------------------------------------- config & composer


def test_config_production_requires_training_export_hmac_key() -> None:
    s = Settings(
        env="production",
        jwt_keys={"p1": "prod-jwt-secret-key-0123456789abcdef"},
        jwt_active_kid="p1",
        survey_jwt_keys={"s1": "prod-survey-jwt-secret-0123456789abc"},
        survey_jwt_active_kid="s1",
        health_enc_keys={"p1": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="},
        health_enc_active_key_id="p1",
        dsr_hmac_key="prod-dsr-hmac-secret-0123456789abcdef",
        training_export_hmac_key=None,
        database_url="postgresql+psycopg://app:StrongPass123!@db.internal:5432/tastoria",
        valkey_url="redis://:StrongValkeyPass123!@valkey.internal:6379/0",
        smtp_starttls=True,
    )
    with pytest.raises(RuntimeError, match="TASTORIA_TRAINING_EXPORT_HMAC_KEY"):
        s.check_production()
    s_ok = Settings(
        env="production",
        jwt_keys={"p1": "prod-jwt-secret-key-0123456789abcdef"},
        jwt_active_kid="p1",
        survey_jwt_keys={"s1": "prod-survey-jwt-secret-0123456789abc"},
        survey_jwt_active_kid="s1",
        health_enc_keys={"p1": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="},
        health_enc_active_key_id="p1",
        dsr_hmac_key="prod-dsr-hmac-secret-0123456789abcdef",
        training_export_hmac_key="prod-export-hmac-secret-0123456789abcd",
        database_url="postgresql+psycopg://app:StrongPass123!@db.internal:5432/tastoria",
        valkey_url="redis://:StrongValkeyPass123!@valkey.internal:6379/0",
        smtp_starttls=True,
    )
    s_ok.check_production()


def test_composer_defaults_preserved_and_calibrated_params_loaded(tmp_path: Path) -> None:
    prov = cmp.Params()
    assert (prov.version, prov.alpha, prov.beta, prov.gamma) == ("tray-p0-provisional", 1.0, 1.0, 0.5)
    assert (cmp.CALIBRATED_DEFAULTS.version, cmp.CALIBRATED_DEFAULTS.alpha) == ("tray-p1-knee-20261118", 16.0)

    loaded = cmp.load_params()
    assert loaded.version == "tray-p1-knee-20261118"
    assert (loaded.alpha, loaded.beta, loaded.gamma) == (16.0, 2.0, 1.0)

    if COMPOSER_SERVING.is_file():
        assert cmp.load_params(COMPOSER_SERVING) == cmp.CALIBRATED_DEFAULTS

    body = {"params": asdict(cmp.CALIBRATED_DEFAULTS)}
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    good = tmp_path / "good_serving.json"
    good.write_text(json.dumps({**body, "artifact_sha256": hashlib.sha256(canon).hexdigest()}), encoding="utf-8")
    assert cmp.load_params(good) == cmp.CALIBRATED_DEFAULTS

    bad = tmp_path / "serving.json"
    bad_data = json.loads(good.read_text(encoding="utf-8"))
    bad_data["params"]["alpha"] = 999.0
    bad.write_text(json.dumps(bad_data), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        cmp.load_params(bad)

    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        cmp.load_params(missing)


# ---------------------------------------------------------------- ranker


def _dummy_recipe(name_vi: str, slot: str, ing_names: list[str], method: str = "xao") -> RecipeView:
    lines = tuple(
        RecipeLine(
            ingredient=IngredientView(
                id=uuid.uuid4(),
                name_vi=n,
                food_group_code="thit",
                is_staple=False,
                countable=False,
                shelf_life_days=3.0,
                is_active=True,
                allergen_codes=frozenset(),
                units={},
            ),
            grams=100.0,
            role="main",
            is_optional=False,
        )
        for n in ing_names
    )
    return RecipeView(
        id=uuid.uuid4(),
        name_vi=name_vi,
        slot=slot,
        servings=2,
        method_code=method,
        status="published",
        lines=lines,
        steps=(StepView(1, "Nấu", "active", 10, True),),
        tag_codes=frozenset(),
        kcal_per_serving=300.0,
    )


def test_numpy_ranker_loads_exported_artifact_and_scores_known_and_unseen() -> None:
    if not RANKER_NPZ.exists() or not RANKER_SERVING.exists():
        pytest.skip("deploy/models/ranker artifacts not present in checkout")
    serving = json.loads(RANKER_SERVING.read_text(encoding="utf-8"))
    vid = uuid.uuid4()
    ranker: NumpyRanker = load_ranker(RANKER_NPZ, version_id=vid, serving=serving)
    assert ranker.version_id == vid

    known_name = str(np.load(RANKER_NPZ, allow_pickle=False)["recipe_names"][0])
    known_slot = str(np.load(RANKER_NPZ, allow_pickle=False)["recipe_slots"][0])
    r_known = _dummy_recipe(known_name, known_slot, ["thịt ba chỉ"])
    r_unseen = _dummy_recipe("Món mới hoàn toàn 123", "man", ["thịt ba chỉ", "tỏi"])

    ctx = RankContext(
        user_id=uuid.uuid4(),
        favorites=[r_known],
        popularity={},
        personal={r_unseen.id: RecipeSignal(positive=3, negative=0)},
    )
    scores = ranker.score(ctx, [r_known, r_unseen])
    assert set(scores) == {r_known.id, r_unseen.id}
    assert all(np.isfinite(v) for v in scores.values())

    ctx_cold = RankContext(user_id=uuid.uuid4(), favorites=[], popularity={}, personal=None)
    cold_scores = ranker.score(ctx_cold, [r_known, r_unseen])
    assert all(np.isfinite(v) for v in cold_scores.values())


# ---------------------------------------------------------------- freshness ONNX


def test_freshness_crop_geometry_and_letterbox() -> None:
    px = crop_box_pixels(Box(0, 0.9, 0.999, 0.999, 1.0, 1.0), 100, 100)
    assert px == (99, 99, 100, 100)
    im = Image.new("RGB", (40, 20), (200, 100, 50))
    arr = letterbox_crop(im, size=224, pad_value=128)
    assert arr.shape == (3, 224, 224) and arr.dtype == np.float32
    assert float(arr[0, 0, 0]) == 128.0  # padded border
    assert float(arr[0, 112, 112]) == pytest.approx(200.0, abs=1.0)


@pytest.mark.parametrize("two_outputs", [True, False])
def test_freshness_classifier_onnx_two_and_one_output_with_abstention(tmp_path: Path, two_outputs: bool) -> None:
    onnx_path = build_freshness_onnx(tmp_path / f"fresh_{two_outputs}.onnx", two_outputs=two_outputs)
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    serving = {
        "input": {"pad_value": 128},
        "abstention": {"tau": 0.60},
        "calibration": {"temperature": 1.0 if two_outputs else 10.0},
        "output": {"calibration_applied_in_onnx": two_outputs},
    }
    clf = FreshnessClassifier(sess, serving=serving)
    crops = [
        Image.new("RGB", (224, 224), (255, 0, 0)),  # confident class 0 (tuoi)
        Image.new("RGB", (224, 224), (0, 255, 0)),  # confident class 1 (dung_som)
        Image.new("RGB", (224, 224), (128, 128, 128)),  # uniform -> max=1/3 < 0.60 -> abstain (kiem_tra)
    ]
    probs = clf.predict_crops(crops)
    assert len(probs) == 3
    assert probs[0][0] > 0.99 and probs[0][3] == 0.0
    assert probs[1][1] > 0.99 and probs[1][3] == 0.0
    assert probs[2] == (0.0, 0.0, 0.0, 1.0)
    for p in probs:
        assert abs(sum(p) - 1.0) <= 1e-4


def test_freshness_micro_batch_16_and_non_finite_abstain() -> None:
    batch_sizes: list[int] = []

    class _CountingFreshSess:
        def get_inputs(self):  # noqa: ANN201
            return [type("In", (), {"name": "image", "shape": [1, 3, 224, 224]})()]

        def get_outputs(self):  # noqa: ANN201
            return [type("Out", (), {"name": "logits"})()]

        def run(self, _out, feed):  # noqa: ANN001, ANN201
            x = next(iter(feed.values()))
            batch_sizes.append(int(x.shape[0]))
            logits = np.tile(np.array([[8.0, 0.0, 0.0]], dtype=np.float32), (int(x.shape[0]), 1))
            if len(batch_sizes) == 2:
                logits[0, 0] = float("nan")
                logits[1, 1] = float("inf")
            return [logits]

    clf = FreshnessClassifier(
        _CountingFreshSess(),
        serving={"abstention": {"tau": 0.60}, "calibration": {"temperature": 1.0}, "output": {"calibration_applied_in_onnx": False}},
    )
    crops = [Image.new("RGB", (64, 64), (200, 100, 50)) for _ in range(20)]
    probs = clf.predict_crops(crops)
    assert len(probs) == 20
    assert batch_sizes == [16, 4]
    assert probs[16] == (0.0, 0.0, 0.0, 1.0)
    assert probs[17] == (0.0, 0.0, 0.0, 1.0)
    assert probs[0][0] > 0.99
