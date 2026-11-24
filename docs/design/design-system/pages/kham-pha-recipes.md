# Page Override: `kham-pha-recipes.md` (`/kham-pha`, `/mon/[id]`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/kham-pha` (`app/src/app/kham-pha.tsx`, placed outside `(tabs)/` in root `<Stack>`), `/mon/[id]` (`?plan=...&item=...`)

## Navigation Placement
- **Expo Router Structure:** `kham-pha.tsx` MUST live outside `(tabs)/` (matching `cai-dat.tsx` and `quan-tri.tsx`) so mobile `<Tabs>` stays strictly `<= 5` tabs (`Bếp nhà`, `Kho bếp`, `Mâm cơm`, `Đi chợ`, `Nhật ký`).
- **Desktop (`>= 1024px`) & Tablet (`768–1023px`):** Dedicated top-level link `"Khám phá"` in the `AppShell` left sidebar rail (`248px` desktop / `72px` compact rail tablet) using `compass` SVG icon.
- **Mobile (`< 768px`):** Accessible from Home (`bep`) quick action bar and header `"Khám phá"` button.

## Layout & Component Overrides
- **Explorer (`kham-pha`):**
  - Search input (`q`) + horizontal filter chips: Slot (`Tất cả`, `Mặn`, `Rau`, `Canh`), Max time (`<=20p`, `<=30p`, `<=45p`), Method (`Kho`, `Xào`, `Luộc`, `Canh`), and `"Đủ đồ trong kho"` pantry-match toggle.
  - Responsive Grid: `1 col` (`<768px`), `2 cols` (`768–1023px`), `3 cols` (`>=1024px`, `maxWidth: 1240px`).
  - Recipe Card: Slot pill, Vietnamese dish name (`h3`), `total_minutes`, `kcal_per_serving` (`tabular-nums`), mini 3-macro summary (`P / C / F` grams using `macro.protein`, `macro.carb`, `macro.fat` with text prefixes `"Đạm"`, `"Bột"`, `"Béo"`), and Pantry Match badge (`Đủ nguyên liệu` in `herbSoft` vs `Thiếu X món` in `warnSoft`).
- **Recipe Detail (`mon/[id]`):**
  - Desktop `>= 1024px`: 2-column split (`4fr` Ingredients w/ pantry match + Macro/Nutrition table + Make-ahead card; `8fr` Numbered cooking steps distinguishing `active` vs `passive` + burner badge + Sources).
  - Offline Fallback: Reads `useCatalog()` (`tastoria.catalog.v1`) seamlessly when offline, displaying a subtle `infoSoft` offline banner (`"Đang xem từ bộ nhớ đệm ngoại tuyến"`).
