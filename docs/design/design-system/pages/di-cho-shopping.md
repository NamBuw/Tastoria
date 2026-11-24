# Page Override: `di-cho-shopping.md` (`/(tabs)/di-cho`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(tabs)/di-cho`

## Layout & 1-Tap-to-Pantry Overrides
- **Two-Section Responsive Split (`>= 1024px`):**
  - Left column (`7fr`): `Cần mua` (`status === 'open'`) list with `48×48dp` SVG checkbox (`check` icon inside `box`), ingredient name, `tabular-nums` estimated grams + source note (`"cho mâm hôm nay"`), and `"Bỏ"` (`trash` SVG icon, `accessibilityLabel`).
  - Right column (`5fr`): `Đã mua` (`status === 'bought'`) card stack featuring the M3/M4 **1-Tap `"Đưa vào kho"`** button (`POST /shopping-items/{id}/to-pantry`) per item + `"Đưa tất cả vào kho"` batch trigger if multiple bought items exist. When `qty_g === null` (or `to-pantry` returns `422`), open a prefilled `AddLotSheet` fallback for that ingredient; batch `"Đưa tất cả vào kho"` tracks per-item results and summarizes partial failures alongside succeeded items.
- **Mobile (`< 768px`):** Vertical list (`Cần mua` -> `Đã mua`) with sticky/top `"Thêm đồ cần mua"` button opening `AddSheet`.
- **Feedback:** Converting a bought item via `to-pantry` displays a non-focus-stealing `aria-live="polite"` toast (`"Đã thêm <Tên nguyên liệu> vào Kho bếp"`) and refreshes both shopping and pantry queries.
