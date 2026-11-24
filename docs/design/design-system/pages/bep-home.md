# Page Override: `bep-home.md` (`/(tabs)/bep`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(tabs)/bep` (also `/` redirects here when signed in)

## Bug Fix & Defect Elimination
- **Remove Duplicate `<FoodStory compact />` (`bep.tsx:237`):** `ScanTile` MUST contain only its icon badge, title, and subtitle — never a nested `FoodStory` card.
- **Fix Primary `ScanTile` Icon Contrast (`bep.tsx:233`):** Replace hardcoded `'rgba(255,255,255,0.18)'` circle fill with theme-aware token overlay (`c.onAccent` at `0.16` alpha or `c.surface` pill with `c.accent` icon) so dark mode (`c.onAccent: #2A0E0C` on `#F2948A`) maintains crisp icon contrast (`>= 4.5:1`).

## Responsive Layout Overrides
- **Mobile (`< 768px`):** Vertical stack inside `16px` gutter: BrandHeader + Header Actions (`Khám phá`, `Cài đặt`, conditional `Quản trị` pill rendered ONLY when `user.role === 'admin' || user.role === 'ml_operator'`, never for `user` or CLI-only `curator`) -> Today's Meal Hero Card (`Tray` compact + 3 active dish titles + `/mam` link) -> 2-col Quick Scan Tiles (`Chụp tủ lạnh` / `Chụp đồ vừa mua`) -> Horizontal Urgent Pantry Strip (`dung_ngay`, `dung_som`, `kiem_tra`) -> Editorial `FoodStory` + Journal CTA card.
- **Desktop (`>= 1024px`):** 2-column bento grid (`maxWidth: 1240px`):
  - Left column (`7fr`): Today's Meal Hero Card (enlarged `Tray` SVG `220px` side-by-side with dish list) + Urgent Pantry Grid (up to 6 visible cards before `"Xem kho"`).
  - Right column (`5fr`): Quick Scan Tiles + Quick Recipe Explorer shortcut (`/kham-pha`) + `FoodStory` / Journal summary card.

## Iconography & States
- Replace `→` (`bep.tsx:185`) with SVG `<Icon name="arrow-right" />`.
- Plan `404` renders actionable Empty card (`"Ra mâm từ đồ đang có"` -> `/mam`), never an error alert.
