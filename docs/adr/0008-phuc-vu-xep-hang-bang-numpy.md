# ADR 0008 — Phục vụ xếp hạng gu bằng mảng NumPy đã xuất, không cài LightFM trong API

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M11 `meal`, M07 `mlops`; bảng `model_versions` (`name = ranker`), `model_deployments`, `meal_plans.ranker_version_id`, `interactions.ranker_version_id`; UC15, UC16, UC29, UC30; NFR-PERF-02; BR-CONSENT-03
- Thay cho: v1 §6.6 ("vector LightFM hoặc tệp LightGBM nạp trong tiến trình API")

## Bối cảnh

Bộ xếp hạng gu có 6 bậc (thiết kế v2 §6.1): trung bình món, bias, content-based, MF/BPR tự cài, LightFM, LambdaMART. Mô hình được chọn bằng CV lồng nhau trên khảo sát; chưa biết trước bậc nào thắng. `POST /meal-plans` phải đạt p95 ≤ 1 s với kho 200 món và 30 lô (NFR-PERF-02), trong đó điểm gu chỉ là một phần.

LightFM 1.17 (20/03/2023) là bản cuối, chỉ có sdist, có issue "Can't install on Python 3.12"; conda-forge dừng ở py311; bản fork `lightfm-next` 1.19.0 có wheel cp312/cp313 cho Linux và macOS (R2 §4). Image API dùng Python 3.12. Ngoài ra, chấm điểm là việc tốn CPU; đặt trong handler `async def` sẽ chặn event loop (review:backend_ops#11).

## Các phương án

1. **Cài LightFM (hoặc `lightfm-next`) trong image API, gọi `model.predict`.** Ít mã. Image phụ thuộc một bản fork cộng đồng; build có thể vỡ.
2. **Xuất sang ONNX.** LightFM không có đường xuất ONNX chính thức; thêm công sức mà không lợi về tốc độ ở quy mô 200 món.
3. **Xuất tham số ra mảng NumPy (`.npz`), API tự tính tích vô hướng và bias.** Phụ thuộc phục vụ chỉ còn NumPy.
4. **Lưu vector món trong pgvector, xếp hạng bằng SQL.** Hợp với tìm láng giềng trên kho lớn; với 200 món, tính trong NumPy nhanh hơn một vòng truy vấn và dễ kiểm thử hơn.

## Quyết định

Chọn **phương án 3**.

- Huấn luyện ngoài API (ADR 0012), với `lightfm-next`, mã MF/BPR tự viết, LightGBM. MLflow ghi thí nghiệm.
- Mỗi bậc mô hình được xuất thành một tệp `.npz` theo một định dạng chung: `item_ids`, `item_bias`, `item_vectors`, `feature_ids`, `feature_vectors` (cho đặc trưng người = 5 món hay ăn), `item_mean` (bậc 1, dự phòng), `slot`. Đăng ký bằng UC29 (`tastoria mlops register ranker <artifact> --metrics <json>`), kiểm `sha256`, qua cổng (`tastoria mlops gate`), triển khai bằng con trỏ `model_deployments` (UC30).
- Người dùng mới không cần vector riêng lưu ở server: vector người = tổng vector đặc trưng của các món trong `user_favorite_recipes`, tính lúc request. Không có bảng vector người dùng.
- Không có đồng ý `personalization` hoặc chưa có món hay ăn: dùng `item_mean` và content-based (BR-CONSENT-03).
- Điểm ŝ' = phân vị theo người trong từng slot, rồi bộ ghép mâm cộng các hạng tử ngữ cảnh (thiết kế v2 §6.2). Bộ xếp hạng không chứa tín hiệu kho, calo hay độ gấp.
- Nếu LambdaMART thắng trên khảo sát: phục vụ bằng LightGBM (4.7.0, có wheel cho Python ≥ 3.10), vẫn không cài LightFM. Quyết định này xem lại khi có kết quả CV.
- Hàm chấm điểm viết dạng `def` đồng bộ (FastAPI chạy trong threadpool), mảng nạp một lần khi khởi động theo con trỏ triển khai.
- Mỗi mâm ghi `meal_plans.ranker_version_id` và `params_version`; mỗi tương tác `served` ghi `ranker_version_id` và `propensity`, để đánh giá ngoại tuyến sau này.

## Hệ quả

Tích cực:
- Image API không phụ thuộc thư viện ngừng phát hành; build tái lập được.
- Chấm 200 món là vài phép nhân ma trận nhỏ, cỡ mili giây, để dành ngân sách 1 s cho bước ghép mâm và lịch nấu.
- Định dạng `.npz` chung cho phép so các bậc mô hình bằng cùng một mã phục vụ, và kiểm thử đơn vị bằng mảng nhỏ.

Tiêu cực, cần theo dõi:
- Phải viết lại công thức dự đoán của từng thư viện; cần kiểm thử khớp số: điểm từ `.npz` so với `model.predict` của thư viện gốc trên cùng dữ liệu, sai số dưới 1e-5.
- Mô hình đổi kiến trúc (thêm đặc trưng) thì phải đổi cả trình xuất lẫn mã phục vụ.
- Trọng số xuất ra học từ điểm khảo sát và tương tác; đó là dữ liệu dẫn xuất từ dữ liệu cá nhân. Đánh giá tác động xử lý như dữ liệu bí danh hoá.

## Căn cứ

- review:ml#14 (LightFM ngừng phát hành, lỗi cài trên 3.12), review:backend_ops#11 (registry, chấm điểm chặn event loop, phục vụ bằng vector đã xuất), review:ml#9 (LambdaMART không gộp tín hiệu ngữ cảnh): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R2 §4 bảng thư viện gợi ý: [02-hoc-may-du-lieu-cong-thuc-dinh-duong.md §4](../research/raw/02-hoc-may-du-lieu-cong-thuc-dinh-duong.md#4-recommender-tooling-pypigithub-checked-today).
- R3 §3, khuyến nghị "Serve the ranking model from exported numpy arrays": [03-cong-nghe-vpp-phan-tich-thiet-ke.md §3](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#3-infrastructure-licensing-and-current-versions).
- Thiết kế v2 §3 dòng 20, §6.1 "Phục vụ", §8 "Mô hình".
- LightFM: https://pypi.org/project/lightfm/ , issue #709: https://github.com/lyst/lightfm/issues/709 , lightfm-next: https://pypi.org/project/lightfm-next/ (R2 mở ngày 17/10/2026).
