"""Tests for the Vietnamese food composition table 2007 parser (tastoria_ml.data.fct2007).

Tests on the real PDF are skipped until it is downloaded to data/raw/fct2007/:
    uv run --package tastoria-ml python -m tastoria_ml.data.fct2007 --raw data/raw/fct2007 --out data/processed/fct2007
"""

import math
from pathlib import Path

import pytest
from tastoria_ml.data import fct2007
from tastoria_ml.data.fct2007 import parse, parse_page

REPO = Path(__file__).resolve().parents[3]
PDF = REPO / "data" / "raw" / "fct2007" / fct2007.PDF_NAME

needs_pdf = pytest.mark.skipif(not PDF.exists(), reason=f"{PDF} not downloaded")


@pytest.fixture(scope="module")
def parsed():
    return parse(PDF)


@pytest.fixture(scope="module")
def foods(parsed):
    return parsed[0]


@pytest.fixture(scope="module")
def nutrients_long(parsed):
    return parsed[1]


# --- the plan's tests, on the real PDF -------------------------------------------------------


@needs_pdf
def test_fct_food_count(foods):
    assert len(foods) == 526 and foods["code"].is_unique


@needs_pdf
def test_fct_known_names(foods):
    names = set(foods["name_vi"])
    for must in ["Rau muống", "Cà chua", "Đậu phụ"]:
        assert any(n.startswith(must) for n in names), must


@needs_pdf
def test_fct_atwater_sanity(foods):
    f = foods.dropna(subset=["energy_kcal", "protein_g", "lipid_g", "glucid_g"])
    f = f[f["energy_kcal"] > 20]
    est = 4 * f.protein_g + 4 * f.glucid_g + 9 * f.lipid_g
    ok = ((est - f.energy_kcal).abs() / f.energy_kcal) <= 0.15
    assert ok.mean() >= 0.90


@needs_pdf
def test_fct_refuse_range(foods):
    r = foods["refuse_pct"].dropna()
    assert ((r >= 0) & (r <= 100)).all()


@needs_pdf
def test_fct_missing_is_nan(nutrients_long):
    assert not (nutrients_long["value"].astype(str).str.strip() == "-").any()


# --- extra checks against figures the PDF itself publishes -----------------------------------


def test_pdf_integrity_guard(tmp_path):
    bad = tmp_path / fct2007.PDF_NAME
    bad.write_bytes(b"%PDF-1.6 truncated")
    with pytest.raises(ValueError, match="sha256"):
        fct2007.verify(bad)


@needs_pdf
def test_pdf_matches_published_file():
    fct2007.verify(PDF)  # size + sha256 of the FAO copy downloaded 2026-10-17


@needs_pdf
def test_fct_group_sizes(foods):
    # Page vii: "Nhóm 1 ... gồm 23 thực phẩm", ..., "Nhóm 14 ... gồm 16 thực phẩm".
    published = {1: 23, 2: 26, 3: 33, 4: 126, 5: 56, 6: 14, 7: 82, 8: 59, 9: 11, 10: 9,
                 11: 21, 12: 27, 13: 23, 14: 16}
    assert foods["group_code"].value_counts().sort_index().to_dict() == published
    assert (foods["code"] // 1000 == foods["group_code"]).all()


@needs_pdf
def test_fct_nutrient_grid_complete(nutrients_long):
    # 86 nutrients per food (page vii) + energy in kJ, which the table prints under kcal.
    assert nutrients_long["nutrient"].nunique() == 87
    assert len(nutrients_long) == 526 * 87
    assert not nutrients_long.duplicated(["code", "nutrient"]).any()


@needs_pdf
def test_fct_names_are_nfc_and_capitalised(foods):
    import unicodedata

    for n in foods["name_vi"]:
        assert unicodedata.normalize("NFC", n) == n
        assert n[0].isupper(), n
    # Names set in the all-caps "H" font lose their case in the text layer ("óc bò").
    assert "Óc bò" in set(foods["name_vi"])


@needs_pdf
def test_fct_spot_values(foods, nutrients_long):
    """Values read by eye from the rendered pages (pdftoppm -r 80), see SOURCE.md."""
    f = foods.set_index("code")
    assert f.loc[2004, "name_vi"] == "Củ sắn"
    assert f.loc[2004, "name_en"] == "Bitter cassava"
    assert f.loc[2004, "refuse_pct"] == 25.0
    assert f.loc[2004, "energy_kcal"] == 152
    assert f.loc[2004, "glucid_g"] == 36.4
    assert math.isnan(f.loc[2003, "lipid_g"])  # printed "-"
    n = nutrients_long.set_index(["code", "nutrient"])["value"]
    assert n[(2004, "energy_kj")] == 635
    # PUFA total is printed twice on top of itself; the clean copy is the right one.
    assert n[(2004, "pufa_total")] == 0.050
    assert n[(1002, "pufa_total")] == 0.200
    assert math.isnan(n[(2003, "pufa_total")])
    assert n[(2004, "cholesterol")] == 0  # printed 0 = absent, kept as 0
    # Value split from its label onto the next line (Thịt vịt, page 332).
    assert n[(7028, "pufa_total")] == 2.815
    # Value cell left blank, only TLTK printed (Quả thanh long, page 274): NaN, not 1.
    assert math.isnan(n[(5044, "cholesterol")])
    sr = nutrients_long.set_index(["code", "nutrient"])["source_ref"]
    assert sr[(5044, "cholesterol")] == 1
    # Energy printed shifted right under "Source" in the text layer (Thìa là, code 4101, page 203).
    assert n[(4101, "energy")] == 28 and n[(4101, "energy_kj")] == 115
    # Spot-checked pages (SOURCE.md): Khoai lang nghệ, Thịt cừu nạc.
    assert f.loc[2009, "refuse_pct"] == 13.0 and n[(2009, "beta_carotene")] == 1470
    assert n[(7010, "sfa_total")] == 6.7 and n[(7010, "purine")] == 182
    assert math.isnan(n[(7010, "pufa_total")])


# --- synthetic pages: layout quirks without the PDF ------------------------------------------

_HEAD = (
    "Tªn thùc phÈm (Vietnamese):             §Ëu phô                     STT:        90\n"
    "Tªn tiÕng Anh (English):                Soybean curd                M· sè:      3013\n"
    "Thμnh phÇn dinh d−ìng trong 100g phÇn ¨n ®−îc (100 grams edible portion)   Th¶i bá (%): {refuse}\n"
    "\n"
    "      Thμnh phÇn dinh d−ìng       ĐV Hμm lượng TLTK                    Thμnh phÇn dinh d−ìng               ĐV    Hμm lượng   TLTK\n"
    "           (Nutrients)           (Unit) (Value) (Source)                    (Nutrients)                   (Unit)  (Value)  (Source)\n"
)


def _page(refuse="0.0", pufa_line="", after_pufa=""):
    """A minimal page in the PDF's layout: every nutrient row of the real template."""
    left = fct2007.LEFT_LABELS
    right = fct2007.RIGHT_LABELS
    rows = []
    for i in range(max(len(left), len(right))):
        lcell = ""
        if i < len(left):
            label, unit = left[i]
            lcell = f" {label:<32}{unit:<6}{'1.0' if label == 'Protein' else '-':>8}"
        rcell = ""
        if i < len(right):
            label, unit = right[i]
            if label.startswith("TS acid béo không no nhiều"):
                rcell = f"     {label:<45}{unit:<6}{pufa_line}"
            elif unit:
                rcell = f"     {label:<45}{unit:<6}{'-':>6}"
            else:
                rcell = f"     {label}"
        rows.append(f"{lcell:<60}{rcell}".rstrip())
        if i < len(right) and right[i][0].startswith("TS acid béo không no nhiều") and after_pufa:
            rows.append(after_pufa)
    return _HEAD.format(refuse=refuse) + "\n".join(rows) + "\n\n   90\n"


def test_parse_page_header():
    rec = parse_page(_page(refuse="12.5"))
    assert rec["code"] == 3013
    assert rec["name_vi"] == "Đậu phụ"
    assert rec["name_en"] == "Soybean curd"
    assert rec["refuse_pct"] == 12.5
    assert rec["values"]["protein"] == (1.0, None)


def test_parse_page_dash_is_nan():
    rec = parse_page(_page(refuse="-", pufa_line="     -"))
    assert math.isnan(rec["refuse_pct"])
    assert math.isnan(rec["values"]["water"][0])
    assert math.isnan(rec["values"]["pufa_total"][0])


def test_parse_page_overprinted_pufa():
    rec = parse_page(_page(pufa_line="0 200", after_pufa=" " * 120 + "0.200           3"))
    assert rec["values"]["pufa_total"] == (0.2, 3)


def test_parse_page_rejects_unknown_row():
    page = _page().replace("Purin", "Purine X")
    with pytest.raises(ValueError, match="Purine X"):
        parse_page(page)


@needs_pdf
def test_fct_english_names(foods):
    en = foods["name_en"].dropna()
    # Ten pages print no English name; they stay empty, not "Mã số: ...".
    assert foods["name_en"].isna().sum() == 10
    assert not en.str.contains("M·|Mã số").any()
    assert foods.set_index("code").loc[7063, "name_en"] == "Pa tê"
    assert (en.str.isascii() | (en == "Pa tê")).all()
