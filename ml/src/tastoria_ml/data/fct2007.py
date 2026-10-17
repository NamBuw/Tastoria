"""Vietnamese food composition table 2007 (Viện Dinh dưỡng, NXB Y học) -> CSV.

Source: the FAO/INFOODS copy of "Bảng thành phần thực phẩm Việt Nam" (VTN_FCT_2007.pdf, 567 pages).
Each food fills one page: a header (Vietnamese name, English name, STT, code, refuse %) and a
two-column grid of 86 nutrients per 100 g edible portion, plus energy in kJ printed under kcal.

Text comes from `pdftotext -layout`. What the parser has to deal with:
- Food names are set in legacy TCVN3 (ABC) fonts, so they are decoded with `tcvn3_to_unicode`.
  Nutrient labels use a Unicode font and are matched as they are. Names drawn in the all-caps
  ABC font lose their case ("óc bò"), so the first letter is capitalised.
- "-" means "no data" (page x: "chưa phân tích, không có số liệu tham khảo") and becomes NaN;
  a printed 0 means the nutrient is absent and stays 0.
- The two-line row "TS acid béo không no nhiều nối đôi (Total polyunsaturated fatty acid)" has
  its value printed twice on top of itself. The text layer gives a damaged copy on the label line
  ("0 050", the dot lost) and a clean copy ("0.050   3") on the next line; the clean one is used.
- Every row label is checked against the page template and every page must yield all 87 rows,
  so a layout the parser does not know stops it instead of silently dropping values.

CLI: python -m tastoria_ml.data.fct2007 --raw data/raw/fct2007 --out data/processed/fct2007
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from tastoria_ml.data.tcvn3 import tcvn3_to_unicode

__all__ = ["PDF_NAME", "URL", "download", "parse", "parse_page", "verify"]

URL = "https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf"
PDF_NAME = "VTN_FCT_2007.pdf"
# The FAO copy as downloaded on 2026-10-17 (HTTP 200, 567 pages, ModDate 2012-12-20).
PDF_SIZE = 4_722_438
PDF_SHA256 = "6c4838ba5623df6d62b2bf4ef1a82968bbfad8a10980247c32b7e60c0c9ca281"

N_FOODS = 526

# Page template, row by row, as printed: (label in the PDF, unit, nutrient id).
# The left column's unnamed second energy row is energy in kJ.
_LEFT = [
    ("Nước (Water )", "g", "water"),
    ("Năng lượng (Energy )", "KCal", "energy"),
    ("", "KJ", "energy_kj"),
    ("Protein", "g", "protein"),
    ("Lipid (Fat)", "g", "lipid"),
    ("Glucid (Carbohydrate)", "g", "glucid"),
    ("Celluloza (Fiber)", "g", "fiber"),
    ("Tro (Ash)", "g", "ash"),
    ("Đường tổng số (Sugar)", "g", "sugar_total"),
    ("Galactoza (Galactose)", "g", "galactose"),
    ("Maltoza (Maltose)", "g", "maltose"),
    ("Lactoza (Lactose)", "g", "lactose"),
    ("Fructoza (Fructose)", "g", "fructose"),
    ("Glucoza (Glucose)", "g", "glucose"),
    ("Sacaroza (Sucrose)", "g", "sucrose"),
    ("Calci (Calcium)", "mg", "calcium"),
    ("Sắt (Iron)", "mg", "iron"),
    ("Magiê (Magnesium)", "mg", "magnesium"),
    ("Mangan (Manganese)", "mg", "manganese"),
    ("Phospho (Phosphorous)", "mg", "phosphorus"),
    ("Kali (Potassium)", "mg", "potassium"),
    ("Natri (Sodium)", "mg", "sodium"),
    ("Kẽm (Zinc)", "mg", "zinc"),
    ("Đồng (Copper)", "μg", "copper"),
    ("Selen (Selenium)", "μg", "selenium"),
    ("Vitamin C (Ascorbic acid)", "mg", "vitamin_c"),
    ("Vitamin B1 (Thiamine)", "mg", "vitamin_b1"),
    ("Vitamin B2 (Riboflavin)", "mg", "vitamin_b2"),
    ("Vitamin PP (Niacin)", "mg", "niacin"),
    ("Vitamin B5 (Pantothenic acid)", "mg", "vitamin_b5"),
    ("Vitamin B6 (Pyridoxine)", "mg", "vitamin_b6"),
    ("Folat (Folate)", "μg", "folate"),
    ("Vitamin B9 (Folic acid)", "μg", "folic_acid"),
    ("Vitamin H (Biotin )", "μg", "biotin"),
    ("Vitamin B12 (Cyanocobalamine)", "μg", "vitamin_b12"),
    ("Vitamin A (Retinol)", "μg", "retinol"),
    ("Vitamin D (Calciferol )", "μg", "vitamin_d"),
    ("Vitamin E (Alpha-tocopherol )", "mg", "vitamin_e"),
    ("Vitamin K (Phylloquinone)", "μg", "vitamin_k"),
    ("Beta-caroten", "μg", "beta_carotene"),
    ("Alpha-caroten", "μg", "alpha_carotene"),
    ("Beta-cryptoxanthin", "μg", "beta_cryptoxanthin"),
    ("Lycopen", "μg", "lycopene"),
    ("Lutein + Zeaxanthin", "μg", "lutein_zeaxanthin"),
    ("Purin", "mg", "purine"),
]
_AMINO = [
    ("Lysin", "lysine"), ("Methionin", "methionine"), ("Tryptophan", "tryptophan"),
    ("Phenylalanin", "phenylalanine"), ("Threonin", "threonine"), ("Valin", "valine"),
    ("Leucin", "leucine"), ("Isoleucin", "isoleucine"), ("Arginin", "arginine"),
    ("Histidin", "histidine"), ("Cystin", "cystine"), ("Tyrosin", "tyrosine"),
    ("Alanin", "alanine"), ("Acid aspartic", "aspartic_acid"), ("Acid glutamic", "glutamic_acid"),
    ("Glycin", "glycine"), ("Prolin", "proline"), ("Serin", "serine"),
]
_RIGHT = [
    ("Tổng số isoflavon (Total isoflavone)", "mg", "isoflavone_total"),
    ("Daidzein", "mg", "daidzein"),
    ("Genistein", "mg", "genistein"),
    ("Glycetin", "mg", "glycitein"),
    ("Tổng số acid béo no", "g", "sfa_total"),
    ("(Total saturated fatty acid)", "", None),
    ("Palmitic (C16:0)", "g", "palmitic_c16_0"),
    ("Margaric (C17:0)", "g", "margaric_c17_0"),
    ("Stearic (C18:0)", "g", "stearic_c18_0"),
    ("Arachidic (C20:0)", "g", "arachidic_c20_0"),
    ("Behenic (22:0)", "g", "behenic_c22_0"),
    ("Lignoceric (C24:0)", "g", "lignoceric_c24_0"),
    ("TS acid béo không no 1 nối đôi", "g", "mufa_total"),
    ("(Total monounsaturated fatty acid)", "", None),
    ("Myristoleic (C14:1)", "g", "myristoleic_c14_1"),
    ("Palmitoleic (C16:1)", "g", "palmitoleic_c16_1"),
    ("Oleic (C18:1)", "g", "oleic_c18_1"),
    ("TS acid béo không no nhiều nối đôi", "g", "pufa_total"),
    ("(Total polyunsaturated fatty acid)", "", None),
    ("Linoleic (C18:2 n6)", "g", "linoleic_c18_2_n6"),
    # Printed "C18:2 n3" in the PDF; alpha-linolenic acid is C18:3 n3. The id follows the name.
    ("Linolenic (C18:2 n3)", "g", "linolenic_c18_3_n3"),
    ("Arachidonic (C20:4)", "g", "arachidonic_c20_4"),
    ("Eicosapentaenoic (C20:5 n3)", "g", "epa_c20_5_n3"),
    ("Docosahexaenoic (C22:6 n3)", "g", "dha_c22_6_n3"),
    ("TS acid béo trans (Total trans fatty acid)", "g", "tfa_total"),
    ("Cholesterol", "mg", "cholesterol"),
    ("Phytosterol", "mg", "phytosterol"),
    *[(label, "mg", nid) for label, nid in _AMINO],
]

LEFT_LABELS = [(label, unit) for label, unit, _ in _LEFT]
RIGHT_LABELS = [(label, unit) for label, unit, _ in _RIGHT]

# Label spellings seen on single pages that deviate from the template.
_ALIASES = {
    "TS acid béo no": "sfa_total",
    "TS acid béo trans": "tfa_total",
    **{label + "e": nid for label, nid in _AMINO if label.endswith("n")},
}

_ROWS = [r for r in _LEFT + _RIGHT if r[2] is not None]
NUTRIENTS: dict[str, str] = {nid: unit for _, unit, nid in _ROWS}  # id -> unit as printed
_LABEL_TO_ID = {label: nid for label, _, nid in _ROWS} | _ALIASES
assert len(NUTRIENTS) == 87 and len(_ROWS) == 87

_UNIT_OUT = {"KCal": "kcal", "KJ": "kJ", "g": "g", "mg": "mg", "μg": "µg"}

_UNIT_RE = r"KCal|KJ|g|mg|μg|µg"
# A value cell is a number or "-"; "\d+ \d{3}" is the damaged overprint ("0 050" for 0.050).
# The TLTK (source) cell is a digit or "-", once with a stray backtick ("1`").
_TOKEN = re.compile(r"\d+ \d{3}(?![\d.])|\d+\.\d+|\d+|-")
_CELL = re.compile(
    r"(?:^|(?<=\s))(?P<label>\S(?:.*?\S)?)?\s{2,}(?P<unit>" + _UNIT_RE + r")"
    r"(?P<tail>(?:\s+(?:\d+ \d{3}(?![\d.])|\d+\.\d+|\d+|-)`?){0,2})(?=\s{2,}|\s*$)"
)
_CONTINUATION = re.compile(r"\(Total (?:saturated|monounsaturated|polyunsaturated) fatty acid\)")
_ORPHAN = re.compile(r"(?P<value>-|\d+\.\d+|\d+)(?:\s{2,}(?P<src>\d+))?")

_NAME_VI = re.compile(r"Tªn thùc phÈm\s*\(\s*Vietnamese\s*\):?\s*(?P<name>.*?)\s{2,}STT:\s*(?P<stt>\d+)")
_NAME_EN = re.compile(r"Tªn tiÕng Anh \(English\):(?P<name>.*?)(?:M· sè:.*)?$")
_CODE = re.compile(r"M· sè:\s*(?P<code>\d+)")
_REFUSE = re.compile(r"Th¶i bá \(%\):[ \t]*(?P<refuse>\S*)")


def _num(token: str | None) -> float:
    if token is None or token.strip() in ("", "-"):
        return math.nan
    return float(token)


def _capitalise(name: str) -> str:
    return name[:1].upper() + name[1:]


def parse_page(text: str) -> dict:
    """Parse one food page of `pdftotext -layout` output.

    Returns {"code", "stt", "name_vi", "name_en", "refuse_pct",
    "values": {nutrient_id: (value, source_ref)}} with NaN for "-" and source_ref None when absent.
    Raises ValueError on any row or header the template does not explain.
    """
    m_vi, m_code, m_refuse = _NAME_VI.search(text), _CODE.search(text), _REFUSE.search(text)
    if not (m_vi and m_code and m_refuse):
        raise ValueError(f"food page header not found: {text[:200]!r}")
    code = int(m_code["code"])
    name_en = None
    for line in text.splitlines():
        if (m := _NAME_EN.search(line)):
            name_en = re.sub(r"\s+", " ", m["name"]).strip() or None
            # English names are ASCII except one set in the TCVN3 font ("Pa tª", code 7063).
            if name_en and not name_en.isascii():
                name_en = tcvn3_to_unicode(name_en)
            break
    name_vi = _capitalise(re.sub(r"\s+", " ", tcvn3_to_unicode(m_vi["name"])).strip())

    lines = text.splitlines()
    try:
        head = next(i for i, line in enumerate(lines) if "(Nutrients)" in line)
    except StopIteration:
        raise ValueError(f"{code}: nutrient grid header not found") from None
    # Centres of the "(Value)" and "(Source)" header cells of both table halves. A cell with a
    # single token (value printed blank, only the source given, or the reverse) is classified
    # by which of these columns the token sits under.
    columns = [
        ((m.start() + m.end()) / 2, kind)
        for kind, word in (("value", r"\(Value\)"), ("src", r"\(Source\)"))
        for m in re.finditer(word, lines[head])
    ]
    if len(columns) != 4:
        raise ValueError(f"{code}: grid header without two Value and two Source columns")

    def kind_at(pos: float) -> str:
        return min(columns, key=lambda c: abs(c[0] - pos))[1]

    values: dict[str, tuple[float, int | None]] = {}
    # Rows printed without a usable value on their own line: damaged overprints, which must be
    # completed by a clean copy on one of the next two lines, and blank cells, which may be.
    pending: dict[str, list] = {}  # nid -> [lines left, src, damaged]

    def src_of(tok: str | None) -> int | None:
        return int(tok) if tok and tok != "-" else None

    for line in lines[head + 1:]:
        if not line.strip() or re.fullmatch(r"\s*\d+\s*", line):  # blank or page number
            continue
        for m in _CELL.finditer(line):
            label = re.sub(r"\s+", " ", m["label"] or "").strip()
            nid = _LABEL_TO_ID.get(label)
            if nid is None:
                raise ValueError(f"{code}: unknown nutrient row {label!r} in {line!r}")
            if nid in values:
                raise ValueError(f"{code}: {nid} appears twice")
            if _UNIT_OUT[m["unit"].replace("µ", "μ")] != _UNIT_OUT[NUTRIENTS[nid]]:
                raise ValueError(f"{code}: {nid} unit {m['unit']!r}, template {NUTRIENTS[nid]!r}")
            toks = [(t.group(), m.start("tail") + (t.start() + t.end()) / 2)
                    for t in _TOKEN.finditer(m["tail"])]
            value = src = None
            if len(toks) == 2:
                value, src = toks[0][0], toks[1][0]
            elif len(toks) == 1:
                # Only a lone digit 1-7 can be a TLTK code; anything else is a value even when
                # the text layer shifts it right (code 4101 prints energy 28 under "Source").
                if not re.fullmatch(r"[1-7]", toks[0][0]) or kind_at(toks[0][1]) == "value":
                    value = toks[0][0]
                else:
                    src = toks[0][0]
            if value is None or " " in value:
                pending[nid] = [2, src_of(src), value is not None]
                values[nid] = (math.nan, src_of(src))
            else:
                values[nid] = (_num(value), src_of(src))

        rest = _CONTINUATION.sub("", _CELL.sub("", line)).strip()
        if rest:
            orphans = re.split(r"\s{2,}", rest)
            # A clean copy goes to a damaged row first, else to the oldest blank one.
            first = (sorted(pending, key=lambda k: not pending[k][2]) or [None])[0]
            if (m := _ORPHAN.fullmatch(rest)) and pending:
                nid = first
                _, src, _ = pending.pop(nid)
                values[nid] = (_num(m["value"]), src_of(m["src"]) or src)
            elif all(o == "-" for o in orphans) and pending:
                if pending[first][2]:
                    raise ValueError(f"{code}: damaged {first} followed by '-' in {line!r}")
                pending.pop(first)  # blank row printed as "-" below: stays NaN
            elif all(o == "-" for o in orphans):
                pass  # overprinted "-" of a row already read as "-"
            elif re.fullmatch(r"[A-Za-z](?: [a-z])?", rest):
                pass  # stray glyphs of an overprinted label ("P i", "S i" on code 1001)
            else:
                raise ValueError(f"{code}: unexplained text {rest!r} in {line!r}")
        for nid in list(pending):
            pending[nid][0] -= 1
            if pending[nid][0] < 0:
                _, _, damaged = pending.pop(nid)
                if damaged:
                    raise ValueError(f"{code}: damaged {nid} value with no clean copy")

    if any(damaged for _, _, damaged in pending.values()):
        raise ValueError(f"{code}: damaged value with no clean copy in {sorted(pending)}")
    missing = set(NUTRIENTS) - set(values)
    if missing:
        raise ValueError(f"{code}: rows not found: {sorted(missing)}")
    return {
        "code": code,
        "stt": int(m_vi["stt"]),
        "name_vi": name_vi,
        "name_en": name_en,
        "refuse_pct": _num(m_refuse["refuse"]),
        "values": values,
    }


def verify(pdf: Path) -> None:
    """Check size and sha256 against the copy this parser was validated on."""
    pdf = Path(pdf)
    size = pdf.stat().st_size
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if size != PDF_SIZE or digest != PDF_SHA256:
        raise ValueError(
            f"{pdf}: size {size} sha256 {digest}, expected size {PDF_SIZE} sha256 {PDF_SHA256}"
        )


def download(dest_dir: Path) -> Path:
    """Download the FAO copy of the PDF into dest_dir (skipped if a verified copy is there)."""
    import requests

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / PDF_NAME
    if out.exists():
        verify(out)
        return out
    part = out.with_suffix(".pdf.part")
    with requests.get(URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            f.writelines(r.iter_content(1 << 16))
    verify(part)
    part.rename(out)
    return out


def _pages(pdf: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    return out.split("\f")


_FOOD_COLS = {
    "energy": "energy_kcal", "water": "water_g", "protein": "protein_g", "lipid": "lipid_g",
    "glucid": "glucid_g", "fiber": "fiber_g", "ash": "ash_g",
}


def parse(pdf: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse the whole PDF into (foods, nutrients_long).

    foods: code, name_vi, name_en, group_code, refuse_pct, energy_kcal, water_g, protein_g,
    lipid_g, glucid_g, fiber_g, ash_g (one row per food).
    nutrients_long: code, nutrient, unit, value, source_ref (526 x 87 rows; value NaN = "-").
    """
    recs = [parse_page(p) for p in _pages(Path(pdf)) if "Th¶i bá (%)" in p]
    if len(recs) != N_FOODS:
        raise ValueError(f"{len(recs)} food pages, expected {N_FOODS}")
    if [r["stt"] for r in recs] != list(range(1, N_FOODS + 1)):
        raise ValueError("STT is not 1..526 in page order")

    foods = pd.DataFrame(
        [
            {
                "code": r["code"],
                "name_vi": r["name_vi"],
                "name_en": r["name_en"],
                "group_code": r["code"] // 1000,
                "refuse_pct": r["refuse_pct"],
                **{col: r["values"][nid][0] for nid, col in _FOOD_COLS.items()},
            }
            for r in recs
        ]
    )
    foods = foods.astype({"code": "int64", "group_code": "int64"})
    if not foods["code"].is_unique:
        raise ValueError("duplicate food codes")

    long = pd.DataFrame(
        [
            {
                "code": r["code"],
                "nutrient": nid,
                "unit": _UNIT_OUT[unit],
                "value": r["values"][nid][0],
                "source_ref": r["values"][nid][1],
            }
            for r in recs
            for nid, unit in NUTRIENTS.items()
        ]
    )
    long = long.astype({"code": "int64", "value": "float64", "source_ref": "Int64"})
    return foods, long


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=Path("data/raw/fct2007"))
    ap.add_argument("--out", type=Path, default=Path("data/processed/fct2007"))
    args = ap.parse_args(argv)

    pdf = download(args.raw)
    foods, long = parse(pdf)
    args.out.mkdir(parents=True, exist_ok=True)
    foods.to_csv(args.out / "foods.csv", index=False)
    long.to_csv(args.out / "nutrients_long.csv", index=False)

    empty = long["value"].isna().mean()
    print(f"foods: {len(foods)}  nutrients: {long['nutrient'].nunique()}  rows: {len(long)}")
    print(f"empty cells ('-' -> NaN): {long['value'].isna().sum()} / {len(long)} = {empty:.1%}")
    print(f"refuse_pct missing: {foods['refuse_pct'].isna().sum()}")
    print(f"wrote {args.out / 'foods.csv'} and {args.out / 'nutrients_long.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
