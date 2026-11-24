# Tastoria Independent UI/UX Evaluation Rubric (`ui-rubric.md`)

**Milestone:** M2 — Auditable Quality Gate for M4 Implementation & M6 Acceptance  
**Scope:** Independent scoring rubric & automated Playwright / DOM assertion specification governing `landing/` and `app/` (Web SPA & Android) across Light & Dark modes and viewports `320px`, `375px`, `390px`, `768px`, `1280px`, `1440px`.  
**Authorities:** `docs/design/design-system/MASTER.md`, `docs/design/design-system/pages/*.md`, `docs/design/ui-redesign-spec.md`.

---

## 1. Hard-Fail Gates (Automatic `REJECT` if ANY Violation > 0)

Before awarding numeric points, automated Playwright E2E runs (`171.226.10.153`) and independent Reviewer/Challenger audits MUST verify **zero violations** on all 6 Hard-Fail Gates across every audited route in **both Light and Dark modes**:

| Gate ID | Gate Name | Pass Condition | Machine-Checkable Playwright / DOM Assertion Hook |
|---|---|---|---|
| **HF-1** | **Zero Console / Runtime / 5xx Errors** | `0` uncaught `pageerror`, `0` `console.error`, `0` unhandled promise rejections, `0` HTTP `>= 500` responses during normal flow (expected `4xx` edge tests and expected `503 model_unavailable` / `queue_full` resilience tests on `/quet` excluded). | Attach `page.on('pageerror')`, `page.on('console', m => m.type() === 'error')`, `page.on('response', r => r.status() >= 500)`. |
| **HF-2** | **Zero Horizontal Overflow** | `document.documentElement.scrollWidth <= window.innerWidth` at **all 6 viewports** (`320`, `375`, `390`, `768`, `1280`, `1440` px) in Light & Dark modes. | `await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)` across every viewport & route. |
| **HF-3** | **Zero Emoji or Legacy Unicode Structural Icons** | `0` color emojis (`U+1F000–U+1FAFF`, `U+2600–U+27BF`) and `0` structural raw text glyphs (`✓`, `×`, `−`, `→`, `←`, `↗`, `‹`, `›`, `↓`, `↑`) inside buttons, tabs, badges, or nav controls — SVG `<Icon>` / `<svg>` only. | DOM text scan inside `button, a, [role="button"], [role="tab"], nav` against regex `/[\u{1F000}-\u{1FAFF}\u2600-\u27BF\u2713\u00D7\u2212\u2190-\u2199\u2039\u203A]/u`. |
| **HF-4** | **Zero Placeholder-Only Inputs** | Every visible `<input>`, `<textarea>`, `<select>` MUST have an associated visible `<label for>` / `aria-labelledby` target (M4 `Field` & `AuthField` MUST render `nativeID` on `<T v="label">` + `aria-labelledby` on `<TextInput>` in addition to `aria-label`, never relying solely on `placeholder`). | Query `input:not([type="hidden"]), textarea, select` -> verify `el.labels?.length > 0` or visible `aria-labelledby` target with `innerText.trim().length > 0`. |
| **HF-5** | **Zero Unlabelled Icon-Only Controls** | Every interactive button/link lacking visible text (`innerText.trim() === ''`) MUST expose a non-empty Vietnamese `aria-label` / `accessibilityLabel`. | Query `button, a[href], [role="button"]` -> if `innerText.trim() === ''`, assert `getAttribute('aria-label')?.trim().length >= 2`. |
| **HF-6** | **Asset & Photography Integrity** | `0` broken images (`complete && naturalWidth > 0`), `0` 3D/Three.js canvas scenes, `0` AI-generated food images, and theme-aware `TrayMark` SVG visible in both Light & Dark modes. | `document.querySelectorAll('img')` -> verify `img.complete && img.naturalWidth > 0`; assert `document.querySelectorAll('canvas')` contains no WebGL 3D food scene; verify SVG stroke luminance differs from header background. |

---

## 2. Weighted 100-Point Scoring Rubric

**Passing Threshold:**
- **Overall Score:** `>= 85 / 100`
- **Category Floor:** **`>= 80%` in EVERY individual category** (no high score in layout can mask a contrast failure).

| # | Category | Max Pts | Min Pass (80%) | Core Verification Focus |
|---|---|---|---|---|
| **C1** | Palette, WCAG 2.1 Contrast & Light/Dark Parity | **20** | **16** | `MASTER.md` tokens only, `>= 4.5:1` text, `>= 3.0:1` UI/borders/focus, Light & Dark parity, color-never-alone |
| **C2** | Typography, Vietnamese Diacritics & Numeric Discipline | **15** | **12** | `Be Vietnam Pro` loaded, `>= 12px` floor, `line-height >= 1.5`, `tabular-nums`, `h1→h6`, `<= 75ch` measure |
| **C3** | Layout, 4/8dp Spacing & Responsive Adaptation | **20** | **16** | Desktop `248px` sidebar rail + `<=1240px` multi-col (`>=1024px`), `<=5` mobile tabs (`<768px`), 4/8dp rhythm, safe areas |
| **C4** | Touch Targets, Keyboard Focus & Motion Discipline | **15** | **12** | `>=44px` web / `>=48dp` app + `>=8px` gap, `:focus-visible`, `150–300ms`, `prefers-reduced-motion` |
| **C5** | Interactive States, Domain Clarity & Chart A11y | **15** | **12** | Explicit `loading`/`empty`/`error`/`success`, RFC 9457 Vietnamese errors, accessible charts + tables, illustrative vs live clarity |
| **C6** | Spec Fidelity & Cross-Surface Cohesion | **15** | **12** | Parity across `landing/` & all 10 `app/` modules vs `ui-redesign-spec.md` & `pages/*.md`, bug fixes verified |
| **Total** | | **100** | **85** *(+ >=80%/cat)* | |

---

### C1. Palette, WCAG 2.1 Contrast & Light/Dark Parity (20 Points; Min 16)
- **C1.1 Semantic Token Compliance (5 pts):** `landing/` and `app/` bind colors to `MASTER.md` CSS vars / `tokens.ts` (`-1 pt` per ad-hoc raw hex or legacy `--ink` / `#26291E` found in screen/component styling; `0/5` if `AuthShell` retains `#F3512C` + `#26291E` or `landing/` lacks `[data-theme="dark"]`).
- **C1.2 Text Contrast `>= 4.5:1` in Light & Dark (6 pts):** Body, muted, accent links, buttons (`onAccent`), `FreshBadge`, `editorialSurface`, `storySurface` (`#nhat-ky` copy + `var(--surface)` embedded macro card), and `limeSurface` pairs achieve `>= 4.5:1` (`>= 3.0:1` for `>= 18pt` / `14pt bold` display text), with ancestor background compositing for transparent RN Web nodes. `-2 pts` per failing pair in either mode.
- **C1.3 UI Component, Border & Focus Contrast `>= 3.0:1` (5 pts):** Input borders (`border`), focus rings (`focus`, `focusOnEditorial`), Footer `TrayMark` (`--accent` on `--surface-alt` = `5.35:1`), chart bars (`macro.*` on `--surface`), and `glaze` on `dish` meet `>= 3.0:1`.
- **C1.4 Color Never Alone (WCAG 1.4.1) (4 pts):** `FreshBadge` pairs solid vs hollow dot + color + Vietnamese text; CP-SAT Gantt pairs `active` (`18px`) vs `passive` (`8px` + border/pattern) + external legend; errors pair `danger` border/icon + message.

### C2. Typography, Vietnamese Diacritics & Numeric Discipline (15 Points; Min 12)
- **C2.1 `Be Vietnam Pro` Loaded & Applied (4 pts):** `document.fonts.check` / `fontFamily` matches `BeVietnamPro_400Regular|BeVietnamPro_500Medium|BeVietnamPro_600SemiBold|BeVietnamPro_700Bold|Vietnam|Be Vietnam Pro` (`true` across `400/500/600/700`); zero fallback to system serif/sans causing Vietnamese diacritic clipping.
- **C2.2 Readable Scale, Floor & Line-Height (4 pts):** Body text `15–16px`, `line-height >= 1.5`, body/metadata floor `13sp` mobile (`12px` web; `12sp` permitted ONLY for compact `eyebrow` & 5-tab labels with `maxFontSizeMultiplier: 1.2`), zero sub-`12px` text in `landing/`, prose measure `<= 75ch`, `#landing-recipe-search` `font-size: 16px`.
- **C2.3 Tabular Numerals (`tabular-nums`) (4 pts):** `font-variant-numeric: tabular-nums` verified on kcal counters, macro grams, multi-timers (`/nau/[id]`, `/nau-xong/[id]`), pantry gram ranges, and admin tables.
- **C2.4 Sequential Heading Hierarchy (3 pts):** Exactly one visible `h1` per route; sequential `h1 -> h2 -> h3` without skipped levels (`T` headings in M4 emit `aria-level` `1|2|3` alongside `accessibilityRole="header"`).

### C3. Layout, 4/8dp Spacing & Responsive Adaptation (20 Points; Min 16)
- **C3.1 Desktop Sidebar Rail, Tablet Rail & Multi-Column Workspace (`>= 768px`) (7 pts):** `app/` renders persistent `248px` left sidebar rail + fluid workspace up to `1240px` at `>= 1024px` (confirming `ui.tsx:552` `maxWidth: 560` bottleneck is lifted), deterministic `72px` compact icon rail at `768–1023px` (hiding `(tabs)` bottom bar at `>= 768px`), and 2–3 column grids on `bep`, `kho`, `kham-pha`, `mam`, `nau/[id]`, `di-cho`, `nhat-ky`, `quan-tri`.
- **C3.2 Mobile Bottom Bar & Drawer Discipline (`< 768px`) (5 pts):** `app/` bottom bar has `<= 5` tabs (`Bếp nhà`, `Kho bếp`, `Mâm cơm`, `Đi chợ`, `Nhật ký`), `kham-pha` / `quan-tri` placed outside `(tabs)/` and cleanly reachable alongside `cai-dat` without overflow; `landing/` header collapses cleanly into an accessible drawer.
- **C3.3 4/8dp Alignment & Visual Balance (4 pts):** Consistent card padding (`16–24px`), vertical rhythm, zero overlapping text/badges, zero clipped cards at `320px`.
- **C3.4 Safe Area & Sticky Footer Clearance (4 pts):** Sticky bars/CTAs (`quet/[id]`, `nau/[id]`, `khao-sat`, bottom tabs) never obscure scrollable content or collide with OS bars.

### C4. Touch Targets, Keyboard Focus & Motion Discipline (15 Points; Min 12)
- **C4.1 Touch Target Dimensions & Spacing (5 pts):** Standalone interactive controls (excluding inline prose links `p a` and `.photo-credit a`) measure `>= 44×44px` (Web) / `>= 48×48dp` (App) with `>= 8px` spacing (`getBoundingClientRect()` check).
- **C4.2 Keyboard Navigation & `:focus-visible` (5 pts):** Logical Tab order across `landing/` and `app/` Web, skip-to-main link works, Escape closes modals/drawers, visible `3px` focus ring (`focus` / `focusOnEditorial`).
- **C4.3 Motion & `prefers-reduced-motion` (5 pts):** Transitions stay within `150–300ms`, animate only `transform`/`opacity`, `<= 2` animated elements per view, and `@media (prefers-reduced-motion: reduce)` suppresses animations cleanly.

### C5. Interactive States, Domain Clarity & Chart Accessibility (15 Points; Min 12)
- **C5.1 All 4 States Implemented (5 pts):** Every module explicitly handles `loading` (skeleton/spinner), `empty` (guidance + primary CTA), `error` (`role="alert"` + Retry / RFC 9457 Vietnamese copy), and `success`.
- **C5.2 Accessible Charts & Quantitative Displays (4 pts):** `nhat-ky` kcal & macro bars, `KcalBar`, and `quet/[id]` freshness probability bars (`p_*`) include direct numeric labels + screen-reader summaries + table fallback (zero Grade-C color-only donuts).
- **C5.3 Domain Transparency & Role Gates (3 pts):** `landing/` Simulator & Story clearly state illustrative nature; `mam` distinguishes `lookup` vs `embedding` substitutes; `quan-tri` strictly enforces `user.role === 'admin' || user.role === 'ml_operator'` (hiding nav and blocking `user` & CLI-only `curator` with 0 unauthorized `/admin/*` API requests) and partitions sub-tabs strictly by role.
- **C5.4 Offline & Async Resilience Indicators (3 pts):** `nau-xong/[id]` offline outbox status & `401` re-login guard, `mon/[id]` / `kham-pha` offline catalog indicator, `quet/[id]` `410 image_purged` fallback, and `landing/` APK `HEAD` polling initial/error `aria-disabled="true"` state work cleanly.

### C6. Fidelity to `MASTER.md`, `ui-redesign-spec.md` & Cross-Surface Cohesion (15 Points; Min 12)
- **C6.1 Website (`landing/`) Completeness (5 pts):** All 8 sections (a–h) implemented including Light/Dark switcher, multi-ingredient Pantry-to-Tray Simulator, inline-bundled filterable KB Showcase, 4-tab AI Showcase using `*-{light,dark}.webp`, Survey CTA, and APK `HEAD` launcher.
- **C6.2 Mobile & Web App (`app/`) Module Completeness (6 pts):** All 10 feature modules (including NEW `kham-pha`, `quan-tri`, `kho` urgency filters, `quet/[id]` `classifier_version_id` + `detections[].p_*`, `di-cho` 1-tap `to-pantry` + `AddLotSheet` fallback, `nhat-ky` macros) match `ui-redesign-spec.md` & `pages/*.md`.
- **C6.3 Audit Defect Remediation (4 pts):** Verified fixes for `bep.tsx:237` duplicate `<FoodStory compact />`, `bep.tsx:233` icon circle contrast, `AuthShell.tsx` contrast, `app.json` palette sync, `useCreatePlan` `Idempotency-Key` `4xx` reset, and 26-occurrence (11-symbol) SVG migration.

---

## 3. Scoring Protocol & Machine-Checkable Playwright Hooks

### 3.1 Independent Audit Execution Protocol (M4 & M6)
1. **Viewport & Theme Matrix:** Run headless Chromium Playwright suite across **12 combinations**: `{320, 375, 390, 768, 1280, 1440} × {light, dark}` on `landing/` and key `app/` Web routes (`dang-nhap`, `bep`, `kho`, `kham-pha`, `mon/[id]`, `mam`, `di-cho`, `nhat-ky`, `quet`, `quet/[id]`, `nau/[id]`, `nau-xong/[id]`, `cai-dat`, `khao-sat`, and role-gated `quan-tri`).
2. **Evidence Collection:** Save full-page screenshots, DOM audit JSON (`scrollWidth`, contrast ratios, computed styles, touch bounding boxes, ARIA violations), and console/network error logs on `171.226.10.153`.
3. **Pass Decision:**
   - Check **HF-1 through HF-6** first. Any `> 0` violation -> **AUTOMATIC FAIL** (must fix before re-scoring).
   - Score **C1–C6** objectively from DOM assertions + visual screenshot review. Pass requires **Total `>= 85/100`** AND **`C1 >= 16`, `C2 >= 12`, `C3 >= 16`, `C4 >= 12`, `C5 >= 12`, `C6 >= 12`**.

### 3.2 Recommended Machine-Checkable Playwright / DOM Assertion Hooks

To make M4 E2E and M6 Rubric checks deterministic, M4 MUST expose stable `data-testid` / `testID` and semantic ARIA attributes:

| Assertion Target | Required Hook (`testID` / DOM / ARIA) | Automated Check Expression |
|---|---|---|
| Theme Switcher (`landing/` & `app/`) | `[data-testid="theme-toggle"]` + `<html data-theme="light|dark">` + `[data-testid="app-root"], body` | Click toggles `data-theme`; `ThemeProvider` syncs `document.documentElement.dataset.theme` and `document.body.style.backgroundColor = c.bg` on Web; verify `getComputedStyle(document.querySelector('[data-testid="app-root"]') ?? document.body).backgroundColor` equals `#FAF5EB` (Light) or `#1C1915` (Dark). |
| Desktop Rail, Tablet Rail vs Mobile Tabs (`app/`) | `[data-testid="desktop-sidebar"]`, `[data-testid="tablet-rail"]`, `[data-testid="mobile-tabbar"]` | At `1280px`: `desktop-sidebar` visible (`width >= 240`), `mobile-tabbar` hidden; at `768px`: `tablet-rail` visible (`width === 72`), `mobile-tabbar` hidden; at `390px`: `mobile-tabbar` visible with `<= 5` tabs, sidebar/rail hidden; auth/onboarding routes suppress rail/sidebar. |
| `ui.tsx` `560px` Cap Lifted | `[data-testid="screen-inner"]` | At `1280px` on `bep`/`kho`/`kham-pha`/`mam`: `getBoundingClientRect().width > 700` and `<= 1240`. |
| Duplicate `FoodStory` Fixed | `[data-testid="food-story-card"]` on `/bep` | `await expect(page.getByTestId('food-story-card')).toHaveCount(1)`. |
| Contrast & Computed Tokens | Computed `color` & ancestor-composited `backgroundColor` on `[data-testid="app-root"], body`, `button`, `.button`, `[data-testid="fresh-badge"]`, `[data-testid="auth-editorial"]`, Footer `TrayMark`, `#nhat-ky` macro card | Composite non-transparent ancestor backgrounds for RN Web `rgba(0,0,0,0)` nodes; compute WCAG 2.1 luminance ratio in Node/Playwright helper; assert `>= 4.5` (normal text) / `>= 3.0` (large/UI, Footer `TrayMark`). |
| Typography & `tabular-nums` | `[data-testid="kcal-value"]`, `[data-testid="timer-value"]`, `[data-testid="macro-value"]` | `getComputedStyle(el).fontFamily` matches `/BeVietnamPro_(400Regular|500Medium|600SemiBold|700Bold)|Vietnam|Be Vietnam Pro/`; `fontVariantNumeric` contains `tabular-nums`; body/metadata `>= 12px` (`12px` permitted on `eyebrow`/`tabLabel`). |
| Touch Target & Spacing | Standalone `button, a:not(p a):not(.photo-credit a), [role="button"], [role="tab"], input` | Visible standalone interactive rects have `width >= 44 && height >= 44` (`>= 48` on app primary controls) and pairwise gap `>= 8px` or non-overlapping bounds (`p a` and `.photo-credit a` inline prose links excluded). |
| Interactive Simulator (`landing/`) | `[data-testid="tray-simulator"]`, `[data-ingredient]`, `[data-testid="simulator-result"]` | Clicking ingredient chips toggles `aria-pressed="true"` and updates `[aria-live="polite"]` tray dishes & kcal without page reload. |
| AI Showcase WebP Swap (`landing/`) | `[data-testid="ai-showcase-tabs"]`, `[data-testid="ai-showcase-img"]` | Switching theme updates `src` from `*-light.webp` to `*-dark.webp`; `naturalWidth > 0`. |
| APK `HEAD` Poll (`landing/`) | `#android-download` | Initial state before `HEAD` settles has `aria-disabled="true"` (no active `href`); mock `404` or `NETWORK_ERROR` keeps `aria-disabled="true"`; mock `200` restores clickable `href`. |
| Freshness Probs & Blob Image (`app/` `quet/[id]`) | `[data-testid="freshness-prob-bars"]`, `[data-testid="scan-image-pane"]` | Reads `Scan.classifier_version_id` & `ScanItem.detections[].p_*` (`detections.length === 0` `user_added` notice, multi-detection selector, `classifier_version_id == null` fallback); fetches scan image via authenticated blob (`410 image_purged` shows fallback card without crashing). |
| Hybrid Substitutes (`app/` `mam`) | `[data-testid="sub-origin-lookup"]`, `[data-testid="sub-origin-embedding"]` | Renders distinct Vietnamese origin badge + `in_pantry` status + 1-tap action. |
| Shopping 1-Tap to Pantry (`app/` `di-cho`) | `[data-testid="shopping-to-pantry-btn"]` | Clicking triggers `POST /shopping-items/{id}/to-pantry` (or opens prefilled `AddLotSheet` when `qty_g === null` / `422`), moves item out of bought list, displays `aria-live` confirmation. |
| Role-Gated Admin (`app/` `quan-tri`) | `[data-testid="nav-quan-tri"]`, `[data-testid="admin-forbidden"]` | Hidden for `user` and `curator` (direct URL renders `admin-forbidden` with 0 `/admin/*` network calls); `admin` renders ONLY DSR/Audit tabs; `ml_operator` renders ONLY Models/Surveys tabs. |
