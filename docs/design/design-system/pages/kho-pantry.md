# Page Override: `kho-pantry.md` (`/(tabs)/kho`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(tabs)/kho`

## Layout & Virtualization Overrides
- **Mobile (`< 768px`):** Single-column `FlatList` (`windowSize={5}`, `React.memo` row cards) below sticky urgency filter strip (`Tất cả`, `Dùng ngay`, `Nên dùng sớm`, `Tươi`, `Cần kiểm tra`, `Chưa thấy`) + search/sort bar (`Khẩn cấp nhất` vs `Mới thêm`).
- **Desktop (`>= 1024px`):** Top filter toolbar (search input + urgency filter chips + sort toggle + `"Thêm đồ"` / `"Quét ảnh"` buttons) above a **2–3 column responsive lot card grid** (`gap: 16px`, `maxWidth: 1240px`), with `AddLotSheet` / `EditLotSheet` opening as centered `520px` modal dialogs (`elev.3`) rather than full-width bottom sheets.

## Domain & Accessibility Rules
- **`FreshBadge` Pairing:** Every lot card MUST display `FreshBadge` (shape-coded dot + color + Vietnamese label) alongside `balance_g_min..max` formatted with `tabular-nums`.
- **Check-Level & Not-Seen Guardrails:** Lots with `urgency > 1.0` / `kiem_tra` (`available = false`) display a distinct `warnSoft` top banner and an explicit `"Xác nhận còn tươi / dùng được"` action (`PATCH /pantry/lots/{id} { user_checked: true }`). `not_seen` lots highlight `"Chưa thấy trong lần quét gần nhất"` with 1-tap confirm or discard.
- **Quick-Add Presets:** Include fast Vietnamese kitchen staples strip (`Trứng gà`, `Đậu phụ`, `Thịt lợn`, `Rau muống`, `Cà chua`, `Hành lá`) inside `AddLotSheet` with `>= 48dp` chip targets.
