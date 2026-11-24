# Page Override: `nhat-ky-journal.md` (`/(tabs)/nhat-ky`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(tabs)/nhat-ky`

## Chart Accessibility & Macro Token Overrides
- **Week Navigation:** Replace raw `‹` / `›` glyphs (`nhat-ky.tsx:45, 47`) with SVG `chevron-left` / `chevron-right` buttons (`>= 48dp`, `accessibilityLabel="Tuần trước"` / `"Tuần sau"`).
- **Daily Kcal Bar Chart (T2..CN vs `e_target_kcal`):**
  - Bar fill uses `c.macro.kcal` (when within target or recorded) / `c.herb` (when on target) + direct numeric `tabular-nums` kcal label above each bar (`"chưa nấu"` when `null`).
  - Target dashed horizontal/vertical reference line uses `c.text` (`14.51:1` Light / `15.32:1` Dark) with explicit legend text `"Mục tiêu: X kcal/ngày"`.
  - **Mandatory Screen-Reader & Table Fallback:** Pair the SVG/View bar chart with a collapsible/visible semantic summary table (Day, Trays, Kcal, Urgent Lots Used) and `accessibilityLabel` summary.
- **Macro Breakdown Card (M3/M4):**
  - Use **horizontal stacked/progress macro bars** (`<= 5` categories; NEVER multi-slice pie/donut charts) using verified tokens: `macro.protein` (`Đạm`), `macro.carb` (`Tinh bột`), `macro.fat` (`Chất béo`), `macro.fiber` (`Chất xơ`), always paired with gram values (`tabular-nums`), % of intake, and visible labels.
- **Desktop (`>= 1024px`):** 2-column dashboard (`7fr` KPI row + Daily Kcal Bar Chart + Macro Breakdown; `5fr` Cooked Meal History timeline cards linking to `/mon/[id]`).
