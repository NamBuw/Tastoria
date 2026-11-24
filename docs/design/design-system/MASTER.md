# Tastoria Unified Design System (`MASTER.md`)

**System Name:** Warm Lacquer & Ceramic Editorial System (*"Mâm gỗ sơn, bát men lam"*)  
**Milestone:** M2 — Unified Design Contract for Website (`landing/`) & Cross-Platform App (`app/` Android + Web)  
**Scope:** Single source of truth for Light ("Rice Paper & Lacquer") and Dark ("Charcoal Lacquer & Warm Cream") tokens, WCAG 2.1 AA contrast compliance, typography, spacing, elevation, brand marks, SVG-only iconography, touch/a11y rules, and motion.  
**Override Rule:** Any route-specific deviations live in `docs/design/design-system/pages/<page>.md`. When implementing a screen, read `MASTER.md` first, then apply the matching `pages/<page>.md` override if present.

---

## 1. Visual & Brand Direction

1. **Dual-Mode Semantic Identity:**
   - **Light Mode — "Rice Paper & Lacquer":** Warm rice-paper background (`#FAF5EB`), crisp cream cards (`#FFFCF6`), deep espresso ink (`#2A211B`), lacquer red interactive accent (`#A63724`), herb green freshness (`#2D6A3E`), and Bát Tràng cobalt ceramic glaze (`#2F5597`).
   - **Dark Mode — "Charcoal Lacquer & Warm Cream":** Warm charcoal lacquer ground (`#1C1915`, never pure `#000000`), elevated dark timber surfaces (`#27221C`, `#342D24`), warm cream ink (`#F7EFDF`), desaturated coral-lacquer interactive accent (`#F2948A`), sage herb (`#7CC68C`), and luminous cobalt UI (`#7BA4E8`).
2. **Reconciling `landing/` Editorial Vibrancy with WCAG 2.1 AA:**
   - Interactive text/buttons/links MUST use `accent` (`#A63724` Light / `#F2948A` Dark).
   - Full-bleed editorial bands (`landing/` Hero & Invitation, `AuthShell` left panel) use `editorialSurface` (`#B63922` Light / `#381B14` Dark) paired with `onEditorial` (`#FAF5EB` Light / `#F7EFDF` Dark), while `landing/` `#nhat-ky` uses `storySurface` (`#2A211B` Light / `#27221C` Dark) paired with `onStory` (`#FAF5EB` Light / `#F7EFDF` Dark) so copy passes `>= 4.5:1` everywhere.
   - Vibrant `#F3512C` is retained strictly as `accentDisplay` for graphical brand marks (`Header TrayMark` bowl fill on `--bg`, graphic dots, and `onLime` `#1C1915` editorial badges where contrast is `5.02:1`). **`accentDisplay` (`#F3512C`) MUST NOT be placed on Light `surfaceAlt` (`#EFE7D8`, `2.84:1 < 3.0:1`).**
3. **Flat Real Photography Only:** Per `docs/design/2026-10-30-motion-references.md`, all culinary photography remains flat (`border-radius: 18px–24px`), with zero 3D perspective/canvas effects and zero AI-generated food images.

---

## 2. Unified Color Token Contract (`CSS` & `TypeScript`)

All components in `landing/style.css` and `app/src/theme/tokens.ts` MUST reference semantic tokens below — **zero hardcoded raw hex values** inside screen or component files.

### 2.1 Complete Light & Dark Token Table

| Semantic Key (`tokens.ts`) | CSS Variable (`landing/style.css`) | Light ("Rice Paper & Lacquer") | Dark ("Charcoal Lacquer & Warm Cream") | Intended Role & Usage Guardrail |
|---|---|---|---|---|
| `bg` | `--bg` | `#FAF5EB` | `#1C1915` | Primary viewport canvas / page ground |
| `surface` | `--surface` | `#FFFCF6` | `#27221C` | Cards, sheets, bottom tab bar, sidebar rail, inputs |
| `surfaceAlt` | `--surface-alt` | `#EFE7D8` | `#342D24` | Recessed tracks, footer ground, table headers, inactive pills |
| `text` | `--text` | `#2A211B` | `#F7EFDF` | Primary headings, body copy, form values |
| `muted` | `--muted` | `#64574A` | `#C7BBAA` | Secondary captions, timestamps, inactive tab labels, placeholders |
| `border` | `--border` | `#8A7A68` | `#958773` | Interactive boundaries (inputs, checkboxes, chips, active card borders; `>= 3.0:1`) |
| `hairline` | `--hairline` | `#E0D5C3` | `#44392D` | Non-interactive decorative dividers, card hairlines, table row rules |
| `accent` | `--accent` | `#A63724` | `#F2948A` | Primary CTA fill, text links, active nav icons/text, active sliders |
| `onAccent` | `--on-accent` | `#FFFFFF` | `#2A0E0C` | Text/SVG stroke placed directly on `accent` fill |
| `accentSoft` | `--accent-soft` | `#F8E1D5` | `#4A2522` | Active tab pill, soft accent badges, selected option surface |
| `accentDisplay` | `--accent-display` | `#F3512C` | `#F3512C` | Graphic-only brand mark (`Header TrayMark` bowl on `--bg`, decorative dot) or badge background paired ONLY with `onLime` (`#1C1915`). **NEVER on Light `surfaceAlt` (`2.84:1 < 3.0:1`)** |
| `editorialSurface` | `--editorial-surface` | `#B63922` | `#381B14` | Full-bleed editorial Hero, Invitation band, `AuthShell` left showcase |
| `onEditorial` | `--on-editorial` | `#FAF5EB` | `#F7EFDF` | Primary editorial headline & body copy placed on `editorialSurface` |
| `lime` | `--lime` | `#D9EE74` | `#D9EE74` | High-contrast lime CTA fill (paired ONLY with `onLime` `#1C1915`) or editorial highlight on `editorialSurface` / `storySurface` |
| `limeSurface` | `--lime-surface` | `#D9EE74` | `#2C3318` | `landing/` `#bo-gia-lap` (replacing legacy `#can-bep`) section background & `AuthShell` photo caption bar |
| `onLime` | `--on-lime` | `#1C1915` | `#1C1915` | High-contrast dark ink placed directly on `lime` (`13.70:1`) or `accentDisplay` (`5.02:1`) fills |
| `storySurface` | `--story-surface` | `#2A211B` | `#27221C` | `landing/` `#nhat-ky` dark-ink story section & photo credit badge (`92%`/solid); embedded preview cards inside MUST use `var(--surface)` |
| `onStory` | `--on-story` | `#FAF5EB` | `#F7EFDF` | Primary headings & body copy placed on `storySurface` |
| `onStoryMuted` | `--on-story-muted` | `#EFE7D8` | `#C7BBAA` | Secondary captions & story subcopy placed on `storySurface` |
| `herb` | `--herb` | `#2D6A3E` | `#7CC68C` | Positive/freshness accent, passive cooking bars, within-target nutrition |
| `herbSoft` | `--herb-soft` | `#DCEBDD` | `#21382A` | Success/fresh soft banner & badge fill |
| `info` *(alias `glazeUi`)* | `--info` | `#2F5597` | `#7BA4E8` | Informational links, AI/ML telemetry badges, semantic substitution tags |
| `infoSoft` | `--info-soft` | `#E3EAF7` | `#1E2D47` | Informational callouts, pgvector `embedding` substitute chip fill |
| `warn` | `--warn` | `#8A5A00` | `#E3B14E` | Caution text/icons, `dung_som` urgency, SLA warnings |
| `warnSoft` | `--warn-soft` | `#F7EACB` | `#3E3218` | Warning banner & `dung_som` badge background |
| `danger` | `--danger` | `#A63724` | `#F2948A` | Destructive actions, form error text/borders, failed states |
| `dangerSoft` | `--danger-soft` | `#F8E1D5` | `#4A2522` | Error alert container background |
| `okSoft` | `--ok-soft` | `#DCEBDD` | `#21382A` | Alias of `herbSoft` for confirmed/completed states |
| `focus` | `--focus` | `#0F4C6C` | `#7FC8F8` | `:focus-visible` 3px outline (`outline-offset: 3px`) on standard surfaces |
| `focusOnEditorial` | `--focus-on-editorial` | `#8FD8FF` | `#7FC8F8` | `:focus-visible` 3px outline on `editorialSurface` |
| `tray` | `--tray` | `#7A3322` | `#5A2418` | Lacquered wooden `Tray` SVG base fill |
| `trayGrain` | `--tray-grain` | `#8C3D29` | `#662B1D` | Lacquered `Tray` SVG radial gradient highlight |
| `trayRim` | `--tray-rim` | `#C9973D` | `#B8893A` | Brass/gold rim ring on `Tray` SVG |
| `dish` | `--dish` | `#FBFAF5` | `#E9E6DC` | Bát Tràng ceramic bowl/plate fill inside `Tray` SVG |
| `glaze` | `--glaze` | `#2F5597` | `#3E68B0` | Cobalt porcelain rim pattern drawn exclusively on `dish` (`4.41:1` Dark graphic) |
| `rice` | `--rice` | `#FFFFFF` | `#F7F5EE` | Steamed rice center bowl fill inside `Tray` SVG |
| `fresh.tuoi` | `--fresh-tuoi` | `#2D6A3E` | `#7CC68C` | Fresh lot dot + text |
| `fresh.dung_som` | `--fresh-dung-som` | `#8A5A00` | `#E3B14E` | Use-soon lot dot + text |
| `fresh.dung_ngay` | `--fresh-dung-ngay` | `#B3261E` | `#F2948A` | Use-today urgent lot dot + text |
| `fresh.kiem_tra` | `--fresh-kiem-tra` | `#5E6660` | `#C7BBAA` | Check-level required hollow-ring dot + text |
| `fresh.chua_ro` | `--fresh-chua-ro` | `#5E6660` | `#C7BBAA` | Unknown freshness hollow-ring dot + text |
| `freshSoft.*` | `--fresh-soft-*` | `#DCEBDD` / `#F7EACB` / `#F8DCD7` / `#EFE7D8` / `#EFE7D8` | `#21382A` / `#3E3218` / `#4A2522` / `#342D24` / `#342D24` | Corresponding `FreshBadge` pill backgrounds (`tuoi`, `dung_som`, `dung_ngay`, `kiem_tra`, `chua_ro`) |
| `macro.kcal` | `--macro-kcal` | `#A63724` | `#F2948A` | Calorie (`kcal`) metric text & bar fill |
| `macro.protein` | `--macro-protein` | `#2F5597` | `#7BA4E8` | Protein (`Đạm`) metric text & bar fill |
| `macro.carb` | `--macro-carb` | `#8A5A00` | `#E3B14E` | Carbohydrate (`Tinh bột`) metric text & bar fill |
| `macro.fat` | `--macro-fat` | `#7A3B8E` | `#D29CE8` | Lipid/Fat (`Chất béo`) metric text & bar fill |
| `macro.fiber` | `--macro-fiber` | `#2D6A3E` | `#7CC68C` | Dietary fiber (`Chất xơ`) metric text & bar fill |
| `macroSoft.fat` | `--macro-fat-soft` | `#F3E5F8` | `#382342` | Soft pill background for Fat macro (`kcal`/`protein`/`carb`/`fiber` soft fills reuse `accentSoft`/`infoSoft`/`warnSoft`/`herbSoft`) |
| `shadow` | `--shadow` | `rgba(40,30,20,0.10)` | `rgba(0,0,0,0.35)` | Subtle card elevation shadow tint |
| `overlay` | `--overlay` | `rgba(20,24,20,0.50)` | `rgba(0,0,0,0.65)` | Modal/sheet scrim (`>= 50%` opacity to isolate foreground) |

> **Theme-Color Meta Sync (`app/app.json` & `landing/index.html`):** Update `<meta name="theme-color">` dynamically (`#FAF5EB` or `#B63922` Light, `#1C1915` Dark) and align `app/app.json` `backgroundColor` to `#FAF5EB` (splash light `#FAF5EB`, splash dark `#1C1915`, `web.themeColor` `#A63724`).

---

### 2.2 Verified WCAG 2.1 Relative Luminance Contrast Matrix

All contrast ratios below were verified programmatically using an in-memory Python WCAG 2.1 relative luminance script (`L = 0.2126 R + 0.7152 G + 0.0722 B`, `CR = (L1 + 0.05) / (L2 + 0.05)`): **154 total checks (77 Light + 77 Dark, covering all core, semantic, editorial, `storySurface`, `limeSurface`, `fresh.*`, `macro.*`, and Footer `TrayMark` pairs), 0 failures**.

| Token Pair | Light Pair & Ratio | Dark Pair & Ratio | Req Threshold | Result |
|---|---|---|---|---|
| `text` on `bg` | `#2A211B` on `#FAF5EB` -> **14.51:1** | `#F7EFDF` on `#1C1915` -> **15.32:1** | `>= 4.5:1` | **PASS** |
| `text` on `surface` | `#2A211B` on `#FFFCF6` -> **15.40:1** | `#F7EFDF` on `#27221C` -> **13.79:1** | `>= 4.5:1` | **PASS** |
| `text` on `surfaceAlt` | `#2A211B` on `#EFE7D8` -> **12.83:1** | `#F7EFDF` on `#342D24` -> **11.87:1** | `>= 4.5:1` | **PASS** |
| `muted` on `bg` / `surface` / `surfaceAlt` | **6.43** / **6.83** / **5.69:1** | **9.27** / **8.35** / **7.19:1** | `>= 4.5:1` | **PASS** |
| `border` on `bg` / `surface` | `#8A7A68` -> **3.82** / **4.05:1** | `#958773` -> **5.00** / **4.50:1** | `>= 3.0:1` | **PASS** |
| `accent` on `bg` / `surface` / `surfaceAlt` | `#A63724` -> **6.05** / **6.42** / **5.35:1** | `#F2948A` -> **7.82** / **7.04** / **6.06:1** | `>= 4.5:1` | **PASS** |
| `accent` on `accentSoft` | `#A63724` on `#F8E1D5` -> **5.24:1** | `#F2948A` on `#4A2522` -> **5.94:1** | `>= 4.5:1` | **PASS** |
| `onAccent` on `accent` | `#FFFFFF` on `#A63724` -> **6.58:1** | `#2A0E0C` on `#F2948A` -> **8.04:1** | `>= 4.5:1` | **PASS** |
| `text` on `accentSoft` | `#2A211B` on `#F8E1D5` -> **12.56:1** | `#F7EFDF` on `#4A2522` -> **11.63:1** | `>= 4.5:1` | **PASS** |
| `accentDisplay` on `bg` / `surface` *(Graphic; NEVER on Light `surfaceAlt` `2.84:1`)* | `#F3512C` -> **3.21** / **3.40:1** | `#F3512C` -> **5.02** / **4.52:1** | `>= 3.0:1` | **PASS** |
| `accent` on `surfaceAlt` *(Footer `TrayMark`)* | `#A63724` on `#EFE7D8` -> **5.35:1** | `#F2948A` on `#342D24` -> **6.06:1** | `>= 3.0:1` | **PASS** |
| `onLime` on `accentDisplay` / `lime` *(Badge / CTA)* | `#1C1915` -> **5.02:1** / **13.70:1** | `#1C1915` -> **5.02:1** / **13.70:1** | `>= 4.5:1` | **PASS** |
| `editorialSurface` text pairs (`onEditorial` / `#FFFFFF` / `lime`) | `#FAF5EB` **5.37:1**, `#FFFFFF` **5.84:1**, `lime` **4.57:1** on `#B63922` | `onEditorial` **13.76:1**, `accent` **7.02:1**, `lime` **12.31:1** on `#381B14` | `>= 4.5:1` | **PASS** |
| `storySurface` text pairs (`onStory` / `onStoryMuted` / `lime`) | `onStory` **14.51:1**, `onStoryMuted` **12.83:1**, `lime` **12.34:1** on `#2A211B` | `onStory` **13.79:1**, `onStoryMuted` **8.35:1**, `lime` **12.34:1** on `#27221C` | `>= 4.5:1` | **PASS** |
| `limeSurface` & `lime` CTA pairs | `text` **12.34:1**, `herb` **5.07:1** on `#D9EE74`; `onLime` on `lime` **13.70:1** | `text` **11.52:1**, `lime` **10.31:1** on `#2C3318`; `onLime` on `lime` **13.70:1** | `>= 4.5:1` | **PASS** |
| `herb` on `bg` / `surface` / `herbSoft` | **5.96** / **6.32** / **5.23:1** | **8.60** / **7.74** / **6.20:1** | `>= 4.5:1` | **PASS** |
| `text` on `herbSoft` (`okSoft`) | `#2A211B` on `#DCEBDD` -> **12.74:1** | `#F7EFDF` on `#21382A` -> **11.04:1** | `>= 4.5:1` | **PASS** |
| `info` on `bg` / `surface` / `infoSoft` | `#2F5597` -> **6.74** / **7.15** / **6.06:1** | `#7BA4E8` -> **6.94** / **6.25** / **5.47:1** | `>= 4.5:1` | **PASS** |
| `text` on `infoSoft` | `#2A211B` on `#E3EAF7` -> **13.05:1** | `#F7EFDF` on `#1E2D47` -> **12.07:1** | `>= 4.5:1` | **PASS** |
| `warn` on `bg` / `surface` / `warnSoft` | `#8A5A00` -> **5.45** / **5.79** / **4.96:1** | `#E3B14E` -> **8.89** / **8.01** / **6.37:1** | `>= 4.5:1` | **PASS** |
| `text` on `warnSoft` | `#2A211B` on `#F7EACB` -> **13.20:1** | `#F7EFDF` on `#3E3218` -> **10.97:1** | `>= 4.5:1` | **PASS** |
| `danger` on `bg` / `surface` / `dangerSoft` | **6.05** / **6.42** / **5.24:1** | **7.82** / **7.04** / **5.94:1** | `>= 4.5:1` | **PASS** |
| `focus` on `bg` / `surface` | `#0F4C6C` -> **8.51** / **9.03:1** | `#7FC8F8` -> **9.61** / **8.65:1** | `>= 3.0:1` | **PASS** |
| `focusOnEditorial` on `editorialSurface` | `#8FD8FF` on `#B63922` -> **3.73:1** | `#7FC8F8` on `#381B14` -> **8.63:1** | `>= 3.0:1` | **PASS** |
| `glaze` on `dish` / `trayRim` on `tray` | **7.01:1** / **3.43:1** | **4.41:1** / **3.93:1** | `>= 3.0:1` | **PASS** |
| `fresh.tuoi` on `freshSoft.tuoi` / `bg` | **5.23:1** / **5.96:1** | **6.20:1** / **8.60:1** | `>= 4.5:1` | **PASS** |
| `fresh.dung_som` on `freshSoft.dung_som` / `bg` | **4.96:1** / **5.45:1** | **6.37:1** / **8.89:1** | `>= 4.5:1` | **PASS** |
| `fresh.dung_ngay` on `freshSoft` / `bg` / `surface` | **5.05** / **6.02** / **6.38:1** | **5.94** / **7.82** / **7.04:1** | `>= 4.5:1` | **PASS** |
| `fresh.kiem_tra` / `chua_ro` on `freshSoft` / `bg` | **4.82:1** / **5.45:1** | **7.19:1** / **9.27:1** | `>= 4.5:1` | **PASS** |
| `macro.kcal` on `bg` / `surface` / `surfaceAlt` | `#A63724` -> **6.05** / **6.42** / **5.35:1** | `#F2948A` -> **7.82** / **7.04** / **6.06:1** | `>= 4.5:1` | **PASS** |
| `macro.protein` on `bg` / `surface` / `surfaceAlt` | `#2F5597` -> **6.74** / **7.15** / **5.96:1** | `#7BA4E8` -> **6.94** / **6.25** / **5.38:1** | `>= 4.5:1` | **PASS** |
| `macro.carb` on `bg` / `surface` / `surfaceAlt` | `#8A5A00` -> **5.45** / **5.79** / **4.82:1** | `#E3B14E` -> **8.89** / **8.01** / **6.89:1** | `>= 4.5:1` | **PASS** |
| `macro.fat` on `bg` / `surface` / `surfaceAlt` / `macroSoft.fat` | `#7A3B8E` -> **6.80** / **7.21** / **6.01** / **6.11:1** | `#D29CE8` -> **8.06** / **7.25** / **6.25** / **6.50:1** | `>= 4.5:1` | **PASS** |
| `text` on `macroSoft.fat` | `#2A211B` on `#F3E5F8` -> **13.05:1** | `#F7EFDF` on `#382342` -> **12.35:1** | `>= 4.5:1` | **PASS** |
| `macro.fiber` on `bg` / `surface` / `surfaceAlt` | `#2D6A3E` -> **5.96** / **6.32** / **5.27:1** | `#7CC68C` -> **8.60** / **7.74** / **6.67:1** | `>= 4.5:1` | **PASS** |

---

## 3. Typography System (`Be Vietnam Pro`)

### 3.1 Font Family & Weight Loading
- **Primary Family:** `Be Vietnam Pro` across both platforms (`BeVietnamPro_{400Regular,500Medium,600SemiBold,700Bold}` in `app/`; local `.woff2` files in `landing/fonts/` — M4 MUST bundle `be-vietnam-pro-500Medium.woff2` alongside 400/600/700 in `landing/` with `font-display: swap`).
- **Technical Monospace (Optional, Admin/Telemetry Only):** System `ui-monospace` / `JetBrains Mono` strictly for SHA-256 prefixes, `request_id`, and `model_version_id` in `quan-tri` and `landing/` technical metrics. Never for Vietnamese prose.
- **Numeric Precision (`tabular-nums`):** Every calorie counter, macro gram readout, countdown timer, percentage bar, pantry weight (`fmtG`), and admin metric MUST set `font-variant-numeric: tabular-nums` (CSS) / `fontVariant: ['tabular-nums']` (React Native).

### 3.2 Cross-Platform Type Scale

| Role (`VARIANTS`) | Web (`px` / `rem`) | Mobile App (`sp`) | Weight | Line Height | Tracking | Usage & Vietnamese Diacritic Rule |
|---|---|---|---|---|---|---|
| `display` *(Hero `h1`)* | `clamp(48px, 6.5vw, 112px)` | — | `700` | `1.02` | `-0.06em` | `landing/` Hero & Invitation display only; clear vertical padding so stacked diacritics (*Đ, ệ, ơ*) never clip |
| `huge` | `36px` (`2.25rem`) | `36sp` | `700` | `44px` (`1.22`) | `-0.8px` | Editorial feature titles (`FoodStory`), active cooking step highlight (`28–36sp`) |
| `h1` | `28px`–`32px` (`1.75–2rem`) | `25sp` (`size.xl`) | `700` | `34–40px` (`1.28`) | `-0.5px` | Screen / page title (exactly one `h1` per view; sequential `h1 -> h2 -> h3`) |
| `h2` | `22px`–`26px` (`1.375–1.625rem`) | `20sp` (`size.lg`) | `700` | `28–34px` (`1.32`) | `-0.3px` | Section headings, sheet titles, card group headers |
| `title` (`h3`) | `18px` (`1.125rem`) | `17sp` (`size.md`) | `600` | `25px` (`1.40`) | `-0.1px` | Card titles, dish names, dialog headers |
| `body` | `16px` (`1rem`) | `15sp` (`size.sm`) | `400` | `24px` (`1.50`+) | `0` | Primary prose, recipe steps, FAQ answers (`line-height >= 1.5`, max measure `<= 75ch` / `68ch` prose) |
| `label` | `14px` (`0.875rem`) | `15sp` (`size.sm`) | `600` | `21px` (`1.50`) | `0` | Form labels, button text, filter chips, nav items (`min 14px` web input labels prevent iOS zoom when inputs stay `>= 16px`) |
| `small` / `caption` | `12px`–`13px` (`0.75–0.8125rem`) | `13sp` (`size.xs`) | `500` | `19px` (`1.50`) | `0` | Metadata, helper text, chart axis labels, table captions. **Body/metadata floor: `13sp` mobile (`12px` web)** — eliminates `landing/style.css`'s `7px–10px` micro-text. |
| `eyebrow` / `tabLabel` | `12px` (`0.75rem`) | `12sp` *(explicitly permitted for compact `eyebrow` & 5-tab labels)* | `600` | `18px` (`1.50`) | `+0.08em` (`0` on tabs) | Uppercase section kickers (`01 / MỞ VỊ GIÁC`) & `<Tabs>` bar labels (`maxFontSizeMultiplier: 1.2` so `64px`-wide tabs at `320px` never clip while still respecting font scaling). |

> **Heading Hierarchy, `ui.tsx` Sync & Readability Guardrails:** Enforce strict sequential `h1 -> h2 -> h3 -> h4` (never skip levels); M4 MUST update `app/src/components/ui.tsx:30–38` `VARIANTS` line-heights (`body: 24`, `title: 25`, `h2: 28`, `h1: 34`), add `eyebrow` + `tabular-nums`, and emit `aria-level` (`1|2|3`) on `T` headings (`accessibilityRole="header"`). Clamp prose containers to `max-width: 68ch` (`<= 75ch`); support `allowFontScaling={true}` (do not disable Dynamic Type) and avoid `numberOfLines={1}` truncation on primary Vietnamese labels/buttons.

---

## 4. Spacing, Layout Grid, Radius, Elevation & Z-Index

### 4.1 Spacing Scale (`4dp` / `8dp` Rhythm)
`space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }`
- **Micro gaps:** `4px` (`xs`) badge icon-to-text, `8px` (`sm`) minimum gap between interactive touch targets and chip rows.
- **Component padding:** `12px` (`md`) inputs/chips, `16px` (`lg`) standard card padding & mobile gutter, `24px` (`xl`) desktop gutter & card group separation, `32px` (`xxl`) section/form blocks.
- **Section rhythm (`landing/`):** `48px` (`3rem`) mobile / `80px–96px` desktop vertical section padding.

### 4.2 Responsive Breakpoints & Container Widths
- **Mobile (`< 768px`):** Verified at `320px`, `375px`, `390px`. Single-column fluid stack (`paddingHorizontal: 16`), sticky 5-tab bottom bar (`app/`), mobile drawer menu (`landing/`).
- **Tablet (`768px – 1023px`):** Verified at `768px`. `24px` gutter (`landing/`: `width: calc(100% - 48px)`); `app/`: deterministic `72px` compact icon rail (hiding mobile bottom tabs at `>= 768px`), 2-column card grids, `maxWidth: 920px`.
- **Desktop (`>= 1024px`):** Verified at `1280px` & `1440px`.
  - `app/`: Persistent `248px` left sidebar rail + fluid workspace canvas up to `maxWidth: 1240px` (replacing `ui.tsx:552` `560px` bottleneck; focused forms like Auth/Onboarding remain capped at `420px–640px` intentionally).
  - `landing/`: `width: min(1320px, calc(100% - 96px))`.

### 4.3 Border Radius Scale
- `radius.sm = 10px`: Text inputs, search fields, table cells, small status pills.
- `radius.md = 14px`: List rows, ingredient chips, secondary panels, code/CLI boxes.
- `radius.lg = 22px` *(24px on `landing/` hero photography)*: Hero cards, tray containers, bottom sheets, photo frames.
- `radius.pill = 999px`: Primary/secondary buttons, filter chips, `FreshBadge`, active nav indicator.

### 4.4 Elevation & Shadow Tokens (Web + Android Native)
To ensure parity between Web CSS and React Native Android (`elevation`), pair every shadow with a `1px` `hairline` border:

| Level | Web `box-shadow` | Android `elevation` | Usage |
|---|---|---|---|
| `elev.0` (Flat) | `none` | `0` | Recessed `surfaceAlt` wells, table rows, flat banners |
| `elev.1` (Card) | `0 1px 2px var(--shadow), 0 6px 16px -10px var(--shadow)` | `2` | Standard `Card`, recipe cards, pantry lots |
| `elev.2` (Floating / Nav) | `0 4px 12px var(--shadow), 0 12px 24px -12px var(--shadow)` | `4` | Active primary buttons, floating tray dish tags, sticky tab bar, popover menus |
| `elev.3` (Modal / Sheet) | `0 16px 40px var(--shadow)` | `8` | Bottom `Sheet`, confirmation dialogs, mobile nav drawer |

### 4.5 Z-Index Scale
`0` (base content) -> `10` (sticky header/tab bar/rail) -> `20` (floating tray tags, scan bbox overlays) -> `40` (mobile nav drawer) -> `100` (modal/sheet + scrim) -> `1000` (toast notifications, skip-to-main link).

---

## 5. Brand Mark (`TrayMark`) & Asset Governance

### 5.1 Theme-Aware `TrayMark` & `brand-mark.svg` Rules
Canonical geometry (`viewBox="0 0 64 64"`):
- Bowl: `M9 30h46c-1 14-11 24-23 24S10 44 9 30Z`
- Base: `M18 59h28` (`strokeWidth="5"`, `strokeLinecap="round"`)
- Steam: `M25 8c-9 8 7 9-1 17M40 5c-9 8 7 10-1 17` (`strokeWidth="5"`, `strokeLinecap="round"`)
- Highlight: `M16 36h32` (`strokeWidth="3"`, `strokeLinecap="round"`)

**Platform Binding Rules (M4 Implementation):**
1. **`landing/` Header (`--bg`) vs. Footer (`--surface-alt`):** BOTH MUST render inline `<svg aria-hidden="true">` (never `<img src="brand-mark.svg">`) with `stroke="currentColor"` (`var(--text)`) on base & steam strokes and `stroke="var(--surface)"` on the rim highlight.
   - **Header (`--bg`):** Bowl uses `fill="var(--accent-display)"` (`#F3512C`, `3.21:1` Light / `5.02:1` Dark >= `3.0:1` WCAG 1.4.11).
   - **Footer (`--surface-alt`):** Bowl MUST use `fill="var(--accent)"` (`#A63724` Light = `5.35:1` on `--surface-alt` `#EFE7D8`; `#F2948A` Dark = `6.06:1` on `--surface-alt` `#342D24`). **`accentDisplay` (`#F3512C`) MUST NOT be placed on Light `surfaceAlt` (`2.84:1 < 3.0:1` WCAG 1.4.11 failure).**
2. **`app/src/components/Brand.tsx` (`TrayMark`):** Use `c.accentDisplay` (`#F3512C`) on `c.bg` / `c.surface` (`3.21:1` / `3.40:1` Light; `5.02:1` / `4.52:1` Dark — never on Light `c.surfaceAlt`), `c.text` for base & steam strokes, and `c.surface` for rim highlight.
3. **`app/assets/brand/*` & `landing/img/brand-mark.svg`:** Update static `<svg>` background/highlight fills from `#fff9ed` to `#FAF5EB` and add `@media (prefers-color-scheme: dark)` stroke fallback `#F7EFDF` inside `icon.svg` when used as a favicon.

### 5.2 Photography & Illustration Assets
- **Reuse `landing/img/{bun-dau,fresh-bowl,pho,vietnamese-table}.jpg`** and `app/assets/food/vietnamese-table.webp` with explicit `width`/`height` or `aspect-ratio` to keep `CLS < 0.1`.
- **Promote `landing/img/{kho,mam,nau,quet}-{light,dark}.webp`** from unreferenced assets into the theme-aware **AI & App Showcase** on `landing/` (dynamically displaying `*-light.webp` or `*-dark.webp` to match the active `[data-theme]`).
- **Retire orphaned v0.1.0 captures** in `landing/docs/landing-*.png` during M4 cleanup.

---

## 6. Zero Structural Emojis & SVG-Only Iconography

### 6.1 Iconography Rules
- **Zero Emojis:** No Unicode color emojis (`U+1F000–U+1FAFF`) and no raw Unicode punctuation symbols (`✓`, `×`, `−`, `+`, `→`, `←`, `↗`, `‹`, `›`, `↓`, `↑`) as structural UI icons.
- **Unified Stroke Style:** `24×24` `viewBox`, `strokeWidth={1.8}`, `strokeLinecap="round"`, `strokeLinejoin="round"`, `fill="none"`, colored via `currentColor` / `c.*` tokens.
- **Standard Icon Sizes:** `icon-sm = 16px` (inline chip/badge), `icon-md = 20px–22px` (buttons, tab bar, header actions), `icon-lg = 24px` (empty states, feature cards).

### 6.2 Mandatory Structural Glyph -> SVG Migration Inventory (26 Occurrences / 11 Symbols)

Every structural Unicode text glyph audited across `app/src/` and `landing/index.html` (26 occurrences across 11 symbol forms) MUST be replaced in M4 with named `<Icon name="..." />` / inline `<svg>` components:

| Raw Glyph | Existing Locations (Exact File & Line) | Replacement SVG Icon Name | Semantic Role & A11y |
|---|---|---|---|
| `✓` | `app/src/components/ui.tsx:220, 298`; `app/src/app/(tabs)/mam.tsx:244`; `app/src/app/nau/[id].tsx:190` | `check` | Selected `Chip`, `Checkbox` tick, added status, completed cooking step (`aria-hidden` inside labeled control) |
| `×` | `app/src/components/ui.tsx:519`; `app/src/app/quet/[id].tsx:122` | `close` / clean unit text (`"đơn vị"` or `"SL:"` for count multiplier, `close` SVG for Sheet dismiss) | `Sheet` close button (`accessibilityLabel="Đóng"`), scan multiplier clarity |
| `−` / `+` | `app/src/components/ui.tsx:379, 383`; `app/src/app/cai-dat.tsx:56` | `minus` / `plus` | `Stepper` decrement/increment (`>=48dp`), `cai-dat` accordion expand/collapse |
| `→` | `app/src/app/(tabs)/bep.tsx:185`; `app/src/app/(auth)/dang-nhap.tsx:62` | `arrow-right` | Journal / navigation action arrow & `"Đăng nhập"` submit arrow |
| `←` | `app/src/components/AuthShell.tsx:37` | `arrow-left` | Back to landing / previous step link |
| `↗` | `app/src/components/AuthShell.tsx:27`; `landing/index.html:19, 25, 39, 40, 42, 43` | `arrow-up-right` | Primary CTA directional arrow |
| `‹` / `›` | `app/src/app/(tabs)/nhat-ky.tsx:45, 47` | `chevron-left` / `chevron-right` | ISO week prev/next stepper |
| `↓` / `↑` | `landing/index.html:28, 40, 43, 46` | `arrow-down` / `arrow-up` | Scroll cue, simulator cue, APK download icon, footer back-to-top (`aria-label="Về đầu trang"`) |

**Additional SVG Icons Required for M4 Modules (`domain.tsx` / `lucide-react-native` if approved by `scan_dependencies` or self-contained `react-native-svg` paths):**
`compass` (`Khám phá`), `shield` (`Quản trị`), `sliders` (filters), `sun` / `moon` (theme switcher), `search`, `trash`, `edit`, `eye` / `eye-off` (password toggle), `flame` (cooking/kcal), `sparkles` (ML/AI insight), `menu` (mobile nav drawer), `alert-triangle` (error/warning banner).

---

## 7. Touch Targets, Forms, Accessibility & Motion

### 7.1 Touch & Pointer Discipline
- **Minimum Target Area:** `>= 48×48dp` (`TOUCH = 48`) in `app/` native & web; `>= 44×44px` on `landing/` buttons, nav links, `<summary>`, and footer anchors. Use `hitSlop` on compact inline icon triggers.
- **Minimum Spacing:** `>= 8px` (`space.sm`) between any two interactive targets (tabs, filter pills, stepper buttons, survey rating scale `1..5`).
- **Tap-Primary Interaction:** Every action reachable by click/tap and keyboard (`Enter`/`Space`), never hover-only.

### 7.2 Form & State Accessibility
- **Visible Labels Always:** Every `<input>` / `<TextInput>` MUST render a visible `<label for="...">` (Web) or `<T v="label">` (App) above the field — **zero placeholder-only inputs**.
- **Accessible Icon Controls:** Every icon-only button (`Sheet` close, back-to-top, theme toggle, password eye toggle, week chevrons) MUST have an explicit Vietnamese `aria-label` / `accessibilityLabel`.
- **Error & Feedback Live Regions:** Validation errors appear directly below the offending field with `role="alert"` / `accessibilityLiveRegion="polite"`. Async submissions disable buttons and show loading feedback (`ActivityIndicator` / spinner) before resolving to success or error.
- **Color Never Alone (WCAG 1.4.1):** Freshness uses dot shape (solid vs hollow ring) + color + label; charts pair bars with direct numeric labels + accessible text/table fallback; Gantt uses height + bar pattern + text legend.

### 7.3 Motion & Reduced-Motion Policy
- **Durations:**
  - `motion.fast = 150ms`: Button press scale (`0.97–0.98`), chip toggle, focus ring.
  - `motion.base = 220ms`: Sheet fade/slide, accordion toggle, card hover elevation.
  - `motion.slow = 280ms`: Scroll-reveal entrance (`translateY(16px -> 0)`, `opacity(0 -> 1)`), max `<= 300ms` for interactive UI.
- **Easing:** `cubic-bezier(0.2, 0.7, 0.2, 1)` (Web) / `Easing.bezier(0.2, 0.7, 0.2, 1)` (RN).
- **GPU-Only Properties:** Animate strictly `transform` and `opacity` (never `width`, `height`, `top`, `left`). Max 1–2 animated elements per view; infinite loops reserved strictly for active loading spinners.
- **Mandatory Reduced Motion:** `@media (prefers-reduced-motion: reduce)` in CSS and `AccessibilityInfo.isReduceMotionEnabled()` in RN MUST disable scroll-reveals, scale bounces, and transitions immediately.
