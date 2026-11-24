# Page Override: `landing.md` (`landing/index.html`, `style.css`, `story.js`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/` and `/gioi-thieu/` (Public, no authentication)

## Surface & Color Overrides
- **Header (`--bg`) vs. Footer (`--surface-alt`):** Inline theme-aware `<svg>` `TrayMark` uses `fill="var(--accent-display)"` on Header `--bg` (`3.21:1` Light / `5.02:1` Dark) and **`fill="var(--accent)"`** on Footer `--surface-alt` (`5.35:1` Light / `6.06:1` Dark — never `--accent-display` on Light `--surface-alt`), with `currentColor` base/steam strokes, Light/Dark/System theme switcher button (`aria-label`, `>=44x44px`), and `<768px` accessible mobile drawer toggle.
- **Hero & Invitation Bands (`editorialSurface`):** Uses `--editorial-surface` (`#B63922` Light / `#381B14` Dark) instead of raw `#f3512c`. Primary text uses `var(--on-editorial)` (`#FAF5EB` Light / `#F7EFDF` Dark); dot accents use `--lime` (`#D9EE74`, `4.57:1` Light / `12.31:1` Dark); focus rings use `--focus-on-editorial` (`#8FD8FF` Light / `#7FC8F8` Dark).
- **Kitchen / Simulator Section (`#bo-gia-lap`, `limeSurface`):** Replaces legacy `#can-bep` ID; uses `--lime-surface` (`#D9EE74` Light / `#2C3318` Dark). Subhead accent uses `--herb` (`#2D6A3E` Light `5.07:1`) or `--lime` (`#D9EE74` Dark `10.31:1`).
- **Story & Journal Preview (`#nhat-ky`, `storySurface`):** Uses `--story-surface` (`#2A211B` Light / `#27221C` Dark, never legacy `--ink`/`#26291E`) paired with `--on-story` / `--on-story-muted`; embedded Weekly Kcal & Macro Preview Card MUST sit inside a `var(--surface)` card container so `--macro-*` bars stay `>= 5.79:1`.
- **AI Showcase Mockups (`#cong-nghe-ai`):** Dynamically swap `landing/img/{quet,kho,mam,nau}-light.webp` and `*-dark.webp` to match active `[data-theme]`.

## Typography & Layout Overrides
- Eliminate all `7px–10px` micro-text: raise `.eyebrow`, `figcaption`, `.hero-footnote`, `.demo-top`, and `.result-label` to `>= 12px` (`0.75rem`) with `line-height >= 1.5`. Set `font-size: 16px` on `#landing-recipe-search` to prevent iOS Safari auto-zoom.
- Container: `width: min(1320px, calc(100% - 96px))` on desktop (`>= 1024px`), `calc(100% - 48px)` on tablet (`768–1023px`), `calc(100% - 32px)` on mobile (`< 768px`, verified down to `320px`).
- Responsive Wrapping (`320px` Safe): Apply `flex-wrap: wrap; gap: var(--space-sm);` to `.ingredient-options`, constraint toggles, KB recipe filter pills, and AI `role="tablist"` tabs; keep `.recipe-demo { transform: none; }` below `768px` to guarantee `scrollWidth <= innerWidth`.

## Interactive & State Rules
- Simulator buttons (`[data-ingredient]` / constraint toggles) use `border: 1.5px solid var(--border)` (never `--hairline` alone) and update live region `aria-live="polite"`.
- Bundle curated KB recipe showcase data inline inside `landing/story.js` (or `<script id="kb-snapshot" type="application/json">`) so `landing/nginx-snippet.conf` never returns `404` on external `.json` fetches.
- APK download `#android-download` initializes with `aria-disabled="true"` (and `href` omitted/removed) during initial `HEAD` check, enables `href` ONLY on `200 OK`, keeps `aria-disabled="true"` on `404` or network error, and polls every 30s (`"Bản Android mới đang được cập nhật…"`).
