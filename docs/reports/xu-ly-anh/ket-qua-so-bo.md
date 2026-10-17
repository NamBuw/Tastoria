# Xử lý ảnh Tastoria: kết quả sơ bộ trên dữ liệu công khai

Ngày chạy: 17/10/2026. Mọi số dưới đây đọc từ tệp kết quả trong `data/processed/cv/` (đường dẫn ghi
cạnh từng bảng). **Toàn bộ là kết quả trên dữ liệu công khai, không có ảnh tủ lạnh nào của nhóm.**
Chúng chỉ cho biết đường ống chạy được và đặt mốc baseline. Chúng không cho biết mô hình hoạt động thế nào
trong tủ lạnh Việt Nam. Số dùng cho báo cáo môn học phải đo lại trên ảnh nhóm tự chụp (mục 8).

## 1. Đã làm gì

| Bước | Mã | Đầu ra |
|---|---|---|
| Bảng lớp thị giác (22 lớp) | `ml/src/tastoria_ml/cv/classes.py` | `data/kb/vision_classes.yaml` |
| Tải Open Images V7 (lọc theo lớp, không cần tài khoản) | `cv/openimages.py` | `data/raw/images/openimages_v7/` (SOURCE.md) |
| Tải bộ rau Bangladesh (Mendeley, CC BY 4.0) | tải tay bằng URL công khai | `data/raw/images/mendeley_bd_vegetables/` (SOURCE.md) |
| Ánh xạ nhãn, khử trùng lặp pHash, dựng bộ YOLO | `cv/build_yolo.py`, `cv/phash.py`, `cv/yolo_format.py` | `data/processed/cv/manifest.csv`, `dataset_stats.json`, `yolo/` |
| Tiền xử lý: gray-world, shades-of-gray, CLAHE trên L | `cv/preprocess.py` | dùng cho ablation |
| Huấn luyện YOLO26n, đánh giá, ONNX, đo độ trễ CPU | `cv/train_detector.py` | `data/processed/cv/detector/*.json`, MLflow |
| Độ tươi: SVM đặc trưng cổ điển vs MobileNetV3-Small | `cv/freshness.py` | `data/processed/cv/freshness/*.json`, MLflow |

Môi trường huấn luyện tách riêng khỏi môi trường dự án (ultralytics, torch không thuộc phụ thuộc của
`tastoria-ml`): `ml/runs/venv-cv` (gitignore), Python 3.12, `ultralytics==8.4.173`, `torch==2.8.0+cu126`,
`mlflow 3.17.1`, `onnxruntime 1.31.0`. Các hàm thuần numpy (`preprocess`, `phash`, `yolo_format`,
`classes`) chạy và được kiểm thử trong môi trường dự án: `uv run --package tastoria-ml pytest ml/tests -q`.

MLflow: `sqlite:///ml/mlruns/mlflow.db`, artifact ở `ml/mlruns/artifacts` (đều gitignore). Hai experiment:
`tastoria-detector-public`, `tastoria-freshness-public`.

## 2. Bảng lớp

22 lớp chọn theo tiêu chí của thiết kế v2 §7: (a) nguyên liệu chính (`main`) của món mặn/rau/canh trong
`dish_list.yaml`, (b) thường để ngăn mát, (c) tách được bằng mắt. Điểm (c) mới là giả thuyết, phải kiểm bằng
vòng gán thử. Mỗi lớp ghi tên Việt/Anh, danh sách nguyên liệu ánh xạ (nhiều–nhiều), đếm được hay không,
định nghĩa một thể hiện, có mô hình độ tươi hay không, nguồn dữ liệu công khai và nhãn cha dự phòng.
Số món ở cột `dish_main_count` được test đếm lại từ `dish_list.yaml`.

- **13 lớp có dữ liệu công khai** nên có trong baseline: cá, tôm, trứng, cà chua, cà rốt, khoai tây, bắp cải,
  súp lơ, bí đỏ, bí đao (gồm bầu), mướp đắng, đậu que, nấm.
- **9 lớp không có dữ liệu công khai tải được mà không cần khoá:** thịt lợn, thịt bò, thịt gà, đậu phụ, su su,
  mướp, rau cải (nhãn cha), rau muống, giá đỗ. Trong đó thịt lợn (47 món), đậu phụ (16) và thịt bò (10) là
  những lớp quan trọng nhất của kho món. Mướp không có ở bộ nào, kể cả Roboflow.
- Đã loại: mực (thường để ngăn đá), dưa chuột (không là `main` của món nào), hành tây và hành lá (phụ liệu),
  cà tím và đậu bắp (ít món, để dự phòng), nhóm rau canh mồng tơi/rau ngót/rau dền (khó tách bằng mắt).

## 3. Dữ liệu phát hiện

### 3.1 Nguồn

| Nguồn | Giấy phép | Lấy gì |
|---|---|---|
| Open Images V7, tập boxable | nhãn CC BY 4.0; ảnh CC BY 2.0 **theo từng ảnh** (manifest chép License, Author, OriginalURL) | 11 nhãn: Tomato, Egg, Cabbage, Carrot, Potato, Broccoli, Pumpkin, Winter melon, Fish, Shrimp, Mushroom. Tối đa 1.500 ảnh/nhãn ở train, 250 ở val/test; bỏ ảnh có khung "depiction" (tranh vẽ, đồ chơi) |
| Jahan et al. 2025, Mendeley gnc4s3z2mf v3 | CC BY 4.0 | 9 nhãn: Tomato, Carrots, Potato, Cabbage, Cauliflower, Pumpkin, Bottle gourd, Bitter Gourd, Green Beans |

Ảnh Open Images được tải dưới dạng thumbnail khoảng 640 px (`Thumbnail300KURL`): 9.042 ảnh. 1.833 ảnh đã
mất thumbnail nên lấy từ bucket S3 công khai rồi thu về cạnh dài 1.024 px. Không ảnh nào tải lỗi. Dung lượng
ảnh là 1,1 GB.

**Roboflow Universe (chưa tải, cần API key):** Viet Hoang Food (thịt ba chỉ, sườn, giá, cải chíp), Robo1
INGREDIENTS (cải chíp, cải thảo, su su, giá, mướp đắng), SmartPantry (đậu phụ, thịt lợn), Nhận Diện Rau
(rau muống), water-spinach-disease, Phcs vegetables (đậu phụ, bí đao), aicook (bò, gà; MIT). Đây là con
đường nhanh nhất để có dữ liệu cho 6/9 lớp đang trống. Trước khi dùng phải kiểm ảnh, nguồn gốc ảnh và giấy
phép thật, vì các bộ cộng đồng này có thể chứa ảnh cào từ web.

### 3.2 Chia tập và khử trùng lặp

- Open Images giữ nguyên chia train / validation / test gốc.
- Bộ Bangladesh có 3.534 khung hình cắt từ **chỉ 10 video**. Chia tập gốc của bộ này trộn các khung của cùng
  một video vào cả train lẫn test, nên ta chia theo video: val = `VID_20250228_135247`, test =
  `VID_20250228_124329` (hai video nhỏ có đủ 9 nhãn), 8 video còn lại làm train.
- pHash 64 bit, Hamming ≤ 4, duyệt theo thứ tự test → val → train để ảnh train trùng ảnh test bị bỏ chứ không
  phải ngược lại. Kết quả bỏ 383 khung Bangladesh ở train, 1 ở val và 2 ảnh Open Images ở train.
- Ảnh nền (không có khung nào của lớp ta) chỉ có 322 ảnh trong train, tức 2,9%, thấp hơn mục tiêu 5–10%.
  Tất cả đều là khung Bangladesh chụp quầy rau không có lớp ta.

### 3.3 Số lượng (`data/processed/cv/dataset_stats.json`)

Ảnh: train 11.091, val 897, test 2.035 (Open Images 8.558 / 685 / 1.630; Bangladesh 2.533 / 212 / 405).

| Lớp | Khung train | Khung val | Khung test | Nguồn |
|---|---:|---:|---:|---|
| ca (cá) | 6.717 | 468 | 410 | OI |
| tom (tôm) | 1.771 | 135 | 364 | OI |
| trung (trứng) | 1.704 | 179 | 644 | OI |
| ca_chua (cà chua) | 14.619 | 801 | 2.870 | OI + BD |
| ca_rot (cà rốt) | 3.727 | 330 | 329 | OI + BD |
| khoai_tay (khoai tây) | 2.896 | 386 | 378 | OI + BD |
| bap_cai (bắp cải) | 1.764 | 89 | 236 | OI + BD |
| sup_lo (súp lơ) | 3.328 | 217 | 628 | OI + BD |
| bi_do (bí đỏ) | 7.817 | 533 | 411 | OI + BD |
| bi_dao (bí đao/bầu) | 2.249 | 185 | 149 | OI (rất ít) + BD |
| muop_dang (mướp đắng) | 2.539 | 166 | 273 | BD |
| dau_que (đậu que) | 5.966 | 99 | 787 | BD |
| nam (nấm) | 3.561 | 137 | 467 | OI |

Mọi lớp đều vượt mốc 300 vật thể train và 30–50 vật thể test của thiết kế. Nhưng các vật thể này không
phải ảnh tủ lạnh. Có 4.693 khung là group_of (Open Images `IsGroupOf=1`).

## 4. Bộ phát hiện baseline: YOLO26n, 640 px

Cấu hình: khởi tạo từ `yolo26n.pt` (COCO; sha256 `9b09cc8b…8ad4fef`), imgsz 640, batch 16 cố định, tối đa
100 epoch, patience 15, seed 0, tăng cường mặc định của ultralytics, không tiền xử lý (nhánh `none`).
Kết quả lấy từ `data/processed/cv/detector/yolo26n_640_none.json`.

- Dừng sớm sau 59 epoch, epoch tốt nhất là 44 (theo mAP50-95 val). Thời gian huấn luyện 3.858 giây.
  Bộ nhớ CUDA reserved cao nhất 3,65 GiB.
- **Val:** mAP50 0,513, mAP50-95 0,340 (P 0,507, R 0,533).
- **Test:** mAP50 0,424, mAP50-95 0,278 (P 0,463, R 0,435).

| Lớp | val mAP50 | val mAP50-95 | test mAP50 | test mAP50-95 |
|---|---:|---:|---:|---:|
| ca | 0,476 | 0,339 | 0,474 | 0,344 |
| tom | 0,513 | 0,374 | 0,476 | 0,356 |
| trung | 0,523 | 0,413 | 0,500 | 0,406 |
| ca_chua | 0,476 | 0,305 | 0,301 | 0,176 |
| ca_rot | 0,372 | 0,208 | 0,272 | 0,176 |
| khoai_tay | 0,276 | 0,159 | 0,368 | 0,273 |
| bap_cai | 0,872 | 0,668 | 0,554 | 0,386 |
| sup_lo | 0,537 | 0,352 | 0,616 | 0,326 |
| bi_do | 0,861 | 0,616 | 0,721 | 0,460 |
| bi_dao | 0,474 | 0,253 | 0,122 | 0,068 |
| muop_dang | 0,303 | 0,121 | 0,172 | 0,052 |
| dau_que | 0,381 | 0,137 | 0,246 | 0,070 |
| nam | 0,602 | 0,473 | 0,686 | 0,519 |

Đọc kết quả:
- Các lớp chủ yếu từ quầy rau Bangladesh (đậu que, mướp đắng, bí đao/bầu) giảm mạnh từ val sang test. Val
  và test ở đây mỗi tập chỉ là **một video**, nên số theo lớp dao động lớn và phụ thuộc video được chọn.
  Ở đậu que và mướp đắng, mAP50-95 thấp hơn hẳn mAP50, tức là khung đặt chưa khít trên đống rau xếp chồng.
- Cà chua có nhiều khung nhất nhưng điểm test thấp (0,301). 2.870 khung test phần lớn là cà chua chồng
  chất trên quầy Bangladesh.
- Bản đồ val dùng để chọn epoch, test chỉ chạy một lần sau khi chọn.

## 5. Ablation tiền xử lý 2×2 (1 seed, 25 epoch)

Bốn nhánh huấn luyện cùng cấu hình: YOLO26n, 640 px, batch 16, seed 0, 25 epoch, không dừng sớm, tăng cường
mặc định. Tiền xử lý áp lên toàn ảnh, giống nhau cho train, val và test (`train_detector prep-arm`). CLAHE dùng
clip 2,0, lưới 8×8. Gray-world tính trên RGB tuyến tính, bỏ điểm cháy, hệ số khuếch đại kẹp trong [0,5; 2].
Kết quả lấy từ `data/processed/cv/detector/abl25_<nhánh>.json`.

| Nhánh | val mAP50 | val mAP50-95 | test mAP50 | test mAP50-95 | epoch tốt nhất |
|---|---:|---:|---:|---:|---:|
| none | 0,520 | 0,341 | 0,402 | 0,258 | 11 |
| gw (gray-world) | 0,507 | 0,339 | 0,407 | 0,271 | 25 |
| clahe (CLAHE trên L) | 0,493 | 0,328 | 0,397 | 0,254 | 15 |
| gw_clahe | 0,501 | 0,337 | 0,400 | 0,264 | 25 |

**Chưa kết luận được gì.** Mỗi nhánh chỉ có một seed. Chênh lệch val mAP50-95 giữa các nhánh (0,328–0,341)
nằm trong biên tương đương ±1,5 điểm đã định trước. Trên val, nhánh none cao nhất. Trên test, gw và gw_clahe
cao hơn none 0,6–1,3 điểm mAP50-95, nhưng hai nhánh này vẫn đang tăng ở epoch 25 còn nhánh none đạt đỉnh ở
epoch 11, nên 25 epoch chưa đủ để so công bằng. Báo cáo cuối cần: ≥ 3 seed mỗi nhánh, chạy đến hội tụ (hoặc
dừng sớm theo val), bootstrap cụm có cặp, và chọn tham số CLAHE trên val. Quan trọng nhất là chạy trên ảnh tủ
lạnh của nhóm. Ảnh mẫu cho thấy gray-world làm ám tím khung hình toàn rau xanh (đúng như lo ngại ở review:cv#7);
bộ kẹp hệ số chỉ hạn chế được một phần.

So với baseline 100 epoch (mục 4, test mAP50-95 0,278), cả bốn nhánh 25 epoch đều thấp hơn 0,7–2,4 điểm.


## 6. ONNX và độ trễ CPU

Xuất `best.pt` của baseline sang ONNX bằng `model.export(format="onnx")` với opset mặc định (ra opset 18), tệp
9.803.051 byte (sha256 `c7d67aff…199cd36`). Đầu ra `output0` có dạng [1, 17, 8400], là đầu ra thô cần ngưỡng
và NMS phía sau, không phải đầu ra end-to-end. Tệp `.onnx` không commit (`ml/runs/`).

Đo bằng onnxruntime 1.31.0, `intra_op_num_threads=2`, `inter_op_num_threads=1`, trên 100 ảnh val (chọn ngẫu
nhiên, seed 0), sau 5 lần chạy khởi động. CPU là Intel Xeon Gold 6542Y của máy huấn luyện dùng chung (lúc đo
còn job khác chạy). `data/processed/cv/detector/yolo26n_640_none_latency.json`:

| Chặng | p50 (ms) | p95 (ms) |
|---|---:|---:|
| chỉ mô hình (640×640) | 23,0 | 23,8 |
| letterbox + mô hình | 26,5 | 32,0 |

Chưa tính giải mã JPEG gốc, hậu xử lý (ngưỡng, NMS) và hàng đợi. Con số trên VPS 2 vCPU sẽ khác, phải đo lại
(review:cv#13).


## 7. Độ tươi (dữ liệu công khai)

Dữ liệu: `data/processed/freshness/manifest.csv`, chỉ lấy ảnh gốc (bỏ bản tăng cường `aug_*` và các dòng
`label_conflict`): 9.182 ảnh, gồm Local Spinach Leaf v3 (3.999 ảnh, 3 loại rau lá, 2 mức) và AgriFreshNET v1
(5.183 ảnh, 8 loại, 3 mức). Nhãn thứ bậc tuoi 3.809 / dung_som 1.643 / dung_ngay 3.730. Đây là nhãn của tác
giả bộ dữ liệu, **không phải** nhãn thị giác 4 mức do 2 người chấm mù như thiết kế yêu cầu.

Chia tập theo lô: với AgriFreshNET, lô = loại nông sản + ngày chụp đọc từ tên tệp (`IMG_YYYYMMDD_…`), tức một
buổi chụp. Có 223 lô ngày; 108 ảnh không có ngày trong tên tệp thì mỗi ảnh là một nhóm. Local Spinach không
công bố lô hay ngày nên mỗi ảnh là một nhóm. Tổng cộng 4.318 nhóm. Dùng StratifiedGroupKFold 5 fold (phân tầng
theo bộ × loại × mức). SVM chạy 3 lần lặp, CNN chạy 1 lần (giới hạn GPU). Hai nhánh dùng chung các fold của lần
lặp 0, nên dự đoán out-of-fold ghép cặp được.

Đầu vào chung: ảnh thu về khung 224×224, mặt nạ tiền cảnh tính một lần bằng GrabCut (khung khởi tạo là 90%
giữa ảnh). Tỷ lệ tiền cảnh trung bình là 0,247 diện tích khung. SVM tính đặc trưng chỉ trên vùng tiền cảnh.
CNN thấy nền tô xám.
- **Cổ điển:** histogram HSV (18+8+8 bin), LBP đều (P8R1, P16R2), GLCM (khoảng cách 1 và 3, 4 hướng, 6 thuộc
  tính), tỷ lệ tiền cảnh, trung bình và độ lệch Lab. SVM RBF, C và gamma chọn bằng GroupKFold(3) bên trong
  phần train.
- **MobileNetV3-Small:** khởi tạo ImageNet, 10 epoch, AdamW lr 1e-3 OneCycle, batch 64, lật ngang/dọc và
  độ sáng ±10%.

Kết quả out-of-fold trên toàn 9.182 ảnh (`data/processed/cv/freshness/summary.json`, `svm.json`, `cnn.json`):

| Nhánh | Accuracy | Macro-F1 | κ trọng số bậc hai | MAE bậc |
|---|---:|---:|---:|---:|
| SVM (HSV+LBP+GLCM), 3 lần lặp | 0,856 ± 0,003 | 0,819 ± 0,003 | 0,878 ± 0,002 | 0,162 ± 0,003 |
| MobileNetV3-Small, 1 lần | 0,888 | 0,855 | 0,919 | 0,119 |

Bootstrap cụm theo nhóm (2.000 lần, lần lặp 0), chênh lệch CNN − SVM: macro-F1 +0,033 (CI95 0,012 đến 0,054),
κ +0,038 (CI95 0,026 đến 0,051).

Ma trận nhầm lẫn (hàng = thật, cột = đoán; thứ tự tuoi, dung_som, dung_ngay; lần lặp 0):

| | SVM | MobileNetV3 |
|---|---|---|
| tuoi | 3.423 / 328 / 58 | 3.504 / 286 / 19 |
| dung_som | 369 / 1.094 / 180 | 322 / 1.190 / 131 |
| dung_ngay | 106 / 254 / 3.370 | 42 / 229 / 3.459 |

Theo loại (lần lặp 0; macro-F1 SVM → CNN): chuối 0,855 → 0,822; mướp đắng 0,708 → 0,778; dưa chuột
0,524 → 0,543; cà tím 0,694 → 0,748; cam 0,831 → 0,883; đu đủ 0,529 → 0,525; dứa 0,772 → 0,874; cà chua
0,754 → 0,849. Ba loại rau lá của Local Spinach đạt accuracy 0,983–1,000 ở cả hai nhánh. Macro-F1 của từng
loại rau lá không có nghĩa, vì bộ này không có mức giữa.

Đọc kết quả:
- Mức giữa `dung_som` là chỗ yếu của cả hai nhánh. Lỗi gần như toàn là nhầm sang mức kề bên.
- Rau lá đạt gần 100% là đáng ngờ chứ không phải tin tốt. Bộ không có lô, ảnh chụp lá đơn trên nền trắng, và
  "non-fresh" do chuyên gia định nghĩa (gồm cả lá bệnh). Rất có thể có ảnh gần giống nhau ở cả train lẫn test.
  Số này không chuyển được sang rau muống để trong túi ở tủ lạnh.
- Thiết kế yêu cầu GroupKFold 5 × 3 cho cả hai nhánh. CNN mới chạy 5 × 1, nên ±sd của CNN chưa có.

## 8. Hạn chế

1. Không có ảnh tủ lạnh nào. Miền ảnh lệch xa: cá trong Open Images chủ yếu là cá sống dưới nước, bí đỏ là bí
   Halloween, trứng có cả trứng Phục sinh tô màu, nấm có nấm mọc ngoài rừng; bộ Bangladesh là quầy rau ngoài
   trời. Số mAP ở trên là mAP trên những ảnh đó.
2. 9/22 lớp (thịt lợn, thịt bò, thịt gà, đậu phụ, su su, mướp, rau cải, rau muống, giá đỗ) chưa có dữ liệu.
   Bộ phát hiện hiện tại không biết các lớp này.
3. Nhãn Open Images không đầy đủ với những lớp không được xác minh trong ảnh. Ảnh chọn vì cà chua có thể có cà
   rốt không được vẽ khung.
4. Val và test phần Bangladesh mỗi tập chỉ là một video, nên số theo lớp của đậu que, mướp đắng, bí đao dao động
   lớn.
5. Ablation tiền xử lý mới chạy 1 seed với 25 epoch. Kết luận cần ≥ 3 seed và biên tương đương ±1,5 mAP50-95
   (thiết kế §7). Tham số CLAHE (clip 2,0, lưới 8×8) đang để mặc định, chưa chọn trên val. Nhánh "chỉ tăng
   cường" (giả lập lệch cân bằng trắng khi train) chưa chạy.
6. Chưa so YOLO11n và imgsz 960. Chưa đánh giá cân bằng trắng bằng thẻ xám (cần ảnh có thẻ).
7. Chưa đánh giá đếm vật thể (cần ảnh tủ lạnh có số vật thật) và chưa chạy baseline Gemini.
8. Độ trễ đo trên máy huấn luyện dùng chung, không phải VPS đích.
9. Độ tươi dùng nhãn của tác giả bộ dữ liệu (2–3 mức). Ảnh chụp riêng từng quả/lá trên nền sạch, khác khung cắt
   trong tủ lạnh.

## 9. Dữ liệu nhóm phải tự thu

1. **Ảnh tủ lạnh ≥ 12–15 hộ** (review:cv#2). Mỗi hộ 2–3 phiên vào các ngày khác nhau, tối đa khoảng 30–50 ảnh
   mỗi phiên sau khi lọc trùng pHash. Ghi metadata: hộ, phiên, ngăn, đèn tủ hay đèn phòng, đời máy. Chụp đúng
   như app gửi: JPEG, cạnh dài 1.280 px.
   - Chọn ≥ 4 hộ làm tập test (chia nhóm có phân tầng) để mỗi lớp có ≥ 30–50 vật thể. Đóng băng tập này trước
     khi huấn luyện.
   - Ưu tiên chụp 9 lớp chưa có dữ liệu: thịt lợn, thịt bò, thịt gà, đậu phụ, su su, mướp, rau cải, rau muống,
     giá đỗ.
   - Mỗi lớp cần ≥ 300 vật thể train từ ảnh của nhóm, hoặc từ Roboflow sau khi có API key và đã kiểm ảnh.
2. **Vòng gán thử 100–150 ảnh**, 2 người gán từ đầu không dùng nháp. Báo F1 giữa hai người (ghép Hungarian
   IoU ≥ 0,5), tỷ lệ không ghép được, trung vị IoU, κ tên lớp (mục tiêu ≥ 0,81). Từ đó quyết định gộp nhãn cha
   (`fallback_parent` trong bảng lớp: thịt đóng gói, quả bầu bí, rau lá).
3. **Lô độ tươi** cho các lớp có `has_freshness_model: true` (cà chua, súp lơ, mướp, mướp đắng, đậu que, rau
   cải, rau muống):
   - Mỗi lô chụp hằng ngày trong tủ, cả ảnh kiểu quét lẫn ảnh cận cảnh, có thẻ xám 18% ở góc.
   - Hai người chấm mù ngày theo thang 4 mức có ảnh mẫu. Báo κ trọng số bậc hai.
   - Chia tập theo lô (GroupKFold 5 × 3).
   - Mỗi loại cần đủ lô để mỗi fold có lô của loại đó: tối thiểu 5 lô/loại, nên 8–10 lô.
4. **Ảnh có thẻ xám** để chấm cân bằng trắng: sai số góc của gray-world, shades-of-gray, gray-edge.
5. **Đo độ trễ trên VPS đích** (`--cpus=2 --memory=4g`) với chính tệp ONNX ở mục 6.

## 10. Cách chạy lại

```bash
# môi trường huấn luyện riêng (không đụng uv.lock của dự án)
uv venv ml/runs/venv-cv --python 3.12
VIRTUAL_ENV=ml/runs/venv-cv uv pip install --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/cu126 torch==2.8.0 torchvision==0.23.0 \
  ultralytics==8.4.173 mlflow onnx onnxruntime onnxslim scikit-learn scikit-image imagehash pandas pyyaml requests
export PYTHONPATH=ml/src PY=ml/runs/venv-cv/bin/python
$PY -m tastoria_ml.cv.openimages all          # Open Images: lọc nhãn, chọn ảnh, metadata, tải ảnh
$PY -m tastoria_ml.cv.build_yolo              # manifest + bộ YOLO
$PY -m tastoria_ml.cv.train_detector train --name smoke --epochs 1
$PY -m tastoria_ml.cv.train_detector train --name yolo26n_640_none --epochs 100 --patience 15
$PY -m tastoria_ml.cv.train_detector train --name abl25_gw --arm gw --epochs 25 --patience 100
$PY -m tastoria_ml.cv.train_detector latency --name yolo26n_640_none
$PY -m tastoria_ml.cv.freshness cache && $PY -m tastoria_ml.cv.freshness svm \
  && $PY -m tastoria_ml.cv.freshness cnn && $PY -m tastoria_ml.cv.freshness report
```

Bộ Bangladesh tải bằng `https://data.mendeley.com/public-api/zip/gnc4s3z2mf/download/3` rồi giải nén vào
`data/raw/images/mendeley_bd_vegetables/extracted/` (sha256 ghi trong SOURCE.md).

Quy tắc GPU dùng chung đã được cài trong `train_detector.GpuGuard` và áp cho cả bộ phát hiện lẫn CNN độ tươi:
chỉ khởi chạy khi còn ≥ 10 GB trống, `set_per_process_memory_fraction(0.15)`, batch cố định, một job một lúc
(khoá tệp), watchdog dừng job ngay khi bộ nhớ trống < 3 GB. Trong các lần chạy, bộ nhớ trống thấp nhất watchdog
ghi được là 9.371 MB (lần chạy baseline), chưa lần nào chạm ngưỡng dừng.
