"""Check WCAG contrast of the theme tokens (text ≥ 4.5 on bg/surface/its soft tint)."""
import re, sys, pathlib
src = pathlib.Path(__file__).parent.parent.joinpath('src/theme/tokens.ts').read_text()
def lum(h):
    h = h.lstrip('#'); r = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    r = [x/12.92 if x <= .03928 else ((x+.055)/1.055)**2.4 for x in r]
    return .2126*r[0]+.7152*r[1]+.0722*r[2]
def cr(a, b):
    a, b = lum(a), lum(b); return (max(a, b)+.05)/(min(a, b)+.05)
bad = 0
for name in ('light', 'dark'):
    block = src.split(f'export const {name}: Palette = {{')[1].split('\n};')[0]
    g = lambda k: re.search(rf'\b{k}: \'(#\w+)\'', block).group(1)
    fr = dict(re.findall(r"(\w+): '(#\w+)'", re.search(r'fresh: \{([^}]*)\}', block).group(1)))
    fs = dict(re.findall(r"(\w+): '(#\w+)'", re.search(r'freshSoft: \{([^}]*)\}', block).group(1)))
    checks = [(t, b, 4.5) for t in ('text', 'muted', 'accent', 'herb', 'danger') for b in ('bg', 'surface', 'surfaceAlt')]
    checks += [('onAccent', 'accent', 4.5), ('border', 'bg', 3), ('border', 'surface', 3), ('text', 'accentSoft', 4.5), ('text', 'okSoft', 4.5), ('text', 'warnSoft', 4.5), ('accent', 'accentSoft', 4.5)]
    for t, b, m in checks:
        v = cr(g(t), g(b)); bad += v < m
        print(f'{name:5} {t:9} on {b:10} {v:5.2f}{"  FAIL" if v < m else ""}')
    for k in fr:
        for b in ('bg', 'surface'):
            v = cr(fr[k], g(b)); bad += v < 4.5
            print(f'{name:5} fresh.{k:9} on {b:7} {v:5.2f}{"  FAIL" if v < 4.5 else ""}')
        v = cr(fr[k], fs[k]); bad += v < 4.5
        print(f'{name:5} fresh.{k:9} on soft    {v:5.2f}{"  FAIL" if v < 4.5 else ""}')
sys.exit(1 if bad else 0)
