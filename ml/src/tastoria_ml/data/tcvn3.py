"""TCVN3 (ABC) to Unicode, for Vietnamese text pulled out of PDFs set in legacy fonts.

TCVN 5712:1993 defines three 8-bit tables. VN3, the one used by the "ABC" fonts (.VnTime,
.VnArial, VnArialHBold, ...), encodes 74 Vietnamese letters at 0xA1-0xFE: all 67 small letters
and the 7 capitals without a tone mark (Ă Â Ê Ô Ơ Ư Đ). The other 60 capitals have no code of
their own (only VN1 holds all 134 letters): ABC draws them with a separate all-caps "H" font
that reuses the small-letter codes.

The Vietnamese food composition table 2007 (VTN_FCT_2007.pdf) sets its food names in ABC fonts
with no usable Unicode map, so `pdftotext` returns each code as the Latin-1 character with the
same number ("G¹o nÕp c¸i" is "Gạo nếp cái"). On that file (poppler 22.02) two codes come out
differently: 0xAD (ư) as U+2212 MINUS SIGN, never U+00AD SOFT HYPHEN, and 0xB5 (à) as U+03BC
GREEK SMALL LETTER MU, never U+00B5 MICRO SIGN. Both spellings are decoded.

What the caller has to handle:
- Case is carried by the font, not the code. A name drawn in the H font as "ÓC BÒ" extracts as
  "ãc bß" and decodes to "óc bò"; restore capitals from the font name or by capitalising.
- Decode only text known to be TCVN3. The table overwrites ordinary Latin-1 letters ("ô" becomes
  "ụ", "μg" becomes "àg"), so decoding Unicode text, or decoding twice, corrupts it.
- Codes that VN3 leaves unassigned (0xAF, 0xB0-0xB4, 0xBA, 0xBF-0xC5, 0xCD, 0xD9-0xDB, 0xE0,
  0xF0) and every other character pass through unchanged.
"""

import unicodedata

__all__ = ["tcvn3_to_unicode"]

# VN3 code chart for 0xA0-0xFF, 16 codes per row; "-" marks a code that is not a VN3 letter.
_VN3_CHART = """
A0  - Ă Â Ê Ô Ơ Ư Đ ă â ê ô ơ ư đ -
B0  - - - - - à ả ã á ạ - ằ ẳ ẵ ắ -
C0  - - - - - - ặ ầ ẩ ẫ ấ ậ è - ẻ ẽ
D0  é ẹ ề ể ễ ế ệ ì ỉ - - - ĩ í ị ò
E0  - ỏ õ ó ọ ồ ổ ỗ ố ộ ờ ở ỡ ớ ợ ù
F0  - ủ ũ ú ụ ừ ử ữ ứ ự ỳ ỷ ỹ ý ỵ -
"""


def _parse_chart(chart: str) -> dict[int, str]:
    table: dict[int, str] = {}
    for row in chart.strip().splitlines():
        base, *cells = row.split()
        if len(cells) != 16:
            raise ValueError(f"TCVN3 chart row {base}: {len(cells)} cells, expected 16")
        for offset, cell in enumerate(cells):
            if cell == "-":
                continue
            letter = unicodedata.normalize("NFC", cell)
            if len(letter) != 1:
                raise ValueError(f"TCVN3 chart row {base}: {cell!r} is not one precomposed letter")
            table[int(base, 16) + offset] = letter
    return table


_VN3 = _parse_chart(_VN3_CHART)

# How pdftotext (poppler 22.02) spells two VN3 codes on VTN_FCT_2007.pdf.
_POPPLER_SPELLINGS = {0x2212: _VN3[0xAD], 0x03BC: _VN3[0xB5]}

_TRANSLATION = {**_VN3, **_POPPLER_SPELLINGS}


def tcvn3_to_unicode(s: str) -> str:
    """Decode TCVN3 (ABC) text, each code read as its Latin-1 character, into NFC Unicode.

    ASCII and characters that are not VN3 codes are returned unchanged.
    """
    return unicodedata.normalize("NFC", s.translate(_TRANSLATION))
