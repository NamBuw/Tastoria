"""Automated UI/UX Rubric Evaluator & Static Design Token Auditor for Tastoria E2E.

Evaluates live rendered pages via Playwright `page.evaluate(...)` on:
1. Horizontal overflow (`scrollWidth <= innerWidth`, tolerance 0px)
2. Touch target geometry (`>= 44px` web / `>= 48px` mobile app interactive elements)
3. Font loading (`document.fonts.status == 'loaded'` + `BeVietnamPro` / `Vietnam` active font family)
4. Live computed WCAG 2.2 AA contrast (`>= 4.5:1` normal text, `>= 3.0:1` large text)
5. Light vs Dark background RGB delta verification
6. Broken images (`complete && naturalWidth > 0`) and zero-area SVGs
7. Responsive shell check (Desktop `1440x900` sidebar rail vs Mobile `390x844` bottom tabs)
8. Static token alignment loading `docs/design/design-system/MASTER.md` with `app/src/theme/tokens.ts` fallback

Outputs structured JSON report to `tests/e2e/artifacts/ui_rubric_report.json`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_DESIGN_PATH = REPO_ROOT / "docs" / "design" / "design-system" / "MASTER.md"
TOKENS_TS_PATH = REPO_ROOT / "app" / "src" / "theme" / "tokens.ts"
DEFAULT_REPORT_PATH = REPO_ROOT / "tests" / "e2e" / "artifacts" / "ui_rubric_report.json"

_JS_RUBRIC_AUDIT = r"""
({ minTouchPx, surfaceMode, viewportWidth }) => {
  const docEl = document.documentElement;
  const body = document.body;

  // 1. Horizontal overflow
  const scrollWidth = Math.ceil(docEl.scrollWidth);
  const innerWidth = window.innerWidth;
  const overflowPx = Math.max(0, scrollWidth - innerWidth);

  // 2. Fonts
  const fontStatus = document.fonts ? document.fonts.status : 'unknown';
  const bodyFontFamily = body ? getComputedStyle(body).fontFamily : '';
  const allFontFamilies = new Set();
  if (bodyFontFamily) allFontFamilies.add(bodyFontFamily);
  document.querySelectorAll('h1, h2, h3, p, button, a, span, div[role="button"]').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.fontFamily) allFontFamilies.add(cs.fontFamily);
  });
  const fontFamiliesStr = Array.from(allFontFamilies).join(' | ');
  const hasExpectedFont = /BeVietnamPro|Be Vietnam Pro|Vietnam/i.test(fontFamiliesStr);

  // 3. Helper: parse rgb/rgba (comma or CSS Color 4 space syntax) & compute WCAG luminance/contrast
  function parseColor(str) {
    if (!str) return null;
    const m = str.match(/rgba?\(\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)(?:\s*(?:,|\/)\s*([\d.]+%?))?\s*\)/i);
    if (!m) return null;
    let a = 1;
    if (m[4] !== undefined) {
      a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : Number(m[4]);
    }
    return {
      r: Math.round(Number(m[1])),
      g: Math.round(Number(m[2])),
      b: Math.round(Number(m[3])),
      a,
    };
  }
  function blend(fg, bg) {
    const a = fg.a;
    return {
      r: Math.round(fg.r * a + bg.r * (1 - a)),
      g: Math.round(fg.g * a + bg.g * (1 - a)),
      b: Math.round(fg.b * a + bg.b * (1 - a)),
      a: 1,
    };
  }
  function effectiveBg(el) {
    const chain = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const bg = parseColor(getComputedStyle(cur).backgroundColor);
      if (bg && bg.a > 0) chain.push(bg);
      cur = cur.parentElement;
    }
    // Start from root / body fallback
    let acc = { r: 255, g: 255, b: 255, a: 1 };
    const docBg = parseColor(getComputedStyle(docEl).backgroundColor);
    const bodyBg = body ? parseColor(getComputedStyle(body).backgroundColor) : null;
    if (docBg && docBg.a >= 0.99) acc = docBg;
    else if (bodyBg && bodyBg.a >= 0.99) acc = bodyBg;
    for (let i = chain.length - 1; i >= 0; i--) {
      acc = chain[i].a >= 0.999 ? chain[i] : blend(chain[i], acc);
    }
    return acc;
  }
  function relLum(c) {
    const f = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function contrastRatio(c1, c2) {
    const l1 = relLum(c1);
    const l2 = relLum(c2);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  }
  function isVisible(el) {
    if (!el || el.nodeType !== 1) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0.5 || rect.height <= 0.5) return false;
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const cs = getComputedStyle(cur);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
      const curRect = cur.getBoundingClientRect();
      if (curRect.width <= 1.5 && curRect.height <= 1.5 && cs.overflow === 'hidden') return false;
      cur = cur.parentElement;
    }
    return true;
  }

  // Root / body background RGB (walk main, screen-*, body, html cleanly; fallback to primary wrapper)
  let rootBg = null;
  const bgCandidates = [
    document.querySelector('main'),
    document.querySelector('[data-testid^="screen-"]'),
    body,
    docEl,
  ].filter(Boolean);
  for (const cand of bgCandidates) {
    const c = parseColor(getComputedStyle(cand).backgroundColor);
    if (c && c.a >= 0.5) {
      rootBg = effectiveBg(cand);
      break;
    }
  }
  if (!rootBg) {
    const wrappers = Array.from(document.querySelectorAll('body > div, #root > div, main > div, section'));
    for (const w of wrappers) {
      if (!isVisible(w)) continue;
      const wr = w.getBoundingClientRect();
      if (wr.width < viewportWidth * 0.5 || wr.height < 120) continue;
      const wc = parseColor(getComputedStyle(w).backgroundColor);
      if (wc && wc.a >= 0.5) {
        rootBg = effectiveBg(w);
        break;
      }
    }
  }
  if (!rootBg) {
    const fallbackEl = document.querySelector('[data-testid^="screen-"]') || document.querySelector('main') || body || docEl;
    rootBg = effectiveBg(fallbackEl);
  }

  // 4. Touch target check on visible primary interactive elements
  const interactiveSel = [
    'button',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    '[role="button"]',
    '[role="tab"]',
    '[role="checkbox"]',
    '[role="radio"]',
    'summary',
    'a.button',
  ].join(',');
  const smallTargets = [];
  let checkedTargets = 0;
  document.querySelectorAll(interactiveSel).forEach((el) => {
    if (!isVisible(el)) return;
    const r = el.getBoundingClientRect();
    // Ignore hidden offscreen or tiny SVG wrapper buttons inside non-mobile decorative elements
    if (r.width === 0 || r.height === 0) return;
    checkedTargets += 1;
    if (r.height < minTouchPx - 1) {
      smallTargets.push({
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        testId: el.getAttribute('data-testid') || '',
        text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
        width: Math.round(r.width),
        height: Math.round(r.height),
      });
    }
  });

  // 5. Live computed WCAG 2.2 AA contrast across visible text elements
  const contrastFailures = [];
  let checkedTextNodes = 0;
  const walker = document.createTreeWalker(body || docEl, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const txt = (node.nodeValue || '').trim();
    if (!txt) continue;
    const el = node.parentElement;
    if (!el || !isVisible(el)) continue;
    const cs = getComputedStyle(el);
    // Skip elements inside aria-hidden decorative outlines (e.g. .invitation-outline)
    if (el.closest('[aria-hidden="true"]')) continue;
    const fgRaw = parseColor(cs.color);
    if (!fgRaw || fgRaw.a < 0.2) continue;
    const bg = effectiveBg(el);
    const fg = fgRaw.a >= 0.999 ? fgRaw : blend(fgRaw, bg);
    const ratio = contrastRatio(fg, bg);
    const fontSize = parseFloat(cs.fontSize) || 14;
    const fontWeight = parseInt(cs.fontWeight, 10) || 400;
    const isLarge = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
    const threshold = isLarge ? 3.0 : 4.5;
    checkedTextNodes += 1;
    if (ratio < threshold) {
      contrastFailures.push({
        text: txt.slice(0, 40),
        ratio: Number(ratio.toFixed(2)),
        threshold,
        fontSize,
        fg: `rgb(${fg.r},${fg.g},${fg.b})`,
        bg: `rgb(${bg.r},${bg.g},${bg.b})`,
      });
    }
  }

  // 6. Broken images & zero-area SVGs
  const brokenImages = [];
  document.querySelectorAll('img').forEach((img) => {
    if (!isVisible(img)) return;
    if (!img.complete || img.naturalWidth <= 0) {
      brokenImages.push({ src: img.currentSrc || img.getAttribute('src') || '', alt: img.alt || '' });
    }
  });
  const zeroSvgs = [];
  document.querySelectorAll('svg').forEach((svg) => {
    const cs = getComputedStyle(svg);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = svg.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) {
      zeroSvgs.push({ ariaLabel: svg.getAttribute('aria-label') || '', testId: svg.getAttribute('data-testid') || '' });
    }
  });

  // 7. Responsive shell detection (app mode: sidebar rail on >=1024px vs bottom tab bar on <768px)
  const explicitSidebar = Array.from(document.querySelectorAll('[data-testid="desktop-sidebar-rail"]'));
  const sidebarVisible = explicitSidebar.length > 0
    ? explicitSidebar.some(isVisible)
    : Array.from(document.querySelectorAll('[data-testid^="sidebar-nav-"], aside nav')).some(isVisible);

  const explicitTabs = Array.from(document.querySelectorAll('[data-testid="mobile-bottom-tabs"]'));
  const tabBarVisible = explicitTabs.length > 0
    ? explicitTabs.some(isVisible)
    : Array.from(document.querySelectorAll('[role="tablist"]')).some(isVisible);

  return {
    url: window.location.pathname + window.location.search,
    surfaceMode,
    viewportWidth,
    scrollWidth,
    innerWidth,
    overflowPx,
    fontStatus,
    hasExpectedFont,
    fontFamilies: fontFamiliesStr.slice(0, 220),
    rootBgRgb: [rootBg.r, rootBg.g, rootBg.b],
    checkedTargets,
    smallTargets: smallTargets.slice(0, 15),
    checkedTextNodes,
    contrastFailures: contrastFailures.slice(0, 15),
    brokenImages,
    zeroSvgs,
    sidebarVisible,
    tabBarVisible,
  };
}
"""


@dataclass
class RubricResult:
    screen_name: str
    viewport: str
    theme: str
    surface_mode: str
    url: str
    overflow_px: int
    font_status: str
    has_expected_font: bool
    root_bg_rgb: list[int]
    checked_targets: int
    small_targets: list[dict[str, Any]] = field(default_factory=list)
    checked_text_nodes: int = 0
    contrast_failures: list[dict[str, Any]] = field(default_factory=list)
    broken_images: list[dict[str, Any]] = field(default_factory=list)
    zero_svgs: list[dict[str, Any]] = field(default_factory=list)
    sidebar_visible: bool = False
    tab_bar_visible: bool = False
    passed: bool = True
    failures: list[str] = field(default_factory=list)


def _rel_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def hex_contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = _rel_luminance(c1), _rel_luminance(c2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _parse_tokens_ts(ts_src: str) -> dict[str, dict[str, str]]:
    """Parse Light/Dark palettes from app/src/theme/tokens.ts without colliding nested keys."""
    parsed: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for mode in ("light", "dark"):
        marker = f"export const {mode}: Palette = {{"
        if marker not in ts_src:
            continue
        block = ts_src.split(marker, 1)[1].split("\n};", 1)[0]
        # Extract nested object blocks (e.g., fresh: { ... }, freshSoft: { ... }, macro: { ... }) first
        nested_ranges: list[tuple[int, int]] = []
        for m in re.finditer(r"\b([A-Za-z0-9_]+):\s*\{([^}]*)\}", block):
            group = m.group(1)
            nested_ranges.append((m.start(), m.end()))
            for k, v in re.findall(r"\b([A-Za-z0-9_]+):\s*'(#[0-9A-Fa-f]{6})'", m.group(2)):
                parsed[mode][f"{group}.{k}"] = v
        # Extract only top-level key: '#HEX' outside nested braces
        top_chars = list(block)
        for s, e in nested_ranges:
            for idx in range(s, e):
                top_chars[idx] = " "
        top_block = "".join(top_chars)
        for k, v in re.findall(r"\b([A-Za-z0-9_]+):\s*'(#[0-9A-Fa-f]{6})'", top_block):
            parsed[mode][k] = v
    return parsed


def load_design_tokens() -> dict[str, Any]:
    """Load unified tokens from docs/design/design-system/MASTER.md, falling back to app/src/theme/tokens.ts."""
    tokens: dict[str, Any] = {"source": "fallback:tokens.ts", "light": {}, "dark": {}}
    if MASTER_DESIGN_PATH.is_file():
        md_text = MASTER_DESIGN_PATH.read_text(encoding="utf-8")
        tokens["source"] = str(MASTER_DESIGN_PATH.relative_to(REPO_ROOT))
        hexes = re.findall(r"`(#[0-9A-Fa-f]{6})`", md_text)
        tokens["master_hex_count"] = len(hexes)

        fresh_subkeys = ("tuoi", "dung_som", "dung_ngay", "kiem_tra", "chua_ro")
        for line in md_text.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 4:
                continue
            key_match = re.search(r"`([^`]+)`", cols[0])
            if not key_match:
                continue
            key = key_match.group(1).strip()
            light_hexes = re.findall(r"#[0-9A-Fa-f]{6}", cols[2])
            dark_hexes = re.findall(r"#[0-9A-Fa-f]{6}", cols[3])
            if key == "freshSoft.*" and len(light_hexes) == 5 and len(dark_hexes) == 5:
                for sub, lh, dh in zip(fresh_subkeys, light_hexes, dark_hexes, strict=True):
                    tokens["light"][f"freshSoft.{sub}"] = lh
                    tokens["dark"][f"freshSoft.{sub}"] = dh
            elif light_hexes and dark_hexes:
                tokens["light"][key] = light_hexes[0]
                tokens["dark"][key] = dark_hexes[0]

    if (not tokens["light"] or not tokens["dark"]) and TOKENS_TS_PATH.is_file():
        tokens["source"] = str(TOKENS_TS_PATH.relative_to(REPO_ROOT))
        ts_parsed = _parse_tokens_ts(TOKENS_TS_PATH.read_text(encoding="utf-8"))
        tokens["light"] = ts_parsed["light"]
        tokens["dark"] = ts_parsed["dark"]
    return tokens


def evaluate_page_rubric(
    page: Page,
    *,
    screen_name: str,
    theme: str,
    surface_mode: str = "app",
    viewport_width: int = 390,
    viewport_height: int = 844,
    check_touch_targets: bool = True,
    check_contrast: bool = True,
    check_shell: bool = False,
    strict: bool = True,
) -> RubricResult:
    """Run automated UI/UX rubric evaluation on the current Playwright page."""
    min_touch = 48 if (surface_mode == "app" and viewport_width < 768) else 44
    raw = page.evaluate(
        _JS_RUBRIC_AUDIT,
        {"minTouchPx": min_touch, "surfaceMode": surface_mode, "viewportWidth": viewport_width},
    )

    failures: list[str] = []
    if raw["overflowPx"] > 0:
        failures.append(f"horizontal_overflow:{raw['overflowPx']}px (scrollWidth={raw['scrollWidth']} > innerWidth={raw['innerWidth']})")
    if raw["fontStatus"] != "loaded":
        failures.append(f"fonts_not_loaded:{raw['fontStatus']}")
    if not raw["hasExpectedFont"]:
        failures.append(f"missing_bevietnampro_font:{raw['fontFamilies']}")
    if raw["brokenImages"]:
        failures.append(f"broken_images:{raw['brokenImages']}")
    if raw["zeroSvgs"]:
        failures.append(f"zero_area_svgs:{raw['zeroSvgs']}")
    if check_touch_targets and raw["smallTargets"]:
        failures.append(f"small_touch_targets(<{min_touch}px):{raw['smallTargets']}")
    if check_contrast and raw["contrastFailures"]:
        failures.append(f"wcag_contrast_failures:{raw['contrastFailures']}")
    if check_shell and surface_mode == "app":
        if viewport_width >= 1024 and not raw["sidebarVisible"]:
            failures.append("desktop_sidebar_rail_missing_at_>=1024px")
        if viewport_width < 768 and not raw["tabBarVisible"]:
            failures.append("mobile_bottom_tabs_missing_at_<768px")

    result = RubricResult(
        screen_name=screen_name,
        viewport=f"{viewport_width}x{viewport_height}",
        theme=theme,
        surface_mode=surface_mode,
        url=raw["url"],
        overflow_px=raw["overflowPx"],
        font_status=raw["fontStatus"],
        has_expected_font=raw["hasExpectedFont"],
        root_bg_rgb=raw["rootBgRgb"],
        checked_targets=raw["checkedTargets"],
        small_targets=raw["smallTargets"],
        checked_text_nodes=raw["checkedTextNodes"],
        contrast_failures=raw["contrastFailures"],
        broken_images=raw["brokenImages"],
        zero_svgs=raw["zeroSvgs"],
        sidebar_visible=raw["sidebarVisible"],
        tab_bar_visible=raw["tabBarVisible"],
        passed=(len(failures) == 0),
        failures=failures,
    )
    if strict and failures:
        raise AssertionError(f"UI Rubric failed on {screen_name} ({theme} {viewport_width}x{viewport_height}): {failures}")
    return result


def assert_theme_rgb_delta(light_result: RubricResult, dark_result: RubricResult, min_delta: int = 80) -> None:
    """Verify Light and Dark mode screenshots actually switched root background pixels."""
    l_rgb = light_result.root_bg_rgb
    d_rgb = dark_result.root_bg_rgb
    delta = sum(abs(a - b) for a, b in zip(l_rgb, d_rgb, strict=True))
    assert delta >= min_delta, (
        f"Light/Dark root background RGB delta too small ({delta} < {min_delta}): "
        f"light={l_rgb}, dark={d_rgb} on {light_result.screen_name}"
    )


class RubricCollector:
    """Collects RubricResult entries across a test session and writes ui_rubric_report.json."""

    def __init__(self, output_path: Path = DEFAULT_REPORT_PATH) -> None:
        self.output_path = output_path
        self.entries: list[dict[str, Any]] = []

    def record(self, result: RubricResult) -> RubricResult:
        self.entries.append(asdict(result))
        return result

    def flush(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        tokens = load_design_tokens()
        passed = sum(1 for e in self.entries if e["passed"])
        payload = {
            "token_source": tokens["source"],
            "total_evaluated": len(self.entries),
            "passed": passed,
            "failed": len(self.entries) - passed,
            "entries": self.entries,
        }
        self.output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.output_path
