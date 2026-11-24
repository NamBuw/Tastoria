# Page Override: `khao-sat-survey.md` (`/khao-sat`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/khao-sat` (`?kenh=link|qr`) — Public (no login required)

## Layout & Rating Ergonomics
- **Focused Measure:** Even on `>= 1024px` desktop, constrain the active survey flow to `maxWidth: 760px` centered inside the shell (or 2-column dish rating cards up to `920px`) so `1..5` rating buttons stay within natural eye scan.
- **1–5 Rating Controls (`Score`):**
  - All 5 score buttons + `"Chưa ăn bao giờ"` toggle MUST be `>= 48×48dp` with `>= 8px` (`space.sm`) gap between buttons (`tabular-nums` digits `1`–`5`, explicit `accessibilityLabel="Chấm X trên 5 điểm cho món ..."`).
  - Sticky bottom progress footer: `"Đã chấm X/Y món"` (`tabular-nums`) + `"Gửi phiếu"` primary CTA (`disabled` until `answered === items.length`, `422 survey_incomplete` guarded visually).
- **Virtualization:** Use `FlatList` (`windowSize={5}`) for the ~45 assigned dishes to prevent Web/Android scroll lag.
- **Error Recovery:** `401 respondent_token_invalid` renders inline `"Bắt đầu phiếu mới"` button; `409 survey_closed` renders clean closed state linking back to `/` or `/bep`.
