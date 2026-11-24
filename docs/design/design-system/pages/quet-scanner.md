# Page Override: `quet-scanner.md` (`/quet`, `/quet/[id]`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/quet` (`?mode=fridge|haul`), `/quet/[id]`

## Freshness Probability, Authenticated Image Fetch & Bounding-Box Visualization
- **Calibrated Freshness Bars (`quet/[id]`):** Bind strictly to **`Scan.classifier_version_id`** (`openapi-v1.yaml:5790`, NOT `freshness_version`) and read `p_tuoi`, `p_dung_som`, `p_dung_ngay`, `p_kiem_tra` from **`ScanItem.detections[]`** (`0..N` `Detection` items):
  - `detections.length === 0` (`origin === 'user_added'`): omit probability bars and show `"Nguyên liệu do bạn tự thêm — chọn độ tươi thủ công"`.
  - `detections.length === 1`: render that detection's 4-row horizontal probability bar chart inside `EditChip` (and compact dominant % badge on the chip):
    - `Tươi`: `c.fresh.tuoi`
    - `Nên dùng sớm`: `c.fresh.dung_som`
    - `Dùng ngay`: `c.fresh.dung_ngay`
    - `Cần kiểm tra`: `c.fresh.kiem_tra`
  - `detections.length > 1` (multi-object chip): default to worst-case urgency detection (`argmax(p_kiem_tra)` / lowest predicted freshness) AND provide a per-detection pill selector (`"Phát hiện #1..#N"`, synced with bbox tap) to inspect individual `Detection.p_*`.
  - Each bar MUST display explicit `tabular-nums` percentage text (e.g., `78%`) + accessible label (`"Xác suất tươi 78%"`). When `Scan.classifier_version_id == null` or all `p_* == null`, show `"Chưa có điểm độ tươi tự động — hãy tự kiểm tra"`.
- **Authenticated Image Fetch & `410 image_purged` Fallback:** Because `GET /scans/{id}/images/{ordinal}` requires `Authorization: Bearer <accessToken>`, NEVER pass the raw endpoint URL directly to `<Image source={{ uri }}>` or `<img src>`. Fetch via `api.GET('/scans/{id}/images/{ordinal}', { parseAs: 'blob' })` -> `URL.createObjectURL(blob)` (revoking on unmount/ordinal change; native uses authenticated blob/data URI). On **`410 image_purged`** (or `404`), show a `c.surfaceAlt` placeholder card (*"Ảnh gốc đã được xoá sau 30 ngày — vẫn có thể sửa và xác nhận nguyên liệu bên dưới"*).
- **Bounding Box Overlay:** Over the loaded scan image, render high-contrast SVG bounding boxes from `item.detections[]` (`strokeWidth: 2`, `c.accent` for selected detection, `c.lime` / `c.focusOnEditorial` with dark pill label using `c.onLime` text on `c.lime` or `c.accentDisplay` so bbox tags remain legible over busy fridge photos — zero raw hexes). Tapping any bbox opens `EditChip` focused on that detection.

## Layout & Iconography Overrides
- **Desktop (`>= 1024px`) `/quet/[id]`:** 2-column split (`5fr` interactive scan image viewer with bbox highlight on left; `7fr` grouped detection chips + `unseen_lots` + confirm footer on right).
- **Mobile (`< 768px`):** Collapsible image strip at top -> `Cần kiểm tra trước khi dùng` group first -> food groups -> `unseen_lots` -> sticky bottom confirm bar (`SafeAreaView` bottom inset).
- **Glyph Fix:** Replace `×${qty}` (`quet/[id].tsx:122`) multiplier symbol with clean Vietnamese unit text (`${qty} đơn vị` or `SL: ${qty}`) or SVG `close` icon where dismissive.
- **Consent Gate:** Show `"Góp ảnh ẩn danh giúp cải thiện AI"` checkbox ONLY when `photo_contribution` consent is active.
