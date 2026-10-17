# ADR 0007 — Lũy đẳng (`Idempotency-Key`, `event_id`) và Unit of Work cho thao tác nhiều module

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M01 `core`; bảng `idempotency_keys`, `interactions`, `pantry_transactions`, `cook_sessions`, `scans`; `POST /scans`, `POST /meal-plans`, `POST /meal-plans/{id}/items/{itemId}/swap`, `POST /cook-sessions`, `POST /cook-sessions/{id}/complete`, `POST /events`, `POST /scans/{id}/confirm`, `POST /cook-sessions/{id}/undo`; UC12, UC13, UC15, UC16, UC19, UC20, UC21, UC34; BR-SCAN-02, BR-PANTRY-02, BR-COOK-02
- Thay cho: v1 §6.3, §6.5 (không có lũy đẳng, không có ranh giới giao dịch)

## Bối cảnh

Trên mạng di động, request hết thời gian chờ rồi được gửi lại là chuyện thường; app còn có hàng đợi outbox gửi lại khi có mạng (thiết kế v2 §9). Với v1, gửi lại `/complete` trừ kho hai lần, ghi calo hai lần và nhân đôi tín hiệu "cooked" cho mô hình xếp hạng; gửi lại `POST /scans` tạo hai job; gửi lại một lô `/events` làm trùng sự kiện (review:backend_ops#3). Nấu xong phải trừ kho, ghi tương tác và đổi trạng thái trong một giao dịch, nhưng v1 không nói ranh giới giao dịch (review:sad#12).

## Các phương án

Cho lũy đẳng:
1. **Chỉ chống bấm hai lần ở app.** Không chống thư viện HTTP tự thử lại hay outbox gửi lại sau khi server đã xử lý.
2. **Chuyển trạng thái có điều kiện** (`UPDATE … WHERE status = 'in_progress'`). Đủ cho thao tác chuyển trạng thái; không áp được cho thao tác tạo mới (`POST /scans`, `POST /meal-plans`).
3. **Header `Idempotency-Key` + bảng lưu phản hồi**, kèm chuyển trạng thái có điều kiện, và khoá do client sinh cho sự kiện.

Cho thao tác nhiều module:
4. **Mỗi service tự commit.** Lỗi giữa chừng để lại trạng thái nửa vời (kho đã trừ, phiên chưa đóng).
5. **Saga/outbox giữa module.** Cần khi tách dịch vụ; thừa với monolith (ADR 0001).
6. **Unit of Work: một giao dịch DB mở ở tầng endpoint, các service nhận phiên và không tự commit.**

## Quyết định

Chọn **3 + 6**.

**Idempotency-Key** (các endpoint có cột lũy đẳng = `Idempotency-Key` trong `model.yaml`: `POST /scans`, `POST /meal-plans`, `POST /meal-plans/{id}/items/{itemId}/swap`, `POST /cook-sessions`, `POST /cook-sessions/{id}/complete`):
- App sinh UUID cho mỗi thao tác và dùng lại đúng khoá đó khi gửi lại từ outbox.
- Server, trong cùng giao dịch với thao tác:
  1. `pg_advisory_xact_lock(hash(user_id, key))` để hai request trùng chạy song song phải xếp hàng;
  2. tìm `idempotency_keys` theo PK (`user_id`, `key`);
  3. có dòng, cùng `request_sha256` → trả lại `status_code` và `response_body` đã lưu, không chạy lại;
  4. có dòng, khác `request_sha256` → 422 `application/problem+json` với `code` ổn định;
  5. không có → chạy thao tác, ghi dòng mới cùng giao dịch.
- Giữ 48 giờ; UC34 dọn dòng quá hạn.

**`event_id`** cho `POST /events`: app sinh UUID cho mỗi sự kiện, dùng làm `interactions.id`; ghi bằng `INSERT … ON CONFLICT (id) DO NOTHING`. Chỉ server ghi `served` (kèm `position`, `ranker_version_id`, `propensity`); app chỉ gửi sự kiện phía giao diện.

**Chuyển trạng thái có điều kiện** cho các endpoint còn lại có lũy đẳng = `true`, ví dụ `POST /scans/{id}/confirm` chỉ chạy từ `done` (BR-SCAN-02), gọi lại khi đã `confirmed` trả kết quả cũ, không ghi kho lần hai.

**Unit of Work** (M01 `core`): context manager mở một `AsyncSession`/giao dịch; endpoint gọi các service trong đó; commit một lần ở cuối.
- Nấu xong (UC20, `POST /cook-sessions/{id}/complete`): `cooking` chuyển `cook_sessions` `in_progress → completed` có điều kiện; `pantry.deduct()` ghi `pantry_transactions` âm theo lô gấp trước (BR-PANTRY-02); `events.record()` ghi `cooked`/`liked`/`disliked` theo từng món nếu có đồng ý `personalization`; `meal` chuyển `meal_plans` sang `cooked`. Một giao dịch (BR-COOK-02).
- Hoàn tác (UC21, `POST /cook-sessions/{id}/undo`) trong 10 phút: ghi giao dịch đảo trỏ `reverses_id`, ghi `undone`, chuyển phiên sang `reverted`. Không xoá dòng nào.
- Xác nhận quét (UC13): tạo `pantry_lots` + `pantry_transactions` (`scan_add`), chuyển lô không thấy sang `not_seen` khi quét toàn tủ (BR-PANTRY-03), chuyển `scans` sang `confirmed`. Một giao dịch.
- Việc ngoài DB (enqueue RQ, xoá tệp) chạy **sau commit**. Nếu tiến trình chết trước khi enqueue, sweeper (UC34) xếp lại các lần quét `queued` có `enqueued_at` rỗng (ADR 0003).

## Hệ quả

Tích cực:
- Gửi lại bao nhiêu lần, kho cũng chỉ bị trừ một lần; kiểm thử: gửi cùng request hai lần tuần tự và hai lần song song.
- Không có trạng thái nửa vời giữa kho, phiên nấu và tương tác.
- Outbox của app gửi lại an toàn.

Tiêu cực, cần theo dõi:
- `idempotency_keys.response_body` lưu bản sao phản hồi (có thể chứa kcal của mâm) trong 48 giờ. Đánh giá tác động ghi nhận; xoá theo `ON DELETE CASCADE` khi xoá tài khoản.
- Advisory lock giữ trong suốt giao dịch; giao dịch nấu xong phải ngắn (không gọi mạng bên trong).
- Service phải được viết để không tự commit; cần kiểm thử và review để giữ quy ước.
- 422 cho khoá trùng khác nội dung buộc app không tái dùng khoá cho thao tác khác; ghi trong hợp đồng OpenAPI.

## Căn cứ

- review:backend_ops#3 (không lũy đẳng, hoàn tác không có API), review:sad#12 (thiếu ranh giới giao dịch, lũy đẳng), review:backend_ops#15 (outbox khi mất mạng): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §8 "API", "Thao tác nhiều module … Unit of Work"; §9 "Hàng đợi outbox"; BR-SCAN-02, BR-PANTRY-02, BR-COOK-02 ở §4.
- Cột lũy đẳng của từng endpoint: [model.yaml](../sad/model.yaml) (`endpoints`).
- RFC 9457 (Problem Details for HTTP APIs): https://www.rfc-editor.org/rfc/rfc9457.html . PostgreSQL advisory locks: https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS (chưa mở lại trong phiên này).
