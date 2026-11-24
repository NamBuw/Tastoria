"""Non-AI-slop Web & App UI Rubric Helpers for Tastoria E2E (M3 Landing & M4 App)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page

BANNED_COPY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NUTRITION5K", re.compile(r"nutrition\s*5k", re.IGNORECASE)),
    ("Yuka", re.compile(r"\byuka\b", re.IGNORECASE)),
    ("~25 nhóm", re.compile(r"~?\s*25\s*nhóm", re.IGNORECASE)),
    ("(correct)", re.compile(r"\(correct\)", re.IGNORECASE)),
    ("(restrict)", re.compile(r"\(restrict\)", re.IGNORECASE)),
    ("(object)", re.compile(r"\(object\)", re.IGNORECASE)),
    ("heuristic", re.compile(r"\bheuristic\b", re.IGNORECASE)),
    ("pipeline", re.compile(r"\bpipeline\b", re.IGNORECASE)),
    ("provenance", re.compile(r"\bprovenance\b", re.IGNORECASE)),
    ("Mỹ Vỵ", re.compile(r"Mỹ\s*Vỵ", re.IGNORECASE)),
    ("310+", re.compile(r"310\+")),
    ("36+", re.compile(r"36\+")),
    ("430 món", re.compile(r"430\s*món", re.IGNORECASE)),
    ("Không quảng cáo", re.compile(r"không\s+quảng\s+cáo", re.IGNORECASE)),
    ("Không cần thẻ", re.compile(r"không\s+cần\s+thẻ", re.IGNORECASE)),
    ("Tòa soạn", re.compile(r"\bt[oò]a\s+soạn\b", re.IGNORECASE)),
    ("Mở bếp", re.compile(r"\bmở\s+bếp\b", re.IGNORECASE)),
    ("đoán liều", re.compile(r"đoán\s+liều", re.IGNORECASE)),
    ("phán cứng", re.compile(r"phán\s+cứng", re.IGNORECASE)),
    ("90% tin cậy", re.compile(r"90%\s*tin\s+cậy", re.IGNORECASE)),
    ("15% đến 35%", re.compile(r"15%\s*đến\s*35%", re.IGNORECASE)),
    ("Chụp món Việt", re.compile(r"chụp\s+món\s+việt", re.IGNORECASE)),
    ("Bóc tách calo", re.compile(r"bóc\s+tách\s+calo", re.IGNORECASE)),
    ("Đo calo thật", re.compile(r"đo\s+calo\s+thật", re.IGNORECASE)),
    ("Tài liệu nội bộ", re.compile(r"tài\s+liệu\s+nội\s+bộ", re.IGNORECASE)),
)

# Prose hyphen check: spaced ASCII hyphens inside Vietnamese prose sentences (e.g. "món - rất ngon")
PROSE_SPACED_HYPHEN_RE = re.compile(r"[A-Za-zÀ-ỹ0-9]\s+-\s+[A-Za-zÀ-ỹ0-9]")

# Dedicated brand leak & AI-slop separator checks (kept separate from BANNED_COPY_PATTERNS
# so raw backend barcode catalog strings in T3_07 do not trigger false positives)
BRAND_LEAK_RE = re.compile(r"\btastoria\b", re.IGNORECASE)
AI_SEPARATOR_RE = re.compile(r"[·•—–|]")

_JS_RUBRIC_AUDIT = r"""
({ minTouchPx, surfaceMode, viewportWidth }) => {
  const docEl = document.documentElement;
  const body = document.body;

  // 1. Horizontal overflow
  const scrollWidth = Math.ceil(docEl.scrollWidth);
  const innerWidth = window.innerWidth;
  const overflowPx = Math.max(0, scrollWidth - innerWidth);

  // 2. Fonts (M3-v2/M4-v2 target: Newsreader + Be Vietnam Pro; forbid Geist Mono & Manrope)
  const fontStatus = document.fonts ? document.fonts.status : 'unknown';
  const allFontFamilies = new Set();
  if (body) {
    const bf = getComputedStyle(body).fontFamily;
    if (bf) allFontFamilies.add(bf);
  }
  document.querySelectorAll('h1, h2, h3, p, button, a, span, code, pre, div[dir="auto"], [data-testid]').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.fontFamily) allFontFamilies.add(cs.fontFamily);
  });
  const fontFamiliesStr = Array.from(allFontFamilies).join(' | ');
  const hasNewsreader = /Newsreader/i.test(fontFamiliesStr);
  const hasBeVietnamPro = /Be\s*Vietnam\s*Pro|BeVietnamPro/i.test(fontFamiliesStr);
  const hasGeistMono = /Geist\s*Mono/i.test(fontFamiliesStr);
  const hasManrope = /Manrope/i.test(fontFamiliesStr);
  const hasExpectedFont = hasNewsreader && hasBeVietnamPro && !hasGeistMono && !hasManrope;

  const colorScheme = getComputedStyle(docEl).colorScheme || '';
  const dataTheme = docEl.dataset ? (docEl.dataset.theme || '') : '';
  const themeColorMetaEl = document.querySelector('meta[name="theme-color"]');
  const themeColorMeta = themeColorMetaEl ? (themeColorMetaEl.getAttribute('content') || '') : '';
  const appRootEl = document.querySelector('[data-testid="app-root"]');
  const bgImages = [];
  if (body) {
    const bImg = getComputedStyle(body).backgroundImage;
    if (bImg && bImg !== 'none') bgImages.push(bImg);
  }
  if (appRootEl) {
    const aImg = getComputedStyle(appRootEl).backgroundImage;
    if (aImg && aImg !== 'none') bgImages.push(aImg);
  }
  const bgImage = bgImages.join(' | ');

  // 3. Color & contrast helpers
  function parseColor(str) {
    if (!str) return null;
    const m = str.match(/rgba?\(\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)\s*[,\s]\s*(\d+(?:\.\d+)?)(?:\s*(?:,|\/)\s*([\d.]+%?))?\s*\)/i);
    if (!m) return null;
    let a = 1;
    if (m[4] !== undefined) {
      a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : Number(m[4]);
    }
    return { r: Math.round(Number(m[1])), g: Math.round(Number(m[2])), b: Math.round(Number(m[3])), a };
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
    rootBg = effectiveBg(body || docEl);
  }

  // 4. Touch targets >= minTouchPx (44px+) on primary controls; >= 38px on compact inline chips/toggles
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
    'a.btn',
    'a.button',
  ].join(',');
  const smallTargets = [];
  let checkedTargets = 0;
  document.querySelectorAll(interactiveSel).forEach((el) => {
    if (!isVisible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    checkedTargets += 1;
    const role = (el.getAttribute('role') || '').toLowerCase();
    const testId = el.getAttribute('data-testid') || '';
    const csMinH = parseFloat(getComputedStyle(el).minHeight) || 0;
    const isCompactAppControl =
      surfaceMode === 'app' &&
      (role === 'checkbox' ||
        role === 'radio' ||
        (role === 'button' &&
          (testId.startsWith('modifier-') || (csMinH >= 38 && csMinH < minTouchPx))));
    const floorPx = isCompactAppControl ? 37.5 : minTouchPx - 1;
    if (r.height < floorPx) {
      smallTargets.push({
        tag: el.tagName.toLowerCase(),
        role,
        testId,
        text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
        width: Math.round(r.width),
        height: Math.round(r.height),
        minRequired: isCompactAppControl ? 38 : minTouchPx,
      });
    }
  });

  // 5. WCAG AA Contrast
  const contrastFailures = [];
  let checkedTextNodes = 0;
  const walker = document.createTreeWalker(body || docEl, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const txt = (node.nodeValue || '').trim();
    if (!txt) continue;
    const el = node.parentElement;
    if (!el || !isVisible(el)) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    const cs = getComputedStyle(el);
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
        fg: `rgb(${fg.r},${fg.g},${fg.b})`,
        bg: `rgb(${bg.r},${bg.g},${bg.b})`,
      });
    }
  }

  // 6. Broken images & hidden sections
  const brokenImages = [];
  document.querySelectorAll('img').forEach((img) => {
    if (!isVisible(img)) return;
    if (img.complete && img.naturalWidth <= 0) {
      brokenImages.push({ src: img.currentSrc || img.getAttribute('src') || '', alt: img.alt || '' });
      return;
    }
    const rect = img.getBoundingClientRect();
    if (img.loading === 'lazy' && !img.complete && (rect.top >= window.innerHeight * 1.2 || rect.bottom <= 0)) {
      return;
    }
    if (!img.complete || img.naturalWidth <= 0) {
      brokenImages.push({ src: img.currentSrc || img.getAttribute('src') || '', alt: img.alt || '' });
    }
  });

  const invisibleSections = [];
  document.querySelectorAll('main section').forEach((sec) => {
    const cs = getComputedStyle(sec);
    if (cs.display === 'none') return;
    if (Number(cs.opacity) < 0.99) {
      invisibleSections.push({ id: sec.id || '', opacity: cs.opacity });
    }
  });

  return {
    url: window.location.pathname + window.location.search,
    surfaceMode,
    viewportWidth,
    scrollWidth,
    innerWidth,
    overflowPx,
    fontStatus,
    hasNewsreader,
    hasBeVietnamPro,
    hasGeistMono,
    hasManrope,
    hasExpectedFont,
    fontFamilies: fontFamiliesStr.slice(0, 260),
    colorScheme,
    dataTheme,
    themeColorMeta,
    bgImage: bgImage.slice(0, 400),
    rootBgRgb: [rootBg.r, rootBg.g, rootBg.b],
    checkedTargets,
    smallTargets: smallTargets.slice(0, 15),
    checkedTextNodes,
    contrastFailures: contrastFailures.slice(0, 15),
    brokenImages,
    invisibleSections,
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
    has_newsreader: bool
    has_be_vietnam_pro: bool
    has_geist_mono: bool
    has_manrope: bool
    has_expected_font: bool
    font_families: str
    color_scheme: str
    data_theme: str
    theme_color_meta: str
    bg_image: str
    root_bg_rgb: list[int]
    checked_targets: int
    small_targets: list[dict[str, Any]] = field(default_factory=list)
    checked_text_nodes: int = 0
    contrast_failures: list[dict[str, Any]] = field(default_factory=list)
    broken_images: list[dict[str, Any]] = field(default_factory=list)
    invisible_sections: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)


def find_banned_copy(text: str) -> list[str]:
    """Return any banned/leaked strings found in customer-facing text."""
    hits: list[str] = []
    for label, pattern in BANNED_COPY_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def find_prose_hyphens(text: str) -> list[str]:
    """Find spaced hyphens (' - ') inside Vietnamese prose sentences."""
    return PROSE_SPACED_HYPHEN_RE.findall(text)


def assert_no_banned_copy(text: str, *, context: str = "UI") -> None:
    hits = find_banned_copy(text)
    assert not hits, f"Banned/leaked copy found in {context}: {hits}"


def assert_no_prose_hyphens(text: str, *, context: str = "UI") -> None:
    hits = find_prose_hyphens(text)
    assert not hits, f"Prose-internal spaced hyphens found in {context}: {hits[:5]}"


def assert_no_brand_leak(text: str, context: str = "UI") -> None:
    hits = BRAND_LEAK_RE.findall(text)
    assert not hits, f"Old brand leak ('tastoria') found in {context}: {hits[:5]}"


def assert_no_ai_separators(text: str, context: str = "UI") -> None:
    hits = AI_SEPARATOR_RE.findall(text)
    assert not hits, f"Banned AI-slop separators ([·•—–|]) found in {context}: {hits[:10]}"


def assert_meal_estimate_copy_clean(out: dict[str, Any], *, context: str = "MealCalorieEstimateOut") -> None:
    """Check only customer-facing MealCalorieEstimateOut fields (not internal `source` enum)."""
    fields: list[str] = []
    for key in ("provenance_label_vi", "domain_shift_note", "source_ref", "dish_name_vi", "serving_desc_vi"):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            fields.append(val)
    for mod in out.get("suggested_modifiers") or []:
        if isinstance(mod, dict) and isinstance(mod.get("label_vi"), str):
            fields.append(mod["label_vi"])
    for cand in out.get("top_candidates") or []:
        if isinstance(cand, dict) and isinstance(cand.get("name_vi"), str):
            fields.append(cand["name_vi"])
    assert_no_banned_copy("\n".join(fields), context=context)


def assert_barcode_copy_clean(out: dict[str, Any], *, context: str = "BarcodeNutritionOut") -> None:
    """Check customer-facing BarcodeNutritionOut string fields."""
    fields: list[str] = []
    for key in ("product_name", "brand", "serving_size", "source"):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            fields.append(val)
    assert_no_banned_copy("\n".join(fields), context=context)


def evaluate_page_rubric(
    page: Page,
    *,
    screen_name: str,
    theme: str = "light",
    surface_mode: str = "landing",
    viewport_width: int = 1440,
    viewport_height: int = 900,
    check_touch_targets: bool = True,
    check_contrast: bool = True,
    check_reduced_motion_opacity: bool = False,
    strict: bool = True,
) -> RubricResult:
    """Evaluate non-AI-slop UI rubric on the active Playwright page."""
    min_touch = 44
    raw = page.evaluate(
        _JS_RUBRIC_AUDIT,
        {"minTouchPx": min_touch, "surfaceMode": surface_mode, "viewportWidth": viewport_width},
    )

    failures: list[str] = []
    if raw["overflowPx"] > 0:
        failures.append(
            f"horizontal_overflow:{raw['overflowPx']}px (scrollWidth={raw['scrollWidth']} > innerWidth={raw['innerWidth']})"
        )
    if raw["fontStatus"] != "loaded":
        failures.append(f"fonts_not_loaded:{raw['fontStatus']}")
    if not raw["hasNewsreader"]:
        failures.append(f"missing_newsreader_font:{raw['fontFamilies']}")
    if not raw["hasBeVietnamPro"]:
        failures.append(f"missing_be_vietnam_pro_font:{raw['fontFamilies']}")
    if raw["hasGeistMono"]:
        failures.append(f"forbidden_geist_mono_font:{raw['fontFamilies']}")
    if raw["hasManrope"]:
        failures.append(f"forbidden_manrope_font:{raw['fontFamilies']}")
    if raw["brokenImages"]:
        failures.append(f"broken_images:{raw['brokenImages']}")
    if check_touch_targets and raw["smallTargets"]:
        failures.append(f"small_touch_targets(<{min_touch}px):{raw['smallTargets']}")
    if check_contrast and raw["contrastFailures"]:
        failures.append(f"wcag_contrast_failures:{raw['contrastFailures']}")
    if check_reduced_motion_opacity and raw["invisibleSections"]:
        failures.append(f"sections_stuck_invisible_under_reduced_motion:{raw['invisibleSections']}")

    result = RubricResult(
        screen_name=screen_name,
        viewport=f"{viewport_width}x{viewport_height}",
        theme=theme,
        surface_mode=surface_mode,
        url=raw["url"],
        overflow_px=raw["overflowPx"],
        font_status=raw["fontStatus"],
        has_newsreader=raw["hasNewsreader"],
        has_be_vietnam_pro=raw["hasBeVietnamPro"],
        has_geist_mono=raw["hasGeistMono"],
        has_manrope=raw["hasManrope"],
        has_expected_font=raw["hasExpectedFont"],
        font_families=raw["fontFamilies"],
        color_scheme=raw["colorScheme"],
        data_theme=raw["dataTheme"],
        theme_color_meta=raw["themeColorMeta"],
        bg_image=raw["bgImage"],
        root_bg_rgb=raw["rootBgRgb"],
        checked_targets=raw["checkedTargets"],
        small_targets=raw["smallTargets"],
        checked_text_nodes=raw["checkedTextNodes"],
        contrast_failures=raw["contrastFailures"],
        broken_images=raw["brokenImages"],
        invisible_sections=raw["invisibleSections"],
        passed=(len(failures) == 0),
        failures=failures,
    )
    if strict and failures:
        raise AssertionError(
            f"UI Rubric failed on {screen_name} ({theme} {viewport_width}x{viewport_height}): {failures}"
        )
    return result


def assert_light_parchment_locked(
    light_res: RubricResult,
    dark_os_res: RubricResult,
    max_delta: int = 15,
) -> None:
    """Verify Light-only broadsheet remains locked to warm light parchment even under OS dark mode."""
    assert dark_os_res.color_scheme == "light", (
        f"Expected color_scheme='light' under OS dark mode on {dark_os_res.screen_name}, "
        f"got {dark_os_res.color_scheme!r}"
    )
    l_rgb = light_res.root_bg_rgb
    d_rgb = dark_os_res.root_bg_rgb
    max_channel_diff = max(abs(a - b) for a, b in zip(l_rgb, d_rgb, strict=True))
    assert max_channel_diff <= max_delta, (
        f"Light vs OS-dark root background RGB drifted ({max_channel_diff} > {max_delta}): "
        f"light={l_rgb}, dark_os={d_rgb} on {dark_os_res.screen_name}"
    )
    r, g, b = d_rgb
    assert r >= 195 and g >= 175 and b >= 135, (
        f"Expected warm light parchment RGB (r>=195, g>=175, b>=135) on {dark_os_res.screen_name}, got {d_rgb}"
    )
