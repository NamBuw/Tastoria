# ADR 0009 — Lịch nấu cả mâm bằng CP-SAT (OR-Tools)

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M12 `cooking`, M11 `meal`; bảng `recipe_steps`, `cook_sessions`, `cook_schedule_entries`, `user_settings.burners`; `POST /cook-sessions`, `POST /meal-plans`; UC15, UC19; BR-COOK-01, BR-TRAY-05; NFR-PERF-02
- Thay cho: v1 §3.7 (quy tắc LPT, dẫn cận của Graham)

## Bối cảnh

Một người nấu 2–3 món cùng lúc. Mỗi món có các bước theo thứ tự (`recipe_steps.step_no`), mỗi bước là chủ động (người nấu phải làm) hoặc thụ động (chờ), có thể chiếm một họng bếp (`uses_burner`). Bếp gia đình thường có 2 họng (`user_settings.burners`, mặc định 2, CK 1..4). Mục tiêu (BR-COOK-01): người nấu không làm hai bước chủ động cùng lúc; số bước chiếm bếp đồng thời ≤ số họng; mọi món xong trong cửa sổ 5 phút trước giờ dọn, món xào xong cuối.

v1 dùng LPT và dẫn cận (4m − 1)/(3m) của Graham. Cận đó chỉ đúng cho máy song song giống nhau, việc độc lập, tối thiểu makespan. Bài toán ở đây có tài nguyên đơn (người nấu), thứ tự trong món, tài nguyên tích luỹ (họng bếp) và mục tiêu kiểu hạn chót. Không mô hình số họng bếp thì lịch có thể đòi 3 nồi trên 2 bếp (review:ml#15).

Ngoài ra, ghép mâm phải bảo đảm makespan ≤ thời gian tối đa người dùng chọn (BR-TRAY-05), nên bộ ghép mâm cũng cần biết lịch có khả thi không.

## Các phương án

1. **List scheduling có ưu tiên (heuristic tự viết).** Nhanh, dễ hiểu. Không chứng minh được tối ưu; dễ sai ở ràng buộc tích luỹ; phải tự kiểm khả thi.
2. **MILP (CBC/HiGHS) với biến thời gian rời rạc.** Làm được, mô hình hoá interval và NoOverlap cồng kềnh.
3. **CP-SAT (OR-Tools 9.15)**: biến interval, `AddNoOverlap`, `AddCumulative`, ràng buộc thứ tự; bài toán 3 món × ≤ 10 bước giải trong mili giây.
4. **Không xếp lịch, chỉ hiện từng món riêng.** Bỏ một tính năng chính của UC19.

## Quyết định

Chọn **phương án 3**, giữ heuristic của phương án 1 làm dự phòng khi hết giờ giải.

Mô hình (đơn vị giây, gốc thời gian là lúc bắt đầu nấu):
- Mỗi bước s của món r là một interval [start, start + minutes·60).
- Thứ tự: end(r, k) ≤ start(r, k+1).
- `AddNoOverlap` trên các interval có `kind = active`.
- `AddCumulative` với dung lượng = số họng bếp, nhu cầu 1 cho bước có `uses_burner = true`.
- Hoàn thành: mọi món xong trong [T − 300, T], T là giờ dọn (`cook_sessions.serve_at` quy về offset); món có `method_code` xào xong cuối (end ≥ end của mọi món khác).
- Mục tiêu: cực tiểu tổng thời gian chờ giữa lúc món xong và T, rồi cực tiểu makespan.
- Giới hạn thời gian giải 1 s, `num_workers = 1` và seed cố định để kết quả lặp lại được.
- Hết giờ mà chưa có lời giải khả thi: dùng list scheduling theo đường găng ngược từ T, kiểm lại mọi ràng buộc; vẫn không khả thi thì báo người dùng.

Kết quả lưu ở `cook_schedule_entries` (`start_offset_s`, `end_offset_s`), cùng `cook_sessions.burners` (ảnh chụp số họng bếp lúc tạo phiên). App lưu lịch vào SQLite để chế độ nấu chạy offline.

Trong ghép mâm (BR-TRAY-05): không gọi CP-SAT cho mọi tổ hợp. Bộ ghép mâm lọc bằng cận dưới rẻ (max của: tổng phút chủ động; đường dài nhất trong từng món; tổng phút chiếm bếp chia số họng) và chỉ gọi CP-SAT cho vài tổ hợp tốt nhất theo hàm mục tiêu, lần lượt đến khi có một mâm khả thi.

Chỗ đặt mã: bộ giải là hàm thuần (không đọc DB), nhận danh sách bước và số họng bếp. `meal` cần gọi nó, nhưng `meal` không được phụ thuộc `cooking` (`cooking` đã phụ thuộc `meal`). Tạm đặt hàm trong `tastoria.core.scheduling` (M01 `core`, mọi module được dùng) cho tới khi mô hình được bổ sung một chỗ đặt chính thức (đề xuất bổ sung mô hình).

## Hệ quả

Tích cực:
- Lịch luôn thoả ràng buộc theo cấu tạo; kiểm thử tính chất: với mọi mâm ghép được từ kho món và 1–4 họng bếp, lịch không có hai bước chủ động chồng nhau, không vượt số họng.
- Mục tiêu "cùng xong lúc dọn mâm" được biểu diễn trực tiếp, không phải xấp xỉ bằng makespan.
- Dùng được làm nội dung báo cáo môn Học máy/PTƯD (mô hình hoá ràng buộc).

Tiêu cực, cần theo dõi:
- Thêm phụ thuộc `ortools` (wheel lớn) vào image API.
- Ngân sách NFR-PERF-02 bị chia cho bộ giải; phải đo p95 thật với kho 200 món.
- Đặt bộ giải ở `core` làm `core` rộng hơn mô tả trong `model.yaml`.
- `cooking` cần đọc `user_settings.burners` (thuộc `profile`) nhưng `profile` không có trong `deps` của `cooking`; đề xuất bổ sung mô hình.

## Căn cứ

- review:ml#15 (LPT dẫn sai lý thuyết, thiếu ràng buộc họng bếp), tài liệu tham khảo [54] Graham 1969 trong mục "refs 51-60": [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R2 §4 (OR-Tools 9.15, CP-SAT, có wheel cp39–cp313/314): [02-hoc-may-du-lieu-cong-thuc-dinh-duong.md §4](../research/raw/02-hoc-may-du-lieu-cong-thuc-dinh-duong.md#4-recommender-tooling-pypigithub-checked-today).
- Thiết kế v2 §3 dòng 17, BR-COOK-01 và BR-TRAY-05 ở §4.
- OR-Tools CP-SAT: https://developers.google.com/optimization/cp/cp_solver ; lập lịch với interval: https://developers.google.com/optimization/scheduling/job_shop (chưa mở lại trong phiên này).
