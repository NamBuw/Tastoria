import unicodedata

from tastoria_ml.data.tcvn3 import tcvn3_to_unicode


def test_known_food_name():
    assert tcvn3_to_unicode("G¹o nÕp c¸i") == "Gạo nếp cái"


def test_tcvn3_u_horn():
    # ư = 0xAD (soft hyphen), ố = 0xE8, ộ = 0xE9, ơ = 0xAC
    assert tcvn3_to_unicode("Rau muèng") == "Rau muống"
    assert tcvn3_to_unicode("D­a chuét") == "Dưa chuột"
    assert tcvn3_to_unicode("L­¬ng") == "Lương"


def test_uppercase_letters():
    # Đ = 0xA7, ậ = 0xCB, ụ = 0xF4, á = 0xB8
    assert tcvn3_to_unicode("§Ëu phô") == "Đậu phụ"
    assert tcvn3_to_unicode("§¸") == "Đá"


def test_ascii_untouched():
    assert tcvn3_to_unicode("Code 1001 (g)") == "Code 1001 (g)"


# Independent reference: lines copied verbatim from glibc localedata/charmaps/TCVN5712-1
# (TCVN 5712:1993 VN1), keeping only the 74 letters VN3 (ABC) also encodes at the same codes:
# 7 capitals without tone marks + all 67 small letters.
GLIBC_TCVN5712_1_VN3_SUBSET = """
/xa1 LATIN CAPITAL LETTER A WITH BREVE
/xa2 LATIN CAPITAL LETTER A WITH CIRCUMFLEX
/xa3 LATIN CAPITAL LETTER E WITH CIRCUMFLEX
/xa4 LATIN CAPITAL LETTER O WITH CIRCUMFLEX
/xa5 LATIN CAPITAL LETTER O WITH HORN
/xa6 LATIN CAPITAL LETTER U WITH HORN
/xa7 LATIN CAPITAL LETTER D WITH STROKE
/xa8 LATIN SMALL LETTER A WITH BREVE
/xa9 LATIN SMALL LETTER A WITH CIRCUMFLEX
/xaa LATIN SMALL LETTER E WITH CIRCUMFLEX
/xab LATIN SMALL LETTER O WITH CIRCUMFLEX
/xac LATIN SMALL LETTER O WITH HORN
/xad LATIN SMALL LETTER U WITH HORN
/xae LATIN SMALL LETTER D WITH STROKE
/xb5 LATIN SMALL LETTER A WITH GRAVE
/xb6 LATIN SMALL LETTER A WITH HOOK ABOVE
/xb7 LATIN SMALL LETTER A WITH TILDE
/xb8 LATIN SMALL LETTER A WITH ACUTE
/xb9 LATIN SMALL LETTER A WITH DOT BELOW
/xbb LATIN SMALL LETTER A WITH BREVE AND GRAVE
/xbc LATIN SMALL LETTER A WITH BREVE AND HOOK ABOVE
/xbd LATIN SMALL LETTER A WITH BREVE AND TILDE
/xbe LATIN SMALL LETTER A WITH BREVE AND ACUTE
/xc6 LATIN SMALL LETTER A WITH BREVE AND DOT BELOW
/xc7 LATIN SMALL LETTER A WITH CIRCUMFLEX AND GRAVE
/xc8 LATIN SMALL LETTER A WITH CIRCUMFLEX AND HOOK ABOVE
/xc9 LATIN SMALL LETTER A WITH CIRCUMFLEX AND TILDE
/xca LATIN SMALL LETTER A WITH CIRCUMFLEX AND ACUTE
/xcb LATIN SMALL LETTER A WITH CIRCUMFLEX AND DOT BELOW
/xcc LATIN SMALL LETTER E WITH GRAVE
/xce LATIN SMALL LETTER E WITH HOOK ABOVE
/xcf LATIN SMALL LETTER E WITH TILDE
/xd0 LATIN SMALL LETTER E WITH ACUTE
/xd1 LATIN SMALL LETTER E WITH DOT BELOW
/xd2 LATIN SMALL LETTER E WITH CIRCUMFLEX AND GRAVE
/xd3 LATIN SMALL LETTER E WITH CIRCUMFLEX AND HOOK ABOVE
/xd4 LATIN SMALL LETTER E WITH CIRCUMFLEX AND TILDE
/xd5 LATIN SMALL LETTER E WITH CIRCUMFLEX AND ACUTE
/xd6 LATIN SMALL LETTER E WITH CIRCUMFLEX AND DOT BELOW
/xd7 LATIN SMALL LETTER I WITH GRAVE
/xd8 LATIN SMALL LETTER I WITH HOOK ABOVE
/xdc LATIN SMALL LETTER I WITH TILDE
/xdd LATIN SMALL LETTER I WITH ACUTE
/xde LATIN SMALL LETTER I WITH DOT BELOW
/xdf LATIN SMALL LETTER O WITH GRAVE
/xe1 LATIN SMALL LETTER O WITH HOOK ABOVE
/xe2 LATIN SMALL LETTER O WITH TILDE
/xe3 LATIN SMALL LETTER O WITH ACUTE
/xe4 LATIN SMALL LETTER O WITH DOT BELOW
/xe5 LATIN SMALL LETTER O WITH CIRCUMFLEX AND GRAVE
/xe6 LATIN SMALL LETTER O WITH CIRCUMFLEX AND HOOK ABOVE
/xe7 LATIN SMALL LETTER O WITH CIRCUMFLEX AND TILDE
/xe8 LATIN SMALL LETTER O WITH CIRCUMFLEX AND ACUTE
/xe9 LATIN SMALL LETTER O WITH CIRCUMFLEX AND DOT BELOW
/xea LATIN SMALL LETTER O WITH HORN AND GRAVE
/xeb LATIN SMALL LETTER O WITH HORN AND HOOK ABOVE
/xec LATIN SMALL LETTER O WITH HORN AND TILDE
/xed LATIN SMALL LETTER O WITH HORN AND ACUTE
/xee LATIN SMALL LETTER O WITH HORN AND DOT BELOW
/xef LATIN SMALL LETTER U WITH GRAVE
/xf1 LATIN SMALL LETTER U WITH HOOK ABOVE
/xf2 LATIN SMALL LETTER U WITH TILDE
/xf3 LATIN SMALL LETTER U WITH ACUTE
/xf4 LATIN SMALL LETTER U WITH DOT BELOW
/xf5 LATIN SMALL LETTER U WITH HORN AND GRAVE
/xf6 LATIN SMALL LETTER U WITH HORN AND HOOK ABOVE
/xf7 LATIN SMALL LETTER U WITH HORN AND TILDE
/xf8 LATIN SMALL LETTER U WITH HORN AND ACUTE
/xf9 LATIN SMALL LETTER U WITH HORN AND DOT BELOW
/xfa LATIN SMALL LETTER Y WITH GRAVE
/xfb LATIN SMALL LETTER Y WITH HOOK ABOVE
/xfc LATIN SMALL LETTER Y WITH TILDE
/xfd LATIN SMALL LETTER Y WITH ACUTE
/xfe LATIN SMALL LETTER Y WITH DOT BELOW
"""

# Codes in 0xA1-0xFE that VN3 leaves unassigned. VN2/VN1 put capitals with tone marks there and the
# five combining tone marks at 0xB0-0xB4; none of them occurs in the FCT 2007 PDF.
VN3_UNASSIGNED = [0xAF, *range(0xB0, 0xB5), 0xBA, *range(0xBF, 0xC6), 0xCD, *range(0xD9, 0xDC), 0xE0, 0xF0]


def test_full_vn3_table_matches_glibc_reference():
    reference = {}
    for line in GLIBC_TCVN5712_1_VN3_SUBSET.strip().splitlines():
        code, name = line.split(" ", 1)
        reference[int(code[2:], 16)] = name
    assert len(reference) == 74
    assert sorted(reference) == sorted(set(range(0xA1, 0xFF)) - set(VN3_UNASSIGNED))
    for code, name in reference.items():
        out = tcvn3_to_unicode(chr(code))
        assert len(out) == 1 and unicodedata.name(out) == name, f"0x{code:02X} -> {out!r}"
    assert unicodedata.is_normalized("NFC", tcvn3_to_unicode("".join(map(chr, range(0xA1, 0xFF)))))


def test_codes_outside_vn3_pass_through():
    unassigned = "".join(map(chr, VN3_UNASSIGNED))
    assert tcvn3_to_unicode(unassigned) == unassigned
    # Already-Unicode letters outside U+00A1-U+00FE, punctuation and the no-break space stay as they are.
    assert tcvn3_to_unicode("Nước – lượng\u00a0") == "Nước – lượng\u00a0"


def test_pdftotext_spellings_from_fct2007():
    # Verbatim name lines from `pdftotext -layout` (poppler 22.02) on VTN_FCT_2007.pdf. That file
    # never yields U+00AD or U+00B5: code 0xAD (ư) comes out as U+2212 MINUS SIGN and code 0xB5 (à)
    # as U+03BC GREEK SMALL LETTER MU.
    assert tcvn3_to_unicode("D\u2212a chuét") == "Dưa chuột"
    assert tcvn3_to_unicode("Ng« v\u03bcng h¹t kh«") == "Ngô vàng hạt khô"
    assert tcvn3_to_unicode("§Ëu t\u2212¬ng (®Ëu n\u03bcnh)") == "Đậu tương (đậu nành)"


def test_case_of_toned_capitals_is_not_in_the_codes():
    # ABC draws capitals with tone marks in a separate all-caps font (VnArialHBold in the FCT PDF)
    # that reuses the small-letter codes. The pages show "Ổi" and "ÓC BÒ"; the codes only say "ổi", "óc bò".
    assert tcvn3_to_unicode("æi") == "ổi"
    assert tcvn3_to_unicode("ãc bß") == "óc bò"
