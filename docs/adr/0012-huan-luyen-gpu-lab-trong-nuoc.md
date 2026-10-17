# ADR 0012 — Huấn luyện trên GPU của lab trong nước; Colab/Kaggle chỉ cho dữ liệu công khai

- Trạng thái: Chấp nhận (vị trí vật lý của máy chủ lab cần được xác nhận khi rà soát pháp lý)
- Ngày: 2026-10-17
- Phạm vi: M07 `mlops`, M15 `admin`; actor A06, A07; UC28, UC29, UC31; CLI `tastoria mlops export-training-data`, `tastoria labeling push|pull`
- Thay cho: v1 §6.1 ("Huấn luyện trên GPU miễn phí (Colab, Kaggle)"), §7.2 ("khử định danh bằng băm có muối")

## Bối cảnh

Huấn luyện cần: ảnh tủ lạnh của các hộ tham gia và ảnh người dùng góp (bộ phát hiện, bộ phân loại độ tươi), điểm khảo sát và tương tác (bộ xếp hạng). Đây là dữ liệu cá nhân; tương tác và ảnh có thể là dữ liệu nhạy cảm (đánh giá tác động §4).

Luật 91/2025/QH15 Điều 20 khoản 1 điểm c: tổ chức, cá nhân dùng nền tảng ở ngoài lãnh thổ Việt Nam để xử lý dữ liệu cá nhân thu thập tại Việt Nam là chuyển dữ liệu cá nhân xuyên biên giới; khoản 2: phải lập hồ sơ đánh giá tác động chuyển xuyên biên giới và gửi trong 60 ngày. Colab và Kaggle chạy trên hạ tầng ở nước ngoài.

v1 gọi bản xuất là "khử định danh" bằng băm có muối. Nhóm giữ muối và bản xuất giữ chuỗi tương tác theo thời gian, nên luôn nối ngược được: đó là bí danh hoá, dữ liệu vẫn là dữ liệu cá nhân (Luật 91 Điều 2 khoản 1 và 11; review:backend_ops#7). Các mô hình của môn Học máy chạy CPU; đưa lên Colab chỉ thêm biến động môi trường, và thư mục `mlruns` mất khi phiên kết thúc (review:ml#14).

Lab có máy chủ GPU NVIDIA L40S (48 GB) dùng chung với người khác. AutoBatch của Ultralytics chỉ trừ bộ nhớ của chính tiến trình nên có thể chọn batch quá lớn và làm job khác hết bộ nhớ (review:cv#11).

## Các phương án

1. **Colab/Kaggle cho mọi việc huấn luyện.** Miễn phí. Chuyển dữ liệu người dùng ra nước ngoài, phát sinh hồ sơ Điều 20; khó tái lập.
2. **Colab với dữ liệu người dùng, thêm mục đích đồng ý riêng "xử lý ở nước ngoài".** Hợp lệ nếu làm đủ hồ sơ; thêm một mục đích, một hồ sơ, một rủi ro.
3. **Máy chủ lab trong nước cho mọi dữ liệu cá nhân; Colab/Kaggle chỉ cho dữ liệu công khai.**
4. **Huấn luyện trên chính máy chủ phục vụ.** Không có GPU; cạnh tranh tài nguyên với API.

## Quyết định

Chọn **phương án 3**.

- Mọi huấn luyện có dữ liệu cá nhân chạy trên máy chủ lab đặt tại Việt Nam:
  - Mô hình CPU (MF, BPR, LightFM, LightGBM, Word2Vec) chạy trên CPU của máy lab, trong image ghim phiên bản có lockfile.
  - Mô hình GPU (YOLO26n/YOLO11n, MobileNetV3-Small) chạy trên L40S với batch cố định (không `batch=-1`), `torch.cuda.set_per_process_memory_fraction(0.15)`, kiểm `nvidia-smi` trước khi chạy, một job một lúc, chạy thử 1 epoch trước khi chạy dài.
- Colab/Kaggle chỉ nhận dữ liệu công khai (Food.com, Open Images, các bộ CC BY đã ghi nguồn).
- Bản xuất huấn luyện (UC28, `tastoria mlops export-training-data --since <date>`):
  - Gọi đúng là **bí danh hoá**: thay `user_id` bằng HMAC-SHA256 với khoá riêng, không nằm cùng bản xuất.
  - Làm thô thông tin gần định danh (giờ → ngày).
  - Chỉ gồm người có đồng ý `personalization`; ảnh chỉ của người có đồng ý `photo_contribution`.
  - Mỗi lần xuất áp danh sách tài khoản đã xoá và đồng ý đã rút.
  - Bản xuất được bảo vệ như dữ liệu cá nhân nhạy cảm.
- MLflow dùng backend SQLite và thư mục artifact trên máy lab; mỗi run ghi commit, sha256 dữ liệu, seed, danh sách id test, phiên bản thư viện (thiết kế v2 §6.4). Bảng `model_versions.mlflow_run_id` nối registry triển khai với run.
- Gán nhãn (UC31) dùng Label Studio tự host (A10) trên hạ tầng trong nước.
- Ngoại lệ có kiểm soát — baseline Gemini của môn Xử lý ảnh: chỉ dùng ảnh tủ lạnh do nhóm tự chụp ở hộ đã có đồng ý của chủ bếp, gói trả phí. Điều khoản Gemini API cho gói trả phí: Google không dùng prompt và phản hồi để cải thiện sản phẩm, có lưu log trong thời gian giới hạn để chống lạm dụng, và dữ liệu "may be stored transiently or cached in any country". Vì vậy đây vẫn là xử lý trên nền tảng ở nước ngoài theo Điều 20 khoản 1 điểm c nếu ảnh chứa dữ liệu cá nhân. Trước khi gửi, nhóm kiểm từng ảnh không có người, giấy tờ, nhãn thuốc hay thông tin nhận dạng; việc có cần hồ sơ Điều 20 khoản 2 hay không ghi vào danh sách rà soát pháp lý.

## Hệ quả

Tích cực:
- Luồng dữ liệu người dùng trong hệ thống không ra nước ngoài, không phát sinh hồ sơ chuyển xuyên biên giới cho phần huấn luyện.
- Thí nghiệm tái lập được (cùng máy, cùng image, MLflow không mất).
- Không làm job của người khác trên GPU dùng chung hết bộ nhớ.

Tiêu cực, cần theo dõi:
- Phụ thuộc lịch dùng chung của máy lab; GPU có thể bận khi cần.
- Giới hạn bộ nhớ ≈ 7 GB làm batch nhỏ, huấn luyện chậm hơn.
- Ngoại lệ Gemini vẫn là điểm cần rà soát pháp lý.
- Vị trí vật lý của máy lab (trong nước) là giả định của quyết định này; nếu sai, quyết định phải xem lại.

## Căn cứ

- review:backend_ops#7 (bí danh hoá, Colab/Kaggle là chuyển xuyên biên giới), review:ml#14 (tái lập, MLflow), review:cv#11 (AutoBatch trên GPU dùng chung): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R1 §5 (Gemini trả `box_2d`, gói trả phí cho ảnh người dùng) và §7: [01-xu-ly-anh-du-lieu-mo-hinh.md §5](../research/raw/01-xu-ly-anh-du-lieu-mo-hinh.md#5-gemini-api-object-detection), [§7](../research/raw/01-xu-ly-anh-du-lieu-mo-hinh.md#7-recommended-plan).
- Thiết kế v2 §3 dòng 21–22, §6.4, §7 "Bộ phát hiện", "Gemini".
- Luật 91/2025/QH15 Điều 2 khoản 1, 11: https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-2 ; Điều 20 khoản 1, 2, 6: https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-20 (mở ngày 17/10/2026; bản đăng lại, chưa đối chiếu Công báo).
- Điều khoản Gemini API, mục Paid Services: https://ai.google.dev/gemini-api/terms (mở ngày 17/10/2026).
- Đánh giá tác động: [07-danh-gia-tac-dong-du-lieu-ca-nhan.md](../sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md).
