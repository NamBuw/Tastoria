# Page Override: `nau-cooking.md` (`/nau/[id]`, `/nau-xong/[id]`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/nau/[id]`, `/nau-xong/[id]`

## Kitchen Ergonomics & Contrast Overrides
- **Wake-Lock & Arm's-Length Legibility (`/nau/[id]`):** Active step card uses elevated `surface` with `2px` `c.accent` border, `28sp`–`32sp` bold step instruction (`line-height: 1.35`), dish slot badge (`Mặn` / `Rau` / `Canh`), and `>= 56dp` `"Xong bước này"` CTA. Completed step icon uses SVG `check` (replaces `✓` at `nau/[id].tsx:190`).
- **CP-SAT Gantt Timeline (Zero In-Bar Text Labels):**
  - Active hands-on bars: `18px`-tall solid `c.accent` bar (zero text inside bars, preventing clipping on short 2-minute steps at `320px`).
  - Passive waiting/simmering bars: `8px`-tall `c.herbSoft` bar with `2px` `c.herb` border/pattern so active vs passive is distinguishable by **color + bar height + border/pattern + external text legend + step cards below**.
  - Live `"bây giờ"` vertical marker: `2px` `c.text` line with `tabular-nums` timestamp.
- **Absolute-Timestamp Multi-Timer (`"Đang chờ"` & Finished Banner):** Render all concurrent passive timers sorted by earliest `endAt`, formatted as `mm:ss` in `tabular-nums` using `endAt - Date.now()` (zero drift across phone lock). When `elapsed >= e.end_offset_s` and the step is not yet marked done, transition it to an explicit **`"Đã xong giờ chờ"`** banner with a `"Xác nhận xong"` action (never vanish silently).
- **Desktop (`>= 1024px`):** 2-column split (`7fr` Current Step + Multi-Timers + Full Chronological Schedule; `5fr` Sticky CP-SAT Gantt Chart + `serve_at` Clock + `"Nấu xong"` / `"Bỏ phiên nấu"` controls).

## Completion, Outbox `401` Guard & 10-Minute Undo (`/nau-xong/[id]`)
- **Offline Outbox Indicator:** When offline, show `infoSoft` status pill (`"Đã ghi, sẽ đồng bộ khi có mạng"`) + `"Gửi lại ngay"` trigger. Remove `401` from `outbox.ts:109` `retryable()` (since `rawRequest` already attempts `refreshSession()`) and surface a re-login prompt (`"Phiên đăng nhập hết hạn — đăng nhập lại để đồng bộ"`) on terminal `401`.
- **10m Undo Countdown (Clock-Skew Safe):** Prominent secondary outline button `"Hoàn tác (còn mm:ss)"` (`tabular-nums`) pinned above deduction list ONLY while `deadline && left > 0 && !isCode(undo.error, 'undo_window_expired')`; hides immediately upon expiry or `409 undo_window_expired` with guidance to edit lots in `/kho`.
