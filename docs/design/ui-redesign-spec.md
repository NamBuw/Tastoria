# Tastoria Website & Cross-Platform App UI Redesign Specification (`ui-redesign-spec.md`)

**Milestone:** M2 — Complete Pre-Implementation UI/UX Specification (Design-First)  
**Design Authority:** `docs/design/design-system/MASTER.md` + `docs/design/design-system/pages/*.md`  
**API Authority:** `docs/api/openapi-v1.yaml` (70 operations) + M3 Planned F8/F9 additions  
**Scope:** Implementation-ready architecture, layouts, responsive wireframes, component specs, interactive state machines, offline/outbox contracts, and `loading | empty | error | success` states for Website (`landing/`) and Mobile/Web App (`app/`).

---

## PART A — Website (`landing/` at `/` and `/gioi-thieu/`)

### A.1 Global Architecture, Theme Switcher & Responsive Grid
- **Theme System (`light | dark | system`):**
  - `<html>` carries `data-theme="light" | "dark"` initialized by an inline head script (zero FOUC) reading `localStorage.getItem('tastoria.theme')` with fallback to `window.matchMedia('(prefers-color-scheme: dark)')`.
  - `<meta name="theme-color">` dynamically updates between `editorialSurface` (`#B63922` Light) / `bg` (`#FAF5EB` Light) and `bg` (`#1C1915` Dark).
  - Header exposes a `>= 44×44px` theme switcher button (`sun` / `moon` SVG, `aria-label="Chuyển giao diện Sáng/Tối"`, `aria-pressed`) updating `[data-theme]`, persisting choice, and hot-swapping theme-paired app screenshots (`*-light.webp` <-> `*-dark.webp`).
- **Breakpoints & Container Rules:**
  - **Desktop (`1440px` / `>= 1024px`):** `width: min(1320px, calc(100% - 96px))`, multi-column editorial grids, inline desktop nav.
  - **Tablet (`768px` / `768–1023px`):** `width: calc(100% - 48px)`, 2-column grids on Hero & Kitchen Simulator, compact horizontal header nav.
  - **Mobile (`390px` / `< 768px`, verified down to `320px`):** `width: calc(100% - 32px)` (`< 768px`), single-column stack, accessible slide-down/drawer menu (`aria-expanded`, `aria-controls="mobile-nav"`, `Escape` closes, focus trapped/returned to menu toggle), horizontal scroll-snap on discovery cards, `transform: none` on `.recipe-demo` so `scrollWidth <= innerWidth` at `320px`.
- **Asset Hygiene & Reuse:**
  - **Keep & Reuse:** `bun-dau.jpg`, `fresh-bowl.jpg`, `pho.jpg`, `vietnamese-table.jpg` (flat photography only, explicit `width`/`height` + `aspect-ratio` to keep `CLS < 0.1`), plus all 8 **`landing/img/{kho,mam,nau,quet}-{light,dark}.webp`** screenshots inside Section (e) AI & App Showcase.
  - **Fix:** Replace `<img src="/gioi-thieu/img/brand-mark.svg">` with inline theme-aware `<svg>` `TrayMark` (`fill="var(--accent-display)"` on Header `--bg`, `fill="var(--accent)"` on Footer `--surface-alt` so Light contrast is `5.35:1`, `currentColor` strokes + `var(--surface)` rim); update `landing/img/brand-mark.svg` / `icon.svg` to `bg` (`#FAF5EB`) + `@media (prefers-color-scheme: dark)` strokes; bundle `be-vietnam-pro-500Medium.woff2`; retire orphaned `landing/docs/landing-*.png` in M4.

### A.2 Desktop (`1440px`) vs Mobile (`390px`) Section Wireframe

```text
DESKTOP (1440px)                                   MOBILE (390px)
+----------------------------------------------+   +------------------------------+
| (a) [TrayMark] tastoria. | Nav (5) | [Theme] |   | (a) [TrayMark] tastoria. [T][M]|
|                          | [Đăng nhập][ĐK ↗] |   |     (Menu drawer on tap)     |
+----------------------------------------------+   +------------------------------+
| (b) HERO (var(--editorial-surface))          |   | (b) HERO                     |
|   Taste. and write   |  [bun-dau.jpg flat]   |   |   Taste. and write           |
|   your story.        |  CHUYỆN NGON #01      |   |   your story.                |
|   [Khám phá bếp ↗]   |                       |   |   [Khám phá bếp ↗]           |
|   [Khảo sát] [APK ↓] |                       |   |   [bun-dau.jpg flat]         |
+----------------------------------------------+   +------------------------------+
| (c) LIVE PANTRY-TO-TRAY SIMULATOR (limeSurf) |   | (c) SIMULATOR (stacked)      |
|   Steps 01-03  |  Multi-Ingredient Picker    |   |   Steps 01-03                |
|   Time/Servings|  [Tray SVG: Mặn/Rau/Canh]   |   |   Multi-Ingredient Picker    |
|                |  Kcal + Urgency + /bep CTA  |   |   [Tray SVG + Dishes]        |
+----------------------------------------------+   +------------------------------+
| (d) KB RECIPE SHOWCASE (filterable 3-col)    |   | (d) KB RECIPES (scroll/1col) |
|   [Tất cả][Mặn][Rau][Canh][<=20p]            |   |   Filter chips               |
|   [Card 1]     [Card 2]     [Card 3]         |   |   [Card 1] -> [Card 2] ...   |
+----------------------------------------------+   +------------------------------+
| (e) AI & ML ARCHITECTURE SHOWCASE (4 tabs)   |   | (e) AI SHOWCASE (tabs+stack) |
|   [1.YOLO][2.Freshness][3.RecSys+Vec][4.CPSAT|   |   4 Pill Tabs                |
|   Metrics & Pipeline  | [quet/mam/nau.webp]  |   |   Metrics + App Screenshot   |
+----------------------------------------------+   +------------------------------+
| (f) STORY & JOURNAL PREVIEW (50/50 split)    |   | (f) STORY & JOURNAL (stack)  |
|   [vietnamese-table.jpg] | Weekly Kcal Card  |   |   [Photo] -> Copy + /nhat-ky |
+----------------------------------------------+   +------------------------------+
| (g) TASTE SURVEY CTA + APK & WEB LAUNCHER    |   | (g) SURVEY + APK LAUNCHER    |
|   [Khảo sát gu ↗] [Mở Web /bep] [APK HEAD]   |   |   Stacked 48px+ CTAs         |
|   FAQ <details> 2-col                        |   |   FAQ <details> 1-col        |
+----------------------------------------------+   +------------------------------+
| (h) FOOTER: Inline TrayMark | Links | Credits|   | (h) FOOTER (compact stacked) |
+----------------------------------------------+   +------------------------------+
```

### A.3 Section-by-Section Component & Interaction Specs

#### (a) Header & Light/Dark Theme Switcher + Mobile Menu
- **Elements:** Skip-to-main link (`.skip`, `z-index: 1000`), inline `TrayMark` (`fill="var(--accent-display)"` on `--bg`) + `tastoria.` wordmark (`/`), 5 anchor links (`#bo-gia-lap` *Thử lên mâm* replacing legacy `#can-bep`, `#mon-viet` *Món Việt* replacing legacy `#kham-pha`, `#cong-nghe-ai` *Công nghệ AI*, `#nhat-ky` *Chuyện bếp*, `#tai-ve` *Tải về*), Theme Toggle (`light -> dark -> system` or direct Light/Dark toggle with `sun`/`moon` SVG), Auth CTAs (`Đăng nhập` -> `/dang-nhap`, `Đăng ký` -> `/dang-ky` with `arrow-up-right` SVG).
- **Tablet (`768px`):** Condense nav gap (`16px`) and hide secondary non-essential labels if needed while keeping all 5 nav links + auth + theme toggle on <=2 clean rows (`>= 44px` hit height).
- **Mobile (`< 768px`):** Header shows Brand Mark, Theme Toggle (`44×44px`), and Menu Toggle (`menu` / `close` SVG, `44×44px`, `aria-expanded`). Expanding opens an accessible drawer (`surface` bg, `hairline` border) containing the 5 section links + `Đăng nhập` + `Đăng ký` (`>= 48px` row height each).

#### (b) Hero (`#hero`, `editorialSurface`)
- **Surface:** `var(--editorial-surface)`. Headline `"Taste. and write your story."` uses `var(--on-editorial)` with `var(--lime)` period dots (`4.57:1` Light / `12.31:1` Dark).
- **CTAs:** Primary lime pill `"Khám phá căn bếp của bạn"` -> `/bep` (`var(--on-lime)` text on `var(--lime)` = `13.70:1`, `arrow-up-right` SVG); secondary outline link `"Làm khảo sát gu món ăn"` -> `/khao-sat?kenh=link` (`focusOnEditorial` outline).
- **Visual:** Flat `bun-dau.jpg` (`aspect-ratio: 1 / 1.1` desktop, `1.15` mobile, `border-radius: 24px`) with caption `CHUYỆN NGON #01 · Mâm nhà mình` (`>= 12px`, zero sub-12px micro-text).

#### (c) Live Pantry-to-Tray Interactive Simulator (`#bo-gia-lap`, `limeSurface`, replacing legacy `#can-bep`)
- **Purpose:** Upgrades `story.js:3–16`'s 3-button static demo into a genuine multi-ingredient Vietnamese meal-tray simulator running deterministically client-side on a curated KB subset bundled inline (no auth required).
- **Left Column:** 3 numbered workflow steps (`01 Nhìn vào tủ lạnh`, `02 Gom thành một mâm`, `03 Nấu và thưởng thức`) + direct link `/bep`.
- **Right Column (`.recipe-demo` elevated card on `--surface`):**
  - **Multi-Select Pantry Ingredient Chips (`aria-pressed`):** 8 common Vietnamese market staples with urgency tags (`Trứng gà · dùng ngay`, `Đậu phụ · nên dùng sớm`, `Thịt ba chỉ · tươi`, `Cá thu/cá lóc · dùng ngay`, `Rau muống · dùng ngay`, `Cải ngọt · nên dùng sớm`, `Cà chua · tươi`, `Bí xanh · tươi`). `.ingredient-options` MUST apply `display: flex; flex-wrap: wrap; gap: var(--space-sm);` (`8px` gap) so multi-word chips wrap cleanly without overflowing `320px`.
  - **Constraint Controls:** Servings toggle (`1`, `2`, `4 người`) + Max time (`30p`, `45p`, `60p`) in wrapping flex rows (`flex-wrap: wrap`).
  - **Live Tray Output (`aria-live="polite"`):**
    - Top-down mini `Tray` SVG preview (3 dishes `Mặn` / `Rau` / `Canh` + center `Cơm X bát`, clamped `<= 100%` container width on `320px`).
    - Dish slots with `tabular-nums` total cook time, estimated `kcal/người`, urgency-saved count, and Ranker-style Vietnamese rationale (`reason_vi`).
    - Explicit disclaimer (`>= 12px`): *"Mô phỏng minh hoạ trên danh mục món Việt mẫu — đăng nhập để ghép mâm theo tủ lạnh thật của bạn."*
  - **States:** `0` ingredients selected -> helpful prompt (`"Chọn ít nhất 1 nguyên liệu để xem gợi ý mâm"`); infeasible combination -> displays closest valid tray + missing ingredient chip (`"Thiếu hành lá / cà chua để đủ mâm 3 món"`).

#### (d) KB Recipe Showcase (`#mon-viet`, `--bg`, replacing legacy `#kham-pha`)
- **Purpose:** Combines the 3 authentic editorial photo cards (`fresh-bowl.jpg`, `vietnamese-table.jpg`, `pho.jpg`) with a filterable **Vietnamese Knowledge-Base (KB) Recipe Showcase** sourced from a curated static JSON snapshot **bundled inline inside `landing/story.js` (or `<script id="kb-snapshot" type="application/json">` in `landing/index.html`)** — preventing `404` under `landing/nginx-snippet.conf:24–58` (which allows only `fonts/`, `img/`, `style.css`, `story.js`, `index.html`; if an external `.json` endpoint is ever added later, both `landing/nginx-snippet.conf` and `deploy/nginx/tastoria.conf` MUST be updated in lockstep).
- **Controls:** Slot filter pills (`Tất cả`, `Mặn`, `Rau`, `Canh`) + quick tag filter (`Dưới 20 phút`, `Ít dầu mỡ`, `Bữa cơm gia đình`) rendered with `flex-wrap: wrap; gap: var(--space-sm);` + text search input `#landing-recipe-search` (with visible `<label for="landing-recipe-search">` and **`font-size: 16px`** to prevent iOS Safari auto-zoom).
- **Grid:** `3 cols` (`1440px`), `2 cols` (`768px`), horizontal scroll-snap or `1-col` card stack (`390px`). Each card shows slot badge, Vietnamese name (`h3`), `method_code`, `total_minutes`, `kcal_per_serving` (`tabular-nums`), and macro chips (`Đạm / Bột / Béo`).
- **States:** Filter returns `0` matches -> Empty card with `"Xoá bộ lọc"` button; No-JS fallback -> renders top 6 static curated KB cards cleanly in HTML.

#### (e) AI Vision, Freshness Calibration, RecSys + pgvector & CP-SAT Architecture Showcase (`#cong-nghe-ai`, `--surface-alt`)
- **Purpose:** Explains Tastoria's 4 ML & Operations Research pillars transparently using verified architecture diagrams & metrics (zero fabricated numbers) paired dynamically with the **theme-matched app screenshots** in `landing/img/`:
  1. **Tab 1 — CV Ingredient Detection (`quet-{light,dark}.webp`):** YOLO multi-class ingredient detection & counting (`13 -> 30` Vietnamese pantry classes), bounding-box review + human-in-the-loop correction.
  2. **Tab 2 — Produce Freshness & Calibration (`kho-{light,dark}.webp`):** MobileNetV3/EfficientNet + Temperature/Platt scaling -> calibrated `p_tuoi / p_dung_som / p_dung_ngay / p_kiem_tra` mapped to market-day urgency sorting.
  3. **Tab 3 — Taste Ranker & pgvector Substitutes (`mam-{light,dark}.webp`):** Personalized meal ranking (`Ranker`) + hybrid `lookup` + `pgvector` semantic/nutritional ingredient substitution + Pareto `(α, β, γ)` tray composition.
  4. **Tab 4 — Parallel Burner CP-SAT Scheduler (`nau-{light,dark}.webp`):** OR-Tools CP-SAT solver minimizing makespan across `1–4` burners + rice cooker, interleaving active & passive steps for target `serve_at`.
- **Interactive Behavior:** `role="tablist"` with `flex-wrap: wrap; gap: var(--space-sm);` and 4 accessible `role="tab"` buttons (`>= 44px`, keyboard ArrowLeft/Right navigation), updating `role="tabpanel"` + swapping `landing/img/<screen>-{light|dark}.webp` based on active theme.

#### (f) Story & Journal Preview (`#nhat-ky`, `var(--story-surface)` + embedded `var(--surface)` card)
- 50/50 split on Desktop/Tablet (`1440px`/`768px`), vertical stack on Mobile (`390px`), grounded on `var(--story-surface)` with primary story copy in `var(--on-story)` (`14.51:1` Light / `13.79:1` Dark) and muted captions in `var(--on-story-muted)` (`12.83:1` Light / `8.35:1` Dark):
  - Left: Flat `vietnamese-table.jpg` with high-contrast credit badge (`var(--story-surface)` @ `92%` / solid bg + `var(--on-story)` text, zero raw hexes).
  - Right: Editorial story + compact **Weekly Kcal & Macro Preview Card** explicitly wrapped in a **`var(--surface)`** card container (`1px solid var(--border)` / `var(--hairline)`, `var(--text)` heading, and `--macro-*` bars rendered against `--surface` so all macro bars maintain `>= 5.79:1` Light / `>= 6.25:1` Dark contrast) + lime CTA `"Viết tiếp chuyện bếp"` -> `/nhat-ky` (`var(--on-lime)` on `var(--lime)` = `13.70:1`).

#### (g) Taste Survey CTA + Android APK & Web App Launcher + FAQ (`#tai-ve`)
- **Invitation Band (`editorialSurface`):** `"Let's make something tasty."` with 3 clear launch paths:
  1. **Web App Launcher:** Primary button `"Mở ứng dụng Web"` -> `/bep`
  2. **Taste Survey CTA:** High-contrast outline/lime button `"Góp gu món Việt (Không cần tài khoản)"` -> `/khao-sat?kenh=link`
  3. **Android APK Launcher (`#android-download`):** Preserves `story.js:30–52` `HEAD /tai-ve/tastoria-<ver>.apk?ready=<ts>` polling state machine with safe disabled initial/error states:
     - `State: INITIAL / CHECKING / 404`: HTML initializes `#android-download` with `aria-disabled="true"` (and `href` omitted / removed; URL kept in `data-apk-href`), text `"Bản Android mới đang được cập nhật…"`, re-polling every `30s`.
     - `State: READY (200 OK)`: Restores `href` from `data-apk-href`, removes `aria-disabled` (or sets `"false"`), and displays `"Tải Android · APK 0.1.4"` with `arrow-down` SVG icon.
     - `State: NETWORK_ERROR`: Keeps `aria-disabled="true"` (`href` removed) on `fetch` rejection and silently retries in `30s`.
- **FAQ (`<details>`):** 4–5 accessible accordion items (`>= 44px` summary hit height, `hairline` dividers).

#### (h) Footer (`--surface-alt`)
- Theme-aware inline `TrayMark` (**`fill="var(--accent)"`**, yielding `5.35:1` Light on `--surface-alt` and `6.06:1` Dark — never `--accent-display` on Light `--surface-alt`) + `tastoria.`, back-to-top anchor (`arrow-up` SVG, `48×48px`, `aria-label="Về đầu trang"`), links to `/khao-sat`, `/dang-nhap`, `/bep`, and expandable photo credits `<details>`.

---

## PART B — Mobile & Web App (`app/`)

### B.1 Responsive Adaptive Shell & Theme Switching

#### Lifting `ui.tsx:552` Bottleneck & Adaptive Navigation
1. **Container Width Refactor (`app/src/components/ui.tsx`):**
   - Replace hardcoded `inner: { maxWidth: 560 }` (`ui.tsx:552`) and `footerInner: { maxWidth: 560 }` (`ui.tsx:554`) with responsive container presets:
     - `variant="workspace"` (default for `bep`, `kho`, `kham-pha`, `mam`, `di-cho`, `nhat-ky`, `quan-tri`): `maxWidth: 1240` on `>= 1024px`, `920` on `768–1023px`, `100%` on `< 768px`.
     - `variant="focused"` (for `onboarding/*`, `cai-dat`, `khao-sat`, `dat-lai-mat-khau`): `maxWidth: 680` centered inside the shell so forms remain ergonomic (`<= 68ch`).
2. **Breakpoint Navigation Wrapper (`AppShell` mounted in root `app/src/app/_layout.tsx` wrapping `<Stack>` / `<Slot />` so resizes preserve route state):**
   - **Shell Suppression Rules:** Suppress the sidebar/rail chrome completely on unauthenticated, auth, and onboarding routes (`/(auth)/*`, `/onboarding/*`, `/dat-lai-mat-khau`, and `/khao-sat` when signed out).
   - **Route Placement (`(tabs)/` vs Root `<Stack>`):** Keep `bep`, `kho`, `mam`, `di-cho`, `nhat-ky` inside `(tabs)/` (`<= 5` tabs), and place `kham-pha` (`app/src/app/kham-pha.tsx`) and `quan-tri` (`app/src/app/quan-tri.tsx`) **outside `(tabs)/`** in the root `<Stack>` (matching `cai-dat.tsx`, `quet/`, `mon/[id].tsx`, `nau/[id].tsx`). Hide `(tabs)/_layout.tsx` bottom tab bar (`tabBarStyle: { display: 'none' }`) whenever `width >= 768px`.
   - **Desktop (`>= 1024px`):** Persistent `248px` left sidebar rail (`c.surface` bg, `1px` `c.hairline` right border):
     - Header: `TrayMark` (`36px`) + `tastoria.`
     - Primary Workspace Links (`>= 48px` row height, SVG icon + Vietnamese label, `c.accentSoft` active pill + `c.accent` text):
       1. `Bếp nhà` (`/bep`, `home`)
       2. `Kho bếp` (`/kho`, `box`)
       3. `Khám phá` (`/kham-pha`, `compass`) — **NEW (outside `(tabs)/`)**
       4. `Mâm cơm` (`/mam`, `tray`)
       5. `Đi chợ` (`/di-cho`, `cart`)
       6. `Nhật ký` (`/nhat-ky`, `book`)
     - Utility & Role-Gated Links (separated by `c.hairline`):
       7. `Quét tủ lạnh` (`/quet`, `camera`)
       8. `Quản trị` (`/quan-tri`, `shield`) — **Rendered ONLY when `user.role === 'admin' || user.role === 'ml_operator'` (never for `user` or CLI-only `curator`)**
       9. `Cài đặt` (`/cai-dat`, `gear`)
     - Footer Controls: Light / Dark / System segmented toggle + signed-in email + `"Đăng xuất"`.
   - **Tablet (`768px – 1023px`):** Deterministic **`72px` compact icon rail** with short accessible labels/tooltips (no drawer toggle ambiguity, bottom tab bar hidden) + 2-column content grids (`maxWidth: 920px`).
   - **Mobile (`< 768px`, verified at `320px`, `375px`, `390px`):**
     - Sticky **5-tab bottom bar** (`minHeight: 68`, `SafeAreaView` bottom inset, `>= 48dp` item height, `12sp` tab label with `maxFontSizeMultiplier: 1.2` so `64px`-wide tabs at `320px` never clip): `Bếp nhà`, `Kho bếp`, `Mâm cơm`, `Đi chợ`, `Nhật ký`.
     - Secondary/new routes (`Khám phá` `/kham-pha`, `Quét` `/quet`, `Cài đặt` `/cai-dat`, and role-gated `Quản trị` `/quan-tri`) are accessed cleanly from Home (`bep`) quick action bar and header action buttons (`>= 48×48dp`), strictly obeying `bottom-nav-limit <= 5`.
3. **ThemeProvider & Base A11y Upgrades (`app/src/theme/index.tsx` & `app/src/components/ui.tsx`):**
   - `ThemeProvider`: expose `{ c, scheme, preference, setPreference }` where `preference: 'light' | 'dark' | 'system'` persists to `AsyncStorage` (`tastoria.theme.v1`) and on Web syncs `<meta name="theme-color">`, `document.documentElement.dataset.theme`, and `document.body.style.backgroundColor = c.bg`.
   - `ui.tsx`: `Field` / `AuthField` MUST render `nativeID` on `<T v="label">` + `aria-labelledby` on `<TextInput>` (in addition to `accessibilityLabel`); `T` headings (`accessibilityRole="header"`) MUST emit `aria-level` (`1|2|3`); `VARIANTS` line-heights synced to `MASTER.md` §3.2.

---

### B.2 Detailed Specifications for All 10 Feature Modules

---

#### Module 1: Auth, Onboarding, Granular Consent & DSR
- **Routes:** `/(auth)/dang-nhap`, `/(auth)/dang-ky`, `/(auth)/quen-mat-khau`, `/dat-lai-mat-khau` (`?token=...`), `/onboarding`, `/onboarding/ho-so`, `/cai-dat`
- **User Roles:** Public for auth/reset routes; authenticated `CurrentUser` (`user | admin | curator | ml_operator`) for onboarding & settings. First-login check in `bep` redirects to `/onboarding` or `/onboarding/ho-so` until completed.
- **API Bindings:**
  - Auth: `POST /auth/login`, `POST /auth/register`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm`
  - Consent & Privacy: `GET /policies/{purpose}/current`, `GET /me/consents`, `POST /me/consents`, `POST /me/consents/{purpose}/withdraw`
  - Profile & Settings: `GET /me/profile`, `PUT /me/profile`, `POST /me/energy-suggestion`, `PUT /me/energy-target`, `PUT /me/allergens`, `PUT /me/diet`, `PUT /me/favorites`, `GET /me/settings`, `PUT /me/settings`
  - DSR: `POST /me/data-requests` (`export | delete | correct | restrict | object`), `GET /me/data-requests/{id}`, `GET /me/data-requests/{id}/download`
- **Wireframes:**
```text
DESKTOP (>=960px) AuthSplit                MOBILE (<768px) Auth / Settings
+-------------------+-------------------+   +-------------------------------+
| [editorialSurface]| [TrayMark]tastoria|   | [TrayMark] tastoria.          |
|  Bữa ngon,        | Title (h1)        |   | Title (h1) & Subtitle         |
|  chuyện còn dài.  | [Visible Label]   |   | [Visible Label: Email]        |
| [vietnamese-table]| [Email Input    ] |   | [Visible Label: Mật khẩu][Eye]|
|-------------------| [Password ][Eye ] |   | [Primary Submit CTA >=48dp]   |
| [limeSurface bar] | [Đăng nhập CTA  ] |   | [Quên mật khẩu] [Đăng ký]     |
+-------------------+-------------------+   +-------------------------------+
```
- **Component Hierarchy & Key Fixes:**
  - `AuthShell.tsx`: Replace hardcoded legacy `#F3512C` -> `c.editorialSurface`, legacy `#26291E` -> `c.onEditorial` (`#FAF5EB` Light / `#F7EFDF` Dark), legacy `#DCEB91` -> `c.limeSurface`; replace `↗` / `←` glyphs with SVG `arrow-up-right` / `arrow-left`.
  - `AuthField`: Visible `<T v="label" nativeID={labelId}>` paired via `aria-labelledby={labelId}` + `accessibilityLabel`, `eye`/`eye-off` SVG password toggle (`>= 48×48dp`), inline field error (`role="alert"` / `accessibilityLiveRegion="polite"`).
  - `onboarding/index`: 3 independent **unchecked** `PolicyCard` switches (`health_profile`, `personalization`, `photo_contribution`) with expandable `text_vi`.
  - `cai-dat`: Theme switcher (`Sáng / Tối / Theo hệ thống`), 7 collapsible sections (`profile`, `allergen`, `favs`, `kitchen`, `consent`, `export`, `delete`) using SVG `plus`/`minus`, expanded DSR request form (`correct | restrict | object` manual requests alongside `export`/`delete`), and conditional `"Mở bảng Quản trị"` banner **ONLY when `user.role === 'admin' || user.role === 'ml_operator'`** (hidden for `user` and CLI-only `curator`).
- **Offline / Outbox:** Refresh token persisted in `SecureStore` (Android) / `sessionStorage` (Web); onboarding progress in `tastoria.onboarding.{userId}`; mutations require network.
- **4 Explicit UI States:**
  - `loading`: Splash screen until fonts/session settle; `Loading` spinner on policies/profile fetch and button spinners on submit.
  - `empty`: Unset optional profile metrics display helper guidance; 0 favorites permitted on skip.
  - `error`: `429 login_locked` (15m lockout banner), `409 email_taken` (inline email error), `409 policy_outdated` (auto-refetches current policy), `409 age_confirmation_required` (inline 18+ confirmation toggle), `422 age_below_minimum` (minor notice skipping kcal target), `409 below_floor_confirmation_required`, `403 reauth_failed` (inline delete password error), `401 token_revoked` (auto `refreshSession()` after consent withdraw).
  - `success`: Redirects to `/bep` or next onboarding step; Settings displays `"Đã lưu."` confirmation; Export displays `"Tải tệp (.zip)"` when `download_available`.

---

#### Module 2: Home Dashboard (`bep`)
- **Routes:** `/(tabs)/bep` (`/` redirects here when signed in)
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /me/profile`, `GET /meal-plans/latest?meal={lunch|dinner}`, `GET /pantry/lots?status=in_stock,not_seen&sort=urgency&limit=100`
- **Wireframes:**
```text
DESKTOP (>=1024px, inside 248px Sidebar Shell)     MOBILE (<768px, 5-Tab Bar)
+-----------------------------------------------+   +---------------------------+
| Bếp nhà today               [Khám phá][Cài đặt]|   | [TrayMark] Tastoria [Cài đặt]
+-------------------------+---------------------+   | [Khám phá món] [Quản trị*]|
| TODAY'S MEAL HERO CARD  | QUICK SCAN TILES    |   +---------------------------+
| [Tray SVG]  Bữa tối     | [Chụp tủ] [Chụp đồ] |   | TODAY'S MEAL HERO CARD    |
| 220px       Mặn / Rau / |---------------------|   | [Tray compact] Bữa tối    |
|             Canh · 2 ng | FOOD STORY & JOURNAL|   | Mặn / Rau / Canh -> /mam  |
|             [Mở mâm ->] | [vietnamese-table]  |   +---------------------------+
+-------------------------+ MỖI BỮA NGON...     |   | [Chụp tủ lạnh] [Chụp mua] |
| URGENT PANTRY GRID (3-col) -> /kho            |   +---------------------------+
| [Dùng ngay] [Sớm] [Kiểm tra]                  |   | ĐỒ CẦN DÙNG GẤP ->        |
+-----------------------------------------------+   | [H-Scroll Cards...]       |
                                                    +---------------------------+
                                                    | [FoodStory] -> Nhật ký    |
                                                    +---------------------------+
```
- **Component Hierarchy & Key Fixes:**
  - **Fix `bep.tsx:237` Defect:** Remove accidental `<FoodStory compact />` inside `ScanTile` so `FoodStory` renders strictly once in the Journal/Story section.
  - **Fix `bep.tsx:233` Contrast:** Use `c.surface` or theme-safe alpha pill behind `ScanTile` icon so dark mode `c.onAccent` (`#2A0E0C`) never sits inside white translucent circle.
  - Replace `→` (`bep.tsx:185`) with SVG `arrow-right`.
- **Offline / Outbox:** Reads TanStack Query cache seamlessly offline; zero mutations on Home.
- **4 Explicit UI States:**
  - `loading`: `Skeleton` (`height: 236`) on Meal Hero Card + `Loading` strip for pantry.
  - `empty`: `404` on `/meal-plans/latest` renders `Empty` card (`"Chưa có mâm cho bữa..."` + `"Ra mâm từ đồ đang có"` -> `/mam`); Pantry empty -> `"Kho đang trống..."`; No urgent lots -> `"Chưa có đồ nào cần dùng gấp."`
  - `error`: Independent `ErrorBox` with `"Thử lại"` (`onRetry`) for meal plan and pantry strip.
  - `success`: Interactive `Tray` preview + urgent lots strip + single `FoodStory` journal card.

---

#### Module 3: Pantry (`kho`)
- **Routes:** `/(tabs)/kho`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /pantry/lots?status=in_stock,not_seen&sort={urgency|created_at}&limit=100`, `POST /pantry/lots`, `PATCH /pantry/lots/{id}`, `POST /pantry/lots/{id}/discard`, `GET /ingredients?q=...&limit=12`, `GET /reference`
- **Wireframes:**
```text
DESKTOP (>=1024px)                                 MOBILE (<768px)
+-----------------------------------------------+   +---------------------------+
| Kho bếp              [+ Thêm đồ] [Quét ảnh]   |   | Kho bếp        [+ Thêm]   |
| [Search input...]   Sort: [Khẩn cấp v]        |   | [Search...] [Sort v]      |
| Filter: [Tất cả][Dùng ngay][Sớm][Tươi][K.tra] |   | [Tất cả][Dùng ngay][Sớm..]|
+-----------------------------------------------+   +---------------------------+
| [! Warn Banner if kiem_tra lots exist]        |   | [! Banner: X đồ cần kiểm] |
| +-------------+ +-------------+ +-----------+ |   | [Lot Card 1 + FreshBadge] |
| | Lot Card 1  | | Lot Card 2  | | Lot Card 3| |   | [Lot Card 2 + FreshBadge] |
| | FreshBadge  | | FreshBadge  | | FreshBadge| |   | [Lot Card 3 + FreshBadge] |
| +-------------+ +-------------+ +-----------+ |   +---------------------------+
+-----------------------------------------------+
```
- **Component Hierarchy & Controls:**
  - **Urgency Filter Pills (M4):** `Tất cả`, `Dùng ngay` (`dung_ngay`), `Nên dùng sớm` (`dung_som`), `Tươi` (`tuoi`), `Cần kiểm tra` (`kiem_tra`), `Chưa thấy` (`not_seen`).
  - **Sort Toggle:** `Khẩn cấp nhất` (`urgency`) vs `Mới thêm` (`created_at`).
  - **Virtualized List (`FlatList`, `windowSize={5}`)** of `LotCard`s (`ingredient_name_vi`, `fmtG` `tabular-nums`, `FreshBadge`, `acquired_at` basis, optional freshness confidence tooltip if `p_* != null`, `not_seen` pill).
  - **`AddLotSheet`:** Quick-add staple chips (`Trứng gà`, `Đậu phụ`, `Thịt lợn`, `Rau muống`, `Cà chua`, `Hành lá`) + `IngredientSearch` + `QuantityEditor` (`count`+`unit_code` | `qty_level` `it|vua|nhieu` | `grams`) + `PurchaseDate` (`0..7` days / `"Không nhớ"`).
  - **`EditLotSheet`:** Prominent `"Xác nhận còn tươi / dùng được"` button for `kiem_tra` (`user_checked: true`), `"Xác nhận vẫn còn trong tủ"` for `not_seen` (`status: 'in_stock'`), edit quantity/date, mark `used_up`, or `discard` (with confirmation).
- **Offline / Outbox:** `useReference()` cached (`1h`); lot mutations require online connectivity.
- **4 Explicit UI States:**
  - `loading`: `Loading rows={4}` skeleton cards on initial load; button spinners on save/discard.
  - `empty`: Unfiltered empty -> `"Kho đang trống"` + CTAs (`Quét tủ lạnh`, `Thêm bằng tay`); Filtered empty -> `"Không có nguyên liệu nào ở mức này"` + `"Xoá bộ lọc"`.
  - `error`: `ErrorBox` on fetch failure; inline RFC 9457 error on sheet (`422 qty_kind_mismatch`, `unit_conversion_missing`, `acquired_at_in_future`, `409 lot_closed`, `lot_not_check_level`).
  - `success`: Immediate list re-sort & `kiem_tra` banner update after mutation.

---

#### Module 4: AI Camera Scan + Calibrated Freshness Probabilities (`quet/index`, `quet/[id]`)
- **Routes:** `/quet` (`?mode=fridge|haul`), `/quet/[id]`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `POST /scans` (`multipart/form-data` + `Idempotency-Key`), `GET /scans/{id}?wait=10` (500ms long-poll while `queued|processing`), `GET /scans/{id}/images/{ordinal}`, `POST /scans/{id}/items`, `PATCH /scans/{id}/items/{itemId}`, `DELETE /scans/{id}/items/{itemId}`, `POST /scans/{id}/confirm`, `POST /scans/{id}/discard`
- **Wireframes:**
```text
DESKTOP (>=1024px) /quet/[id]                      MOBILE (<768px) /quet/[id]
+-----------------------------------------------+   +---------------------------+
| <- Xác nhận nguyên liệu                       |   | <- Xác nhận nguyên liệu   |
+-----------------------+-----------------------+   +---------------------------+
| SCAN IMAGE + BBOX SVG | 1. CẦN KIỂM TRA       |   | [Thumb Image w/ Bbox]     |
| [Photo w/ high-contrast|  [Chip: Rau cải 62%] |   | 1. CẦN KIỂM TRA           |
|  bounding boxes]      | 2. NHÓM RAU CỦ / THỊT |   |   [Chip: Rau cải · kiểm]  |
| [Tab: Ảnh 1 | Ảnh 2]  |  [Chips...]           |   | 2. NHÓM NGUYÊN LIỆU       |
|                       | [+ Thêm nguyên liệu]  |   |   [Chips...]              |
|                       | 3. ĐỒ CHƯA THẤY LẦN NÀY|   | [+ Thêm nguyên liệu]      |
|                       | [Ngày mua] [Lưu vào kho]  | [Sticky: Ngày mua + Lưu]  |
+-----------------------+-----------------------+   +---------------------------+
```
- **Freshness Probabilities, Authenticated Image Fetch & Human-in-the-Loop Controls:**
  - `/quet`: Segmented mode (`Toàn tủ lạnh` | `Đồ vừa mua`), 1–2 image capture/library picker (client resize `<= 1280px` JPEG), conditional `contribute` checkbox (shown ONLY if `photo_contribution` consent granted).
  - `/quet/[id]`: Groups `ScanItem` chips (`Cần kiểm tra trước khi dùng` first, then `food_group`), flagging `detections[].confidence < 0.5` as `chưa chắc`.
  - **Authenticated Image Fetch & Bbox Overlay (`410 image_purged` Safe):** Because `GET /scans/{id}/images/{ordinal}` requires `Authorization: Bearer <accessToken>` (never cookies), NEVER pass the raw endpoint URL to `<Image source={{ uri }}>` or `<img src>`. Fetch via `api.GET('/scans/{id}/images/{ordinal}', { parseAs: 'blob' })` -> `URL.createObjectURL(blob)` (with `URL.revokeObjectURL` cleanup on unmount/ordinal change; native uses authenticated blob/data URI). Render interactive SVG bounding boxes from `item.detections[]` over the loaded image; tapping a bbox selects/opens its `EditChip` sheet (focusing that detection). If the endpoint returns **`410 image_purged`** (or `404`), render a clean `c.surfaceAlt` fallback card (*"Ảnh gốc đã được xoá sau 30 ngày theo chính sách lưu trữ — vẫn có thể sửa danh sách nguyên liệu bên dưới"*) while keeping `ScanItem` chips & confirmation usable.
  - **Freshness Probability Bars inside `EditChip` (`Scan.classifier_version_id` & `ScanItem.detections[]`):**
    - Bind model metadata strictly to **`Scan.classifier_version_id`** (`openapi-v1.yaml:5790`, NOT `freshness_version`), and read `p_tuoi`, `p_dung_som`, `p_dung_ngay`, `p_kiem_tra` from **`ScanItem.detections[]`** (`0..N` `Detection` objects per item):
      - `detections.length === 0` (`origin === 'user_added'`): omit probability bars and show `"Nguyên liệu do bạn tự thêm — chọn độ tươi thủ công"`.
      - `detections.length === 1`: render that detection's 4 calibrated bars (`0–100%` `tabular-nums`, colored via `c.fresh.*` with Vietnamese labels + accessible text).
      - `detections.length > 1` (multi-object chip): aggregate default summary by worst-case urgency (`argmax(p_kiem_tra)` / lowest predicted freshness detection) AND provide per-detection pills (`"Phát hiện #1..#N"`, synced with bbox tap) so the user can inspect each object's `p_*`.
      - `Scan.classifier_version_id == null` or all `p_* == null`: display fallback note (`"Chưa có điểm độ tươi tự động — hãy tự kiểm tra"`). User can always override `ingredient_id`, quantity/count/`qty_level`, `user_freshness`, or delete false positives.
- **Offline / Outbox:** `useIdempotencyKey()` prevents duplicate uploads on retry; scan upload/poll/confirm require network.
- **4 Explicit UI States:**
  - `loading`: Upload progress -> `"Ảnh đang chờ xử lý…"` (`queued`) -> `"Đang nhận diện nguyên liệu…"` (`processing`) while polling; blob spinner while fetching scan image.
  - `empty`: 0 detected items -> Clear guidance + `"+ Thêm nguyên liệu bị sót"` and `"Bỏ kết quả này"`.
  - `error`: `404` (scan disabled -> `"Quét ảnh chưa mở"` + `"Mở Kho bếp"`), `410 image_purged` (image-pane fallback preserving chip confirmation), `413 image_too_large`, `415 unsupported_media_type`, `503 model_unavailable`/`queue_full`, `failed|expired` scan -> `"Quét lại"` / `"Nhập tay trong Kho"`, `422 qty_level_required` / `freshness_check_required` on confirm.
  - `success`: `ScanConfirmResult` summary (`created_lot_ids.length` new lots, `not_seen_lot_ids.length` unseen lots) + CTAs `"Ra mâm cơm"` / `"Xem kho"`.

---

#### Module 5: NEW Recipe Explorer (`kham-pha`) + Recipe Detail (`mon/[id]`)
- **Routes:** `/kham-pha` (NEW), `/mon/[id]` (`?plan=...&item=...`)
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:**
  - Existing: `GET /recipes` (`q`, `slot`, `tag`, `cursor`, `limit`), `GET /recipes/{id}`, `GET /catalog/snapshot`, `GET /reference`, `GET /pantry/lots`, `POST /events` (outbox `viewed`)
  - **M3 Planned (F9):** Expanded `GET /recipes` filters (`max_minutes`, `method_code`, `kcal_max`, `pantry_match`) + `RecipeSummary` macros (`protein_g`, `lipid_g`, `carb_g`, `fiber_g`) & `pantry_match_ratio`.
- **Wireframes:**
```text
DESKTOP (>=1024px) /kham-pha                       DESKTOP (>=1024px) /mon/[id]
+-----------------------------------------------+   +---------------------------+
| Khám phá món Việt   [Search input...]         |   | <- Quay lại  Cá kho tộ    |
| Slot: [Tất cả][Mặn][Rau][Canh]  [Đủ đồ kho]   |   +-------------+-------------+
| Thời gian: [<=20p][<=30p][<=45p] Phương pháp..|   | NGUYÊN LIỆU | CÁC BƯỚC NẤU|
+-----------------------------------------------+   | +StockMatch | 1.[Active]  |
| +-------------+ +-------------+ +-----------+ |   |-------------| 2.[Passive] |
| | Dish Card 1 | | Dish Card 2 | | Dish Card3| |   | DINH DƯỠNG  |-------------|
| | [Đủ đồ] 25p | | [Thiếu 1]   | | [Đủ đồ]   | |   | Kcal + P/C/F| NGUỒN THAM  |
| | 420kcal P/C/F | 310kcal     | | 180kcal   | |   | [Make-ahead]| KHẢO        |
| +-------------+ +-------------+ +-----------+ |   +-------------+-------------+
+-----------------------------------------------+
```
- **Component Hierarchy:**
  - `kham-pha`: Search input (`<T v="label">Tìm món</T>`), Slot/Time/Method/`Đủ đồ trong kho` filter chips, responsive `1/2/3-col` `FlatList`/`Grid` (`RecipeSummaryCard`), cursor `"Tải thêm"` button.
  - `mon/[id]`: Title, slot & method badges, `total_minutes`, `kcal_per_serving`, `make_ahead` callout, ingredient list with `fmtG` + **Pantry Match Badge** (`Có đủ` in `herbSoft` vs `Thiếu X g` in `warnSoft`), horizontal macro progress bars (`macro.protein/carb/fat/fiber`), numbered steps (`active` vs `passive` + burner icon), sources.
- **Offline / Outbox:** `useCatalog()` caches `tastoria.catalog.v1` (`staleTime: 6h`, `gcTime: Infinity`) so filtering `/kham-pha` and viewing `/mon/[id]` operate **fully offline**; `viewed` event queues via `outbox.ts` ONLY if `personalization` consent is granted.
- **4 Explicit UI States:**
  - `loading`: `3-col` / `1-col` skeleton cards on `kham-pha`; `Loading` on `mon/[id]`.
  - `empty`: 0 search/filter matches -> `"Không tìm thấy món phù hợp"` + `"Xoá bộ lọc"`.
  - `error`: `404 not_found`/`recipe_not_published` or uncached offline error -> `ErrorBox` with `"Thử lại"`.
  - `success`: Paginated cards with pantry match & macros + offline banner when serving from `tastoria.catalog.v1`.

---

#### Module 6: Meal Tray Composer + Hybrid Substitutes (`mam`)
- **Routes:** `/(tabs)/mam`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /meal-plans/latest?meal={lunch|dinner}`, `POST /meal-plans` (`Idempotency-Key`), `GET /meal-plans/{id}`, `POST /meal-plans/{id}/accept`, `POST /meal-plans/{id}/items/{itemId}/swap` (`Idempotency-Key`), `GET /meal-plans/{id}/items/{itemId}/substitutes`, `POST /meal-plans/{id}/items/{itemId}/substitutions`, `POST /shopping-items`, `POST /cook-sessions` (`Idempotency-Key`)
- **Wireframes:**
```text
DESKTOP (>=1024px) /mam                            MOBILE (<768px) /mam
+-----------------------------------------------+   +---------------------------+
| [Bữa trưa | Bữa tối]        [Ghép mâm mới]    |   | [Bữa trưa | Bữa tối]      |
+---------------------+-------------------------+   | [Tray <= 272px on 320px]  |
| STICKY TRAY CANVAS  | SLOT CARDS & CONTROLS   |   |  Cơm 2 bát · KcalBar      |
|   (Lacquered Tray   | [Mặn: Cá kho] [Đổi/Thay]|   | [Mặn] [Rau] [Canh]        |
|    SVG 360px)       | [Rau: Muống]  [Đổi/Thay]|   | [reason_vi + Ranker badge]|
|   Cơm 2 bát         | [Canh: Chua]  [Đổi/Thay]|   | [Nhận mâm và nấu]         |
|   [KcalBar]         | [reason_vi + Ranker tag]|   +---------------------------+
|   [Nhận mâm và nấu] | [Số người 1..6] [Giờ ăn]|   (Dish actions -> Sheet)
+---------------------+-------------------------+
```
- **Component Hierarchy & ML Integrations:**
  - `Composer`: `persons` (`1–6`), `max_minutes` (`30|45|60|90|120`), `coeater_allergen_codes`, `pinned_lot_ids` (`<= 2` available lots with `FreshBadge`).
  - `PlanView`: Interactive `Tray` SVG (`Math.min(width - 48, 300)` on mobile -> `<= 272px` at `320px`, `360px` on desktop) + Slot Cards + `KcalBar` + `rice_bowls_per_person` + `reason_vi` + M3 **Ranker version badge** (`ranker_version_id` when ML ranker active, e.g., `"Xếp hạng cá nhân hoá"`).
  - **Hybrid Substitutes Sheet (`"Thiếu gì?"`):** Groups/badges candidates cleanly by `origin`:
    - `lookup` -> `"Gợi ý chuẩn"` (`herbSoft` badge)
    - `embedding` (M3 pgvector) -> `"Tương đồng ngữ nghĩa & dinh dưỡng"` (`infoSoft` badge + `sparkles` SVG)
    - Displays `in_pantry` (`available_g_min`), conversion `ratio` / `grams`, `"Dùng thay"` or `"Thêm vào đi chợ"`.
  - **Swap Sheet (`"Đổi món"`):** 4 Vietnamese reasons (`khong_hop_gu`, `moi_an`, `thieu_thoi_gian`, `khac`).
- **Offline / Outbox & `Idempotency-Key` Reset Rule:** `useIdempotencyKey()` guards `create_plan`, `swap_item`, `create_session`; requires network. **CRITICAL:** `onError` MUST call `idem.reset()` on all terminal `4xx` responses (every status except `409 idempotency_in_progress`), preventing 48h cached `422 no_feasible_tray` / `422 pin_unsatisfiable` replay when the user restocks via `di-cho` -> `to-pantry` and retries `"Ra mâm"` with the same body.
- **4 Explicit UI States:**
  - `loading`: `Loading` (`"Đang ghép mâm…"` / `"Đang tìm món khác…"`).
  - `empty`: `404` on `/meal-plans/latest` auto-opens `Composer`; empty substitutes -> `"Kho đủ nguyên liệu cho món này."`
  - `error`: `422 no_feasible_tray` -> `NoTray` card showing nearest shortfalls + 1-tap `"Thêm vào đi chợ"` (using SVG `check` on `"Đã thêm"`); `422 pin_unsatisfiable` -> `"Bỏ ghim đồ gây vướng"`; `409 no_alternative`; `409 conflict_state` (`over_time_minutes` confirm prompt); `409 cook_session_in_progress` -> redirects to `/nau/[id]`.
  - `success`: Interactive composed/swapped/substituted tray launching `/nau/[id]`.

---

#### Module 7: Guided Cooking Gantt + Multi-Timer + 10m Undo (`nau/[id]`, `nau-xong/[id]`)
- **Routes:** `/nau/[id]`, `/nau-xong/[id]`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /cook-sessions/{id}`, `POST /cook-sessions/{id}/abandon`, `POST /cook-sessions/{id}/complete` (`Idempotency-Key`), `POST /cook-sessions/{id}/undo`
- **Wireframes:**
```text
DESKTOP (>=1024px) /nau/[id]                       MOBILE (<768px) /nau/[id]
+-----------------------------------------------+   +---------------------------+
| <- Nấu cả mâm · Xong lúc 18:30                |   | Nấu cả mâm · Xong 18:30   |
+-------------------------+---------------------+   +---------------------------+
| CURRENT STEP CARD (28sp)| CP-SAT GANTT CHART  |   | [CP-SAT Gantt Horizontal] |
| [Mặn] Đun liu riu 10p   | Mặn: [==][--][==]   |   | CURRENT STEP CARD (28sp)  |
| [   Xong bước này    ]  | Rau:      [===]     |   | [   Xong bước này    ]    |
| Next: Nhặt rau muống    | Canh:   [==][---]   |   | ĐANG CHỜ (Multi-Timer)    |
|-------------------------|   | bây giờ         |   |  · Canh bí   04:12        |
| ĐANG CHỜ (Multi-Timer)  |---------------------|   |  · Thịt kho  09:45        |
|  · Canh bí      04:12   | [Nấu xong, trừ kho] |   | [Full Schedule List]      |
|  · Thịt kho     09:45   | [Bỏ phiên nấu]      |   | [Sticky: Nấu xong]        |
+-------------------------+---------------------+   +---------------------------+
```
- **Component Hierarchy & Ergonomics:**
  - `useScreenOn` wake-lock kept active on `/nau/[id]`.
  - **CP-SAT Gantt Chart:** Per-dish tracks distinguishing `active` (`18px` tall solid `c.accent` bar) vs `passive` (`8px` tall `c.herbSoft` bar w/ `2px` `c.herb` border/pattern) + live `"bây giờ"` marker + external text legend + step list below (**zero in-bar text labels**, preventing clipping on narrow 2-minute bars at `320px`).
  - **Current Step Card:** `28sp`–`32sp` bold step text, `>= 56dp` `"Xong bước này"` button, SVG `check` for finished steps (`nau/[id].tsx:190`).
  - **Multi-Timer (`"Đang chờ"` & Finished Banner):** Concurrent passive timers computed as `fmtLeft(endAt - now)` (`tabular-nums`) from absolute timestamps so phone sleep causes zero drift. When `elapsed >= e.end_offset_s` and the step is not yet marked done, transition the timer into an explicit **`"Đã xong giờ chờ"`** banner with a `"Xác nhận xong"` action (never disappear silently).
  - **`/nau-xong/[id]`:** Optional per-dish feedback (`Hợp gu` / `Không hợp` / `Bỏ chấm`), grouped deduction summary (`fmtG`), `shortfalls[]` zero-stock notice, and **10-minute Undo countdown** (`Hoàn tác (còn mm:ss)`) rendered ONLY while `deadline && left > 0 && !isCode(undo.error, 'undo_window_expired')` (clock-skew safe).
- **Offline / Outbox:** `useCookSession(id)` caches schedule in `tastoria.cook.{id}`; `useDoneSteps(id)` persists ticks in `tastoria.cook.{id}.done`; `"Nấu xong"` enqueues in `tastoria.outbox.v1` with fixed `Idempotency-Key` (replayed every 20s and on app foreground). **Auth Expiry Guard (`outbox.ts:109`):** Remove `401` from `retryable()` (since `rawRequest` already runs `refreshSession()`) so invalid refresh tokens do not spin in a 20s silent loop, and surface an explicit re-login prompt (`"Phiên đăng nhập hết hạn — đăng nhập lại để đồng bộ"` -> `/dang-nhap`).
- **4 Explicit UI States:**
  - `loading`: `Loading` if session not cached locally.
  - `empty`: Hidden `"Đang chờ"` when 0 passive timers running (unless finished timers await confirmation in `"Đã xong giờ chờ"`); `"Đã xong mọi bước phải đứng bếp..."` when active steps finish; `"Không trừ lô nào..."` if seasonings only.
  - `error`: Outbox offline queue -> `"Đã ghi, sẽ đồng bộ khi có mạng"` + `"Gửi lại ngay"`; `401` outbox failure -> re-login banner; `409 undo_window_expired` -> immediately hides undo button and guides manual `/kho` adjustment.
  - `success`: Auto-redirect completed session to `/nau-xong/[id]`; Undo restores lots and returns to `/mam`.

---

#### Module 8: Smart Shopping List + 1-Tap to Pantry (`di-cho`)
- **Routes:** `/(tabs)/di-cho`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /shopping-items?status=open,bought&limit=100`, `POST /shopping-items`, `PATCH /shopping-items/{id}` (`open|bought|dropped`), **M3 Planned (F9):** `POST /shopping-items/{id}/to-pantry`
- **Wireframes:**
```text
DESKTOP (>=1024px)                                 MOBILE (<768px)
+-----------------------------------------------+   +---------------------------+
| Đi chợ                       [+ Thêm đồ mua]  |   | Đi chợ         [+ Thêm]   |
+-------------------------+---------------------+   +---------------------------+
| CẦN MUA (Open)          | ĐÃ MUA (Bought)     |   | CẦN MUA                   |
| [ ] Cà chua · 300g  [x] | [v] Trứng gà · 6 quả|   | [ ] Cà chua · 300g    [x] |
|     cho mâm hôm nay     |     [Đưa vào kho]   |   | ĐÃ MUA                    |
| [ ] Hành lá · 50g   [x] | [Đưa tất cả vào kho]|   | [v] Trứng gà [Đưa vào kho]|
+-------------------------+---------------------+   +---------------------------+
```
- **Component Hierarchy:**
  - `AddSheet`: `IngredientSearch`, optional grams, optional note.
  - `Cần mua` row: `48×48dp` SVG checkbox, ingredient name, `tabular-nums` grams + note, `"Bỏ"` (`trash` SVG).
  - `Đã mua` row: Checkbox to uncheck + **M3/M4 `"Đưa vào kho (1 chạm)"`** button (`POST /shopping-items/{id}/to-pantry`) + batch `"Đưa tất cả vào kho"`. When an item has `qty_g === null` (or `to-pantry` returns `422` requiring quantity), open a prefilled `AddLotSheet` fallback for that ingredient; batch `"Đưa tất cả vào kho"` tracks per-item results and summarizes partial failures alongside succeeded items.
- **Offline / Outbox:** Online required for mutations and `to-pantry`.
- **4 Explicit UI States:**
  - `loading`: `Loading` rows on fetch; inline spinner on `to-pantry`.
  - `empty`: `Empty` `"Danh sách trống"` + hint pointing to `"Thiếu gì?"` in `/mam`.
  - `error`: `ErrorBox` on fetch/patch/`to-pantry` error (`409 conflict_state`, `422 validation_error` -> `AddLotSheet` prefill fallback).
  - `success`: Live `Cần mua` / `Đã mua` partitioning; `to-pantry` invalidates `qk.shopping` & `['lots']` and shows `"Đã đưa vào Kho bếp"` toast (`aria-live="polite"`).

---

#### Module 9: Weekly Nutrition & Macro Journal (`nhat-ky`)
- **Routes:** `/(tabs)/nhat-ky`
- **User Roles:** Authenticated `CurrentUser`
- **API Bindings:** `GET /journal?week=YYYY-Www` (**M3 Planned F9:** extended with weekly/daily macros `protein_g`, `lipid_g`, `carb_g`, `fiber_g` and `cooked_history[]`)
- **Wireframes:**
```text
DESKTOP (>=1024px)                                 MOBILE (<768px)
+-----------------------------------------------+   +---------------------------+
| Chuyện bếp · [‹] Tuần 46/2026 [›]             |   | [‹] Tuần 46/2026 [›]      |
+-------------------------+---------------------+   +---------------------------+
| KPIs: [5 Mâm] [8 Lô kịp]| LỊCH SỬ BỮA ĐÃ NẤU  |   | [5 Mâm đã nấu] [8 Lô kịp] |
|-------------------------| · T5 Tối: Cá kho..  |   | CALO HÀNG NGÀY (T2..CN)   |
| CALO HÀNG NGÀY (T2..CN) | · T4 Trưa: Đậu phụ..|   | [Bars + Direct Numbers]   |
| [Bar Chart + Target]    |                     |   | [A11y Summary Table]      |
| [A11y Summary Table]    |                     |   | DINH DƯỠNG (P / C / F / X)|
|-------------------------|                     |   | [Horizontal Macro Bars]   |
| DINH DƯỠNG (P / C / F)  |                     |   | LỊCH SỬ BỮA ĐÃ NẤU        |
| [Horizontal Macro Bars] |                     |   | [Meal History Cards]      |
+-------------------------+---------------------+   +---------------------------+
```
- **Component Hierarchy & Chart Accessibility:**
  - ISO Week switcher (`chevron-left` / `chevron-right` SVG icons replacing `‹` / `›`, disabling next on current/future weeks).
  - KPI Cards: `cooked_trays` & `urgent_lots_used` (`tabular-nums`).
  - Daily Kcal Bar Chart (T2..CN): Vertical bars (`macro.kcal` / `herb`) + direct numeric `tabular-nums` values + `e_target_kcal` reference line (`c.text`) + **visible/expandable accessible data table** + `accessibilityLabel` summary.
  - **Macro Breakdown (M3/M4):** Horizontal progress bars (`macro.protein`, `macro.carb`, `macro.fat`, `macro.fiber`) with explicit gram values and % text (zero multi-slice donut charts).
  - **Cooked History Timeline:** Cards showing date, meal (`Bữa trưa` / `Bữa tối`), dishes (tap -> `/mon/[id]`), and kcal/person.
- **Offline / Outbox:** Read-only; serves cached week queries offline.
- **4 Explicit UI States:**
  - `loading`: `Loading` skeleton for KPI + chart + history on week change.
  - `empty`: Days with `null` kcal display `"chưa nấu"`; 0-tray weeks show `0` KPIs + `"Tuần này bạn chưa ghi nhận mâm nào"` + CTA `"Lên mâm hôm nay"` -> `/mam`.
  - `error`: `ErrorBox` (`422 invalid_iso_week` or network) with `"Thử lại"`.
  - `success`: Full 7-day chart + macro bars + history + `kcal_range_status === 'calibrating'` notice if FCT calibration pending.

---

#### Module 10: Public Taste Survey (`khao-sat`) & Staff Admin/MLOps Console (`quan-tri`)

##### 10a. Public Taste Survey (`khao-sat`)
- **Routes:** `/khao-sat` (`?kenh=link|qr`)
- **User Roles:** Public (unauthenticated; `X-Respondent-Token`)
- **API Bindings:** `GET /policies/survey/current`, `POST /survey/respondents`, `GET /survey/respondents/{id}`, `PUT /survey/respondents/{id}/ratings/{recipeId}`, `PUT /survey/respondents/{id}/favorites`, `POST /survey/respondents/{id}/complete`
- **Layout:** Centered `maxWidth: 760px` on desktop, single-column `FlatList` (`windowSize={5}`) on mobile. Per-dish `1..5` `Score` buttons (`>= 48×48dp`, `>= 8px` gap) + `"Chưa ăn bao giờ"` toggle + sticky footer `"Đã chấm X/Y món"` + `"Gửi phiếu"`.
- **Offline / Outbox:** Persists `{ id, token }` in `tastoria.survey.v1`; mutations require network.
- **4 Explicit UI States:** `loading` (policy/respondent spinner), `empty` (`409 survey_closed` / `404` -> `"Khảo sát chưa mở"`), `error` (`401 respondent_token_invalid` -> `"Bắt đầu phiếu mới"`, `409 survey_already_completed`, `422 survey_incomplete`), `success` (clears local token, renders thank-you view).

##### 10b. NEW Staff Admin & MLOps Console (`quan-tri`)
- **Routes:** `/quan-tri` (`app/src/app/quan-tri.tsx`, outside `(tabs)/`)
- **User Roles:** Strictly role-gated to **`admin` and `ml_operator` ONLY** (`user.role === 'admin' || user.role === 'ml_operator'`, matching `openapi-v1.yaml:2936–3184`; `curator` is CLI-only with 0 HTTP `/admin/*` endpoints). Regular `'user'` and `'curator'` accounts never see the nav link and receive a `403` access-denied guard view if navigated directly — **without firing any unauthorized `/admin/*` API requests**.
- **API Bindings (`docs/api/openapi-v1.yaml:2936–3184`):**
  - `admin` ONLY: `GET /admin/data-requests`, `POST /admin/data-requests/{id}/resolve`, `GET /admin/audit-log`
  - `ml_operator` ONLY: `GET /admin/models`, `GET /admin/surveys`
- **Strict Role-Partitioned Sub-Tabs (Zero Cross-Role Tabs or Prefetches):**
  - When `user.role === 'admin'`: render ONLY `[Yêu cầu DSR, Nhật ký kiểm toán]`.
  - When `user.role === 'ml_operator'`: render ONLY `[Đăng ký mô hình, Đợt khảo sát]`.
- **Wireframes:**
```text
DESKTOP (>=1024px) /quan-tri                       MOBILE (<768px) /quan-tri
+-----------------------------------------------+   +---------------------------+
| Quản trị hệ thống  [Role: admin | ml_operator]|   | Quản trị hệ thống         |
| admin:       [Yêu cầu DSR][Audit Log]         |   | [Role-Partitioned Tabs]   |
| ml_operator: [Mô hình][Đợt khảo sát]          |   |                           |
+-----------------------------------------------+   +---------------------------+
| Filters: [Status v] [Type v] [Entity/Action]  |   | [Filter Pills (wrapped)]  |
| +-------------------------------------------+ |   | +-----------------------+ |
| | ID | User | Type | Status | Due At | Act  | |   | | Stacked Card per Row  | |
| | .. | ..   | ..   | ..     | ..     | [Xử] | |   | | [Key: Val]   [Xử lý]  | |
| +-------------------------------------------+ |   | +-----------------------+ |
| (Model Tab: 4 Deployment Cards + CLI Copy Box)|   +---------------------------+
+-----------------------------------------------+
```
- **Component Hierarchy:**
  - **DSR Queue (`admin`):** Filter pills (`status`, `type`, `flex-wrap: wrap`), SLA `due_at` badge (`warn`/`danger`), `"Xử lý"` modal for manual types (`correct|restrict|object`) requiring `note` (`1..2000` chars); read-only badge on automated types (`export|delete|withdraw|access`).
  - **Audit Log (`admin`):** Filter by `actor_user_id`, `entity`, `action`, `from..to`; `monospace` `request_id` copy action (`overflow-wrap: anywhere` so UUIDs wrap cleanly on `320px`).
  - **Model Registry (`ml_operator`):** 4 deployment status cards (`detector`, `freshness`, `ranker`, `substitution`), version table (`version`, SHA-256 prefix, `preprocess_version`, `metrics`, `status`, `is_active`), copyable CLI snippet (`tastoria mlops gate|deploy|rollback ...` styled with `overflow-wrap: anywhere; word-break: break-word;` to prevent `320px` overflow).
  - **Surveys (`ml_operator`):** Survey form table with `respondents_completed / respondents_total` progress bar (`tabular-nums`).
- **Offline / Outbox:** Strictly online (server writes `audit_log` on every read/write).
- **4 Explicit UI States:**
  - `loading`: Table/card skeletons per sub-tab.
  - `empty`: `"Không có yêu cầu dữ liệu nào."`, `"Chưa có bản ghi kiểm toán."`, `"Chưa đăng ký mô hình nào."`, `"Chưa có đợt khảo sát."`.
  - `error`: `403 forbidden` guard card, `409 request_not_manual` / `conflict_state`, `422 reason_required` inline note validation.
  - `success`: Resolved DSR row updates immediately and refreshes Audit Log.
