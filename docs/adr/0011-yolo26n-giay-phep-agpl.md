# ADR 0011 — Bộ phát hiện YOLO26n và nghĩa vụ giấy phép AGPL-3.0

- Trạng thái: Chấp nhận (phần giấy phép cần rà soát pháp lý trước khi phát hành)
- Ngày: 2026-10-17
- Phạm vi: M08 `scan` (worker suy luận), M07 `mlops`; bảng `model_versions` (`name = detector`), `model_version_classes`, `vision_classes`, `scans.detector_version_id`; UC12, UC29, UC30
- Thay cho: v1 §3.2, tài liệu tham khảo [30] ("Ultralytics YOLOv8, phiên bản 8.0.0, 2023")

## Bối cảnh

Bộ phát hiện nhận ~20 lớp nguyên liệu trong ảnh tủ lạnh, chạy ONNX trên CPU của máy chủ (`--cpus=2 --memory=4g`), mục tiêu p95 ≤ 3 s cho cả lần quét (NFR-PERF-01). Tủ lạnh có nhiều vật nhỏ (ớt, tỏi, chanh).

Đến 10/2026, Ultralytics đã lên 8.4.x, mô hình mặc định là YOLO26. Trên bảng COCO của Ultralytics: YOLO26n 2,4 triệu tham số, 40,9 mAP50-95 (40,1 end-to-end), 38,9 ms CPU ONNX, không cần NMS; YOLO11n 2,6 triệu, 39,5 mAP, 56,1 ms; YOLOv8n 3,2 triệu, 37,3 mAP, 80,4 ms (R1 §3, review:cv#11).

Mọi mô hình Ultralytics phát hành theo AGPL-3.0 hoặc giấy phép Enterprise trả phí. Trang giấy phép của Ultralytics nói AGPL "covers the training code and the models produced", và triển khai dạng SaaS/API vẫn phải mở toàn bộ mã dự án hoặc mua Enterprise; đồ án học tập nằm trong nhóm dùng AGPL miễn phí, không phải ngoại lệ (R1 §3, R3 §3).

## Các phương án

1. **YOLO26n (chính) và YOLO11n (so sánh), AGPL-3.0.** Tốt nhất về độ trễ CPU và độ chính xác trong nhóm nano; công cụ huấn luyện, xuất ONNX và tài liệu đầy đủ.
2. **Mô hình Apache-2.0: D-FINE-N (4 triệu tham số, 42,8 mAP), DEIM-D-FINE-N, RF-DETR-N (30,5 triệu), RT-DETRv2-S.** Không vướng AGPL. Chưa có số đo CPU công bố; RF-DETR-N lớn hơn nhiều; công cụ kém tiện hơn.
3. **Chỉ dùng Gemini (API).** Không phải huấn luyện. Ảnh người dùng ra nước ngoài (ADR 0012), chi phí theo lượt, không có điểm tin cậy; mất sản phẩm chính của môn Xử lý ảnh.
4. **Mua giấy phép Enterprise.** Không hợp với đồ án.

## Quyết định

- Chọn **phương án 1**: YOLO26n là mô hình chính, YOLO11n so sánh, mỗi mô hình thử imgsz 640 và 960; chọn trên tập val rồi khoá trước khi chạy test. Ghim một bản `ultralytics==8.4.x` cụ thể, ghi đúng phiên bản trong tài liệu tham khảo.
- Giữ **D-FINE-N** (hoặc RF-DETR-N) làm mô hình so sánh Apache-2.0 và là lối thoát giấy phép nếu dự án thương mại hoá.
- Suy luận trong worker bằng `onnxruntime`, không cài `ultralytics` trong image phục vụ. Việc này không làm mất nghĩa vụ AGPL theo cách Ultralytics diễn giải (mô hình sinh ra cũng thuộc AGPL).
- Nghĩa vụ AGPL-3.0 §13 (người dùng tương tác qua mạng phải được nhận mã nguồn):
  - Repo mã nguồn công khai theo AGPL-3.0 (cần người dùng đồng ý đẩy repo lên GitHub, thiết kế v2 §13 mục 4).
  - App và landing có liên kết "Mã nguồn" tới đúng commit đang chạy.
  - Trọng số được công bố chỉ là bản huấn luyện trên dữ liệu công khai và ảnh của nhóm có đồng ý chủ bếp. Bản huấn luyện thêm ảnh người dùng góp (`photo_contribution`) không công bố trọng số khi chưa có rà soát pháp lý về việc này.
- Mỗi `model_versions` của bộ phát hiện ghi `sha256`, `preprocess_version`, bản đồ lớp (`model_version_classes` → `vision_classes`); mỗi lần quét ghi `scans.detector_version_id`.

## Hệ quả

Tích cực:
- Độ trễ CPU thấp nhất trong các lựa chọn đã đo công khai, hợp với máy 2 vCPU.
- Đầu ra không cần NMS và cách gán nhãn ưu tiên vật nhỏ hợp bài toán tủ lạnh.
- Có lối thoát giấy phép đã được đo trong cùng thí nghiệm.

Tiêu cực, cần theo dõi:
- Toàn bộ mã backend phải công khai theo AGPL; không giữ được phần nào làm mã đóng.
- Cách Ultralytics diễn giải phạm vi AGPL cho trọng số và mô hình xuất ONNX là quan điểm của nhà phát hành, chưa được kiểm chứng pháp lý.
- Xung đột tiềm ẩn giữa nghĩa vụ công bố mã/mô hình và bảo vệ dữ liệu cá nhân nếu trọng số học từ ảnh người dùng; đã chặn bằng quy tắc công bố ở trên, ghi vào đánh giá tác động.

## Căn cứ

- review:cv#11 (bộ phát hiện cũ hai thế hệ, chưa chọn imgsz, GPU dùng chung): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R1 §3 bảng bộ phát hiện và đoạn "What AGPL means here": [01-xu-ly-anh-du-lieu-mo-hinh.md §3](../research/raw/01-xu-ly-anh-du-lieu-mo-hinh.md#3-detector-choice-oct-2026); R1 §7 mục Detector: [01-xu-ly-anh-du-lieu-mo-hinh.md §7](../research/raw/01-xu-ly-anh-du-lieu-mo-hinh.md#7-recommended-plan).
- R3 §3 (Ultralytics AGPL, khuyến nghị giữ repo công khai): [03-cong-nghe-vpp-phan-tich-thiet-ke.md §3](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#3-infrastructure-licensing-and-current-versions).
- Thiết kế v2 §3 dòng 1, §7 "Bộ phát hiện".
- Ultralytics models: https://docs.ultralytics.com/models/ ; giấy phép: https://www.ultralytics.com/license ; D-FINE: https://github.com/Peterande/D-FINE ; RF-DETR: https://github.com/roboflow/rf-detr (R1 mở ngày 17/10/2026).
- AGPL-3.0 §13 "Remote Network Interaction": https://www.gnu.org/licenses/agpl-3.0.html (chưa mở lại trong phiên này).
