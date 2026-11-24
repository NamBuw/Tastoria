from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from tastoria_ml.cv import openimages as oi


def test_ood_label_mids_real_table_no_overlap() -> None:
    if not (oi.META / "oidv7-class-descriptions-boxable.csv").exists():
        pytest.skip("oidv7-class-descriptions-boxable.csv not present")
    ood_mids, excl_mids = oi.ood_label_mids()
    assert len(ood_mids) == len(oi.OOD_LABELS)
    assert not (set(ood_mids) & set(excl_mids))


def test_select_ood_excludes_pizza_mapped_depiction_and_pos_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = tmp_path / "meta"
    ood_root = tmp_path / "ood"
    ood_meta = ood_root / "meta"
    ood_images = ood_root / "images"
    stage = tmp_path / "stage_oi"
    meta.mkdir(parents=True)
    monkeypatch.setattr(oi, "ROOT", tmp_path)
    monkeypatch.setattr(oi, "META", meta)
    monkeypatch.setattr(oi, "OOD_ROOT", ood_root)
    monkeypatch.setattr(oi, "OOD_META", ood_meta)
    monkeypatch.setattr(oi, "OOD_IMAGES", ood_images)
    monkeypatch.setattr(oi, "STAGE", stage)

    # Copy real class CSV if available, else build minimal synthetic one
    real_cls = Path(__file__).resolve().parents[3] / "data/raw/images/openimages_v7/meta/oidv7-class-descriptions-boxable.csv"
    if real_cls.exists():
        (meta / "oidv7-class-descriptions-boxable.csv").write_text(real_cls.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        pytest.skip("oidv7-class-descriptions-boxable.csv missing")

    ood_mids, excl_mids = oi.ood_label_mids()
    mid_by_ood = {v: k for k, v in ood_mids.items()}
    mid_by_excl = {v: k for k, v in excl_mids.items()}

    (meta / "train-selected.txt").write_text("img_pos_overlap\n", encoding="utf-8")
    (meta / "validation-selected.txt").write_text("", encoding="utf-8")

    header = "ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside\n"
    train_rows = [
        f"img_clean_apple,xclick,{mid_by_ood['Apple']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_apple_pizza,xclick,{mid_by_ood['Apple']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_apple_pizza,xclick,{mid_by_excl['Pizza']},1,0.2,0.8,0.2,0.8,0,0,0,0,0",
        f"img_crab_seafood,xclick,{mid_by_ood['Crab']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_crab_seafood,xclick,{mid_by_excl['Seafood']},1,0.1,0.9,0.1,0.9,0,0,0,0,0",
        f"img_cuc_tomato,xclick,{mid_by_ood['Cucumber']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_cuc_tomato,xclick,{mid_by_excl['Tomato']},1,0.2,0.6,0.2,0.6,0,0,0,0,0",
        f"img_depiction,xclick,{mid_by_ood['Banana']},1,0.1,0.5,0.1,0.5,0,0,0,1,0",
        f"img_pos_overlap,xclick,{mid_by_ood['Bell pepper']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
    ]
    val_rows = [
        f"img_val_cheese,xclick,{mid_by_ood['Cheese']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_val_cheese_plate,xclick,{mid_by_ood['Cheese']},1,0.1,0.5,0.1,0.5,0,0,0,0,0",
        f"img_val_cheese_plate,xclick,{mid_by_excl['Plate']},1,0.1,0.9,0.1,0.9,0,0,0,0,0",
    ]
    train_csv = tmp_path / "train-bbox.csv"
    val_csv = tmp_path / "val-bbox.csv"
    train_csv.write_text(header + "\n".join(train_rows) + "\n", encoding="utf-8")
    val_csv.write_text(header + "\n".join(val_rows) + "\n", encoding="utf-8")

    summary = oi.select_ood(caps={"train": 10, "validation": 10}, csv_paths={"train": train_csv, "validation": val_csv})
    assert list(summary["train"]["chosen_labels"].keys()) == ["img_clean_apple"]
    assert summary["train"]["chosen_labels"]["img_clean_apple"] == ["Apple"]
    assert list(summary["validation"]["chosen_labels"].keys()) == ["img_val_cheese"]
    assert not (ood_meta / "test-ood-selected.json").exists()

    # Fake metadata CSV + image fetch -> verify m1_v1 manifest & commercial license flag
    (ood_meta / "train-ood-images-selected.csv").write_text(
        "ImageID,Subset,OriginalURL,OriginalLandingURL,License,AuthorProfileURL,Author,Title,OriginalSize,OriginalMD5,Thumbnail300KURL,Rotation\n"
        "img_clean_apple,train,https://ex/a.jpg,https://ex/a,https://creativecommons.org/licenses/by/2.0/,u,a,t,100,m,https://ex/t.jpg,0.0\n",
        encoding="utf-8",
    )
    (ood_meta / "validation-ood-images-selected.csv").write_text(
        "ImageID,Subset,OriginalURL,OriginalLandingURL,License,AuthorProfileURL,Author,Title,OriginalSize,OriginalMD5,Thumbnail300KURL,Rotation\n"
        "img_val_cheese,validation,https://ex/v.jpg,https://ex/v,https://creativecommons.org/licenses/by-nc/2.0/,u,a,t,100,m,https://ex/vt.jpg,0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oi, "_get_image", lambda split, iid, thumb: (Image.new("RGB", (640, 480), (180, 40, 40)), "thumbnail"))
    manifest_summary = oi.fetch_ood_images(workers=2)
    assert manifest_summary["schema_version"] == "m1_v1"
    assert manifest_summary["source_name"] == "openimages_v7_ood"
    assert manifest_summary["images"] == 2
    assert manifest_summary["neg_images"] == 2
    assert manifest_summary["is_commercial_ok"] == "mixed"

    recs = oi.ood_records()
    by_stem = {r["stem"]: r for r in recs}
    assert by_stem["img_clean_apple"]["is_commercial_ok"] is True
    assert by_stem["img_clean_apple"]["split_hint"] == "train"
    assert by_stem["img_val_cheese"]["is_commercial_ok"] is False
    assert by_stem["img_val_cheese"]["split_hint"] == "val"


def test_is_commercial_license() -> None:
    assert oi._is_commercial_license("https://creativecommons.org/licenses/by/2.0/") is True
    assert oi._is_commercial_license("https://creativecommons.org/licenses/by-sa/4.0/") is True
    assert oi._is_commercial_license("https://creativecommons.org/licenses/by-nc/2.0/") is False
    assert oi._is_commercial_license("") is False
