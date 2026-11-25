"""Pure-Python + PIL + NumPy 1D EAN-13 / EAN-8 / UPC-A barcode image decoder."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.meal_calorie.estimator import MAX_BYTES, MAX_PIXELS, _sniff

MAX_BARCODE_EDGE = 1600

_L_BITS = (
    "0001101",
    "0011001",
    "0010011",
    "0111101",
    "0100011",
    "0110001",
    "0101111",
    "0111011",
    "0110111",
    "0001011",
)
_R_BITS = tuple("".join("1" if ch == "0" else "0" for ch in bits) for bits in _L_BITS)
_G_BITS = tuple(bits[::-1] for bits in _R_BITS)

_EAN13_PARITY = (
    "LLLLLL",
    "LLGLGG",
    "LLGGLG",
    "LLGGGL",
    "LGLLGG",
    "LGGLLG",
    "LGGGLL",
    "LGLGLG",
    "LGLGGL",
    "LGGLGL",
)
_PARITY_TO_DIGIT = {pat: str(i) for i, pat in enumerate(_EAN13_PARITY)}


def _runs_of_bits(bits: str) -> tuple[int, int, int, int]:
    runs: list[int] = []
    cur = bits[0]
    cnt = 0
    for ch in bits:
        if ch == cur:
            cnt += 1
        else:
            runs.append(cnt)
            cur = ch
            cnt = 1
    runs.append(cnt)
    return (runs[0], runs[1], runs[2], runs[3])


_L_RUNS = tuple(_runs_of_bits(b) for b in _L_BITS)
_G_RUNS = tuple(_runs_of_bits(b) for b in _G_BITS)
_R_RUNS = tuple(_runs_of_bits(b) for b in _R_BITS)
_LG_ENTRIES = [(d, "L", _L_RUNS[d]) for d in range(10)] + [(d, "G", _G_RUNS[d]) for d in range(10)]
_L_ENTRIES = [(d, "L", _L_RUNS[d]) for d in range(10)]
_R_ENTRIES = [(d, "R", _R_RUNS[d]) for d in range(10)]


def verify_ean_check_digit(digits: str) -> bool:
    """Validate EAN-8, UPC-A (12), or EAN-13 check digit using standard modulo-10 weights."""
    if not digits.isdigit() or len(digits) not in (8, 12, 13):
        return False
    body = digits[:-1]
    total = 0
    for idx, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if idx % 2 == 0 else 1)
    check = (10 - (total % 10)) % 10
    return check == int(digits[-1])


def _match_digit(
    w0: int,
    w1: int,
    w2: int,
    w3: int,
    entries: list[tuple[int, str, tuple[int, int, int, int]]],
) -> tuple[int, str, float] | None:
    total = w0 + w1 + w2 + w3
    if total < 4:
        return None
    scale = 7.0 / total
    n0, n1, n2, n3 = w0 * scale, w1 * scale, w2 * scale, w3 * scale
    t1 = (w0 + w1) * scale
    t2 = (w1 + w2) * scale

    best: tuple[int, str, float] | None = None
    for digit, parity, (i0, i1, i2, i3) in entries:
        l1 = abs(n0 - i0) + abs(n1 - i1) + abs(n2 - i2) + abs(n3 - i3)
        edge = abs(t1 - (i0 + i1)) + abs(t2 - (i1 + i2))
        err = l1 + 0.5 * edge
        if max(abs(n0 - i0), abs(n1 - i1), abs(n2 - i2), abs(n3 - i3)) > 0.72:
            continue
        if best is None or err < best[2]:
            best = (digit, parity, err)
    return best


def _rle_row(binary_bars: np.ndarray) -> tuple[list[int], list[bool]]:
    """Run-length encode a 1D boolean array where True == black bar."""
    if binary_bars.size < 20:
        return [], []
    changes = np.flatnonzero(binary_bars[1:] != binary_bars[:-1]) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [binary_bars.size]))
    lengths = (ends - starts).tolist()
    vals = binary_bars[starts].tolist()
    return lengths, vals


def _try_decode_runs(lengths: list[int], is_bar: list[bool]) -> list[str]:
    """Scan run-length encoded 1D binary line for valid EAN-13 and EAN-8 symbols."""
    n = len(lengths)
    found: list[str] = []
    for idx in range(n - 42):
        # Start guard: black bar, white space, black bar of ~equal unit width, preceded by quiet white space
        if not is_bar[idx] or is_bar[idx + 1] or not is_bar[idx + 2]:
            continue
        if idx > 0 and is_bar[idx - 1]:
            continue
        g0, g1, g2 = lengths[idx], lengths[idx + 1], lengths[idx + 2]
        u = (g0 + g1 + g2) / 3.0
        if u < 0.9 or max(g0, g1, g2) > 2.2 * min(g0, g1, g2):
            continue
        if idx > 0 and lengths[idx - 1] < 2.2 * u:
            continue

        # Try EAN-13 (59 runs total from idx)
        if idx + 59 <= n:
            code13 = _decode_ean13_at(lengths, is_bar, idx, u)
            if code13 is not None:
                found.append(code13)

        # Try EAN-8 (43 runs total from idx)
        if idx + 43 <= n:
            code8 = _decode_ean8_at(lengths, is_bar, idx, u)
            if code8 is not None:
                found.append(code8)
    return found


def _valid_guard_5(lengths: list[int], base: int, u_est: float) -> bool:
    seg = lengths[base : base + 5]
    return min(seg) >= 0.35 * u_est and max(seg) <= 2.4 * u_est and max(seg) <= 2.8 * min(seg)


def _valid_guard_3(lengths: list[int], base: int, u_est: float) -> bool:
    seg = lengths[base : base + 3]
    return min(seg) >= 0.35 * u_est and max(seg) <= 2.4 * u_est and max(seg) <= 2.8 * min(seg)


def _decode_ean13_at(lengths: list[int], is_bar: list[bool], idx: int, u0: float) -> str | None:
    if not _valid_guard_5(lengths, idx + 27, u0) or not _valid_guard_3(lengths, idx + 56, u0):
        return None
    if idx + 59 < len(lengths) and not is_bar[idx + 59] and lengths[idx + 59] < 2.0 * u0:
        return None

    left_digits: list[str] = []
    parity_bits: list[str] = []
    pos = idx + 3
    for _ in range(6):
        res = _match_digit(lengths[pos], lengths[pos + 1], lengths[pos + 2], lengths[pos + 3], _LG_ENTRIES)
        if res is None:
            return None
        left_digits.append(str(res[0]))
        parity_bits.append(res[1])
        pos += 4

    first_digit = _PARITY_TO_DIGIT.get("".join(parity_bits))
    if first_digit is None:
        return None

    right_digits: list[str] = []
    pos = idx + 32
    for _ in range(6):
        res = _match_digit(lengths[pos], lengths[pos + 1], lengths[pos + 2], lengths[pos + 3], _R_ENTRIES)
        if res is None:
            return None
        right_digits.append(str(res[0]))
        pos += 4

    code = first_digit + "".join(left_digits) + "".join(right_digits)
    return code if verify_ean_check_digit(code) else None


def _decode_ean8_at(lengths: list[int], is_bar: list[bool], idx: int, u0: float) -> str | None:
    if not _valid_guard_5(lengths, idx + 19, u0) or not _valid_guard_3(lengths, idx + 40, u0):
        return None
    if idx + 43 < len(lengths) and not is_bar[idx + 43] and lengths[idx + 43] < 2.0 * u0:
        return None

    left_digits: list[str] = []
    pos = idx + 3
    for _ in range(4):
        res = _match_digit(lengths[pos], lengths[pos + 1], lengths[pos + 2], lengths[pos + 3], _L_ENTRIES)
        if res is None:
            return None
        left_digits.append(str(res[0]))
        pos += 4

    right_digits: list[str] = []
    pos = idx + 24
    for _ in range(4):
        res = _match_digit(lengths[pos], lengths[pos + 1], lengths[pos + 2], lengths[pos + 3], _R_ENTRIES)
        if res is None:
            return None
        right_digits.append(str(res[0]))
        pos += 4

    code = "".join(left_digits) + "".join(right_digits)
    return code if verify_ean_check_digit(code) else None


def _binarize_1d_variants(profile: np.ndarray) -> list[np.ndarray]:
    """Return adaptive local-mean and global-midpoint thresholded black-bar masks."""
    w = profile.size
    if w < 60:
        return []
    win = max(25, (w // 12) | 1)
    half = win // 2
    padded = np.pad(profile.astype(np.float32), (half, half), mode="edge")
    csum = np.concatenate(([0.0], np.cumsum(padded)))
    local_mean = (csum[win:] - csum[:-win]) / float(win)
    out = [profile < (local_mean - 4.0), profile < local_mean]
    p_min, p_max = float(np.percentile(profile, 5)), float(np.percentile(profile, 95))
    if p_max - p_min > 18.0:
        out.append(profile < (0.5 * (p_min + p_max)))
    return out


def _scan_gray_array(gray: np.ndarray) -> dict[str, int]:
    """Sweep evenly spaced horizontal strips (forward + reversed) and vote on valid barcodes."""
    h, w = gray.shape
    votes: dict[str, int] = {}
    if h < 12 or w < 60:
        return votes

    row_indices = np.unique(np.linspace(max(2, h // 10), min(h - 3, (9 * h) // 10), 17, dtype=int))
    for y in row_indices:
        y0, y1 = max(0, y - 2), min(h, y + 3)
        band = gray[y0:y1, :].mean(axis=0)
        for bars in _binarize_1d_variants(band):
            for seq in (bars, bars[::-1]):
                lengths, is_bar = _rle_row(seq)
                for code in _try_decode_runs(lengths, is_bar):
                    votes[code] = votes.get(code, 0) + 1
                    if votes[code] >= 3:
                        return votes
    return votes


def _load_sanitized_gray(data: bytes) -> Image.Image:
    if len(data) > MAX_BYTES:
        raise ApiError(
            413,
            ProblemCode.image_too_large,
            f"Ảnh lớn hơn {MAX_BYTES} byte.",
            errors=[{"pointer": "/image", "code": "size", "message": "ảnh > 3 MB"}],
        )
    fmt = _sniff(data)
    if fmt is None:
        raise ApiError(
            415,
            ProblemCode.unsupported_media_type,
            "Tệp không phải ảnh JPEG/PNG/WebP.",
            errors=[{"pointer": "/image", "code": "image", "message": "định dạng ảnh không hợp lệ"}],
        )
    try:
        with Image.open(io.BytesIO(data), formats=[fmt]) as im:
            w, h = im.size
            if w <= 0 or h <= 0:
                raise ApiError(415, ProblemCode.unsupported_media_type, "Không giải mã được ảnh.")
            if w * h > MAX_PIXELS:
                raise ApiError(422, ProblemCode.image_too_many_pixels, f"Ảnh {w}×{h} vượt 4096×4096 điểm ảnh.")
            im.load()
            orientation = im.getexif().get(0x0112, 1)
            upright = ImageOps.exif_transpose(im) if orientation != 1 else im
            gray = upright.convert("L")
            if max(gray.size) > MAX_BARCODE_EDGE:
                gray.thumbnail((MAX_BARCODE_EDGE, MAX_BARCODE_EDGE), Image.Resampling.BILINEAR)
            return Image.frombytes("L", gray.size, gray.tobytes())
    except ApiError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ApiError(422, ProblemCode.image_too_many_pixels, str(exc)) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ApiError(415, ProblemCode.unsupported_media_type, "Không giải mã được ảnh.") from exc


def decode_barcode_from_image(data: bytes) -> str | None:
    """Decode EAN-13, EAN-8, or UPC-A barcode digits from JPEG/PNG/WebP bytes, or return None."""
    gray_im = _load_sanitized_gray(data)
    all_votes: dict[str, int] = {}

    def _merge(v: dict[str, int]) -> str | None:
        for k, cnt in v.items():
            all_votes[k] = all_votes.get(k, 0) + cnt
            if all_votes[k] >= 2:
                return k
        return None

    for candidate in (gray_im, gray_im.rotate(90, expand=True)):
        hit = _merge(_scan_gray_array(np.asarray(candidate, dtype=np.uint8)))
        if hit:
            return hit

    # Light skew sweep if axis-aligned scans only got 0–1 hit
    for angle in (-12, 12, 78, 102):
        rot = gray_im.rotate(angle, expand=True, fillcolor=255)
        hit = _merge(_scan_gray_array(np.asarray(rot, dtype=np.uint8)))
        if hit:
            return hit

    if all_votes:
        best_code, best_cnt = max(all_votes.items(), key=lambda kv: kv[1])
        if best_cnt >= 1:
            return best_code
    return None
