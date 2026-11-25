"""Unit tests for pure-Python EAN-13 / EAN-8 barcode decoding from images."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from tastoria.modules.meal_calorie.barcode_decode import (
    _EAN13_PARITY,
    _G_BITS,
    _L_BITS,
    _R_BITS,
    decode_barcode_from_image,
    verify_ean_check_digit,
)


def _encode_ean13_bits(digits: str) -> str:
    assert len(digits) == 13 and verify_ean_check_digit(digits)
    parity = _EAN13_PARITY[int(digits[0])]
    left = "".join((_L_BITS if parity[i] == "L" else _G_BITS)[int(digits[1 + i])] for i in range(6))
    right = "".join(_R_BITS[int(digits[7 + i])] for i in range(6))
    return "101" + left + "01010" + right + "101"


def _encode_ean8_bits(digits: str) -> str:
    assert len(digits) == 8 and verify_ean_check_digit(digits)
    left = "".join(_L_BITS[int(digits[i])] for i in range(4))
    right = "".join(_R_BITS[int(digits[4 + i])] for i in range(4))
    return "101" + left + "01010" + right + "101"


def _render_barcode_png(bits: str, *, module_px: int = 4, height_px: int = 120, rotate_deg: float = 0.0, noise: bool = False) -> bytes:
    quiet = 12
    total_modules = len(bits) + 2 * quiet
    w = total_modules * module_px
    h = height_px + 40
    im = Image.new("L", (w, h), 245)
    draw = ImageDraw.Draw(im)
    for idx, b in enumerate(bits):
        if b == "1":
            x0 = (quiet + idx) * module_px
            draw.rectangle([x0, 20, x0 + module_px - 1, 20 + height_px], fill=15)
    if rotate_deg:
        im = im.rotate(rotate_deg, expand=True, fillcolor=245)
    if noise:
        rng = np.random.default_rng(42)
        arr = np.asarray(im, dtype=np.int16) + rng.integers(-18, 19, size=im.size[::-1])
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_decode_ean13_upright_rotated_and_noisy():
    code = "8934563138165"
    bits = _encode_ean13_bits(code)
    assert decode_barcode_from_image(_render_barcode_png(bits)) == code
    assert decode_barcode_from_image(_render_barcode_png(bits, rotate_deg=90)) == code
    assert decode_barcode_from_image(_render_barcode_png(bits, rotate_deg=180)) == code
    assert decode_barcode_from_image(_render_barcode_png(bits, rotate_deg=10, noise=True)) == code


def test_decode_ean8():
    code = "40170725"
    bits = _encode_ean8_bits(code)
    assert decode_barcode_from_image(_render_barcode_png(bits, module_px=5)) == code


def test_decode_blank_or_random_noise_returns_none():
    blank = Image.new("RGB", (320, 180), (240, 240, 240))
    buf = io.BytesIO()
    blank.save(buf, format="PNG")
    assert decode_barcode_from_image(buf.getvalue()) is None

    rng = np.random.default_rng(7)
    noisy = Image.fromarray(rng.integers(0, 255, size=(180, 320), dtype=np.uint8), mode="L")
    buf2 = io.BytesIO()
    noisy.save(buf2, format="JPEG")
    assert decode_barcode_from_image(buf2.getvalue()) is None
