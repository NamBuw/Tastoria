"""Unit tests verifying produce-only freshness scope (vision_classes.has_freshness_model)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from tastoria.modules.catalog.schemas import IngredientView, VisionClassView
from tastoria.modules.mlops.schemas import ModelVersionView
from tastoria.modules.scan import worker as scan_worker
from tastoria.modules.scan.detector import Box
from tastoria.modules.scan.worker import WorkerContext
from unit.test_scan_mushroom import _FakeSession


def _make_ing(name: str, *, countable: bool = False) -> IngredientView:
    return IngredientView(
        id=uuid.uuid4(),
        name_vi=name,
        food_group_code="rau_cu" if countable else "thit",
        is_staple=False,
        countable=countable,
        shelf_life_days=5.0,
        is_active=True,
        allergen_codes=frozenset(),
        units={"qua": 100.0} if countable else {},
    )


def test_worker_runs_freshness_only_on_has_freshness_model_classes(tmp_path: Path, monkeypatch) -> None:
    tomato_vid = 8
    pork_vid = 1
    ing_tomato = _make_ing("cà chua", countable=True)
    ing_pork = _make_ing("thịt ba chỉ", countable=False)
    ing_map = {ing_tomato.id: ing_tomato, ing_pork.id: ing_pork}

    monkeypatch.setattr(
        scan_worker.catalog,
        "vision_classes",
        lambda _s: {
            tomato_vid: VisionClassView(tomato_vid, "ca_chua", "cà chua", True, True, ing_tomato.id),
            pork_vid: VisionClassView(pork_vid, "thit_lon", "thịt lợn", False, False, ing_pork.id),
        },
    )
    monkeypatch.setattr(scan_worker.catalog, "ingredients_by_ids", lambda _s, ids: {iid: ing_map[iid] for iid in ids})

    img_path = tmp_path / "fridge.jpg"
    im = Image.new("RGB", (600, 300), (200, 40, 40))
    im.paste(Image.new("RGB", (300, 300), (190, 130, 120)), (300, 0))
    im.save(img_path, "JPEG", quality=92)

    class _MixedDetector:
        def detect(self, _rgb):  # noqa: ANN001
            return [
                Box(0, 0.90, 0.02, 0.1, 0.45, 0.9),  # ca_chua (has_freshness_model=True)
                Box(1, 0.88, 0.52, 0.1, 0.95, 0.9),  # thit_lon (has_freshness_model=False)
            ]

    seen_crop_sizes: list[tuple[int, int]] = []

    class _RecordingFreshness:
        def predict_crops(self, crops):  # noqa: ANN001
            seen_crop_sizes.extend(c.size for c in crops)
            return [(0.91, 0.06, 0.03, 0.0) for _ in crops]

    class _Queue:
        def publish(self, *_a, **_kw) -> None:
            pass

    now = datetime.now(timezone.utc)
    scan_id = uuid.uuid4()
    scan = scan_worker.Scan(id=scan_id, user_id=uuid.uuid4(), mode="fridge", status="queued", attempts=0, created_at=now)
    photo = scan_worker.ScanImage(
        id=uuid.uuid4(), scan_id=scan_id, ordinal=1, shelf_group=1, storage_key="fridge.jpg", width=600, height=300
    )
    sess = _FakeSession(scan, [photo])
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
        class_map={0: tomato_vid, 1: pork_vid},
        is_active=True,
    )
    fresh_ver = ModelVersionView(
        id=uuid.uuid4(),
        name="freshness",
        version="v2",
        artifact_key="k2",
        sha256="1" * 64,
        preprocess_version="letterbox_224",
        metrics={},
        status="validated",
        created_at=now,
        class_map={},
        is_active=True,
    )
    ctx = WorkerContext(
        sessionmaker=lambda: sess,  # type: ignore[arg-type]
        storage_dir=tmp_path,
        queue=_Queue(),  # type: ignore[arg-type]
        detector=_MixedDetector(),  # type: ignore[arg-type]
        detector_version=det_ver,
        freshness_version=fresh_ver,
        freshness=_RecordingFreshness(),  # type: ignore[arg-type]
    )

    assert scan_worker.run_job(ctx, scan_id) == "done"
    assert len(seen_crop_sizes) == 1  # ONLY ca_chua crop was scored for freshness!
    by_vid = {d.vision_class_id: d for d in sess.added_detections}
    assert by_vid[tomato_vid].p_tuoi == 0.91
    assert by_vid[pork_vid].p_tuoi is None and by_vid[pork_vid].p_kiem_tra is None


def test_worker_skips_freshness_when_only_non_produce_detected(tmp_path: Path, monkeypatch) -> None:
    pork_vid = 1
    ing_pork = _make_ing("thịt lợn", countable=False)
    monkeypatch.setattr(
        scan_worker.catalog,
        "vision_classes",
        lambda _s: {pork_vid: VisionClassView(pork_vid, "thit_lon", "thịt lợn", False, False, ing_pork.id)},
    )
    monkeypatch.setattr(scan_worker.catalog, "ingredients_by_ids", lambda _s, ids: {ing_pork.id: ing_pork})

    img_path = tmp_path / "pork.jpg"
    Image.new("RGB", (320, 240), (190, 120, 110)).save(img_path, "JPEG", quality=90)

    class _PorkDetector:
        def detect(self, _rgb):  # noqa: ANN001
            return [Box(0, 0.90, 0.1, 0.1, 0.9, 0.9)]

    called = {"n": 0}

    class _FailIfCalledFreshness:
        def predict_crops(self, _crops):  # noqa: ANN001
            called["n"] += 1
            raise AssertionError("freshness should not be called for non-produce")

    class _Queue:
        def publish(self, *_a, **_kw) -> None:
            pass

    now = datetime.now(timezone.utc)
    scan_id = uuid.uuid4()
    scan = scan_worker.Scan(id=scan_id, user_id=uuid.uuid4(), mode="fridge", status="queued", attempts=0, created_at=now)
    photo = scan_worker.ScanImage(
        id=uuid.uuid4(), scan_id=scan_id, ordinal=1, shelf_group=1, storage_key="pork.jpg", width=320, height=240
    )
    sess = _FakeSession(scan, [photo])
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
        class_map={0: pork_vid},
        is_active=True,
    )
    fresh_ver = ModelVersionView(
        id=uuid.uuid4(),
        name="freshness",
        version="v2",
        artifact_key="k2",
        sha256="1" * 64,
        preprocess_version="letterbox_224",
        metrics={},
        status="validated",
        created_at=now,
        class_map={},
        is_active=True,
    )
    ctx = WorkerContext(
        sessionmaker=lambda: sess,  # type: ignore[arg-type]
        storage_dir=tmp_path,
        queue=_Queue(),  # type: ignore[arg-type]
        detector=_PorkDetector(),  # type: ignore[arg-type]
        detector_version=det_ver,
        freshness_version=fresh_ver,
        freshness=_FailIfCalledFreshness(),  # type: ignore[arg-type]
    )

    assert scan_worker.run_job(ctx, scan_id) == "done"
    assert called["n"] == 0
    assert sess.added_detections[0].p_tuoi is None
