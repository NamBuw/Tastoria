# Tastoria — Thiết kế v2 (sau nghiên cứu, 17/10/2026)

Tài liệu này là bản thiết kế dùng để làm. Nền là `Tastoria_Tai_lieu_thiet_ke.pdf` (v1, 14/10/2026). Chỗ nào v2 khác v1 thì v2 thắng. Mỗi thay đổi ghi căn cứ: `R1`–`R4` là bốn báo cáo trong `docs/research/raw/` (01 ảnh, 02 học máy–dữ liệu, 03 công nghệ–phân tích thiết kế, 04 đối thủ–bằng chứng); `ml#`, `cv#`, `sad#`, `be#` là phát hiện của workflow soi tài liệu (6 góc nhìn). Mục đánh dấu **[Claude quyết]** là lựa chọn mình tự đưa ra vì người dùng giao toàn quyền ("xong thì tự code"); người dùng có thể đổi.

---

## 1. Mục đích

Tastoria trả lời câu "tối nay nấu gì" bằng **một mâm cơm Việt** ghép từ nguyên liệu đang có, ưu tiên đồ sắp hỏng, vừa nhu cầu năng lượng. Đầu vào là 1–2 ảnh tủ lạnh hoặc túi đồ vừa mua.

Định vị (sửa §1.5 v1 theo R4): từng thành phần đã có tiền lệ (gợi ý cả bộ món ở DELISH KITCHEN, me:new; ưu tiên đồ sắp hết hạn ở Samsung Food+, Frish). Chưa sản phẩm nào làm trọn chuỗi **một ảnh → mâm cơm Việt có định lượng khớp kho → ưu tiên đồ sắp hỏng → bám mục tiêu calo**, và chưa có gì tương tự bằng tiếng Việt. Kết quả chính cần chứng minh: mô hình tự huấn luyện so với Gemini trên nguyên liệu Việt.

**Mục tiêu**
1. Đủ sản phẩm chấm cho ba môn: Xử lý ảnh, Học máy, Phát triển ứng dụng thông minh (PTƯD), cộng bộ phân tích thiết kế hệ thống chuẩn (SRS, UML trong Visual Paradigm, ERD chuẩn hoá từng quan hệ).
2. Một hệ thống chạy thật: app Android + web (một mã nguồn), backend, mô hình, landing page, triển khai trên máy chủ.
3. Mọi con số trên app truy được về công thức có nguồn và dữ liệu có nguồn.

**Phi mục tiêu (ngoài phạm vi v2)**: tính calo từ ảnh món đã nấu; mã vạch, hoá đơn; thực đơn tuần; nhắc hạn dùng bằng thông báo đẩy; đặt hàng; hồ sơ nhiều người trong một hộ; thời tiết; bản iOS; slot "món tô" **[Claude quyết]** (giữ trong ghi chú tương lai, không có trong v2).

**Chống mục tiêu (làm ra cũng coi là hỏng)**
- Bịa dữ liệu: ảnh, khảo sát, đánh giá người dùng, kết quả thí nghiệm. Thiếu dữ liệu thật thì báo thiếu.
- Đề xuất mâm có món, gia vị hay đồ thay thế thuộc nhóm dị ứng người ăn đã khai.
- Đề xuất nấu đồ đã ở mức "kiểm tra trước khi dùng".
- Văn bản landing/app giọng quảng cáo, cường điệu.

## 2. Sản phẩm nộp (giả định, chưa được người dùng xác nhận)

| Môn | Sản phẩm |
|---|---|
| Xử lý ảnh | Báo cáo + mã: tiền xử lý (cân bằng trắng, CLAHE) có thí nghiệm 2×2; bộ phát hiện YOLO26n/YOLO11n; đếm; phân loại độ tươi cổ điển vs MobileNetV3; baseline Gemini 3 cấp; xuất ONNX chạy trong worker |
| Học máy | Báo cáo + notebook: xếp hạng gu (6 bậc, có cài đặt tự viết), ghép mâm có ràng buộc (mặt Pareto), thay thế nguyên liệu (bảng tra + Word2Vec), learning curve, ablation, phân tích lỗi |
| PTƯD | Bộ phân tích thiết kế (§12), mã backend + app + landing, triển khai, kiểm thử (đơn vị, tính chất, tích hợp, E2E, tải), đo độ trễ, bộ kiểm thử người dùng (SUS) |

Báo cáo viết Markdown → xuất PDF (pdflatex + vntex) và DOCX.

## 3. Bảng thay đổi chính so với v1

| # | v1 | v2 | Căn cứ |
|---|---|---|---|
| 1 | YOLOv8n, ultralytics 8.0.0 | YOLO26n (chính) và YOLO11n, ghim `ultralytics==8.4.x`; thử imgsz 640 và 960 | R1 §3, cv#11 |
| 2 | "Gemini không trả khung" | Gemini trả `box_2d` (0–1000) → so 3 cấp: khung, đếm, danh sách | R1 §5, cv#3 |
| 3 | ~30 lớp chọn theo tần suất trong công thức | ~20 lớp chọn theo 3 tiêu chí (nguyên liệu chính, để ngăn mát, tách được bằng mắt); bảng lớp ↔ nguyên liệu nhiều–nhiều; định nghĩa "một thể hiện" | cv#4 |
| 4 | Nhãn độ tươi = d/L FoodKeeper | Nhãn thị giác 4 mức do 2 người chấm (mù ngày chụp), κ trọng số; d/L là biến phụ; chỉ 6–8 loại rau lá/rau thơm/cà chua | cv#1, cv#5 |
| 5 | Độ gấp u lưu cứng, 3 mức | Tính lúc đọc theo **lô**; thêm mức 4 "kiểm tra trước khi dùng" bị loại khỏi kho khả dụng | cv#5, sad#6 |
| 6 | Kho 1 dòng/nguyên liệu, đơn vị tự do | `pantry_lots` + `pantry_transactions` (chỉ ghi thêm); đơn vị chuẩn là gam dạng khoảng [min, max] | sad#3, sad#6 |
| 7 | 5 bếp, test 1 bếp | Mục tiêu ≥ 12–15 hộ, ≥ 4 hộ test, ≥ 30–50 vật thể/lớp ở test; bootstrap cụm theo hộ | cv#2 |
| 8 | κ ≥ 0,8 sau ghép IoU, cùng sửa nháp | Vòng thử gán từ đầu, ghép Hungarian, F1 giữa người gán + κ trên cặp ghép, mục tiêu κ ≥ 0,81; test gán từ đầu | cv#6, ref[63] |
| 9 | Khảo sát 40–50 món chung, mô hình phản hồi ngầm | Khảo sát khối không đầy đủ (10 món neo + 35 món ngẫu nhiên phân tầng) + câu "5 món hay ăn"; bài toán xếp hạng điểm có bậc | ml#1, ml#2 |
| 10 | Food.com để chọn thuật toán | Food.com chỉ để kiểm cài đặt/tái lập (chia theo mốc thời gian toàn cục); chọn mô hình bằng CV lồng nhau trên khảo sát | ml#7, ml#8 |
| 11 | Bậc 5 LambdaMART gộp độ phủ/độ gấp/calo + thời tiết | LambdaMART là bộ xếp hạng gu theo đặc trưng; tín hiệu ngữ cảnh chỉ nằm trong bộ ghép mâm; bỏ thời tiết | ml#9 |
| 12 | Top-10 mỗi loại theo gu, 10³ tổ hợp | Cắt top-K theo điểm cấp món của chính hàm mục tiêu, ŝ chuẩn hoá về [0,1], có dự phòng khi không khả thi | ml#6, sad#10 |
| 13 | α, β, γ chọn theo tỷ lệ nhận mâm | Quy tắc công bố trước trên bộ kịch bản tủ lạnh, dùng điểm thật của người khảo sát làm "oracle" gu; vẽ mặt Pareto | ml#5 |
| 14 | Word2Vec trên RecipeNLG | Bảng tra cặp thay thế Việt (chính) + Word2Vec skip-gram trên danh sách nguyên liệu Food.com (230 nghìn công thức) để xếp lại trong nhóm; RecipeNLG tuỳ chọn | R2 §5, ml#11, ml#12 |
| 15 | Thay thế không kiểm dị ứng | Lọc cứng dị ứng/chế độ ăn cho cả gia vị và đồ thay thế; dị ứng người ăn cùng truyền theo bữa | ml#3, sad#4 |
| 16 | Danh mục dị ứng Codex trước 2024 | CXS 1-1985 sửa 2024: thêm vừng, đậu nành sang nhóm tuỳ quốc gia (Tastoria vẫn giữ đậu nành làm nhóm bổ sung) | ref[64], sad#4 |
| 17 | Lịch nấu LPT | CP-SAT (OR-Tools): NoOverlap cho bước chủ động, Cumulative theo số họng bếp (mặc định 2), thứ tự bước; mục tiêu cùng xong lúc dọn mâm | ml#15 |
| 18 | PAL 1,55/1,85/2,20 "khớp VN 2026" | PAL 1,50/1,75/2,00 theo tỷ lệ năng lượng công cụ tra cứu Viện Dinh dưỡng 2026 | R2 §7 |
| 19 | MinIO, Redis | Ổ đĩa + `X-Accel-Redirect` (MinIO archived 25/04/2026); Valkey 9 (BSD-3) thay Redis | R3 §3, be#8 |
| 20 | LightFM trong API | `lightfm-next` chỉ dùng khi huấn luyện; API chấm điểm bằng vector NumPy đã xuất | R2 §4, ml#14, be#11 |
| 21 | Huấn luyện Colab/Kaggle | Huấn luyện trên L40S của lab (Việt Nam) với giới hạn bộ nhớ; Colab chỉ cho dữ liệu công khai | be#7, sad#14 |
| 22 | "Khử định danh" bằng băm có muối | Gọi đúng là **bí danh hoá** (HMAC-SHA256, khoá tách riêng); vẫn là dữ liệu cá nhân nhạy cảm | be#7 |
| 23 | Đồng ý theo loại dữ liệu | Đồng ý theo **mục đích**, nhật ký chỉ ghi thêm, gắn phiên bản điều khoản; bảng yêu cầu của chủ thể dữ liệu | sad#11 |
| 24 | WCAG 2.1, 2.5.5 "tối thiểu 44 px" | WCAG 2.2 mức AA (2.5.8 = 24 px); Tastoria tự đặt vùng chạm ≥ 44 × 44 dp | R3 §4, sad#13 |
| 25 | Số liệu Food.com 270K/1,4M | 231.637 công thức, 226.570 người, 1.132.367 tương tác (đếm lại khi tải ở D0) | R2 §3, ml#7 |
| 26 | Đối thủ: Mama, Cookez, Chef Genie, Cold-to-Cooked | DELISH KITCHEN, me:new, Frish, Samsung Food+, Eat This Much, Cookpad VN, Thực đơn 365 | R4 §2 |
| 27 | — | Thêm chế độ quét "đồ vừa mua" (cho ngày mua thật, vật không bị che) | R4 §6 |

## 4. Quy tắc nghiệp vụ (BR)

Mỗi BR có ít nhất một ca kiểm thử tự động. Tham số in đậm nằm trong bảng cấu hình, đổi được.

**Mâm cơm**
- **BR-TRAY-01** Số người n ∈ [1, 6]. n = 1: mâm 2 món = mặn + (rau hoặc canh), lấy cặp có hàm mục tiêu cao hơn. n ≥ 2: mặn + rau + canh. Slot hợp lệ: `man`, `rau`, `canh`.
- **BR-TRAY-02** Lượng cần: need(r, i, n) = gam_i × n / servings_r; đồ đếm được làm tròn lên theo đơn vị.
- **BR-TRAY-03** Cơm là biến liên tục: số bát/người = clip((E_mâm − E_món/người) / E_bát, **0,5**, **3**), làm tròn 0,5 bát. E_bát tính từ bảng thành phần cho **150 g cơm** **[Claude quyết, đo lại khi có dữ liệu]**. App hiện "gợi ý x bát cơm".
- **BR-TRAY-04** Khả thi kho: với mọi nguyên liệu không phải gia vị luôn có, Σ need ≤ cận dưới của lượng khả dụng (lô ở mức ≤ "dùng ngay"). Chia nguyên liệu giữa các món được tính chung.
- **BR-TRAY-05** Thời gian: makespan lịch nấu (BR-COOK) ≤ thời gian tối đa người dùng chọn.
- **BR-TRAY-06** Không có mâm khả thi: thử mâm 2 món; vẫn không có thì trả danh sách nguyên liệu còn thiếu của 3 mâm tốt nhất để đưa vào danh sách đi chợ.
- **BR-TRAY-07** Năng lượng nhóm: E_mâm của nhóm = E_mâm người dùng × n (xấp xỉ, ghi rõ trên UI và báo cáo).
- **BR-TRAY-08** Người dùng ghim tối đa **2** lô "phải dùng"; mâm hợp lệ phải dùng mỗi lô ghim ít nhất **50%** lượng g_min của lô đó; không có mâm thoả thì báo và gợi ý bỏ ghim (R4 §6).
- **BR-SWAP-01** Đổi món = giải lại với các slot còn lại cố định, loại các món đã bị đổi ra trong mâm này. Người dùng chọn 1 lý do: không hợp gu / mới ăn / thiếu thời gian / khác. Chỉ "không hợp gu" là nhãn âm về gu.

**Dị ứng, chế độ ăn**
- **BR-ALG-01** Không món, gia vị hay đồ thay thế nào trong mâm thuộc nhóm dị ứng hoặc trái chế độ ăn đã khai của người dùng **hoặc người ăn cùng của bữa đó**. Gia vị luôn có trong `recipe_ingredients` với `is_staple = true`; cờ này chỉ miễn kiểm kho, không miễn kiểm dị ứng. Kiểm thử: toàn kho món × mọi nhóm dị ứng = 0 vi phạm, chạy trong CI.
- **BR-ALG-02** Nhóm dị ứng theo Codex CXS 1-1985 sửa 2024 (ngũ cốc chứa gluten, giáp xác, trứng, cá, đậu phộng, sữa, vừng, hạt cây) + nhóm bổ sung đậu nành, nhuyễn thể.
- **BR-DIET-01** Chế độ ăn (v2: `chay`) loại các nhóm thực phẩm qua bảng `diet_exclusions`.

**Lượng và kho**
- **BR-QTY-01** Đơn vị tính chuẩn là gam khối lượng lúc mua. Kho lưu khoảng [g_min, g_max].
- **BR-QTY-02** Đồ đếm được quy đổi qua `ingredient_units` (ví dụ 1 quả trứng gà = **50 g**, nguồn ghi trong bảng). Mức ít/vừa/nhiều quy đổi qua `qty_levels` theo nhóm thực phẩm (ghi đè được theo nguyên liệu).
- **BR-PANTRY-01** Mỗi lần thêm đồ tạo một **lô** riêng có `acquired_at` (ngày mua người dùng nhập, nếu không thì lần đầu thấy).
- **BR-PANTRY-02** Trừ kho khi nấu xong theo lô có độ gấp cao nhất trước; ghi giao dịch âm; **hoàn tác trong 10 phút** bằng giao dịch đảo.
- **BR-PANTRY-03** Quét toàn tủ: lô không thấy trong lần quét chuyển `not_seen` và hỏi người dùng, không tự xoá. Quét "đồ vừa mua": chỉ thêm lô mới, ngày mua = hôm nay.
- **BR-SCAN-01** Gộp nhiều ảnh trong một lần quét: cùng một ngăn thì số đếm của lớp = max giữa các ảnh; người dùng đánh dấu "ngăn khác" thì cộng.
- **BR-SCAN-02** Chỉ `POST /scans/{id}/confirm` (lũy đẳng, từ trạng thái `done`) mới ghi vào kho; sửa chip không ghi kho.

**Độ tươi và độ gấp**
- **BR-FRESH-01** u_time = d / L, d = số ngày từ `acquired_at`, L = thời hạn ngăn mát của nguyên liệu (FoodKeeper ánh xạ, hiệu chỉnh theo dữ liệu nhóm khi có).
- **BR-FRESH-02** u_img = Σ_c P(c)·m(c) với m(tươi) = **0,25**, m(dùng sớm) = **0,65**, m(dùng ngay) = **0,9**, m(kiểm tra) = **1,2**, từ bộ phân loại đã hiệu chỉnh nhiệt độ. Lô không có ảnh độ tươi: u = u_time.
- **BR-FRESH-03** Ngày mua do người dùng nhập: u = max(u_time, u_img). Ngày chỉ là lần đầu thấy và max P(c) ≥ **0,6**: u = u_img; còn lại u = max(u_time, u_img).
- **BR-FRESH-04** Nhãn: u < **0,5** tươi; [0,5; 0,8) nên dùng sớm; [0,8; 1,0] dùng ngay; > 1,0 hoặc lớp "kiểm tra" có xác suất lớn nhất → **kiểm tra trước khi dùng**: không tính vào lượng khả dụng, không được thưởng trong hàm mục tiêu, chip buộc người dùng xác nhận. Ngưỡng chọn trên lô validation theo nhãn thị giác rồi khoá trước khi test.
- **BR-FRESH-05** u tính lúc đọc, không lưu. Nhãn trên app luôn có chữ kèm chấm màu; là gợi ý chất lượng, không kết luận an toàn thực phẩm.

**Năng lượng (mục 2 v1, có sửa)**
- **BR-NUT-01** Chỉ phục vụ người ≥ 18 tuổi. Khoảng tuổi nửa mở [18, 30), [30, 60), ≥ 60. BMR mặc định FAO/WHO/UNU 1985 theo cân nặng (bảng ở v1 §2.1, đã xác minh R2 §7); Mifflin–St Jeor là phương án so sánh.
- **BR-NUT-02** PAL: nhẹ **1,50**, trung bình **1,75**, nặng **2,00** (R2 §7). TEE = BMR × PAL.
- **BR-NUT-03** Giảm cân: E = TEE − **500**, không dưới **1.200** (nữ) / **1.500** (nam) kcal. Mục tiêu do chuyên gia đặt ghi đè mọi công thức. Không có tăng cân tự động.
- **BR-NUT-04** E_mâm = E × s, s = **0,35** bữa trưa, **0,30** bữa tối.
- **BR-NUT-05** Dinh dưỡng món theo EuroFIR: Σ w_i·EP_i/100·n_ik·RF_ik; RF = 1 cho năng lượng và chất sinh năng lượng ở v2; món rán ngập dầu dùng hệ số hấp thu chất béo. Lưu kèm phiên bản dữ liệu.
- **BR-NUT-06** Calo hiển thị dạng khoảng; nửa độ rộng = phân vị 80 của sai số tương đối khi so ≥ 30 món với Viện Dinh dưỡng. Chưa đo xong thì không hiện khoảng, hiện "đang hiệu chỉnh".

**Đồng ý và quyền dữ liệu**
- **BR-CONSENT-01** Mục đích: `health_profile` (nhạy cảm), `personalization` (dữ liệu hành vi, nhạy cảm), `photo_contribution` (tuỳ chọn, mặc định tắt), `survey` (người tham gia khảo sát). Không tích sẵn.
- **BR-CONSENT-02** Không đồng ý `health_profile`: không lưu chỉ số cơ thể; β = 0; app hiện "chưa có mục tiêu".
- **BR-CONSENT-03** Không đồng ý `personalization`: không ghi `interactions`; xếp hạng dùng trung bình món + content-based từ 5 món hay ăn.
- **BR-CONSENT-04** Rút đồng ý có hiệu lực ngay (tăng `token_version`), xoá dữ liệu của mục đích đó trong ≤ 24 giờ.
- **BR-DSR-01** Yêu cầu của chủ thể dữ liệu (truy cập, sửa, tải về, xoá, rút đồng ý, hạn chế, phản đối) ghi vào `dsr_requests`; hệ thống tự hoàn tất ≤ 24 giờ, luôn trong hạn NĐ 356/2025 Điều 5.
- **BR-RETAIN-01** Ảnh quét gốc xoá sau **30 ngày** trừ khi đã đồng ý góp ảnh. Bản sao lưu giữ ≤ **14 ngày** (7 bản ngày + 1 bản tuần) để nằm trong hạn xoá 20 ngày.

**Kho món**
- **BR-CATALOG-01** Món ở trạng thái `published` là bất biến: sửa nguyên liệu hoặc bước thì tạo bản mới và chuyển bản cũ sang `retired`; mâm và phiên nấu cũ vẫn trỏ đúng bản đã dùng. Nguyên liệu và món không bị xoá cứng (chỉ `is_active=false` / `retired`); dữ liệu cá nhân thì xoá cứng.

**Nấu**
- **BR-COOK-01** Lịch nấu: một người nấu không làm hai bước chủ động cùng lúc; số bước chiếm bếp đồng thời ≤ số họng bếp (mặc định **2**); bước trong một món theo thứ tự; mọi món xong trong cửa sổ **5 phút** trước giờ dọn, món xào xong cuối.
- **BR-COOK-02** "Nấu xong" lũy đẳng: trừ kho + ghi tương tác + chuyển trạng thái trong một giao dịch. Đánh giá thích/không thích **theo từng món**.

## 5. Dữ liệu

| Dữ liệu | Nguồn | Dùng cho |
|---|---|---|
| Thành phần thực phẩm | Bảng TPTP VN 2007 (PDF trên FAO, 526 thực phẩm, có tỷ lệ thải bỏ, mã TCVN3); USDA FDC Foundation + SR Legacy (CC0) khi thiếu | Dinh dưỡng món, EP |
| Thời hạn bảo quản | FSIS FoodKeeper (CC0) | L ban đầu |
| Kho công thức | Nhóm biên soạn 150–200 món mặn/rau/canh, gam lúc mua, bước chủ động/thụ động/chiếm bếp, ghi nguồn từng món (≥ 2 nguồn), viết lại bằng lời mình | Ghép mâm, dinh dưỡng, lịch nấu |
| Kiểm định calo | Tra tay ≥ 30 món ở công cụ Viện Dinh dưỡng (không tải hàng loạt) | Nửa độ rộng khoảng calo |
| Tương tác công khai | Food.com (Kaggle, "© Original Authors", nghiên cứu) | Kiểm cài đặt gợi ý; Word2Vec |
| Ảnh huấn luyện công khai | Open Images V7 (CC BY), bộ Mendeley CC BY (Bangladesh vegetables, Local Spinach Leaf, AgriFreshNET), bộ Roboflow CC BY (cần API key) | Tiền huấn luyện, train |
| Ảnh tủ lạnh của nhóm | ≥ 12–15 hộ, 2–3 phiên/hộ, metadata hộ/phiên/ngăn/đèn/máy | Train + **toàn bộ tập test** |
| Lô độ tươi của nhóm | 6–8 loại, ≥ 6–8 lô/loại, ≥ 3 nơi mua, chụp kiểu quét 2 lần/ngày, thẻ xám ở góc | Bộ phân loại độ tươi |
| Khảo sát gu | 80–100 người, khối không đầy đủ, thử trước 15–20 người | Xếp hạng gu |
| Cặp thay thế | 80–100 truy vấn (món, nguyên liệu thiếu), 2 người soạn đáp án độc lập trước khi chạy mô hình | Đánh giá thay thế |

Dữ liệu cần người thật (ảnh, lô rau, khảo sát, đáp án thay thế, người thử app) **không được sinh giả**. Hệ thống có sẵn công cụ thu (trang khảo sát, chế độ góp ảnh, hướng dẫn chụp, bộ gán nhãn); trong lúc chờ, báo cáo dùng dữ liệu công khai và ghi rõ giới hạn.

## 6. Học máy

**6.1 Xếp hạng gu** — ŝ(u, r) chỉ đo gu, không chứa tín hiệu ngữ cảnh.
- Bậc: (1) trung bình món có co rút; (2) bias người + món; (3) content-based: cosine giữa vector gu (trung bình đặc trưng của 5 món hay ăn) và vector món (nguyên liệu, cách nấu, thẻ vị); (4) biased MF tường minh và BPR với cặp từ chênh lệch điểm — **tự cài bằng NumPy/PyTorch**, đối chiếu thư viện (Cornac/implicit); (5) LightFM (`lightfm-next`) loss logistic nhãn ±1 (≥ 4 → +1, ≤ 2 → −1) với đặc trưng người = 5 món hay ăn; (6) LambdaMART (LightGBM lambdarank) nhãn = điểm − 1, đặc trưng: thẻ, nguyên liệu, cách nấu, độ khớp 5 món hay ăn, trung bình món, điểm MF ngoài fold.
- Đánh giá trên khảo sát: CV lồng nhau theo người; NDCG@5 có bậc (gain = điểm − 1) + AUC cặp theo người; tách theo slot; warm, item cold-start (giữ 20% món), user cold-start (giữ 20% người, chỉ thấy 5 món hay ăn); ≥ 5 seed; so sánh chính duy nhất: mô hình cá nhân hoá tốt nhất vs trung bình món; còn lại hiệu chỉnh Holm; bootstrap cặp theo người.
- Food.com: chia theo mốc thời gian toàn cục (10% muộn nhất test, 10% liền trước validation), 5-core, xếp trên toàn bộ món, HR@10, NDCG@10; rating 0 = không chấm sao.
- Thí nghiệm bổ sung: learning curve (20/40/60/80 người), ablation đặc trưng, độ nhạy số chiều và λ, phân tích lỗi.
- Phục vụ: xuất vector/điểm ra NumPy; ŝ' = phân vị theo người trong từng slot.

**6.2 Ghép mâm** — max Σ ŝ'(u,r) + α·U(m) − β·|E(m) − E_mâm|/E_mâm − γ·D(m), ràng buộc BR-TRAY, BR-ALG, BR-DIET.
- U(m) = Σ_i u_i·min(1, dùng_i/có_i) / Σ_i u_i trên lô có u ∈ [0,5; 1,0]; D(m) phạt trùng cách nấu hoặc nguyên liệu chính.
- Ứng viên: mọi món qua lọc cứng; cắt top-K = **20** mỗi slot theo điểm cấp món (ŝ' + α·U_r − β·lệch calo_r); duyệt tổ hợp, kiểm khả thi gộp; hết khả thi thì K = toàn bộ; vẫn hết thì BR-TRAY-06.
- Dòng lý do: thành phần đóng góp chuẩn hoá lớn nhất so với mâm tốt nhì.
- Trọng số: bộ 100–200 kịch bản tủ lạnh (nhãn test ảnh + tủ tổng hợp từ đồng xuất hiện), tách chỉnh/test; oracle gu = điểm thật của người khảo sát; quy tắc công bố trước: tối đa lượng đồ gấp được dùng với gu giảm ≤ **0,2** điểm và |ΔE|/E ≤ **15%**; vẽ mặt Pareto.
- Đánh giá: khả thi = kiểm thử tính chất (100% theo cấu tạo); so với "top-1 theo gu mỗi slot có kiểm khả thi" trên kịch bản test: lượng đồ gấp dùng, gu, lệch calo, đa dạng; kiểm định ghép cặp.

**6.3 Thay thế nguyên liệu**
- Nguồn ứng viên: (a) bảng tra cặp thay thế tiếng Việt do nhóm soạn có ngữ cảnh (slot, cách nấu) và nguồn; (b) Word2Vec skip-gram (`sg=1`, window ≥ độ dài danh sách dài nhất, `shrink_windows=False`) trên danh sách nguyên liệu Food.com + kho Việt, qua bảng đồng nghĩa Việt–Anh; (c) dự phòng kNN vector dinh dưỡng trong nhóm.
- Lọc cứng: cùng nhóm thực phẩm, qua BR-ALG/BR-DIET, không phải cặp bổ sung (PMI cao); tự động ghép mâm chỉ dùng (a) và đồ có trong kho; "Thiếu gì?" hiện 3 gợi ý, người dùng chấp nhận thì ghi `meal_plan_item_substitutions` và tính lại dinh dưỡng.
- Đánh giá: Hit@1/3, MRR, độ phủ; baseline ngẫu nhiên cùng nhóm, kNN dinh dưỡng, PMI kiểu Teng, bảng tra; dev 30% / test 70%; McNemar hoặc bootstrap cặp.

**6.4 Tái lập** — MLflow (SQLite + thư mục artifact trên máy lab); mỗi run ghi commit, sha256 dữ liệu, seed, danh sách id test, phiên bản thư viện.

## 7. Xử lý ảnh

- **Lớp**: bảng `vision_classes` (~20 lớp) với tên Việt/Anh, ánh xạ nhiều–nhiều tới nguyên liệu, đếm được hay không, định nghĩa một thể hiện (quả / bó-túi kiểu group-of / gói), có mô hình độ tươi hay không. Mỗi lớp ≥ 300 vật thể train, ≥ 30–50 vật thể test; không đạt thì gộp nhãn cha (ví dụ "rau cải") hoặc bỏ. 5–10% ảnh nền.
- **Gán nhãn**: vòng thử 100–150 ảnh gán từ đầu bởi 2 người; ghép Hungarian IoU ≥ 0,5 không phân lớp; báo F1 giữa người, tỷ lệ không ghép, trung vị IoU, κ tên lớp (mục tiêu ≥ 0,81); hướng dẫn v2; test gán từ đầu có phân xử; nháp Grounding DINO/YOLOE chỉ cho train.
- **Bộ phát hiện**: YOLO26n vs YOLO11n × imgsz {640, 960}, chọn trên val rồi khoá; ONNX; đo độ trễ CPU trên máy đích (`--cpus=2 --memory=4g`). Huấn luyện trên L40S: batch cố định, `set_per_process_memory_fraction(0.15)`, kiểm `nvidia-smi` trước, một job một lúc, chạy thử 1 epoch.
- **Tiền xử lý**: 2×2 (gray-world × CLAHE-L) + nhánh "chỉ tăng cường"; áp giống nhau train/val/test ở mức toàn ảnh, không áp lên khung cắt; ≥ 3 seed; biên tương đương ±1,5 mAP50-95; tham số CLAHE chọn trên val. Đánh giá riêng cân bằng trắng bằng thẻ xám (sai số góc; gray-world vs shades-of-gray vs gray-edge, RGB tuyến tính, bỏ điểm cháy).
- **Đếm**: tính trên cặp (ảnh, lớp đếm được) có c > 0 hoặc ĉ > 0; MAE, MAE tương đối, đúng tuyệt đối, đúng ±1; ngưỡng conf chọn trên val; baseline đếm từ khung Gemini và trung vị theo lớp.
- **Độ tươi**: 6–8 loại; nhãn thị giác 4 mức, 2 người chấm mù ngày, κ trọng số bậc hai; cổ điển (HSV + LBP + GLCM trên mặt nạ tiền cảnh, SVM RBF) vs MobileNetV3-Small; GroupKFold theo lô 5 × 3; macro-F1 + κ trọng số + MAE bậc; bootstrap cụm theo lô; McNemar chính xác chỉ là phân tích phụ. Khung cắt từ ảnh 1.280 px.
- **Gemini**: model ID ghim + ngày chạy; prompt đóng (enum 20 lớp), nhiệt độ 0, media_resolution cố định, chọn prompt trên val; 3 lần chạy; gói trả phí; chỉ ảnh của nhóm đã được chủ bếp đồng ý.
- **Vòng phản hồi**: sửa chip là tín hiệu chọn ảnh cho học chủ động (với người đã đồng ý góp ảnh), không phải nhãn khung.

## 8. Kiến trúc backend

- **Modular monolith** FastAPI, mỗi module một package có `service.py` là giao diện công khai; module khác chỉ gọi service; cưỡng chế bằng `import-linter`. Module: `identity`, `privacy`, `profile`, `catalog`, `pantry`, `scan`, `meal`, `substitute`, `cooking`, `journal`, `events`, `survey`, `mlops`, `admin`.
- Thao tác nhiều module (nấu xong, xác nhận quét) chạy trong một **Unit of Work** (một giao dịch DB).
- **API**: tiền tố `/api/v1`; lỗi RFC 9457 `application/problem+json` có `code` ổn định; header `Idempotency-Key` cho POST quét, mâm, phiên nấu, nấu xong (bảng `idempotency_keys`, giữ 48 giờ); `event_id` do app sinh cho `/events`; phân trang keyset (created_at, id); tuần ISO 8601, múi giờ Asia/Ho_Chi_Minh; id công khai UUID; mọi truy vấn theo {id} lọc theo chủ sở hữu (chống BOLA).
- **Quét bất đồng bộ**: `POST /scans` → 202 + `Location` + `Retry-After: 1`; `GET /scans/{id}?wait=10` long-poll; trạng thái queued → processing → done | failed | expired; job timeout 30 s, thử lại tối đa 2 lần; sweeper mỗi phút.
- **Worker**: Valkey + RQ; nạp phiên ONNX một lần trước khi nhận job; `intra_op_num_threads = 2`, tắt spin; job: suy luận quét, xuất dữ liệu người dùng, xoá tài khoản.
- **Việc định kỳ**: container `scheduler` (cron) gọi `python -m tastoria.jobs.<tên>`: xoá ảnh quá hạn, sao lưu, dọn token/idempotency hết hạn.
- **Lưu tệp**: volume riêng, thư mục `tmp/` (xoá 30 ngày), `contrib/`, `models/`; API kiểm quyền rồi trả `X-Accel-Redirect` tới location internal của nginx.
- **Ảnh tải lên**: ≤ 2 ảnh × 3 MB, kiểm magic bytes, Pillow `MAX_IMAGE_PIXELS` = 4096², `exif_transpose` rồi mã hoá lại JPEG không metadata.
- **Xác thực**: Argon2id (`pwdlib`); access JWT 15 phút có `kid`; refresh token ngẫu nhiên 30 ngày lưu băm, xoay vòng theo family, dùng lại token đã thu hồi → thu hồi cả family; `/auth/logout`, `/auth/logout-all`; `users.token_version`; khoá 15 phút sau 5 lần sai theo (email, IP) trong Valkey; đặt lại mật khẩu qua email (dev: Mailpit).
- **Mã hoá cột**: chỉ số cơ thể mã hoá ở tầng ứng dụng (AES-GCM, `key_id`); chỉ module `profile` giải mã; module khác nhận ràng buộc qua `profile.get_meal_constraints()`.
- **Mô hình**: `model_versions` (sha256, class_map, preprocess_version, metrics, status) + `model_deployments` làm con trỏ duy nhất tới bản đang chạy; đổi bản = đổi con trỏ + restart; quay lui < 5 phút.

## 9. App, giao diện, landing

- **App**: Expo SDK 58 (React Native 0.88), TypeScript, expo-router, một mã nguồn cho Android và web (`web.output: "single"`). Mô-đun bên thứ nhất: camera, image-picker, image-manipulator (nén 1.280 px JPEG), secure-store (token), sqlite (catalog + phiên nấu offline), notifications, keep-awake. Client API sinh từ OpenAPI. Hàng đợi outbox cho nấu xong, sự kiện, sửa chip.
- **Màn hình** (bổ sung so với v1 Hình 1): Đăng ký/Đăng nhập, Quên mật khẩu, Hồ sơ 60 giây (4 bước + màn đồng ý riêng), Trang chủ, Quét (toàn tủ / đồ vừa mua), Xác nhận nguyên liệu, Kho, Mâm cơm hôm nay, Đổi món (lý do), Thiếu gì?, Danh sách đi chợ, Nấu cả mâm, Nấu xong, Nhật ký, Cài đặt (hồ sơ, đồng ý, tải dữ liệu, xoá tài khoản), Khảo sát gu (người ngoài, không cần tài khoản).
- **Ngôn ngữ thị giác** giữ v1 §5.2: nền kem màu gạo, nhấn nâu đất nung, xanh lá/hổ phách/đỏ cam + **xám** (mức "kiểm tra") cho độ tươi, Be Vietnam Pro (tự host WOFF2), mâm tròn nhìn từ trên. Chế độ tối.
- **Landing**: HTML/CSS tĩnh, không framework; câu chữ mô tả thẳng, số liệu thật đã đo.

## 10. Triển khai

- Docker Compose trên máy chủ lab (đóng vai VPS): `nginx` (cổng duy nhất, bind 127.0.0.1), `api`, `worker`, `scheduler`, `migrate` (chạy một lần, có pg_dump trước), `postgres` (PostgreSQL 18 + pgvector 0.8.x), `valkey`. Landing và web app là tệp tĩnh trong nginx. Ra Internet qua Cloudflare Tunnel sẵn có (cần người dùng đồng ý tên miền).
- Sao lưu: `pg_dump -Fc` mã hoá, đẩy ra Drive bằng rclone, giữ ≤ 14 ngày; script khôi phục + diễn tập.
- Healthcheck `/healthz`, `/readyz`; log JSON có `request_id`.

## 11. Yêu cầu phi chức năng (rút gọn; bản đầy đủ ở SRS)

| Mã | Yêu cầu | Ngưỡng | Điều kiện đo |
|---|---|---|---|
| NFR-PERF-01 | Xử lý quét ở server (enqueue → done) | p95 đặt theo số đo vòng đầu; mục tiêu ≤ 3 s | `--cpus=2 --memory=4g`, ảnh 1.280 px thật, 1 worker, 5 người đồng thời, ≥ 300 mẫu |
| NFR-PERF-02 | `POST /meal-plans` | p95 ≤ 1 s | kho 200 món, 30 lô |
| NFR-PERF-03 | Quét đầu–cuối trên điện thoại | báo p50/p95 theo Wi-Fi/4G | mốc thời gian phía app |
| NFR-REL-01 | Khôi phục | RPO ≤ 24 h, RTO ≤ 2 h, diễn tập ≥ 1 lần | |
| NFR-SEC-01 | Token | access 15 phút, refresh 30 ngày xoay vòng | |
| NFR-SEC-02 | Đăng nhập sai | khoá 15 phút sau 5 lần | |
| NFR-PRIV-01 | Yêu cầu chủ thể dữ liệu | hoàn tất ≤ 24 h | |
| NFR-A11Y-01 | Truy cập | WCAG 2.2 AA; vùng chạm ≥ 44 × 44 dp | |
| NFR-USE-01 | Khả dụng | SUS ≥ 68; ≥ 80% người thử hoàn thành mỗi nhiệm vụ | 8–10 người |
| NFR-MAINT-01 | Kiểm thử | độ phủ ≥ 80% cho meal, pantry, profile, cooking; import-linter xanh | CI |

## 12. Bộ sản phẩm phân tích thiết kế hệ thống

1. SRS theo ISO/IEC/IEEE 29148:2018: phạm vi, bên liên quan, thuật ngữ; FR/NFR/BR có mã, MoSCoW, tiêu chí chấp nhận Given/When/Then; giả định, ràng buộc.
2. Sơ đồ use case: tổng quan + theo gói; actor: Khách, Người dùng, Người ăn cùng (không tài khoản, qua người dùng), Người tham gia khảo sát, Quản trị viên, Người biên soạn công thức, Người vận hành mô hình, Người gán nhãn, Bộ lập lịch (thời gian), Dịch vụ email. Đặc tả use case kiểu Cockburn cho từng UC.
3. Sơ đồ hoạt động có làn; sơ đồ tuần tự cho các luồng lõi; sơ đồ lớp phân tích (BCE) và thiết kế; 8 sơ đồ máy trạng thái (Scan, MealPlan, CookSession, Consent, PantryLot, Account, ModelVersion, DsrRequest); sơ đồ thành phần (module + phụ thuộc được phép); sơ đồ gói; sơ đồ triển khai.
4. ERD mức khái niệm (Chen) → logic/vật lý (Crow's foot), phân tích phụ thuộc hàm và dạng chuẩn từng quan hệ (đến BCNF, ghi rõ phi chuẩn hoá có kiểm soát), từ điển dữ liệu, ràng buộc, chỉ mục.
5. Ma trận truy vết UC ↔ FR ↔ API ↔ module ↔ bảng ↔ ca kiểm thử, không ô trống.
6. Kế hoạch kiểm thử; ADR; hồ sơ đánh giá tác động xử lý dữ liệu cá nhân (mẫu).
7. **Bộ nhập Visual Paradigm**: PlantUML (nhập bằng plugin PlantUML-VP), `schema_vp.sql` cho Tools > DB > Reverse DDL, hướng dẫn từng bước; ảnh SVG/PNG render sẵn. Nguồn chuẩn của lược đồ là migration Alembic; ERD đối chiếu với migration trước khi nộp.

## 13. Cần người dùng cung cấp hoặc quyết định (không chặn việc khác)

1. Hạn nộp và tiêu chí chấm từng môn (đang giả định theo §2).
2. Ảnh tủ lạnh ≥ 12–15 hộ, lô rau độ tươi, người chấm nhãn thị giác, 80–100 người khảo sát, 2 người soạn đáp án thay thế, 8–10 người thử app.
3. API key Gemini (gói trả phí) cho baseline; API key Roboflow (miễn phí) nếu muốn dùng bộ ảnh cộng đồng.
4. Đồng ý đưa lên tên miền công khai (đề xuất `tastoria.ctslab.net`) và đẩy repo lên GitHub.
5. Phiên bản Visual Paradigm dùng được (Community hay có Standard/thử 30 ngày) để chọn cách dựng ERD.
