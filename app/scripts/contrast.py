"""Check WCAG 2.1 contrast of all theme tokens (text >= 4.5 on surfaces; borders & UI >= 3.0)."""
import pathlib
import re
import sys

src = pathlib.Path(__file__).parent.parent.joinpath('src/theme/tokens.ts').read_text(encoding='utf-8')


def lum(h: str) -> float:
    h = h.lstrip('#')
    r = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in r]
    return 0.2126 * r[0] + 0.7152 * r[1] + 0.0722 * r[2]


def cr(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def parse_rgba(expr: str) -> tuple[float, float, float, float]:
    r, g, b, a = (float(x.strip()) for x in expr.split(','))
    return r, g, b, a


def blend_rgba(r: float, g: float, b: float, a: float, base_hex: str) -> str:
    bh = base_hex.lstrip('#')
    br, bg_c, bb = (int(bh[i : i + 2], 16) for i in (0, 2, 4))
    return '#{:02X}{:02X}{:02X}'.format(
        round(r * a + br * (1 - a)),
        round(g * a + bg_c * (1 - a)),
        round(b * a + bb * (1 - a)),
    )


def parse_block(block: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    rgba_tokens: dict[str, tuple[float, float, float, float]] = {}
    nested_ranges: list[tuple[int, int]] = []
    for m in re.finditer(r'\b([A-Za-z0-9_]+):\s*\{([^}]*)\}', block):
        group = m.group(1)
        nested_ranges.append((m.start(), m.end()))
        for k, v in re.findall(r"\b([A-Za-z0-9_]+):\s*'(#[0-9A-Fa-f]{6})'", m.group(2)):
            tokens[f'{group}.{k}'] = v
    chars = list(block)
    for s, e in nested_ranges:
        for i in range(s, e):
            chars[i] = ' '
    top = ''.join(chars)
    for k, v in re.findall(r"\b([A-Za-z0-9_]+):\s*'(#[0-9A-Fa-f]{6})'", top):
        tokens[k] = v
    for k, expr in re.findall(r"\b([A-Za-z0-9_]+):\s*'rgba\(([^)]+)\)'", top):
        rgba_tokens[k] = parse_rgba(expr)
    if 'bg' in tokens:
        for k, (r, g, b, a) in rgba_tokens.items():
            tokens[k] = blend_rgba(r, g, b, a, tokens['bg'])
    return tokens


bad = 0
for name in ('light',):
    block = src.split(f'export const {name}: Palette = {{')[1].split('\n};')[0]
    t = parse_block(block)

    checks: list[tuple[str, str, float]] = [
        (fg, bg, 4.5)
        for fg in ('text', 'muted', 'accent', 'herb', 'danger', 'info', 'warn')
        for bg in ('bg', 'surface', 'surfaceAlt', 'surfaceCard')
    ]
    checks += [
        ('onAccent', 'accent', 4.5),
        ('border', 'bg', 3.0),
        ('border', 'surface', 3.0),
        ('borderDashed', 'bg', 2.2),
        ('borderDashed', 'surface', 2.2),
        ('text', 'accentSoft', 4.5),
        ('text', 'okSoft', 4.5),
        ('text', 'herbSoft', 4.5),
        ('text', 'warnSoft', 4.5),
        ('text', 'infoSoft', 4.5),
        ('text', 'dangerSoft', 4.5),
        ('text', 'macroSoft.fat', 4.5),
        ('accent', 'accentSoft', 4.5),
        ('herb', 'herbSoft', 4.5),
        ('info', 'infoSoft', 4.5),
        ('warn', 'warnSoft', 4.5),
        ('danger', 'dangerSoft', 4.5),
        ('macro.fat', 'macroSoft.fat', 4.5),
        ('accentDisplay', 'bg', 3.0),
        ('accentDisplay', 'surface', 3.0),
        ('accent', 'surfaceAlt', 3.0),
        ('onAccent', 'accentDisplay', 4.5),
        ('onLime', 'lime', 4.5),
        ('lime', 'bg', 4.5),
        ('lime', 'surface', 4.5),
        ('onEditorial', 'editorialSurface', 4.5),
        ('onStory', 'storySurface', 4.5),
        ('onStoryMuted', 'storySurface', 4.5),
        ('text', 'limeSurface', 4.5),
        ('focus', 'bg', 3.0),
        ('focus', 'surface', 3.0),
        ('focusOnEditorial', 'editorialSurface', 4.5),
        ('glaze', 'dish', 3.0),
        ('trayRim', 'tray', 3.0),
    ]
    checks += [
        (f'macro.{m}', bg, 4.5)
        for m in ('kcal', 'protein', 'carb', 'fat', 'fiber')
        for bg in ('bg', 'surface', 'surfaceAlt')
    ]
    checks += [
        ('macroChart.carb', bg, 3.0)
        for bg in ('surface', 'surfaceCard')
    ]
    checks += [
        (f'macroChart.{m}', bg, 3.0)
        for m in ('protein', 'lipid', 'fiber')
        for bg in ('bg', 'surface', 'surfaceAlt', 'surfaceCard')
    ]

    for fg, bg, req in checks:
        v = cr(t[fg], t[bg])
        bad += v < req
        print(f'{name:5} {fg:18} on {bg:16} {v:5.2f}{"  FAIL" if v < req else ""}')

    for k in ('tuoi', 'dung_som', 'dung_ngay', 'kiem_tra', 'chua_ro'):
        for bg in ('bg', 'surface'):
            v = cr(t[f'fresh.{k}'], t[bg])
            bad += v < 4.5
            print(f'{name:5} fresh.{k:12} on {bg:16} {v:5.2f}{"  FAIL" if v < 4.5 else ""}')
        v = cr(t[f'fresh.{k}'], t[f'freshSoft.{k}'])
        bad += v < 4.5
        print(f'{name:5} fresh.{k:12} on soft             {v:5.2f}{"  FAIL" if v < 4.5 else ""}')

sys.exit(1 if bad else 0)
