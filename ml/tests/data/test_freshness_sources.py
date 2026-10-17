import hashlib
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from tastoria_ml.data import freshness_sources as fs

REPO = Path(__file__).resolve().parents[3]
RAW_ROOT = REPO / "data" / "raw" / "images" / "freshness"
MANIFEST_CSV = REPO / "data" / "processed" / "freshness" / "manifest.csv"


# ---------- synthetic fixtures (no network) ----------


def _touch(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


@pytest.fixture
def fake_raw(tmp_path):
    ls = tmp_path / "local_spinach_leaf" / "extracted" / "Local Spanish Leaf Disease Dataset"
    _touch(ls / "Water Spinach Fresh" / "_0_1.png", b"a")
    _touch(ls / "Water Spinach Non fresh" / "_0_2.png", b"b")
    _touch(ls / "Red Spinach Non Fresh" / "_0_3.png", b"c")
    af = tmp_path / "agrifreshnet" / "extracted" / "Processed Data"
    _touch(af / "Fresh Banana(1-4)" / "IMG_1.jpg", b"d")
    _touch(af / "Fresh Banana(1-4)" / "aug_7_IMG_1.jpg", b"e")
    _touch(af / "Fresh Banana(1-4)" / "IMG_2_HDR_AE~3.jpg", b"f")
    _touch(af / "Semi fresh banana(4-7)" / "IMG_9.jpg", b"g")
    _touch(af / "Semi_Fresh eggplant(4-8)" / "eggplant(2).jpeg", b"h")
    _touch(af / "Semi Fresh Bittermelon ( 3-5)" / "x.jpg", b"i")
    _touch(af / "Rotten Orange(20-35)" / "IMG-1.jpg", b"same")
    _touch(af / "Fresh Orange(1-9)" / "IMG-1.jpg", b"same")
    return tmp_path


def test_parse_folder_names():
    assert fs.parse_agrifreshnet_folder("Semi fresh Pineapple (15-25)") == ("pineapple", "Semi-Fresh", 15, 25)
    assert fs.parse_agrifreshnet_folder("Semi_Fresh eggplant(4-8)") == ("eggplant", "Semi-Fresh", 4, 8)
    assert fs.parse_agrifreshnet_folder("Rotten banana(7-13)") == ("banana", "Rotten", 7, 13)
    assert fs.parse_agrifreshnet_folder("Fresh Bittermelon(1-3)") == ("bittermelon", "Fresh", 1, 3)
    assert fs.parse_spinach_folder("Water Spinach Non fresh") == ("water spinach", "non-fresh")
    assert fs.parse_spinach_folder("Red Spinach Fresh") == ("red spinach", "fresh")
    with pytest.raises(ValueError):
        fs.parse_agrifreshnet_folder("Banana")


def test_synthetic_manifest(fake_raw):
    m = fs.build_manifest(fake_raw)
    m["name"] = m.path.map(lambda p: Path(p).name)
    by = m[m.produce != "orange"].set_index(["dataset", "name"]).sort_index()
    assert by.loc[("local_spinach_leaf", "_0_2.png"), "label3"] == "dung_ngay"
    assert by.loc[("local_spinach_leaf", "_0_1.png"), "label3"] == "tuoi"
    assert by.loc[("agrifreshnet", "IMG_9.jpg"), "label3"] == "dung_som"
    assert by.loc[("agrifreshnet", "x.jpg"), "label3"] == "dung_som"
    # augmented copy and HDR variants share the original's group (no split leakage)
    assert by.loc[("agrifreshnet", "aug_7_IMG_1.jpg"), "group_id"] == by.loc[("agrifreshnet", "IMG_1.jpg"), "group_id"]
    assert by.loc[("agrifreshnet", "aug_7_IMG_1.jpg"), "is_augmented"]
    assert not by.loc[("agrifreshnet", "IMG_1.jpg"), "is_augmented"]
    assert by.loc[("agrifreshnet", "IMG_2_HDR_AE~3.jpg"), "group_id"].endswith("IMG_2_HDR_AE")
    # same bytes under two different freshness labels -> flagged
    orange = m[m.produce == "orange"]
    assert orange.label_conflict.all()
    assert not m[m.produce == "banana"].label_conflict.any()
    assert all(Path(p).is_absolute() for p in m.path)
    assert m.sha256.str.len().eq(64).all()


def test_verify_rejects_wrong_file(tmp_path):
    p = tmp_path / "f.zip"
    p.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    fs.verify_file(p, size=5, sha256=good)
    with pytest.raises(ValueError, match="size"):
        fs.verify_file(p, size=6, sha256=good)
    with pytest.raises(ValueError, match="sha256"):
        fs.verify_file(p, size=5, sha256="0" * 64)


def test_safe_extract_blocks_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        fs.safe_extract(z, tmp_path / "out")


def test_only_original_spinach_file_selected():
    # v3 has two zips with byte-identical image sets; the plan keeps only the non-augmented one
    sel = fs.SOURCES["local_spinach_leaf"]["files"]
    assert len(sel) == 1 and "augment" not in sel[0]["filename"].lower()


# ---------- real data ----------


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST_CSV.is_file():
        pytest.skip(f"missing {MANIFEST_CSV}; run python -m tastoria_ml.data.freshness_sources")
    m = pd.read_csv(MANIFEST_CSV)
    m["path"] = m.path.map(lambda p: str(REPO / p))
    return m


def test_manifest_labels(manifest):
    assert set(manifest.label3) <= {"tuoi", "dung_som", "dung_ngay"}
    assert set(manifest.dataset) == {"local_spinach_leaf", "agrifreshnet"}


def test_manifest_files_exist(manifest):
    sample = manifest.sample(min(200, len(manifest)), random_state=0)
    assert all(Path(p).is_file() for p in sample.path)


def test_water_spinach_present(manifest):
    ls = manifest[manifest.dataset == "local_spinach_leaf"]
    assert ls.produce.str.contains("water", case=False).any()


def test_manifest_counts_match_published(manifest):
    # Local Spinach v3: 3,999 originals (dataset description); AgriFreshNET processed zip: 24 folders x 590
    counts = manifest.dataset.value_counts()
    assert counts["local_spinach_leaf"] == 3999
    assert counts["agrifreshnet"] == 24 * 590
    af = manifest[manifest.dataset == "agrifreshnet"]
    assert af.groupby(["produce", "label_raw"]).ngroups == 24
    assert manifest.group_id.notna().all()


def test_source_md_complete():
    for ds in ("local_spinach_leaf", "agrifreshnet"):
        src = RAW_ROOT / ds / "SOURCE.md"
        if not src.is_file():
            pytest.skip(f"missing {src}; run python -m tastoria_ml.data.freshness_sources")
        text = src.read_text()
        for needle in ("https://data.mendeley.com/datasets/", "sha256", "CC BY 4.0", "Downloaded", "Citation"):
            assert needle in text, (ds, needle)
