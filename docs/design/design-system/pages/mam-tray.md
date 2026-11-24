# Page Override: `mam-tray.md` (`/(tabs)/mam`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(tabs)/mam`

## Responsive Split Workspace (`>= 1024px` vs `< 768px`)
- **Desktop (`>= 1024px`):** 2-column split (`maxWidth: 1240px`):
  - Left column (`5fr`, sticky): `MealSwitch` (`Bữa trưa` / `Bữa tối`), interactive top-down lacquered `Tray` SVG (`360px`), `"Cơm X bát"` pill, `KcalBar` with target vertical marker, and primary `"Nhận mâm và nấu"` / `"Nấu cả mâm"` CTA.
  - Right column (`7fr`): Slot cards (`Mặn`, `Rau`, `Canh`) with inline `"Đổi món"` / `"Thiếu gì?"` / `"Xem công thức"`, `reason_vi` Ranker explanation chip (showing `ranker_version_id` badge when ML Ranker active), inline `persons` stepper (`1–6`), `serve_at` selector, and Composer re-roll drawer.
- **Mobile (`< 768px`):** Single-column flow (`Tray` clamped via `Math.min(width - 48, 300)` -> `<= 272px` on `320px` viewport above Slot cards, dish actions opening `Sheet`).

## Hybrid Substitutes, Shortfall & Idempotency UX
- **Substitute Origin Badges:** Inside `"Thiếu gì?"` sheet, clearly distinguish candidate origin:
  - `origin === 'lookup'`: `"Gợi ý chuẩn"` (`herbSoft` bg, `herb` text).
  - `origin === 'embedding'`: `"Tương đồng ngữ nghĩa & dinh dưỡng"` (`infoSoft` bg, `info` text, `sparkles` SVG icon).
  - Show `in_pantry` (`available_g_min`), conversion `ratio` / `grams`, and 1-tap `"Dùng thay"` or `"Thêm vào đi chợ"`.
- **Infeasible Tray (`422 no_feasible_tray`) & `Idempotency-Key` Reset:** Render `NoTray` card listing `shortfalls[]` (nearest tray preview + missing grams) with 1-tap `"Thêm vào đi chợ"` buttons (`mam.tsx:244` `"Đã thêm"` uses SVG `check` icon instead of `✓`). **CRITICAL:** Call `idem.reset()` in `onError` on terminal `4xx` responses (all codes except `409 idempotency_in_progress`) for `create_plan`, `swap_item`, and `create_session`, preventing 48h cached `422 no_feasible_tray` replay after restocking via `di-cho` -> `to-pantry`.
