# Dữ liệu nguồn của Tastoria (giai đoạn D0)

Tải và chuẩn hoá ngày 17/10/2026 theo kế hoạch `docs/superpowers/plans/2026-10-17-d0-nen-du-lieu.md`.
Mã nguồn ở `ml/src/tastoria_ml/data/`. Dữ liệu thô ở `data/raw/<nguồn>/` (không commit), mỗi thư mục có
`SOURCE.md` ghi URL, ngày tải, giấy phép, trích dẫn và sha256. Bảng đã chuẩn hoá ở `data/processed/<nguồn>/`.

Mọi số dòng dưới đây đếm trực tiếp từ tệp trong `data/processed/` ngày 17/10/2026. Bộ test
`uv run --package tastoria-ml pytest ml/tests -q`: 58 passed.

Tổng dung lượng thô trên ổ: fct2007 4,6 MB; usda 6,3 MB; foodkeeper 628 KB; foodcom 615 MB; ảnh độ tươi 1,3 GB
(gồm cả zip và thư mục đã giải nén).

## 1. Bảng thành phần thực phẩm Việt Nam 2007 (Viện Dinh dưỡng – Bộ Y tế)

- **Là gì:** bảng thành phần thực phẩm chính thức của Việt Nam, NXB Y học 2007, một thực phẩm mỗi trang,
  86 chất trên 100 g phần ăn được, kèm tỷ lệ thải bỏ. PDF dùng mã chữ TCVN3, được chuyển sang Unicode NFC
  bằng `tcvn3.py`.
- **URL gốc:** https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf
  (liệt kê trên trang FAO/INFOODS châu Á; trang ghi nhãn "(2000)" nhưng tệp là bản 2007).
- **Giấy phép (nguyên văn):** không có. PDF không có dòng bản quyền hay giấy phép nào; trang FAO cũng không
  ghi giấy phép cho tệp này. Xử lý như ấn phẩm có bản quyền của Viện Dinh dưỡng: dùng giá trị số cho học
  thuật, ghi nguồn, không phát tán lại PDF.
- **Tệp:**

  | Tệp | Kích thước | Số dòng |
  |---|---:|---:|
  | `data/raw/fct2007/VTN_FCT_2007.pdf` | 4.722.438 byte (567 trang) | — |
  | `data/processed/fct2007/foods.csv` | 41.903 byte | 526 |
  | `data/processed/fct2007/nutrients_long.csv` | 1.053.098 byte | 45.762 |

- **Số đo:** 526 thực phẩm, 14 nhóm (số thực phẩm theo nhóm 1→14: 23, 26, 33, 126, 56, 14, 82, 59, 11, 9, 21,
  27, 23, 16), khớp số in trong PDF. `nutrients_long` có 87 chất mỗi thực phẩm (86 chất + năng lượng kJ).
  Ô trống ("-" hoặc để trống → NaN): 22.521 / 45.762 = 49,2%. Trong `foods.csv`: thiếu `name_en` 10 dòng,
  `refuse_pct` 10, `lipid_g` 75, `fiber_g` 20, `ash_g` 2, `protein_g` 1; năng lượng, nước, glucid đủ cả 526.
  Kiểm tra Atwater (4·P + 4·G + 9·L lệch ≤ 15% so với kcal): 415/415 thực phẩm có đủ bốn giá trị và > 20 kcal.
  Đối chiếu tay 5 trang ngẫu nhiên: khớp hết (chi tiết trong `SOURCE.md`).
- **Hạn chế:** số liệu khoảng 20 năm tuổi; nhiều giá trị lấy từ bảng khác (FAO 1972, USDA SR18, ASEAN 2000)
  chứ không phải phân tích tại Việt Nam (cột TLTK). Gần một nửa ô chất dinh dưỡng trống. PDF in tên chữ hoa;
  bộ đọc chỉ viết hoa chữ đầu ("Khoai lang nghệ"). PDF ghi "C18:2 n3" cho axit linolenic, mã chất trong bảng
  là `linolenic_c18_3_n3`. Lớp chữ của PDF lệch ở một số trang; các trang đã biết được liệt kê và có test.
- **Dùng ở đâu:** tính dinh dưỡng món từ công thức (tài liệu thiết kế mục 2.4: hàm lượng chất n và tỷ lệ phần
  ăn được EP = 1 − thải bỏ); cột `fct_code` của bảng `ingredients` trỏ vào mã thực phẩm này.

## 2. USDA FoodData Central (Foundation Foods + SR Legacy)

- **Là gì:** cơ sở dữ liệu thành phần thực phẩm của Bộ Nông nghiệp Mỹ. Lấy hai bộ: Foundation Foods bản
  2026-04-30 (JSON) và SR Legacy bản 04/2018 (CSV).
- **URL gốc:** https://fdc.nal.usda.gov/download-datasets/
  - https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2026-04-30.zip
  - https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
- **Giấy phép (nguyên văn, trang https://fdc.nal.usda.gov/, mục Licensing):**
  > USDA FoodData Central data are in the public domain and they are not copyrighted. They are published
  > under CC0 1.0 Universal (CC0 1.0) No permission is needed for their use, but we request that users list
  > FoodData Central as the source of the data, and when possible, notify us of the product that uses the
  > data so we may better track how FDC is being used in the public domain.
- **Tệp:**

  | Tệp | Kích thước | Số dòng |
  |---|---:|---:|
  | `FoodData_Central_foundation_food_json_2026-04-30.zip` | 469.303 byte | — |
  | `FoodData_Central_sr_legacy_food_csv_2018-04.zip` | 6.074.592 byte | — |
  | `data/processed/usda/foods.csv` | 1.087.746 byte | 8.156 |

- **Số đo:** 8.156 dòng = 7.793 `sr_legacy_food` + 363 `foundation_food`; 25 nhóm (`category`). Số SR Legacy
  khớp bảng đếm đi kèm zip (food = 7.793, food_nutrient = 644.125). Tỷ lệ dòng có giá trị: năng lượng 0,995;
  protein 0,999; chất béo 0,997; carbohydrate 0,995; chất xơ 0,909; đường 0,753; natri 0,986.
- **Hạn chế:** giống và điều kiện của Mỹ. Chỉ 95/363 thực phẩm Foundation có năng lượng mã 1008; phần còn lại
  lấy Atwater 2048 rồi 2047; 42 thực phẩm Foundation không có năng lượng (NaN). Carbohydrate "by difference"
  âm nhẹ ở 10 loại thịt cá sống Foundation, giữ nguyên như USDA công bố (khi tính coi < 0 là 0). Một số thực
  phẩm có mặt ở cả hai bộ dưới hai `fdc_id` khác nhau (ví dụ "Spinach, raw" SR 23 kcal và "Spinach, mature"
  Foundation 21,6 kcal).
- **Dùng ở đâu:** bổ sung cho nguyên liệu không có trong bảng Việt Nam (tài liệu thiết kế mục 4.1: "chỉ dùng
  khi thiếu").

## 3. FSIS FoodKeeper (thời hạn bảo quản)

- **Là gì:** dữ liệu thời hạn bảo quản thực phẩm của Cục An toàn và Kiểm tra Thực phẩm (FSIS, USDA). Phiên
  bản dữ liệu trong tệp: 128.0, Modified_Date 09-06-2018.
- **URL gốc:** trang https://catalog.data.gov/dataset/fsis-foodkeeper-data, tệp
  https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json
- **Giấy phép (nguyên văn, metadata data.gov):** `License: https://creativecommons.org/publicdomain/zero/1.0/`
  (CC0 1.0 Universal).
- **Tệp:**

  | Tệp | Kích thước | Số dòng |
  |---|---:|---:|
  | `data/raw/foodkeeper/foodkeeper.json` | 631.800 byte | — |
  | `data/processed/foodkeeper/products.csv` | 67.058 byte | 661 |

- **Số đo:** 661 sản phẩm, 25 nhóm. 363/661 sản phẩm có thời hạn tủ lạnh (`fridge_min_days`,
  `fridge_max_days`); 298 sản phẩm còn lại không có giá trị tủ lạnh (NaN). Nhóm "Produce / Fresh Vegetables"
  có 68 sản phẩm, 65 có thời hạn tủ lạnh. Thời hạn ghi theo tuần/tháng/năm được quy về ngày (tuần = 7,
  tháng = 30, năm = 365).
- **Hạn chế:** xây cho điều kiện Mỹ; không có mục riêng cho nhiều rau Việt (không có rau muống, mồng tơi,
  rau ngót; rau lá chỉ có các mục chung như "Greens", "Herbs", "Bagged greens"). Cần ánh xạ tay từ nguyên
  liệu Việt sang mục FoodKeeper và hiệu chỉnh bằng ảnh tự chụp. fsis.usda.gov trả HTTP 403 cho yêu cầu
  HTTP thường; tệp được tải bằng Chromium headless (Playwright), nên tải lại cần môi trường có Playwright.
- **Dùng ở đâu:** thời hạn bảo quản L trong công thức mức cần dùng gấp u (mục 2.5) và nhãn độ tươi theo ngày
  chụp (mục 3.3, 4.3).

## 4. Food.com Recipes and Interactions

- **Là gì:** dữ liệu cào từ Food.com (trước là GeniusKitchen) đi kèm bài EMNLP 2019 của Majumder, Li, Ni,
  McAuley. Lấy hai tệp gốc `RAW_recipes.csv` và `RAW_interactions.csv`, không lấy các tệp đã lọc
  `interactions_*`/`PP_*`.
- **URL gốc:** https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions (version 2),
  tải qua endpoint công khai của Kaggle không cần token. Bài báo: https://aclanthology.org/D19-1613/
- **Giấy phép (nguyên văn, trang Kaggle):** "Data files © Original Authors"
- **Tệp:**

  | Tệp | Kích thước | Số dòng |
  |---|---:|---:|
  | `data/raw/foodcom/RAW_recipes.csv` | 294.520.189 byte | — |
  | `data/raw/foodcom/RAW_interactions.csv` | 349.436.524 byte | — |
  | `data/processed/foodcom/recipes.parquet` | 17.009.613 byte | 231.637 |
  | `data/processed/foodcom/interactions.parquet` | 8.988.770 byte | 1.132.367 |
  | `data/processed/foodcom/stats.json` | 275 byte | — |

  Kích thước hai tệp thô khớp đúng từng byte với `totalBytes` Kaggle công bố.
- **Số đo:** 231.637 công thức; 226.570 người dùng; 1.132.367 tương tác, từ 2000-01-25 đến 2018-12-20.
  1.071.520 tương tác có chấm sao; 60.847 có rating = 0 (đánh giá không chấm sao, `has_rating = False`).
  Phân bố sao 1→5: 12.818; 14.123; 40.855; 187.360; 816.364. 166.256 người dùng (73%) chỉ có đúng 1 tương tác,
  trung vị 1 tương tác/người; 23.086 người có từ 5 tương tác trở lên.
- **Hạn chế:** giấy phép không rõ ràng ("© Original Authors"), chỉ dùng cho nghiên cứu, không phát tán lại.
  Món Âu–Mỹ; đánh giá tự nguyện, lệch mạnh về 5 sao. Rất thưa: phần lớn người dùng chỉ có một tương tác, nên
  chia theo thời gian "tương tác cuối mỗi người làm tập kiểm tra" sẽ cần lọc người dùng có đủ lịch sử. Cột
  `minutes` có giá trị bất thường: 262 công thức trên 10.000 phút, giá trị lớn nhất 2.147.483.647. Một công
  thức không có tên.
- **Dùng ở đâu:** chỉ để so sánh và chọn thuật toán xếp hạng món theo gu (mục 3.4: phổ biến, content-based,
  MF/BPR, LightFM). Không chuyển trọng số sang món Việt.

## 5. Ảnh độ tươi: Local Spinach Leaf Dataset (Mendeley Data V3)

- **Là gì:** ảnh lá của ba loại rau (mồng tơi, rau dền đỏ, rau muống) chia hai lớp tươi / không tươi, của
  Hasan, Shaha, Akhi (2024).
- **URL gốc:** https://data.mendeley.com/datasets/skf6w2s2h2/3 (DOI 10.17632/skf6w2s2h2.3)
- **Giấy phép (nguyên văn, trường `data_licence` của Mendeley API):** "CC BY 4.0 - Creative Commons
  Attribution 4.0 International - http://creativecommons.org/licenses/by/4.0". Kèm mô tả: "You can share, copy
  and modify this dataset so long as you give appropriate credit, provide a link to the CC BY license, and
  indicate if changes were made, but you may not do so in a way that suggests the rights holder has endorsed
  you or your use of the dataset. Note that further permission may be required for any content within the
  dataset that is identified as belonging to a third party."
- **Tệp:** `Local Spanish Leaf Disease Dataset.zip`, 300.291.182 byte, sha256 khớp Mendeley; giải nén vào
  `extracted/` (thư mục bộ này 580 MB trên ổ). Không tải tệp "local Spinach Fresh and Non Fresh Dataset.zip"
  (300.130.942 byte) vì chứa đúng 3.999 tệp cùng tên và cùng CRC32.
- **Số đo (từ `data/processed/freshness/manifest.csv`):** 3.999 ảnh, 3 loại rau; nhãn `tuoi` 1.892,
  `dung_ngay` 2.107; không có ảnh tăng cường; không có `dung_som`.

  | Rau | fresh | non-fresh |
  |---|---:|---:|
  | Malabar spinach (mồng tơi) | 395 | 616 |
  | Red spinach (rau dền đỏ) | 850 | 723 |
  | Water spinach (rau muống) | 647 | 768 |

- **Hạn chế:** chỉ hai lớp, nên không có mức "dùng sớm". Bộ dữ liệu không công bố lô hay đợt chụp, nên mỗi ảnh
  là một `group_id` riêng (3.999 nhóm): không chia tập theo lô được, có nguy cơ ảnh gần giống nhau rơi vào cả
  tập huấn luyện và tập kiểm tra. Nền chụp khác ảnh tủ lạnh.
- **Dùng ở đâu:** tiền huấn luyện bộ phân loại độ tươi (mục 3.3), sau đó tinh chỉnh bằng ảnh nhóm tự chụp
  (mục 4.3). Đây là bộ duy nhất trong D0 có rau muống.

## 6. Ảnh độ tươi: AgriFreshNET (Mendeley Data V1)

- **Là gì:** ảnh 8 loại nông sản ở ba trạng thái Fresh / Semi-Fresh / Rotten, tên thư mục kèm khoảng thời hạn
  (ngày), của Risdin, Salauddin, Tufa, Hossain (2026).
- **URL gốc:** https://data.mendeley.com/datasets/42m5tb7yv9/1 (DOI 10.17632/42m5tb7yv9.1)
- **Giấy phép (nguyên văn, trường `data_licence` của Mendeley API):** "CC BY 4.0 - Creative Commons
  Attribution 4.0 International - http://creativecommons.org/licenses/by/4.0", kèm đúng đoạn mô tả như mục 5.
- **Tệp:** `Processed Data.zip`, 347.828.971 byte, sha256 khớp Mendeley; giải nén vào `extracted/` (thư mục bộ
  này 693 MB trên ổ).
- **Số đo (từ `manifest.csv`):** 14.160 ảnh, 8 loại (chuối, mướp đắng, dưa chuột, cà tím, cam, đu đủ, dứa, cà
  chua), mỗi tổ hợp loại × trạng thái 590 ảnh; mỗi nhãn `tuoi` / `dung_som` / `dung_ngay` 4.720 ảnh. 8.943 ảnh
  là bản tăng cường (`aug_*`); chỉ còn 5.217 ảnh gốc, gom thành 5.176 `group_id` (bản tăng cường gắn về ảnh gốc).
  Có 14.120 mã sha256 khác nhau trên 14.160 ảnh; 34 dòng bị đánh dấu `label_conflict` (cùng một tệp nằm dưới
  hai trạng thái).
- **Hạn chế:** trang dữ liệu ghi "24 classes" và 14.500 ảnh; thực tế là 8 loại × 3 trạng thái và 14.160 ảnh.
  Hơn 60% là ảnh tăng cường, nên phải chia tập theo `group_id` và bỏ các dòng `label_conflict`. Chỉ có cà tím,
  dưa chuột, cà chua, mướp đắng là rau quả hay gặp trong bếp Việt; không có rau lá. Nền chụp khác ảnh tủ lạnh.
- **Dùng ở đâu:** như mục 5, tiền huấn luyện bộ phân loại độ tươi ba mức. Hai bộ ảnh gộp lại trong
  `manifest.csv`: 18.159 dòng, 5.664.330 byte.

## 7. Nguồn bị chặn hoặc chưa lấy được

Trong D0, cả sáu nguồn ở trên đều đã tải được. Các chỗ từng bị chặn và cách đã xử lý:

| Nguồn | Bị chặn ở đâu | Đã xử lý | Cần gì nếu phải tải lại |
|---|---|---|---|
| FoodKeeper | fsis.usda.gov trả HTTP 403 cho script | Tải bằng Chromium headless (Playwright) | Môi trường có Playwright, hoặc tải tay bằng trình duyệt rồi đặt vào `data/raw/foodkeeper/` (kiểm sha256 trong `SOURCE.md`) |
| Food.com | Không có bản sao Hugging Face khớp đúng byte | Tải thẳng từ endpoint công khai của Kaggle, không cần token | Nếu Kaggle đóng endpoint công khai: token Kaggle của người dùng |

Các nguồn có trong tài liệu thiết kế (mục 4.1) nhưng không nằm trong D0 và chưa có dữ liệu:

| Nguồn | Tình trạng | Cần gì |
|---|---|---|
| CSDL thành phần nông sản Việt Nam, Bui và cộng sự 2025 | Không có URL dữ liệu công khai hay giấy phép dữ liệu; PDF bài báo nằm sau biểu mẫu tải của SEARCA (theo `docs/research/raw/02-*.md`) | Xin dữ liệu từ nhóm tác giả hoặc SEARCA, kèm điều khoản sử dụng |
| Tra cứu giá trị dinh dưỡng món ăn, Viện Dinh dưỡng | Cố ý không tải hàng loạt; tài liệu thiết kế chỉ cho tra thủ công khoảng 30 món | Nhóm tra tay khi kiểm định calo (mục 2.4) |
| Nhu cầu dinh dưỡng khuyến nghị 2026, Viện Dinh dưỡng | Mới có bản tóm tắt công khai | Bản đầy đủ của tài liệu cho bảng chi tiết |
| RecipeNLG | Chưa tải (không thuộc D0); điều khoản chỉ cho nghiên cứu, giáo dục phi thương mại | Chấp nhận điều khoản trên trang chính thức, khoảng 2,1 GB ổ |
