# Đối chiếu tài liệu với mã và dọn tệp mô hình (05/11/2026)

Nguồn sự thật dùng để đối chiếu: `data/kb/vision_classes.yaml` (lớp thị giác), `deploy/models/detector/` (mô hình
đang chạy), `docs/api/openapi-v1.yaml` (70 thao tác, khớp router theo `test_openapi_contract.py`), CSDL sau
`tastoria db upgrade` (63 bảng), kết quả chạy kiểm thử ngày 05/11/2026, và bản live `https://tastoria.ctslab.net`
(`/healthz`, `/readyz`, `/tai-ve/tastoria-0.1.4.apk` đều trả 200; `safework.ctslab.net/healthz` trả 404).

## 1. Lớp thị giác: bảng có gì, mô hình nhận gì

| | Số lớp | Danh sách |
|---|---:|---|
| `classes` (phân tích, thiết kế v2 §7) | 22 | thịt lợn, thịt bò, thịt gà, cá, tôm, trứng, đậu phụ, cà chua, cà rốt, khoai tây, bắp cải, súp lơ, bí đỏ, bí đao, su su, mướp, mướp đắng, đậu que, rau cải, rau muống, giá đỗ, nấm |
| `proposed_classes` (thêm 30/10/2026) | 15 | mì tôm, xúc xích, đồ hộp, sữa, sữa chua, hành lá, tỏi, ớt, chanh; đồ ăn vặt: bim bim, bánh ngọt, bánh quy, kẹo, nước ngọt, bánh mì |
| Bảng `vision_classes` sau `catalog import` | 37 | cả hai danh sách trên |
| Mô hình đang chạy `yolo26n_640_none` (`model_version_classes`) | 13 | ca, tom, trung, ca_chua, ca_rot, khoai_tay, bap_cai, sup_lo, bi_do, bi_dao, muop_dang, dau_que, nam |
| Bộ `data/processed/cv/yolo_v2` (chưa huấn luyện) | 30 | 37 trừ thịt lợn, thịt gà, su su, mướp, rau cải, rau muống, giá đỗ |

Đồ ăn vặt (nhóm thực phẩm mới `do_an_vat`) vào kho được nhưng không bao giờ vào mâm: `catalog.NON_MEAL_FOOD_GROUPS`
luôn nằm trong `excluded_food_groups` và trong `recipe_allowed` / `ingredient_allowed`.

## 2. Chỗ lệch đã tìm thấy và cách sửa

### Mã và dữ liệu

| # | Chỗ lệch | Sửa |
|---|---|---|
| 1 | Việc dở của lượt trước: thêm 15 lớp `proposed_classes`, 7 nguyên liệu, nhóm `do_an_vat`, `build_yolo_v2.py` / `lvis.py` / `rpc.py`, nhưng chưa dựng bộ v2, backend chưa loại đồ ăn vặt, `catalog import` chỉ đọc `classes` | Giữ phần đúng; dựng `yolo_v2` + `manifest_v2.csv` + `dataset_stats_v2.json` (train 15.865 / val 1.485 / test 2.035 / heldout 1.253 ảnh, 30 lớp); importer nạp cả `proposed_classes` (37 dòng) |
| 2 | `build_yolo_v2.py` cứng `rows[22:]` để lấy lớp đề xuất | Tính từ số dòng `classes` của tệp |
| 3 | Đồ ăn vặt có `meal_ingredient: false` nhưng không gì trong backend thực thi điều đó | `NON_MEAL_FOOD_GROUPS = {"do_an_vat"}` trong `catalog/service.py`, áp cho mọi chế độ ăn và cả khi bên gọi không truyền nhóm; kiểm thử `backend/tests/integration/test_non_meal_group.py` |
| 4 | `bánh mì` có `meal_ingredient: false` nhưng thuộc nhóm `ngu_coc`, nên bộ lọc theo nhóm không chặn | Giữ theo yêu cầu đã ghi; kiểm thử ML buộc lớp không-vào-mâm ngoài `do_an_vat` không được món nào dùng (bánh mì: 0 món). Muốn chặn cứng thì phải chuyển nhóm của nguyên liệu, việc này đổi bảng FCT nên để người dùng quyết |
| 5 | Chú thích `vision_classes.yaml`: "thứ tự trong danh sách = chỉ số lớp YOLO"; "proposed chưa vào CSDL" | Sửa: chỉ số lấy từ `names` của dataset / ONNX; ghi hiện trạng 37 / 13 / 30 ở đầu tệp |
| 6 | Không có gì kiểm bản đồ lớp của mô hình đang chạy với bảng | Kiểm thử `ml/tests/cv/test_classes.py::test_deployed_detector_classes_are_in_the_table_and_match_the_docs` (đọc metadata `names` của `deploy/models/detector/model.onnx`, bỏ qua nếu máy không có tệp) |
| 7 | Số đếm trong kiểm thử backend: 225 nguyên liệu, 18 × 3 mức lượng, 22 lớp | 232 (230 + 2 đồ làm sẵn), 19 × 3, 22 + 15 = 37 |
| 8 | `deploy/.env.example`: `RESET_URL_BASE` và `MAIL_FROM` trỏ `safework.ctslab.net` | Đổi sang `tastoria.ctslab.net`. **`deploy/.env` trên máy chủ chưa sửa** (không đụng bí mật đang chạy); vô hại khi `MAILER=log`, phải sửa trước khi bật SMTP — ghi ở `deploy/README.md` |
| 9 | Từ điển dữ liệu sinh từ `db/schema.sql` (62 bảng), thiếu `recipe_make_ahead` của migration 0003; ERD cũng thiếu | `db/gen_dictionary.py` chạy trên CSDL sau `tastoria db upgrade` → 63 bảng, 396 cột; thêm mục `recipe_make_ahead` vào `db/dictionary_meta.py`; `docs/erd/gen_erd.py` đọc thêm SQL của migration, ERD04 và ERD08 sinh và render lại (63 bảng) |

### Tài liệu

| Tệp | Chỗ lệch | Sửa |
|---|---|---|
| `docs/reports/xu-ly-anh/BaoCao_XuLyAnh_ThiGiacMayTinh.pdf` | Ghi "chạy thật trên safework.ctslab.net"; K = 22 lớp; không phân biệt bảng và mô hình; không có bộ v2 | Viết `bao-cao-xu-ly-anh.md` thành nguồn đầy đủ của PDF (bản cũ là nháp dừng ở mục 6); thêm mục 4.2 bộ v2, đồ ăn vặt, 37/13/30; số đo độ trễ ghi rõ đo qua địa chỉ cũ; nhánh tăng cường seed 3 bị dừng ở epoch 29 (đã xoá, không có số). PDF dựng lại bằng `make_pdf.sh` (pandoc → pdflatex + vntex T5 + lmodern), 12 trang, 657 KB |
| `docs/reports/xu-ly-anh/ket-qua-so-bo.md` | "22 lớp"; URL safework | Ghi chú cập nhật 37 lớp / 13 mô hình / 30 bộ v2; URL ghi rõ là địa chỉ lúc đo |
| `docs/reports/ptud/bao-cao-ptud.md` | Live ở safework.ctslab.net; APK 0.1.1 (đã gỡ, landing trỏ 0.1.4); 223 nguyên liệu; 62 bảng; 346 / 252 kiểm thử; "13 trong 22 lớp"; mục hạn chế nói README backend/deploy chưa cập nhật | tastoria.ctslab.net, APK 0.1.4 (versionCode 5, sha256 `fa7fb439…`, nhúng `https://tastoria.ctslab.net/api/v1` — đã kiểm trong bundle), 230 nguyên liệu (184 FCT, 30 USDA, 16 chưa nguồn), 63 bảng, 347 / 254 + 1 skipped, 37 lớp bảng / 13 mô hình, bỏ mục README đã sửa |
| `docs/reports/hoc-may/bao-cao-hoc-may.md` | "225 nguyên liệu" | Ghi rõ là số lúc chạy thí nghiệm; 7 nguyên liệu mới không dùng trong món nào nên kết quả không đổi |
| `docs/reports/pttkht/` (báo cáo pha, commit 465b0b3) | §5.3 nói các ca TC01–TC12 "chưa phải biên bản đã chạy" trong khi đa số đã có kiểm thử tự động; Phụ lục B chỉ ghi 62 bảng của `schema.sql` | Thêm đoạn đối chiếu từng TC với tên kiểm thử và số chạy 05/11/2026 (TC02, TC10 chưa có ca riêng); Phụ lục B ghi bảng thứ 63. Dựng lại PDF từ LaTeX (`latex/build.sh`). URL (tastoria.ctslab.net), 34 UC, 70 endpoint đã đúng; nội dung SafeWork / ABC Shop chỉ được nhắc là không dùng |
| `docs/sad/00-thuat-ngu.md`, `01-SRS.md`, `adr/0011` | "~20 lớp thị giác"; SRS "62 bảng" | 37 lớp bảng, 13 mô hình; 63 bảng (62 + migration 0003) |
| `docs/sad/BaoCao_PhanTichThietKe.md`, `use-cases/UC33.md` | 62 bảng | 63 bảng |
| `docs/sad/use-cases/UC25.md` | Câu hỏi mở "Ai nhập `vision_classes`?" | Đã chốt: `tastoria catalog import` của UC25 |
| `backend/README.md` | Vision classes chỉ nói `classes`; "Next steps" còn ghi chưa có `catalog substitutes import`, "chưa có cặp thay thế" | Mô tả 37 / 13, nhóm không-vào-mâm; bỏ mục đã làm (197 cặp đang nạp) |
| `deploy/README.md` | "Sao lưu chưa đặt lịch" (crontab đã có dòng 03:15 VN); `RESET_URL_BASE` safework | Ghi lịch đang chạy; URL đúng và cảnh báo về `deploy/.env` |
| `README.md` (gốc) | Chỉ có tiêu đề | Bố cục repo, URL live, lớp thị giác, lệnh kiểm thử |
| `app/README.md` | Còn ghi endpoint quét và khảo sát "chưa có trong backend" | **Chưa sửa** (thư mục `app/` do lượt làm việc khác phụ trách) |
| `landing/` | Không có số liệu lệch (APK 0.1.4, ảnh giữ 30 ngày) | Không đổi |

Còn lệch, để nguyên có chủ ý: `docs/vp-import-kit/` và `db/schema_vp.sql` mô tả 62 bảng của `schema.sql` (bộ nhập
Visual Paradigm chưa có `recipe_make_ahead`); `docs/sad/04-chuan-hoa.md` phân tích chuẩn hoá 62 bảng của
`schema.sql`; các tệp `.docx` trong `docs/reports/pttkht/` là bản biên tập trước LaTeX (README của thư mục đã nói PDF
LaTeX là bản hiện hành).

## 3. Dọn tệp mô hình và bản dựng

`du` trước: `ml/runs` 2,6 GB, `data/processed` 1,4 GB, `dist` 277 MB, `deploy/models` 9,4 MB,
`docs/design-preview` 17 MB. Sau: `ml/runs` 673 MB, `dist` 80 MB. **Giải phóng 2.261 MB.**

Giữ: mô hình đang chạy (`deploy/models/detector/model.onnx` = `ml/runs/detect/yolo26n_640_none/weights/best.onnx`,
md5 `43f6c3e1…`), `best.pt` của mọi lần chạy có số trong báo cáo (abl25_*, abl60_* 8 lần, grid20_* 5 lần,
yolo26n_640_none) kèm thư mục `*_eval_*` và JSON kết quả trong `data/processed/cv/`, bản xuất `best_e2e_640.onnx`
dùng cho đo không-NMS, mô hình độ tươi `mobilenetv3_small_final.{pt,onnx}`, mọi dữ liệu gốc `data/raw/`, `deploy/.env`,
khoá ký (ngoài repo).

Đã xoá:

| Đường dẫn | Dung lượng | Lý do |
|---|---:|---|
| `ml/runs/freshness/X224.npy` | 1.382,1 MB | Bộ đệm ảnh 224 px; `tastoria_ml.cv.freshness` sinh lại từ `data/raw/images/freshness` |
| `ml/runs/freshness/M224.npy` | 460,7 MB | Bộ đệm mặt nạ GrabCut, sinh lại cùng lệnh trên |
| `ml/runs/detect/*/weights/last.pt` (21 tệp) | 123,1 MB | Checkpoint epoch cuối; báo cáo dùng `best.pt` |
| `ml/runs/detect/smoke`, `smoke_eval_{test,val}`, `smoke.gpu.log` | 13,3 MB | Chạy thử 1 epoch (kết quả vẫn ở `data/processed/cv/detector/smoke.json`) |
| `ml/runs/detect/smoke3_gwclahe` (+ `_eval_test`, `_eval_val`, `.gpu.log`) | 26,6 MB | Chạy thử 3 epoch |
| `ml/runs/preds/smoke3_gwclahe__test__{e2e,nms}.npz` | 16,2 MB | Dự đoán của lần chạy thử trên |
| `ml/runs/detect/abl60_aug_s2` (+ `.gpu.log`) | 17,9 MB | Lần chạy bị dừng ở epoch 29 vì GPU dùng chung cạn bộ nhớ; không có số trong báo cáo |
| `ml/runs/detect/freshness_cnn_smoke.gpu.log`, `ml/runs/smoke.log` | 0,1 MB | Log chạy thử |
| `ml/runs/detect/yolo26n_640_none/weights/best_raw_640.onnx` | 9,8 MB | Bản xuất lại đầu thô của `best.pt` (cùng cỡ với `best.onnx` đang triển khai); `cv/onnx_latency.py` sinh lại |
| `weights/yolo26n.pt` (gốc repo) | 5,5 MB | Trùng byte với `ml/runs/weights/yolo26n.pt` (ultralytics tự tải vào thư mục làm việc) |
| `dist/tastoria-0.1.0.apk`, `0.1.1.apk`, `0.1.2.apk`, `0.1.3.apk` (+ `.source` của 0.1.2, 0.1.3) | 206,0 MB | APK cũ; giữ 0.1.4 (bản mới nhất, trang giới thiệu trỏ tới) và `tastoria-vp-kit.zip` |

Không xoá:

- `data/processed/cv/yolo` và `yolo_v2`: `du` báo 1,3 GB mỗi thư mục nhưng ảnh là hard link tới `data/raw/images`
  (`os.link`), nên không tốn thêm chỗ; phần riêng của `data/processed/cv` chỉ khoảng 154 MB (nhãn, manifest, JSON).
  Xoá chúng không lấy lại được dung lượng.
- `docs/design-preview/` (17 MB ảnh chụp giao diện, chưa commit): thuộc lượt làm việc về giao diện, không phải mô hình.
- `ml/runs/preds/abl60_*.npz`, `ml/runs/queue/*.log`: dự đoán và log của các lần chạy có trong báo cáo, dùng cho
  bootstrap.

`.gitignore` gốc thêm `*.npy`, `*.apk`, `*.aab`, `/weights/` (đã có `*.pt`, `*.onnx`, `ml/runs/`, `dist/`);
`data/processed/cv/.gitignore` loại `yolo_v2/images/`, `yolo_v2/labels/`. Không có tệp nhị phân lớn nào đang nằm
trong git (tệp lớn nhất được theo dõi là `data/processed/cv/manifest_v2.csv`, 5,9 MB).

## 4. Kiểm thử sau khi sửa

- `uv run --package tastoria-backend pytest backend/tests -q`: 347 passed (gồm ca tích hợp trên container tạm, có
  `test_non_meal_group.py` và `catalog import` với 37 lớp).
- `CUDA_VISIBLE_DEVICES= uv run --package tastoria-ml pytest ml/tests -q`: 254 passed, 1 skipped (cần `cv2`).
