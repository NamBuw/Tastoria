# Kế hoạch kiểm thử Tastoria

Phiên bản 1.1 — 17/10/2026. Nguồn mã: `docs/sad/model.yaml` (actor, UC, module, bảng, endpoint, BR, NFR); nội dung, ngưỡng và điều kiện đo của BR và NFR lấy từ SRS (`docs/sad/01-SRS.md` §3.3, §3.4), là bản chi tiết của §4 và §11 thiết kế v2; FR ở bảng "Yêu cầu chức năng" của từng `docs/sad/use-cases/UCxx.md`. Cấu trúc tài liệu theo ISO/IEC/IEEE 29119-3 ở mức kế hoạch kiểm thử tổng thể (master test plan) gộp với đặc tả ca kiểm thử.

## 1. Mục tiêu và phạm vi

### 1.1. Mục tiêu

1. Chứng minh mỗi yêu cầu chức năng (FR) trong 34 đặc tả use case có ít nhất một ca kiểm thử với kết quả mong đợi kiểm được bằng máy hoặc bằng quan sát có tiêu chí.
2. Chứng minh mỗi quy tắc nghiệp vụ (BR) có ít nhất một ca kiểm thử tự động (yêu cầu ở §4 bản thiết kế v2). Ba quy tắc an toàn lõi — BR-ALG-01 (dị ứng), BR-TRAY-04 (khả thi kho), BR-COOK-01 (lịch nấu) — được kiểm bằng kiểm thử tính chất trên toàn miền đầu vào, không chỉ ví dụ.
3. Đo mỗi yêu cầu phi chức năng (NFR, gồm mọi điều khoản con dạng `NFR-…-nn.x`) và ràng buộc RB-06 theo đúng ngưỡng và điều kiện đo ghi ở SRS §3.4 (§2.4 với RB-06).
4. Giữ ma trận truy vết UC → FR → TC không có ô trống (`docs/sad/tools/gen_traceability.py`).

### 1.2. Trong phạm vi

- Backend FastAPI (16 module M01–M16), 70 endpoint dưới `/api/v1` cùng `GET /healthz`, `GET /readyz`, 13 lệnh CLI và 3 tác vụ định kỳ.
- CSDL PostgreSQL 18 + pgvector: ràng buộc, trigger chỉ ghi thêm, view `v_current_consents`, `v_pantry_lot_balance`, `v_journal_days`.
- Worker quét (Valkey + RQ, ONNX Runtime), bộ ghép mâm, bộ lập lịch CP-SAT, bộ gợi ý thay thế.
- App Expo một mã nguồn: bản web (Playwright) và bản Android (Maestro).
- Hồ sơ mô hình ở mức tích hợp: cổng kiểm định (UC29), tương đương ONNX/PyTorch, tiền xử lý.

### 1.3. Ngoài phạm vi

- Chất lượng thống kê của mô hình (mAP, macro-F1, NDCG, Hit@k): đánh giá trong báo cáo môn Xử lý ảnh và Học máy theo §6–§7 bản thiết kế v2. Kế hoạch này chỉ kiểm cơ chế cổng và tính tái lập.
- Landing page tĩnh (chỉ kiểm liên kết hỏng và axe-core trong CI, không lập ca riêng).
- Các phi mục tiêu ở §1 bản thiết kế v2 (iOS, mã vạch, thông báo đẩy, …).
- Rà soát pháp lý hồ sơ đánh giá tác động dữ liệu cá nhân: ca kiểm thử chỉ kiểm cơ chế kỹ thuật của BR-CONSENT-*, BR-DSR-01, BR-RETAIN-01.

## 2. Chiến lược theo tầng

Mỗi tầng có công cụ, nơi chạy và ngưỡng chặn riêng. Ca kiểm thử ở §5 ghi "Loại" theo tầng dưới đây.

| Tầng | Công cụ | Chạy ở | Chặn hợp nhất khi |
|---|---|---|---|
| Đơn vị | pytest, freezegun | mỗi commit (CI) | một ca đỏ hoặc độ phủ dưới ngưỡng NFR-MAINT-01 |
| Tính chất | Hypothesis (profile `ci` 200 ví dụ, `nightly` 2.000) | mỗi commit + hằng đêm | một phản ví dụ |
| Tích hợp API | pytest + httpx `AsyncClient`, PostgreSQL và Valkey thật qua docker compose | mỗi commit | một ca đỏ |
| Hợp đồng | Schemathesis, openapi-spec-validator | mỗi PR | một 5xx hoặc lệch schema |
| Bảo mật | pytest (BOLA, lũy đẳng, tải lên), pip-audit, npm audit | mỗi PR | một ca đỏ; lỗ hổng mức cao |
| Vận hành (CLI/job) | pytest gọi lệnh CLI và `python -m tastoria.jobs.*` trong container `api` | mỗi PR | một ca đỏ |
| Mô hình | pytest trên bộ ảnh vàng, cổng UC29 | khi đăng ký mô hình | lệch vượt dung sai |
| E2E | Playwright (web), Maestro (Android emulator) | hằng đêm + trước phát hành | một luồng đỏ |
| Tải | k6, Locust | trước phát hành, trên máy đích | p95 vượt ngưỡng NFR-PERF |
| UAT | phiên thử có người điều phối, bảng SUS | một vòng trước nộp | NFR-USE-01 không đạt |
| Kiểm tra quy trình | đối chiếu nhật ký, sổ MLflow, danh sách máy | trước phát hành | một bản ghi không đạt (NFR-PRIV-01.d, NFR-MAINT-01.c) |

### 2.1. Kiểm thử đơn vị

Phủ các hàm thuần, không I/O:

- **Công thức năng lượng** (module profile): tuổi theo năm Asia/Ho_Chi_Minh, BMR FAO/WHO/UNU 1985 theo giới × 3 khoảng tuổi nửa mở, PAL 1,50/1,75/2,00, giảm cân TEE − 500 với sàn 1.200/1.500 kcal, E_mâm × 0,35/0,30, Mifflin–St Jeor so sánh (TC-NUT-01 đến TC-NUT-04, TC-NUT-07, TC-NUT-11). Ca tham số hoá lấy giá trị tính tay từ bảng hệ số, kiểm cả biên 18, 30, 60 tuổi.
- **Quy đổi lượng** (module pantry, catalog): need(r, i, n) = gam_i × n / servings_r, làm tròn lên theo `ingredient_units`, quy đổi mức ít/vừa/nhiều qua `qty_levels`, lượng thay thế theo `ratio` (TC-MEAL-05, TC-SCAN-19, TC-MEAL-34, TC-COOK-10).
- **Độ gấp** (module pantry): u_time = d/L, u_img = Σ P(c)·m(c), kết hợp theo BR-FRESH-03, nhãn theo ngưỡng 0,5/0,8/1,0 (TC-PANT-02 đến TC-PANT-04, TC-SCAN-11, TC-SCAN-14). Ca biên dùng giá trị sát ngưỡng (0,4999; 0,5; 0,7999; 0,8; 1,0; 1,0001).
- **Ghép mâm**: hàm mục tiêu, U(m), số bát cơm, top-K so với duyệt vét cạn trên kho tổng hợp nhỏ (TC-MEAL-10, TC-MEAL-11, TC-MEAL-14).

Ngưỡng tham số in đậm ở §4 bản thiết kế v2 đọc từ cấu hình; ca đơn vị đọc cùng cấu hình đó, nên đổi tham số không cần sửa ca, chỉ đổi giá trị mong đợi tính sẵn trong fixture.

### 2.2. Kiểm thử tính chất (Hypothesis)

Dùng khi miền đầu vào quá lớn để liệt kê và vi phạm là lỗi an toàn:

- **BR-ALG-01, 0 vi phạm** (TC-PROP-01): với toàn bộ kho món thật × mọi nhóm trong `allergen_groups` (10 nhóm) và mọi tập con 1–3 nhóm của người dùng cộng người ăn cùng, mọi đầu ra của ghép mâm, đổi món và gợi ý thay thế không chứa nguyên liệu thuộc nhóm đã khai, kể cả gia vị `is_staple` và đồ `is_optional`. Phần duyệt món × nhóm là vét cạn (không ngẫu nhiên); phần kho và yêu cầu do Hypothesis sinh. Chạy trong CI, đỏ khi có ≥ 1 vi phạm. Cùng kiểm tra được gọi sau mỗi lần nhập kho món (TC-CAT-06).
- **BR-TRAY-04, khả thi kho** (TC-PROP-03): mọi mâm trả về có Σ need ≤ Σ g_min của lô khả dụng cho mọi nguyên liệu không phải gia vị luôn có; khi trả `no_feasible_tray`, kiểm chéo bằng duyệt vét cạn trên kho nhỏ.
- **BR-COOK-01, lịch hợp lệ** (TC-PROP-04): với 2–3 món và 1–4 họng bếp, lịch CP-SAT không có hai bước chủ động chồng nhau, không vượt số họng bếp, giữ thứ tự bước, mọi món xong trong 5 phút trước giờ dọn, món xào xong cuối.
- Thêm: số dư kho và hoàn tác bằng máy trạng thái Hypothesis (TC-PROP-05), đơn điệu của độ gấp (TC-PROP-06), đổi món không quay lại món đã đổi (TC-PROP-07), sàn năng lượng (TC-PROP-08), giao món khảo sát phân tầng (TC-SURV-02), xen kẽ sweeper và worker (TC-JOB-08).

Phản ví dụ Hypothesis tìm được lưu trong cơ sở dữ liệu ví dụ của Hypothesis trong repo và trở thành ca hồi quy `@example`.

### 2.3. Tích hợp API với PostgreSQL thật

- `docker compose -f compose.test.yml` dựng `postgres` (pgvector/pgvector:pg18), `valkey`, `mailpit`, `label-studio` (chỉ cho nhóm LBL). Không dùng SQLite hay mock CSDL: trigger chỉ ghi thêm, unique một phần, khoá tư vấn và FK ghép chỉ đúng trên PostgreSQL.
- Mỗi ca chạy trong một CSDL tạo từ template đã migrate (Alembic `upgrade head`), xoá sau ca; ca cần hai giao dịch song song dùng kết nối riêng.
- Đồng hồ: freezegun cho mã Python, `SET LOCAL` múi giờ phiên cho SQL; ca liên quan múi giờ cố định Asia/Ho_Chi_Minh.
- Tiêm lỗi giữa giao dịch (TC-AUTH-04, TC-SCAN-20, TC-MEAL-18, TC-COOK-08, TC-COOK-17) bằng fixture thay hàm repository ném lỗi ở bước thứ k, rồi kiểm không còn dòng nào.
- Bộ phát hiện và bộ phân loại độ tươi được thay bằng bản giả trả kết quả cố định trong tầng này; mô hình thật chỉ dùng ở tầng mô hình và E2E.

### 2.4. Hợp đồng (Schemathesis)

TC-CONT-01 chạy Schemathesis trên `docs/api/openapi-v1.yaml` với token cho từng vai trò (`user`, `admin`, `curator`, `ml_operator`, `respondent_token`). Kiểm: không 5xx, mã trạng thái có trong đặc tả, `Content-Type` đúng, thân đúng schema, lỗi là `application/problem+json` có `code`. TC-CONT-02 chặn trôi giữa mã và đặc tả: OpenAPI sinh từ FastAPI phải trùng tệp trong repo, và client TypeScript sinh từ đặc tả phải biên dịch được với app.

### 2.5. Bảo mật

- **BOLA** (TC-SEC-01 cùng các ca 404 trong từng nhóm): người A gọi mọi endpoint có `{id}` bằng id tài nguyên của B → 404 `not_found`, không 403, không lộ tồn tại; danh sách endpoint lấy tự động từ `model.yaml` (mọi đường dẫn có tham số, auth `user`), nên endpoint mới không bị sót.
- **Lũy đẳng** (TC-SEC-02, TC-SEC-03): gửi đôi tuần tự và 10 yêu cầu song song cùng `Idempotency-Key` (hoặc cùng `event_id`) tới năm endpoint có khoá và `POST /events`; chỉ một tác dụng.
- **Tải lên độc hại** (TC-SEC-04, TC-SCAN-02, TC-SCAN-03): giả đuôi và polyglot (kiểm magic bytes), ảnh 20000 × 20000 px nén nhỏ (bom giải nén, chặn bởi `MAX_IMAGE_PIXELS` = 4096²), ảnh có GPS (EXIF bị bỏ sau khi mã hoá lại).
- **Xác thực và phân quyền**: giả mạo JWT (TC-SEC-06), vai trò nhân sự (TC-SEC-05, TC-ADM-01), token người tham gia khảo sát (TC-SEC-07), location internal của nginx (TC-SEC-08), khoá đăng nhập (TC-AUTH-07).
- **Chuỗi cung ứng**: pip-audit, npm audit, quét bí mật, import-linter (TC-SEC-09).

### 2.6. E2E

- **Web**: Playwright trên bản web xuất tĩnh (`web.output: "single"`) phục vụ qua nginx của compose, trình duyệt Chromium và WebKit. Ảnh quét lấy từ bộ ảnh vàng.
- **Android**: Maestro trên emulator API 34 với APK bản phát hành thử; camera dùng ảnh giả của emulator. Kiểm riêng hành vi chỉ có trên thiết bị: secure-store, outbox khi mất mạng, giữ màn hình sáng khi nấu (TC-AUTH-13, TC-SCAN-10, TC-E2E-02).
- Các ca hiển thị (nhãn độ tươi có chữ, công tắc đồng ý mặc định tắt, câu cảnh báo khi xoá tài khoản) là E2E vì yêu cầu nằm ở giao diện.

### 2.7. Tải (k6/Locust)

Chạy trên máy đích với giới hạn `--cpus=2 --memory=4g` (MT-chuẩn của SRS §3.4). k6 cho luồng quét (TC-PERF-01, 5 người dùng ảo, ≥ 300 mẫu) và endpoint đọc (TC-PERF-04, 20 người dùng), Locust cho `POST /meal-plans` (TC-PERF-02, 10 người dùng đồng thời, kho 200 món, 30 lô); TC-PERF-06 ghi `docker stats` trong lúc chạy TC-PERF-01 và TC-PERF-02. Ngưỡng đạt/không đạt lấy nguyên từ SRS §3.4.1; đổi ngưỡng phải qua quy trình đổi ngưỡng của SRS (tăng phiên bản SRS). Độ trễ quét lấy từ cột `enqueued_at`, `finished_at` của `scans`, không lấy từ phía client. Quét đầu–cuối trên điện thoại (TC-PERF-03) đo bằng mốc thời gian trong app.

### 2.8. ONNX so với PyTorch trên ảnh vàng

Bộ ảnh vàng: 50 ảnh tủ lạnh của nhóm (đã được chủ bếp đồng ý) cố định bằng sha256, không thuộc tập train. TC-ONNX-01 so đầu ra ONNX Runtime (CPU, `intra_op_num_threads = 2`) với PyTorch cùng trọng số: khung ghép Hungarian IoU ≥ 0,99, |Δconf| ≤ 0,01, cùng tập lớp; xác suất độ tươi |ΔP| ≤ 1e-3. TC-ONNX-02 kiểm tensor đầu vào lúc phục vụ trùng lúc huấn luyện theo `preprocess_version`. Hai ca chạy trong cổng kiểm định UC29 trước khi bản mô hình chuyển `validated`.

### 2.9. Kiểm thử chấp nhận người dùng

8–10 người thật (NFR-USE-01), không phải thành viên nhóm, mỗi người một phiên 30–40 phút có người điều phối đọc kịch bản cố định. Năm nhiệm vụ ở TC-UAT-02; sau đó điền thang SUS 10 câu bản tiếng Việt (TC-UAT-01). Ghi: hoàn thành không trợ giúp hay không, thời gian, số lỗi, trích lời nguyên văn. Không sinh giả người thử hay câu trả lời; thiếu người thì báo cáo ghi rõ số người thực có.

## 3. Môi trường và dữ liệu kiểm thử

### 3.1. Môi trường

| Môi trường | Thành phần | Dùng cho |
|---|---|---|
| CI | GitHub Actions runner; docker compose `postgres`, `valkey`, `mailpit` | đơn vị, tính chất, tích hợp, hợp đồng, bảo mật, vận hành |
| Staging (máy chủ lab) | compose đủ dịch vụ như §10 bản thiết kế v2: `nginx`, `api`, `worker`, `scheduler`, `migrate`, `postgres`, `valkey`; Label Studio | E2E, tải, mô hình, diễn tập khôi phục |
| Thiết bị | emulator Android API 34; một điện thoại Android tầm trung thật | Maestro, TC-PERF-03, UAT |

Phiên bản ghim: PostgreSQL 18 + pgvector 0.8, Valkey 9, Python 3.12, ONNX Runtime và `ultralytics==8.4.x` theo `uv.lock`. Remote rclone của tác vụ sao lưu trong CI là thư mục cục bộ; trên staging là thư mục Drive riêng cho kiểm thử.

### 3.2. Dữ liệu kiểm thử

| Bộ dữ liệu | Nội dung | Nguồn |
|---|---|---|
| Seed tham chiếu | 10 `allergen_groups`, `diets` (`chay`) + `diet_exclusions`, `food_groups`, `nutrients`, `qty_levels`, `cooking_methods`, `tags`, `consent_purposes`, `policy_versions` | tệp seed trong repo, giống production |
| Kho món thật | 150–200 món đã nhập qua UC25 | nhóm biên soạn; dùng cho TC-PROP-01 đến TC-PROP-04, TC-PERF-02 |
| Kho món tổng hợp nhỏ | 5–60 món/slot sinh bằng factory, có món dị ứng, món xào, món retired | sinh trong fixture; chỉ để kiểm cơ chế |
| Bảng thành phần | trích FCT 2007 và USDA đã nhập | dữ liệu công khai |
| Ảnh vàng | 50 ảnh tủ lạnh thật + nhãn đã phân xử | ảnh của nhóm, có đồng ý |
| Ảnh độc hại | giả đuôi, polyglot, 20000 × 20000 px, EXIF GPS, 3 MB + 1 byte | sinh bằng script trong `tests/fixtures/` |
| Người dùng mẫu | A, B (BOLA), người có/không có từng đồng ý, nhân sự mỗi vai trò | factory |

Quy tắc: dữ liệu cá nhân trong kiểm thử là giả do factory sinh; không dùng bản sao CSDL production. Dữ liệu cần người thật (ảnh, khảo sát, người thử UAT) không được sinh giả để thay kết quả đo; dữ liệu giả chỉ dùng để kiểm cơ chế phần mềm.

## 4. Tiêu chí vào/ra và độ phủ

### 4.1. Tiêu chí vào

- Đặc tả UC liên quan có bảng FR với tiêu chí Given/When/Then, `check_refs.py` sạch.
- `db/schema.sql` áp được (`test_ddl.sh` xanh) và migration Alembic khớp.
- `openapi-v1.yaml` hợp lệ.
- Với E2E và tải: bản build staging khởi động, `GET /readyz` trả 200.

### 4.2. Tiêu chí ra (mỗi bản phát hành)

- 100% ca tầng đơn vị, tính chất, tích hợp, hợp đồng, bảo mật, vận hành xanh; không phản ví dụ Hypothesis mở.
- TC-PROP-01 (BR-ALG-01) xanh trên kho món thật hiện hành — điều kiện không có ngoại lệ.
- **NFR-MAINT-01**: độ phủ dòng và nhánh ≥ 80% cho từng module `meal`, `pantry`, `profile`, `cooking` (coverage.py, `--cov-branch`, đo riêng mỗi module, không lấy trung bình); import-linter xanh (TC-MAINT-01). Module khác không có ngưỡng chặn nhưng độ phủ được báo trong CI.
- E2E xanh trên Chromium và Android, và trên đủ ma trận nền tảng của TC-E2E-05 (RB-06); TC-PERF-01 … TC-PERF-06 đạt ngưỡng; TC-REL-01 đã diễn tập ít nhất một lần (NFR-REL-01), TC-REL-03 bấm giờ đạt.
- Không lỗi mức nghiêm trọng hoặc cao còn mở; lỗi mức trung bình có ghi nhận và hạn sửa.
- Ma trận truy vết: 0 FR, 0 UC, 0 BR không có TC; mọi mã NFR và mọi điều khoản con có ít nhất một TC (bảng ở §4.3).

### 4.3. Độ phủ yêu cầu

Danh mục có 271 ca. Phủ: 446/446 FR trong 34 tệp UC, 39/39 BR, 10/10 mã NFR của `model.yaml` gồm 31/31 điều khoản NFR ở SRS §3.4 (10 điều khoản gốc và 21 điều khoản con `.b`–`.e`) cùng ràng buộc đo được RB-06, 34/34 UC có ít nhất một ca. Ngưỡng và điều kiện đo lấy từ SRS §3.4. Cột "Tham chiếu" ở §5 là nguồn duy nhất cho ánh xạ TC → FR/BR/UC/NFR; trường `tests:` trong front-matter mỗi UC liệt kê các ca có tham chiếu tới UC đó (trực tiếp hoặc qua FR của nó). `gen_traceability.py` đọc cả hai; công cụ hiện gộp điều khoản con vào mã NFR cha, nên bảng dưới là nơi kiểm phủ ở mức điều khoản.

Phủ NFR theo điều khoản:

| Điều khoản | Ca kiểm thử |
|---|---|
| NFR-PERF-01 | TC-PERF-01 |
| NFR-PERF-01.b | TC-PERF-06 |
| NFR-PERF-02 | TC-PERF-02 |
| NFR-PERF-02.b | TC-PERF-04 |
| NFR-PERF-02.c | TC-PERF-05 |
| NFR-PERF-03 | TC-PERF-03 |
| NFR-REL-01 | TC-REL-01 |
| NFR-REL-01.b | TC-REL-02, TC-SEC-02, TC-E2E-02 |
| NFR-REL-01.c | TC-REL-03, TC-MLOP-11 |
| NFR-REL-01.d | TC-REL-04, TC-SCAN-06, TC-JOB-07 |
| NFR-SEC-01 | TC-AUTH-05, TC-SEC-06 |
| NFR-SEC-01.b | TC-AUTH-03 |
| NFR-SEC-01.c | TC-SEC-01 |
| NFR-SEC-01.d | TC-SEC-05 |
| NFR-SEC-02 | TC-AUTH-07 |
| NFR-SEC-02.b | TC-SEC-04 |
| NFR-SEC-02.c | TC-SEC-10 |
| NFR-PRIV-01 | TC-PRIV-06, TC-PRIV-11, TC-PRIV-21, TC-ADM-02 |
| NFR-PRIV-01.b | TC-PRIV-22, TC-JOB-01, TC-JOB-05 |
| NFR-PRIV-01.c | TC-PROF-04, TC-NUT-06 |
| NFR-PRIV-01.d | TC-PRIV-23 |
| NFR-A11Y-01 | TC-A11Y-01 |
| NFR-A11Y-01.b | TC-A11Y-02 |
| NFR-USE-01 | TC-UAT-01, TC-UAT-02 |
| NFR-USE-01.b | TC-UAT-03 |
| NFR-USE-01.c | TC-CONT-03 |
| NFR-MAINT-01 | TC-MAINT-01, TC-SEC-09 |
| NFR-MAINT-01.b | TC-MAINT-02 |
| NFR-MAINT-01.c | TC-MAINT-03 |
| NFR-MAINT-01.d | TC-MAINT-04 |
| NFR-MAINT-01.e | TC-CONT-02 |
| RB-06 (ràng buộc nền tảng) | TC-E2E-05 |

Số ca theo loại:

| Loại | Số ca |
|---|---|
| Tích hợp API | 141 |
| Vận hành (CLI/job) | 40 |
| Đơn vị | 23 |
| Bảo mật | 19 |
| E2E | 18 |
| Tính chất | 10 |
| Tải | 6 |
| Tĩnh/CI | 5 |
| Mô hình | 3 |
| UAT | 3 |
| Kiểm tra quy trình | 2 |
| Hợp đồng | 1 |
| **Tổng** | **271** |

### 4.4. Tạm dừng và tiếp tục

Tạm dừng chạy E2E và tải khi tầng tích hợp đỏ hoặc staging không sẵn sàng; tiếp tục khi nguyên nhân đã sửa và tầng dưới xanh lại. Tạm dừng UAT khi một nhiệm vụ không làm được vì lỗi phần mềm (không phải vì người thử).

## 5. Danh mục ca kiểm thử

Quy ước: mã `TC-<NHOM>-<nn>`; "Loại" theo bảng ở §2; tham số tính bằng gam, kcal, giây. Một ca có thể kiểm nhiều FR khi chúng chia chung tiền điều kiện; mỗi FR vẫn có kết quả mong đợi riêng trong ca. Các ca 404 do sai chủ sở hữu được gom thêm vào TC-SEC-01.

### 5.1. Tài khoản và phiên (UC01–UC04) — nhóm `AUTH`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-AUTH-01 | Đăng ký thành công cấp đúng tài khoản và phiên, không ghi đồng ý | Tích hợp API | FR-01-01, FR-01-06, FR-01-08, UC01 | CSDL rỗng; email `a@x.vn` chưa có | `POST /auth/register` với email và mật khẩu hợp lệ; đọc `users`, `refresh_tokens`, `consent_events` | 201; 1 dòng `users` role=user, status=active, token_version=0; access JWT `exp − iat` = 900 s; 1 refresh token hạn 30 ngày, family_id mới; 0 dòng `consent_events` |
| TC-AUTH-02 | Từ chối đăng ký sai dữ liệu | Tích hợp API | FR-01-02, FR-01-03, FR-01-04, UC01 | `users` có `a@x.vn`; `password_min_length` = L | Đăng ký lần lượt: `A@X.VN`; mật khẩu dài L − 1; email `abc@` | 409 `email_taken`; 422 `weak_password`; 422 `invalid_email`; số dòng `users` không đổi sau cả ba |
| TC-AUTH-03 | Bí mật chỉ lưu dạng băm | Tích hợp API | FR-01-05, FR-02-10, NFR-SEC-01.b, UC01, UC02 | Bật bắt log ở mức DEBUG | Đăng ký với mật khẩu P, đăng nhập, làm mới phiên; quét CSDL, log, thân phản hồi tìm P và chuỗi refresh token gốc | `password_hash` bắt đầu `$argon2id$`; `refresh_tokens.token_sha256` = SHA-256(token); P và token gốc không xuất hiện ở đâu |
| TC-AUTH-04 | Đăng ký là một giao dịch | Tích hợp API | FR-01-07, UC01 | Tiêm lỗi vào bước ghi `refresh_tokens` (fixture monkeypatch) | Gửi `POST /auth/register` | 5xx problem+json; không còn dòng `users` nào của email đó |
| TC-AUTH-05 | Đăng nhập cấp token đúng hạn và claim | Tích hợp API | FR-02-01, NFR-SEC-01, UC02 | Tài khoản active | `POST /auth/login` đúng mật khẩu; giải mã JWT | 200; JWT có `kid`, `token_version` = giá trị trong `users`, hạn 15 phút; refresh token hạn 30 ngày, family_id mới |
| TC-AUTH-06 | Không lộ email tồn tại qua lỗi đăng nhập | Tích hợp API | FR-02-02, UC02 | Một email có tài khoản, một email không có | Đăng nhập sai mật khẩu với email có thật; đăng nhập với email không có | Cả hai: 401 `invalid_credentials`, thân phản hồi giống nhau trừ `request_id` |
| TC-AUTH-07 | Khoá 15 phút sau 5 lần sai theo (email, IP) | Tích hợp API | FR-02-03, FR-02-04, FR-02-05, NFR-SEC-02, UC02 | Đồng hồ giả (freezegun) và Valkey thật | Sai 5 lần từ IP X; đăng nhập đúng từ IP X; đăng nhập đúng từ IP Y; tua 15 phút; đăng nhập đúng từ X | Lần sai thứ 5 và lần đúng ở X trước 15 phút trả 429 `login_locked` có `Retry-After` ≤ 900; IP Y đăng nhập được; sau 15 phút X đăng nhập được và bộ đếm, `failed_logins` về 0 |
| TC-AUTH-08 | Xoay vòng refresh token và phát hiện dùng lại | Tích hợp API | FR-02-06, FR-02-07, UC02 | Đã đăng nhập, có refresh R1 | `POST /auth/refresh` với R1 → R2; gửi lại R1 | Lần 1: R1 revoked, `replaced_by_id` = R2, cùng family; lần 2: 401 `refresh_reused`, mọi token của family bị thu hồi, R2 không làm mới được |
| TC-AUTH-09 | Chặn tài khoản chờ xoá và token cũ phiên bản | Tích hợp API | FR-02-08, FR-02-09, UC02 | Tài khoản A status=deletion_requested; tài khoản B có access token với token_version cũ | A đăng nhập và làm mới phiên; B gọi `GET /me/profile` | A: 403 `account_deletion_pending`; B: 401 |
| TC-AUTH-10 | Đăng xuất một thiết bị thu hồi đúng family | Tích hợp API | FR-03-01, FR-03-02, UC03 | Hai thiết bị, hai family F1, F2 | `POST /auth/logout` với refresh của F1; gửi lại cùng token | Mọi token F1 revoked, F2 không đổi; lần gửi lại 204, không thu hồi thêm |
| TC-AUTH-11 | Đăng xuất mọi thiết bị có hiệu lực ngay | Tích hợp API | FR-03-03, FR-03-04, UC03 | Hai phiên đang hoạt động | `POST /auth/logout-all`; dùng access token cũ gọi `GET /me/settings` | token_version +1 và mọi refresh token revoked trong một giao dịch; yêu cầu kế tiếp bằng token cũ trả 401 |
| TC-AUTH-12 | Đăng xuất không thu hồi token của người khác | Bảo mật | FR-03-05, UC03 | Người A và B đều đăng nhập | Gọi `POST /auth/logout` bằng access token của A, thân chứa refresh token của B | Không token nào của B bị thu hồi; phản hồi không cho biết token B tồn tại |
| TC-AUTH-13 | App xoá token và gửi lại thu hồi khi có mạng | E2E | FR-03-06, UC03 | Maestro trên emulator Android; chế độ máy bay | Đăng xuất khi mất mạng; kiểm secure-store; bật mạng | Token bị xoá ngay khỏi secure-store; khi có mạng app gửi `POST /auth/logout` và server ghi revoked |
| TC-AUTH-14 | Yêu cầu đặt lại mật khẩu không lộ tài khoản | Tích hợp API | FR-04-01, FR-04-02, FR-04-03, UC04 | Mailpit (A09) chạy trong compose | `POST /auth/password-reset/request` với email có và không có tài khoản | Cả hai 202 cùng thân; chỉ email có tài khoản tạo 1 dòng `password_resets` (chỉ băm, expires_at đúng TTL) và đúng 1 thư trong Mailpit |
| TC-AUTH-15 | Chống gửi lặp và vô hiệu token cũ | Tích hợp API | FR-04-04, FR-04-05, UC04 | Đã có token T1 còn hạn tạo trong cooldown | Gửi yêu cầu lần 2 trong cooldown; tua quá cooldown, gửi lần 3 | Lần 2 không tạo token, không thư; lần 3 tạo T2 và T1 không còn dùng được |
| TC-AUTH-16 | Xác nhận đặt lại với token xấu hoặc mật khẩu yếu | Tích hợp API | FR-04-06, FR-04-09, UC04 | Token sai, token đã dùng, token hết hạn, token hợp lệ | `POST /auth/password-reset/confirm` với ba token xấu; với token hợp lệ và mật khẩu ngắn | Ba lần 400 `reset_token_invalid` cùng thân; mật khẩu ngắn 422 `weak_password` và token vẫn dùng được |
| TC-AUTH-17 | Đặt lại mật khẩu thành công là một giao dịch | Tích hợp API | FR-04-07, FR-04-08, FR-04-10, FR-04-11, UC04 | Tài khoản đang bị khoá đăng nhập, có 2 refresh token | Confirm với token hợp lệ và mật khẩu mới; đăng nhập bằng mật khẩu mới | `password_hash` mới, `used_at` đặt, token_version +1, mọi refresh revoked; trạng thái khoá bị xoá, đăng nhập được ngay |
| TC-AUTH-18 | Đặt lại mật khẩu là một giao dịch | Tích hợp API | FR-04-12, UC04 | Tiêm lỗi vào bước thu hồi refresh token (monkeypatch) | Confirm với token hợp lệ và mật khẩu mới; đăng nhập bằng mật khẩu cũ | 5xx problem+json; đăng nhập bằng mật khẩu cũ 200; `used_at` NULL; `token_version` không đổi; refresh token cũ vẫn dùng được |

### 5.2. Đồng ý và quyền dữ liệu (UC05–UC08) — nhóm `PRIV`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-PRIV-01 | Chọn đúng bản điều khoản hiện hành | Tích hợp API | FR-05-01, UC05 | `policy_versions` của `personalization` có v1 (quá khứ), v2 (quá khứ, mới hơn), v3 (tương lai) | `GET /policies/personalization/current` | Trả v2 |
| TC-PRIV-02 | Công tắc đồng ý mặc định tắt | E2E | FR-05-02, BR-CONSENT-01, UC05 | Playwright, người dùng mới | Mở Cài đặt > Đồng ý | Ba công tắc `health_profile`, `personalization`, `photo_contribution` riêng, đều tắt |
| TC-PRIV-03 | Ghi đồng ý gắn phiên bản điều khoản | Tích hợp API | FR-05-03, FR-05-04, FR-05-05, BR-CONSENT-01, UC05 | Bản hiện hành v2, bản cũ v1 | `POST /me/consents` với v2; gửi lại v2; gửi v1 | Lần 1: 1 dòng grant có policy_version_id, channel, app_version; lần 2 không ghi thêm; v1: 409 `policy_outdated`, không ghi |
| TC-PRIV-04 | Trạng thái đồng ý và cổng has_consent | Đơn vị | FR-05-06, FR-05-07, UC05 | Bốn người: chưa grant, grant v2, withdraw, grant v1 khi v2 đã hiệu lực | `GET /me/consents`; gọi `privacy.has_consent` | Trạng thái lần lượt none, granted, withdrawn, superseded; has_consent chỉ đúng với granted |
| TC-PRIV-05 | Rút đồng ý có hiệu lực ngay | Tích hợp API | FR-05-08, FR-05-09, BR-CONSENT-04, UC05 | Người dùng đã grant `personalization` | `POST /me/consents/personalization/withdraw`; gọi API bằng access token cũ | Trong một giao dịch: 1 dòng withdraw, token_version +1, 1 `dsr_requests` type=withdraw status=received có subject_ref = HMAC(user_id); token cũ 401 |
| TC-PRIV-06 | Xoá dữ liệu theo mục đích trong ≤ 24 giờ | Vận hành (CLI/job) | FR-05-10, FR-05-11, FR-05-12, FR-05-13, BR-CONSENT-04, NFR-PRIV-01, UC05 | Có hồ sơ mã hoá, interactions, ảnh contributed và tệp trong `contrib/` | Rút lần lượt ba mục đích; chạy worker; đồng hồ giả +24 giờ | Cột `*_enc`, enc_key_id, kcal_target, kcal_source = NULL; 0 `interactions` và `POST /events` sau đó không ghi; contributed=false và tệp contrib bị xoá; mỗi dsr completed trước received_at + 24 h |
| TC-PRIV-07 | Rút mục đích chưa đồng ý là thao tác rỗng | Tích hợp API | FR-05-14, UC05 | Mục đích ở none và withdrawn | Gọi withdraw cho từng mục đích | 200 trạng thái hiện tại; không sự kiện, không đổi token_version, không dsr |
| TC-PRIV-08 | Nhật ký đồng ý chỉ ghi thêm | Tích hợp API | FR-05-15, UC05 | Kết nối DB bằng vai trò ứng dụng | UPDATE và DELETE trực tiếp một dòng `consent_events`; xoá dòng `users` | UPDATE/DELETE bị trigger từ chối; xoá users thì dòng consent bị xoá dây chuyền |
| TC-PRIV-09 | Tạo yêu cầu tải dữ liệu, không trùng | Tích hợp API | FR-06-01, FR-06-02, BR-DSR-01, UC06 | Người dùng chưa có yêu cầu mở | `POST /me/data-requests` type=export hai lần | Lần 1: 202 có id, dòng received có subject_ref, received_at, acknowledged_at; lần 2 trả cùng id |
| TC-PRIV-10 | Nội dung tệp xuất đầy đủ và không chứa bí mật | Vận hành (CLI/job) | FR-06-04, FR-06-06, FR-06-07, FR-06-11, UC06 | Người dùng có dữ liệu ở mọi bảng liệt kê ở bước 6 UC06 và 2 ảnh chưa purge | Chạy job xuất; giải nén tệp kết quả | Mọi bản ghi có mặt; không có password_hash, token_sha256, request_sha256, khoá; có 2 tệp ảnh; có tệp mô tả cột tiếng Việt kèm thời điểm xuất |
| TC-PRIV-11 | Xuất dữ liệu đúng hạn và kiểm toán giải mã | Vận hành (CLI/job) | FR-06-03, FR-06-05, NFR-PRIV-01, UC06 | Yêu cầu export received | Chạy worker; đọc `dsr_requests`, `audit_log` | completed có result_key, completed_at − received_at ≤ 24 h; chỉ số sức khoẻ ở dạng rõ trong tệp; 1 dòng audit_log mỗi lần giải mã |
| TC-PRIV-12 | Tải tệp xuất: quyền, trạng thái, kiểm toán | Tích hợp API | FR-06-08, FR-06-09, FR-06-10, UC06 | Yêu cầu export của A (một bản received, một bản completed); người B | B gọi `GET /me/data-requests/{id}` và `/download` của A; A tải bản received; A tải bản completed | B: 404 `not_found` cả hai; bản received: 409 `request_not_ready`; bản completed: 200 có header `X-Accel-Redirect`, 1 dòng audit_log action=dsr_download |
| TC-PRIV-13 | Nhận yêu cầu xoá tài khoản | Tích hợp API | FR-07-01, FR-07-02, FR-07-03, UC07 | Tài khoản active, 2 phiên | Gửi type=delete với mật khẩu sai; gửi với mật khẩu đúng; dùng access token cũ và đăng nhập lại | Mật khẩu sai bị từ chối, không ghi; đúng: một giao dịch tạo dsr delete, status=deletion_requested, token_version +1, mọi refresh revoked; token cũ 401, đăng nhập 403 |
| TC-PRIV-14 | Job xoá tài khoản xoá cứng dữ liệu cá nhân, giữ kho món | Vận hành (CLI/job) | FR-07-04, FR-07-05, FR-07-06, FR-07-07, FR-07-08, BR-DSR-01, BR-CATALOG-01, UC07 | Người dùng có dữ liệu ở mọi bảng bước 9 UC07, tệp trong tmp/ và contrib/, tệp xuất | Chạy job xoá; đếm dòng theo user_id; liệt kê volume; đếm `recipes`, `ingredients` | Tệp bị xoá trước dòng users; 0 dòng dữ liệu cá nhân; dsr delete còn với user_id NULL, subject_ref không đổi, completed ≤ 24 h; số dòng bảng catalog không đổi |
| TC-PRIV-15 | Job xoá chạy lại được | Vận hành (CLI/job) | FR-07-09, UC07 | Đã chạy job xoá một lần, hoặc ngắt giữa chừng sau khi xoá tệp | Chạy lại job | Thoát mã 0, kết quả cuối giống lần chạy đầy đủ, không lỗi vì tệp hay dòng đã mất |
| TC-PRIV-16 | App nêu hạn xoá và hạn bản sao lưu | E2E | FR-07-10, BR-RETAIN-01, UC07 | Playwright, màn Xoá tài khoản | Mở màn xác nhận xoá | Có câu nêu ≤ 24 giờ và bản sao lưu hết hạn sau tối đa 14 ngày, trước nút xác nhận |
| TC-PRIV-17 | Yêu cầu sửa/hạn chế/phản đối | Tích hợp API | FR-08-01, FR-08-02, FR-08-03, BR-DSR-01, UC08 | Người dùng chưa có yêu cầu mở | Gửi type=restrict note rỗng; gửi có note; gửi lại cùng type | Note rỗng 422 `invalid_request`; có note: dòng received đủ trường; gửi lại trả dòng cũ |
| TC-PRIV-18 | App dẫn tới cách tự xử lý trước khi gửi yêu cầu | E2E | FR-08-04, UC08 | Playwright | Chọn "Yêu cầu sửa"; chọn "Phản đối xử lý" | Màn sửa hồ sơ (UC10) được đề nghị trước; hướng dẫn rút personalization (UC05) hiện trước khi cho gửi |
| TC-PRIV-19 | Quản trị đóng yêu cầu thủ công | Tích hợp API | FR-08-05, FR-08-06, FR-08-07, FR-08-08, FR-08-09, UC08 | Yêu cầu restrict received; một yêu cầu export; tài khoản admin và user | User gọi `POST /admin/data-requests/{id}/resolve`; admin rejected không note; admin completed có note; gọi lại; admin resolve yêu cầu export | 403; 422 `reason_required`; completed_at đặt, note nối kết quả, 1 dòng audit dsr_resolve; gọi lại không thêm audit; export: 409 `request_not_manual` |
| TC-PRIV-20 | Không nhận yêu cầu loại access qua API | Tích hợp API | FR-06-12, BR-DSR-01, UC06 | Người dùng đăng nhập | `POST /me/data-requests` với `type = access` | 422 `invalid_request`; `detail` nêu cách xem và tải dữ liệu; số dòng `dsr_requests` không đổi |
| TC-PRIV-21 | Hạn xác nhận và hạn hoàn tất của yêu cầu thủ công | Tích hợp API | FR-08-01, FR-08-10, FR-08-11, BR-DSR-01, NFR-PRIV-01, UC08 | Đồng hồ giả; người dùng chưa có yêu cầu mở | Gửi `correct` và `object` lúc T; đọc `GET /me/data-requests/{id}`; mở màn trạng thái trên app | `acknowledged_at` − `received_at` ≤ 24 h (thực tế = 0); `due_at` = T + 10 ngày và T + 15 ngày; app hiện "Đã nhận lúc …" và "Hạn xử lý: …" |
| TC-PRIV-22 | Dữ liệu tài khoản đã xoá không còn ở đâu sau 20 ngày | Vận hành (CLI/job) | NFR-PRIV-01.b, BR-RETAIN-01, UC07, UC32, UC33 | Tài khoản có dữ liệu ở mọi bảng, có ảnh trên đĩa, có mặt trong các bản sao lưu; đồng hồ giả | Xoá tài khoản lúc T; chạy job xoá, UC32 và UC33 mỗi ngày giả lập tới T + 20 ngày; tìm `user_id`, email, HMAC trong CSDL, volume và mọi bản sao lưu | Tới T + 24 h không còn trong CSDL và volume; tới T + 20 ngày không còn trong bản sao lưu nào; chỉ còn `dsr_requests.subject_ref` |
| TC-PRIV-23 | Dữ liệu cá nhân chỉ xử lý trên hạ tầng trong nước | Kiểm tra quy trình | NFR-PRIV-01.d, BR-CONSENT-03, UC28 | Nhật ký mọi lần chạy UC28; danh sách máy huấn luyện và gán nhãn | Đối chiếu đích xuất của từng lần UC28 với danh sách máy; kiểm bản xuất không có `user_id`, email | 100% bản xuất có dữ liệu cá nhân nằm trên máy trong nước; Colab/Kaggle chỉ nhận dữ liệu công khai; bản xuất chỉ có bí danh |

### 5.3. Hồ sơ 60 giây và cập nhật hồ sơ (UC09–UC10) — nhóm `PROF`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-PROF-01 | Màn đồng ý onboarding | E2E | FR-09-01, FR-09-02, BR-CONSENT-01, UC09 | Playwright, tài khoản mới | Bắt đầu hồ sơ 60 giây; tích `health_profile`; tiếp tục | Màn đồng ý hiện trước bước 1, 3 ô chưa tích kèm phiên bản điều khoản; `consent_events` mới có channel=onboarding và policy_version_id hiện hành |
| TC-PROF-02 | Tiến độ và tiếp tục hồ sơ dở | E2E | FR-09-03, FR-09-12, UC09 | Playwright; hai người: có và không có đồng ý health_profile | Làm tới bước 3 rồi đóng app; mở lại | Thanh tiến độ 4 bước (2 bước khi không đồng ý); mở lại vào đúng bước đầu tiên chưa được server xác nhận |
| TC-PROF-03 | Cổng đồng ý và tuổi khi lưu chỉ số cơ thể | Tích hợp API | FR-09-04, FR-09-05, FR-09-13, FR-10-03, BR-CONSENT-02, BR-NUT-01, UC09, UC10 | Đồng hồ giả năm 2026 (Asia/Ho_Chi_Minh); người không có đồng ý health_profile; người có đồng ý | `PUT /me/profile` chỉ số cơ thể; người có đồng ý gửi lần lượt `birth_year` = 2009; 2008 không có `adult_confirmed`; 2008 với `adult_confirmed = true`; 2007 | Không đồng ý: 403 `consent_required`, không ghi; 2009: 422 `age_below_minimum`; 2008 không xác nhận: 422 `age_confirmation_required`, không ghi; 2008 có xác nhận: 200; 2007: 200 |
| TC-PROF-04 | Chỉ số cơ thể mã hoá ở tầng ứng dụng | Tích hợp API | FR-09-06, NFR-PRIV-01.c, UC09 | Đã lưu giới, năm sinh, chiều cao, cân nặng | Đọc thô `profiles` bằng psql; giải mã bằng khoá theo enc_key_id | Cột `*_enc` là bytea không chứa giá trị rõ; giải mã ra đúng giá trị; enc_key_id khác NULL |
| TC-PROF-05 | Gợi ý mục tiêu chưa ghi cho tới khi xác nhận | Tích hợp API | FR-09-07, FR-09-08, UC09 | Hồ sơ đủ chỉ số | `POST /me/energy-suggestion`; đọc profiles; `PUT /me/energy-target` kcal_source=suggested | Gợi ý có E, E_mâm trưa = E × 0,35, tối = E × 0,30; trước khi xác nhận kcal_target NULL; sau đó kcal_target ghi, kcal_source=suggested |
| TC-PROF-06 | Dị ứng, chế độ ăn, món hay ăn trong onboarding | Tích hợp API | FR-09-09, FR-09-10, FR-09-11, BR-ALG-02, UC09 | Seed 10 nhóm `allergen_groups`, diet `chay` | `GET /reference`; `PUT /me/allergens` rỗng không có cờ "không dị ứng"; `PUT /me/diet` chay rồi NULL; `PUT /me/favorites` 6 món, và 5 món có 1 món draft | Đủ 10 nhóm (8 Codex 2024 + đậu nành, nhuyễn thể); bước dị ứng không qua khi chưa chọn; diet_code lưu chay rồi NULL; favorites 6 món và món draft đều 422 |
| TC-PROF-07 | Đọc hồ sơ giải mã chỉ chủ sở hữu và có kiểm toán | Tích hợp API | FR-10-01, UC10 | Người A có hồ sơ mã hoá | A gọi `GET /me/profile`; đếm audit_log | Trả giá trị rõ của A; thêm 1 dòng audit_log action=decrypt; không có đường nào đọc hồ sơ của người khác |
| TC-PROF-08 | Cập nhật chỉ số cần đồng ý hiện hành | Tích hợp API | FR-10-02, UC10 | Đồng ý health_profile ở trạng thái superseded | `PUT /me/profile` đổi cân nặng, mức vận động | 403 `consent_required`; không đổi dòng profiles |
| TC-PROF-09 | Đánh dấu mục tiêu lỗi thời | Tích hợp API | FR-10-04, UC10 | kcal_source=suggested, kcal_target = K | `PUT /me/profile` đổi cân nặng | Phản hồi có gợi ý mới và target_stale=true; kcal_target vẫn = K |
| TC-PROF-10 | Thay tập dị ứng | Tích hợp API | FR-10-05, FR-10-06, BR-ALG-02, UC10 | Người có dị ứng {egg} | `PUT /me/allergens` {fish, peanut}; gửi {fish, xyz}; trên app xoá hết dị ứng | Tập thành {fish, peanut}; mã lạ 422, tập không đổi; app hỏi xác nhận trước khi gửi tập rỗng |
| TC-PROF-11 | Chế độ ăn hợp lệ và áp ngay cho ghép mâm | Tích hợp API | FR-10-07, FR-10-08, BR-DIET-01, UC10 | Kho món có món thịt; người chưa có diet | `PUT /me/diet` mã lạ; `PUT /me/diet` chay; ngay sau 200 gọi `POST /meal-plans` | Mã lạ 422; mâm ngay sau đó không có món chứa nhóm thực phẩm trong `diet_exclusions` của chay |
| TC-PROF-12 | Cài đặt bếp: mặc định và biên | Tích hợp API | FR-10-09, FR-10-10, UC10 | Người chưa có dòng user_settings | `GET /me/settings`; `PUT /me/settings` burners 0, 5, 1, 4; default_persons 0, 7; timezone `Mars/Base` | Mặc định burners=2, default_persons=2, Asia/Ho_Chi_Minh; ngoài biên và timezone sai 422; 1 và 4 nhận |
| TC-PROF-13 | Món hay ăn và PUT lũy đẳng | Tích hợp API | FR-10-11, FR-10-12, UC10 | 5 món published | `PUT /me/favorites` cùng thân hai lần; đếm `user_favorite_recipes` | Hai lần 200, trạng thái giống nhau, đúng 5 dòng, không trùng |

### 5.4. Mục tiêu năng lượng (UC11) — nhóm `NUT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-NUT-01 | Tính tuổi và chặn dưới 18 | Đơn vị | FR-11-01, BR-NUT-01, UC11 | Đồng hồ giả 31/12 23:30 UTC (đã sang năm mới ở Asia/Ho_Chi_Minh) | Gọi hàm tính tuổi với `birth_year` 2009, 2008 (đã lưu kèm xác nhận), 2007 | Năm hiện tại lấy theo Asia/Ho_Chi_Minh (2027 sau 17:00 UTC ngày 31/12/2026); với Y = 2026: 2009 bị từ chối, 2008 cho tuổi công thức 18, 2007 cho 19 |
| TC-NUT-02 | BMR FAO/WHO/UNU 1985 theo giới và khoảng tuổi | Đơn vị | FR-11-02, BR-NUT-01, UC11 | Bảng hệ số mục 10 UC11 | pytest tham số hoá: 2 giới × tuổi {18, 29, 30, 59, 60, 80} × 2 cân nặng | BMR khớp giá trị tính tay tới 0,1 kcal; biên 30 và 60 thuộc khoảng sau (nửa mở) |
| TC-NUT-03 | PAL và TEE | Đơn vị | FR-11-03, BR-NUT-02, UC11 | BMR = 1.500 | Tính TEE với light, moderate, heavy | 2.250; 2.625; 3.000 |
| TC-NUT-04 | Giữ cân và giảm cân có sàn | Đơn vị | FR-11-04, FR-11-05, BR-NUT-03, UC11 | TEE nữ 1.600; TEE nam 2.500; TEE nam 1.900 | Tính E với maintain và lose | maintain: E = TEE; lose: nữ 1.200 (floor_applied=true), nam 2.000 (false), nam 1.500 (true) |
| TC-NUT-05 | Miền mục tiêu không có tăng cân | Tích hợp API | FR-11-06, BR-NUT-03, UC11 | Hồ sơ đủ | `PUT /me/profile` goal=gain | 422; không tồn tại nhánh công thức tăng cân (kiểm bằng tìm mã nguồn trong CI) |
| TC-NUT-06 | Gợi ý minh bạch, không ghi, có kiểm toán | Tích hợp API | FR-11-07, FR-11-15, NFR-PRIV-01.c, UC11 | Hồ sơ đủ; chụp profiles trước | `POST /me/energy-suggestion` | Phản hồi có BMR, PAL, TEE, tên phương trình, nguồn; profiles không đổi; 1 dòng audit_log action=decrypt, entity=profiles, purpose=health_profile |
| TC-NUT-07 | Năng lượng mâm theo bữa | Đơn vị | FR-11-08, BR-NUT-04, UC11 | E = 2.000 | Tính E_mâm lunch, dinner | 700 và 600, số nguyên |
| TC-NUT-08 | Ghi mục tiêu theo nguồn | Tích hợp API | FR-11-09, FR-11-10, FR-11-11, BR-NUT-03, UC11 | Hồ sơ cho E gợi ý = 1.850 | PUT kcal_source=suggested kèm kcal 3.000; PUT user 700 và 5.001; PUT expert 1.700 rồi đổi cân nặng | suggested lưu 1.850 (bỏ số client); 700 và 5.001 bị 422; expert giữ 1.700 sau khi đổi cân nặng |
| TC-NUT-09 | Tự nhập dưới sàn cần xác nhận | Tích hợp API | FR-11-12, BR-NUT-03, UC11 | Người nữ | PUT user 1.100 không cờ; PUT lại với confirm_below_floor=true | Lần 1: below_floor=true, không lưu; lần 2 lưu 1.100 |
| TC-NUT-10 | Thiếu đồng ý hoặc thiếu trường | Tích hợp API | FR-11-13, FR-11-14, BR-CONSENT-02, UC11 | Người không có đồng ý; người có đồng ý nhưng thiếu cân nặng | Gọi `POST /me/energy-suggestion` và `PUT /me/energy-target` | Không đồng ý: cả hai 403 `consent_required`, app hiện "Chưa có mục tiêu năng lượng"; thiếu trường: 422 `profile_incomplete` nêu weight |
| TC-NUT-11 | Mifflin–St Jeor chỉ để so sánh | Đơn vị | FR-11-16, UC11 | Nam 70 kg, 175 cm, 30 tuổi | Tính gợi ý có bật phương án so sánh | Có BMR Mifflin = 9,99·70 + 6,25·175 − 4,92·30 + 166 − 161 kèm nhãn "phương án so sánh"; E chỉ từ FAO |

### 5.5. Quét và xác nhận (UC12–UC13) — nhóm `SCAN`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-SCAN-01 | Nhận lần quét bất đồng bộ | Tích hợp API | FR-12-01, FR-12-08, UC12 | Ảnh JPEG thật 1.280 px | `POST /scans` 1 ảnh mode=fridge; 2 ảnh mode=haul; 3 ảnh; mode=xyz | 202, `Location: /api/v1/scans/{id}`, `Retry-After: 1`, status=queued, scans.mode đúng; 3 ảnh và mode lạ 422 |
| TC-SCAN-02 | Giới hạn kích thước và loại tệp | Bảo mật | FR-12-02, FR-12-03, FR-12-04, UC12 | Tệp 3 MB + 1 byte; tệp PDF đổi đuôi .jpg; PNG 4097 × 4096 | Gửi từng tệp qua `POST /scans` | 413 `image_too_large`; 415 `unsupported_media_type`; 422 `image_too_many_pixels`; không có tệp nào lưu xuống đĩa |
| TC-SCAN-03 | Xoay theo EXIF và bỏ metadata | Tích hợp API | FR-12-05, UC12 | JPEG Orientation=6, có GPS và tên máy | Tải lên; đọc tệp đã lưu bằng Pillow | Ảnh đã xoay đúng chiều (width/height hoán đổi); không còn khối EXIF, GPS, XMP |
| TC-SCAN-04 | Lũy đẳng khi tạo lần quét | Tích hợp API | FR-12-06, FR-12-07, UC12 | Key K | Gửi không có header; gửi với K; gửi lại K cùng thân; gửi K với ảnh khác; tua 49 giờ và chạy sweeper | Thiếu header 400 `idempotency_key_required`; lần lặp trả nguyên văn phản hồi đầu, 1 dòng scans; thân khác 422 `idempotency_key_reused`; sau 48 giờ K được dùng lại |
| TC-SCAN-05 | Long-poll | Tích hợp API | FR-12-09, UC12 | Worker dừng; worker chạy | `GET /scans/{id}?wait=10` khi worker dừng; khi worker xong ở giây thứ 2 | Trả sau 10 ± 0,5 s với queued; trả ngay khi done (< 0,5 s sau khi job xong) |
| TC-SCAN-06 | Cắt job quá giờ và thử lại khi lỗi suy luận | Tích hợp API | FR-12-10, FR-12-19, NFR-REL-01.d, UC12 | Job giả treo 40 s; bộ phát hiện giả ném lỗi ở mọi lần chạy | Tạo lần quét với job treo; tạo lần quét với bộ phát hiện lỗi; chờ worker | Job treo: lần chạy dừng ở 30 ± 1 s, scan vẫn processing, không có scan_items (phần hết lượt do sweeper, TC-JOB-07); bộ phát hiện lỗi: đúng 3 lần chạy, attempts = 3, status = failed, error_code khác `timeout` |
| TC-SCAN-07 | Ghi phiên bản mô hình đã dùng | Tích hợp API | FR-12-11, FR-30-09, UC12, UC30 | model_deployments trỏ detector D1, freshness F1 | Tạo lần quét; triển khai D2 và khởi động lại worker; quét lại | Lần 1 ghi D1, F1, preprocess_version; lần 2 ghi D2 |
| TC-SCAN-08 | Từ khung tới chip và đếm nhiều ảnh | Đơn vị | FR-12-12, FR-12-13, BR-SCAN-01, UC12 | Bộ phát hiện giả trả khung cố định; lớp `egg` ánh xạ is_default tới trứng gà | Ảnh 1 và 2 cùng shelf_group có 3 và 4 trứng; trường hợp 2: khác shelf_group | Một scan_item duy nhất cho trứng gà, origin=model; model_count = 4 (cùng ngăn), = 7 (khác ngăn) |
| TC-SCAN-09 | Không xem được lần quét của người khác | Bảo mật | FR-12-14, UC12 | Scan của A | B gọi `GET /scans/{id}`, `GET /scans/{id}/images/1` | 404 `not_found`, không có X-Accel-Redirect |
| TC-SCAN-10 | App thoát chờ sau 20 giây | E2E | FR-12-15, UC12 | Maestro; server giả giữ queued | Tải ảnh lên, chờ | Sau 20 s hiện "Thử lại" và "Nhập tay" |
| TC-SCAN-11 | Xác suất độ tươi và u_img | Đơn vị | FR-12-16, BR-FRESH-02, UC12 | Bộ phân loại giả trả P = (0,1; 0,2; 0,3; 0,4) và (0,7; 0,2; 0,1; 0) | Tính u_img cho hai khung cùng chip | u_img = 0,025+0,13+0,27+0,48 = 0,905 và 0,175+0,13+0,09 = 0,395; chip mang 0,905; detections lưu đủ p_* |
| TC-SCAN-12 | Cờ góp ảnh theo đồng ý lúc tải lên | Tích hợp API | FR-12-17, BR-CONSENT-01, UC12 | Người có và không có đồng ý photo_contribution | Mỗi người tải 1 ảnh | contributed = true chỉ với người có đồng ý hiện hành |
| TC-SCAN-13 | Danh sách đồ không thấy chỉ ở quét toàn tủ | Tích hợp API | FR-12-18, BR-PANTRY-03, UC12 | Kho có lô cà chua, rau muống; ảnh chỉ thấy cà chua | Quét mode=fridge rồi mode=haul; đọc `GET /scans/{id}` khi done | fridge: danh sách có rau muống; haul: không có danh sách |
| TC-SCAN-14 | Nhãn độ tươi của chip tại ngưỡng | Đơn vị | FR-13-01, BR-FRESH-04, UC13 | Bảng giá trị u | Gán nhãn cho u = 0,4999; 0,5; 0,7999; 0,8; 1,0; 1,0001; u = 0,6 với p_kiem_tra lớn nhất; chip không xác suất | Tươi; Nên dùng sớm; Nên dùng sớm; Dùng ngay; Dùng ngay; Kiểm tra; Kiểm tra; không nhãn |
| TC-SCAN-15 | App hiện nhãn bằng chữ kèm chấm màu | E2E | FR-13-02, BR-FRESH-05, UC13 | Playwright, scan done có đủ 4 nhãn | Mở màn xác nhận | Mỗi nhãn có chữ và chấm màu; có dòng "Gợi ý chất lượng, không phải kết luận an toàn thực phẩm" |
| TC-SCAN-16 | Sửa chip | Tích hợp API | FR-13-03, FR-13-04, FR-13-05, FR-13-06, UC13 | Scan done có chip model cà chua (model_count 3) | `PATCH /scans/{id}/items/{itemId}` đổi sang cà tím; sửa final_count 5; `POST /scans/{id}/items` thêm hành lá; thêm lại hành lá; `DELETE` chip model và chip user_added | original_ingredient_id = cà chua, user_action=relabeled; final_count=5, model_count giữ 3, edited; chip user_added tạo; trùng 409 `duplicate_item`; chip model thành deleted, chip user_added mất dòng |
| TC-SCAN-17 | Sửa chip không ghi kho và chỉ khi done | Tích hợp API | FR-13-07, FR-13-08, BR-SCAN-02, UC13 | Một scan processing, một scan done | Sửa chip ở cả hai; đếm `pantry_lots`, `pantry_transactions` | processing: 409 `scan_not_editable`; done: sửa được; số dòng kho không đổi |
| TC-SCAN-18 | Bắt buộc xác nhận đồ cần kiểm tra | Tích hợp API | FR-13-09, FR-13-20, BR-FRESH-04, UC13 | Chip nhãn Kiểm tra chưa có user_freshness | `POST /scans/{id}/confirm`; đặt user_freshness "Vẫn dùng được"; confirm lại | Lần 1: 409 `freshness_check_required`; lần 2: lô mới có user_checked_at = thời điểm xác nhận |
| TC-SCAN-19 | Quy đổi lượng khi xác nhận | Đơn vị | FR-13-10, FR-13-11, BR-QTY-01, BR-QTY-02, UC13 | 1 quả trứng = 50 g; qty_levels rau lá: vua = [200; 400] | Xác nhận chip trứng model_count 6 final_count 4; chip rau lá mức vua; chip rau chưa có mức | Trứng g_min = g_max = 200; rau [200; 400]; chip thiếu mức 422 `qty_level_required` |
| TC-SCAN-20 | Xác nhận là một giao dịch | Tích hợp API | FR-13-12, UC13 | Tiêm lỗi khi ghi lô thứ 2 | Confirm | 5xx; không lô nào được tạo; scans.status vẫn done |
| TC-SCAN-21 | Quét đồ vừa mua tạo lô mới | Tích hợp API | FR-13-13, BR-PANTRY-01, BR-PANTRY-03, UC13 | Kho đã có lô cà chua; múi giờ người dùng Asia/Ho_Chi_Minh | Quét mode=haul thấy cà chua; confirm lúc 23:30 giờ VN | Lô mới riêng, acquired_at = ngày xác nhận theo giờ VN, acquired_basis=purchase_date_entered, source_scan_item_id = chip; lô cũ không đổi |
| TC-SCAN-22 | Quét toàn tủ: lô mới, cập nhật lô cũ, đánh dấu không thấy | Tích hợp API | FR-13-14, FR-13-15, FR-13-16, BR-PANTRY-01, BR-PANTRY-03, UC13 | Kho: cà chua (2 lô in_stock), rau muống in_stock, hành not_seen | Quét fridge thấy cà chua, hành, trứng (mới); confirm | Trứng: lô mới first_seen, acquired_at = scans.created_at; cà chua: không lô mới, p_* cập nhật ở lô acquired_at mới nhất; hành về in_stock; rau muống thành not_seen, không giao dịch, không xoá |
| TC-SCAN-23 | Xác nhận lũy đẳng, trạng thái sai, huỷ | Tích hợp API | FR-13-17, FR-13-18, BR-SCAN-02, UC13 | Scan done; scan failed | Confirm hai lần tuần tự và hai lần song song; confirm scan failed; discard scan done hai lần | Cùng tóm tắt 200, kho chỉ ghi một lần; failed: 409 `invalid_scan_state`; discard → discarded, không ghi kho, lần hai 200 |
| TC-SCAN-24 | Chép quan sát độ tươi vào lô | Tích hợp API | FR-13-19, UC13 | Chip có hai khung, u_img lớn nhất ở khung 2 | Confirm | Lô có p_* của khung 2, freshness_observed_at = scans.finished_at, freshness_model_version_id = scans.classifier_version_id |

### 5.6. Kho (UC14) — nhóm `PANT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-PANT-01 | Danh sách kho | Tích hợp API | FR-14-01, UC14 | Lô in_stock, not_seen, used_up, discarded; có giao dịch trừ | `GET /pantry/lots` | Chỉ in_stock và not_seen; lượng từ v_pantry_lot_balance; có u, nhãn, available; sắp u giảm dần |
| TC-PANT-02 | u theo thời gian | Đơn vị | FR-14-02, BR-FRESH-01, UC14 | L = 4 ngày, acquired_at = now − 36 giờ | Tính u_time | 0,375 (d thập phân) |
| TC-PANT-03 | Kết hợp u_time và u_img | Đơn vị | FR-14-03, BR-FRESH-03, UC14 | u_time = 0,3; u_img = 0,7 | Bốn trường hợp: purchase_date_entered; first_seen với max P = 0,6; first_seen với max P = 0,59; lô không xác suất | 0,7; 0,7 (= u_img); 0,7 (max); 0,3 |
| TC-PANT-04 | Nhãn kho và lô không rõ hạn | Đơn vị | FR-14-04, FR-14-05, BR-FRESH-02, BR-FRESH-04, UC14 | Bảng u như TC-SCAN-14; lô L NULL không ảnh | Gán nhãn | Đúng ngưỡng như TC-SCAN-14; lô không tính được u: "Chưa rõ hạn", available=true |
| TC-PANT-05 | u tính lúc đọc, không lưu | Tích hợp API | FR-14-06, BR-FRESH-05, UC14 | Một lô | Đọc lúc t và t + 2 ngày (đồng hồ giả); kiểm lược đồ | u khác nhau theo thời điểm đọc; không bảng nào có cột u |
| TC-PANT-06 | Lô kiểm tra và not_seen không khả dụng | Tích hợp API | FR-14-07, BR-FRESH-04, BR-TRAY-04, UC14 | Lô nhãn Kiểm tra chưa xác nhận; lô not_seen; đủ cho một món nếu tính cả hai | Đọc kho; gọi `POST /meal-plans` | Hai lô available=false; lượng khả dụng meal nhận không gồm hai lô; mâm không dùng chúng để thoả khả thi |
| TC-PANT-07 | App hiện nhãn kho | E2E | FR-14-08, BR-FRESH-05, UC14 | Playwright, kho có đủ nhãn | Mở màn Kho | Chữ kèm chấm màu, chấm xám cho Kiểm tra; có dòng gợi ý chất lượng |
| TC-PANT-08 | Thêm lô bằng tay | Tích hợp API | FR-14-09, BR-PANTRY-01, BR-QTY-01, UC14 | Nguyên liệu đếm được và không đếm được | `POST /pantry/lots` 3 quả trứng có ngày mua; 250 g thịt không ngày mua; gửi hai lần | Mỗi lần một lô mới; trứng [150; 150], purchase_date_entered; thịt [250; 250], first_seen, acquired_at ≈ now |
| TC-PANT-09 | Sửa lượng bằng giao dịch | Tích hợp API | FR-14-10, FR-14-17, BR-QTY-01, UC14 | Lô [200; 300] | `PATCH /pantry/lots/{id}` thành [150; 250]; lại [150; 250]; [−1; 10]; [300; 200] | 1 giao dịch manual_edit delta (−50; −50), initial không đổi; lần lặp không ghi; âm và g_min > g_max 422 `validation_error` |
| TC-PANT-10 | Bỏ đồ | Tích hợp API | FR-14-11, FR-14-19, UC14 | Lô [100; 120], u = 0,9 | `POST /pantry/lots/{id}/discard` hai lần | Giao dịch discard delta (−100; −120), urgency_at_event = 0,9, status=discarded; lần hai 200, không ghi |
| TC-PANT-11 | Ngày mua | Tích hợp API | FR-14-12, UC14 | Lô first_seen | PATCH acquired_at hôm qua; PATCH ngày mai | acquired_basis=purchase_date_entered; ngày mai 422 `acquired_at_in_future` |
| TC-PANT-12 | Chuyển trạng thái lô bằng tay | Tích hợp API | FR-14-13, UC14 | Lô ở từng trạng thái | Thử mọi cặp chuyển | Chỉ not_seen→in_stock, not_seen→used_up, in_stock→used_up được nhận; →used_up kèm manual_edit đưa lượng về 0; còn lại 409 `invalid_lot_transition` |
| TC-PANT-13 | Xác nhận đồ kiểm tra vẫn dùng được | Tích hợp API | FR-14-14, FR-14-15, UC14 | Lô Kiểm tra; lô Tươi | Xác nhận ở cả hai; đọc kho; quét fridge mới thấy lô đó ở mức kiểm tra | Lô Tươi 409 `lot_not_check_level`; lô Kiểm tra có user_checked_at, đọc thành Dùng ngay, available=true; sau quan sát mới trở lại Kiểm tra |
| TC-PANT-14 | Chống BOLA ở kho | Bảo mật | FR-14-16, UC14 | Lô của A | B gọi PATCH, discard trên lô của A | 404 `not_found`, lô không đổi |
| TC-PANT-15 | Hỏi xác nhận trước khi bỏ đồ | E2E | FR-14-18, UC14 | Playwright; lô `in_stock` | Bấm "Bỏ đồ"; bấm Huỷ; bấm lại và xác nhận | Hộp xác nhận có câu "không hoàn tác được"; Huỷ không gửi request; xác nhận gửi đúng một `POST /pantry/lots/{id}/discard` |

### 5.7. Mâm cơm, đổi món, thay thế (UC15–UC17) — nhóm `MEAL`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-MEAL-01 | Kiểm tham số tạo mâm | Tích hợp API | FR-15-01, FR-15-02, FR-15-03, BR-TRAY-01, BR-TRAY-08, UC15 | Người dùng có kho | `POST /meal-plans` persons 0 và 7; max_minutes 9 và 181; meal=breakfast; 3 lô ghim; lô ghim của người khác; lô ghim not_seen; mã dị ứng lạ | Mọi trường hợp 422; không dòng `meal_plans` nào |
| TC-MEAL-02 | Lũy đẳng tạo mâm | Tích hợp API | FR-15-04, FR-15-05, UC15 | Key K | Gửi hai lần cùng thân; gửi K với persons khác | Lần hai trả nguyên văn mã và thân, 1 mâm; thân khác 422 `idempotency_key_reused` |
| TC-MEAL-03 | Lọc dị ứng cả gia vị, đồ tuỳ chọn và người ăn cùng | Tích hợp API | FR-15-06, BR-ALG-01, UC15 | Món A chứa nước mắm (cá, is_staple); món B có tôm khô is_optional; A02 dị ứng cá; người ăn cùng dị ứng giáp xác | Tạo mâm nhiều lần với kho đủ cho mọi món | Không mâm nào chứa A hoặc B |
| TC-MEAL-04 | Lọc chế độ ăn và chỉ món published | Tích hợp API | FR-15-07, FR-15-08, BR-DIET-01, BR-CATALOG-01, UC15 | A02 diet=chay; kho món có món thịt published, món chay draft, món chay retired | Tạo mâm | Không món nào có nhóm thực phẩm bị loại; không món draft hay retired |
| TC-MEAL-05 | Lượng cần theo số người | Đơn vị | FR-15-09, BR-TRAY-02, BR-QTY-02, UC15 | Món servings 4 có 300 g thịt và 3 quả trứng (50 g/quả) | need với n = 2 và n = 3 | Thịt 150 g và 225 g; trứng 1,5 → 2 quả (100 g) và 2,25 → 3 quả (150 g) |
| TC-MEAL-06 | Khả thi kho gộp giữa các món | Đơn vị | FR-15-10, BR-TRAY-04, UC15 | Hai món cùng cần 200 g cà chua; kho 300 g cà chua khả dụng; gia vị luôn có không có trong kho | Kiểm khả thi mâm chứa cả hai | Không khả thi (400 > 300); gia vị luôn có không làm mâm bất khả thi |
| TC-MEAL-07 | Cấu trúc mâm theo số người | Tích hợp API | FR-15-11, BR-TRAY-01, UC15 | Kho đủ | Tạo mâm n = 1, n = 2 | n = 1: 2 món man + (rau hoặc canh, slot cho hàm mục tiêu cao hơn); n = 2: đúng man, rau, canh |
| TC-MEAL-08 | Giới hạn thời gian nấu | Tích hợp API | FR-15-12, BR-TRAY-05, UC15 | Kho món nhỏ có tổ hợp makespan 35 và 50 phút; burners = 1 | Tạo mâm max_minutes 40 | Mâm trả về có makespan ≤ 40 với burners của người dùng |
| TC-MEAL-09 | Lô ghim phải dùng ít nhất 50% | Tích hợp API | FR-15-13, BR-TRAY-08, FR-15-30, UC15 | Lô ghim cải 400 g; một kịch bản có món dùng 200 g, một kịch bản món dùng tối đa 150 g | Tạo mâm có ghim | Kịch bản 1: mâm dùng ≥ 200 g cải; kịch bản 2: 422 `pin_unsatisfiable` nêu id lô |
| TC-MEAL-10 | Top-K và chọn tổ hợp tối ưu | Đơn vị | FR-15-14, FR-15-15, UC15 | Kho món tổng hợp 60 món/slot; tủ chỉ khả thi với món ngoài top-20 | So kết quả bộ ghép với duyệt vét cạn trên toàn bộ tổ hợp | Bộ ghép mở rộng K rồi trả đúng tổ hợp có hàm mục tiêu lớn nhất như vét cạn |
| TC-MEAL-11 | Thưởng dùng đồ gấp chỉ cho lô hợp lệ | Đơn vị | FR-15-16, BR-FRESH-04, UC15 | Lô u = 0,4, 0,6, 0,95, 1,1 và một lô không tính được u (L NULL, không có ảnh độ tươi) | Tính U(m) cho mâm dùng hết cả năm lô | Chỉ lô 0,6 và 0,95 vào tử và mẫu; lô 1,1 (Kiểm tra) và lô "Chưa rõ hạn" không được thưởng; lô "Chưa rõ hạn" vẫn tính vào lượng khả dụng |
| TC-MEAL-12 | Xếp hạng theo đồng ý cá nhân hoá | Tích hợp API | FR-15-17, FR-15-18, BR-CONSENT-03, UC15 | Người không đồng ý và người có đồng ý personalization; ranker R1 đang chạy | Tạo mâm cho từng người; theo dõi truy vấn SQL | Không đồng ý: không truy vấn `interactions`, ranker_version_id NULL; có đồng ý: ranker_version_id = R1 |
| TC-MEAL-13 | Năng lượng mâm và nhóm | Tích hợp API | FR-15-19, FR-15-20, FR-15-40, BR-NUT-04, BR-TRAY-07, BR-CONSENT-02, UC15 | E = 2.000; người khác không đồng ý health_profile | Tạo mâm dinner n = 3 cho người 1 rồi mở màn mâm; tạo mâm cho người 2 | Người 1: `e_target_kcal` = 600 (theo một người), `persons` = 3, màn hiện mục tiêu nhóm 1.800 kcal kèm chữ "ước lượng theo người dùng"; người 2: `e_target_kcal` NULL, β = 0, app hiện "chưa có mục tiêu" |
| TC-MEAL-14 | Số bát cơm gợi ý | Đơn vị | FR-15-21, BR-TRAY-03, UC15 | E_mâm 1 người = 700; E_bát (150 g) = 195 | E_món/người = 400, 650, 100 | 1,5 bát (1,54 → 1,5); 0,5 (chặn dưới); 3 (chặn trên) |
| TC-MEAL-15 | Calo dạng khoảng hoặc đang hiệu chỉnh | Tích hợp API | FR-15-22, BR-NUT-06, UC15 | Tham số h = 0,15; trường hợp chưa hiệu chỉnh | Tạo mâm có Σ `kcal_per_person` = 600 (E(m) theo một người) | kcal_low = 510, kcal_high = 690; chưa hiệu chỉnh: cả hai NULL, app hiện "đang hiệu chỉnh" |
| TC-MEAL-16 | Dòng lý do | Đơn vị | FR-15-23, UC15 | Mâm tốt nhất hơn mâm nhì chủ yếu nhờ U | Sinh reason_vi | Không rỗng, nhắc dùng đồ sắp hỏng |
| TC-MEAL-17 | Không có mâm khả thi | Tích hợp API | FR-15-24, BR-TRAY-06, FR-15-31, UC15 | Kho chỉ đủ cho mặn + canh; kho trống | Tạo mâm n = 2 | Kho 1: mâm 2 món; kho trống: 422 `no_feasible_tray` kèm nguyên liệu thiếu (id, gam) của 3 mâm tốt nhất, không lưu meal_plans |
| TC-MEAL-18 | Lưu mâm là một giao dịch | Tích hợp API | FR-15-25, UC15 | Tiêm lỗi khi ghi meal_plan_pins | Tạo mâm có ghim | 5xx; 0 dòng meal_plans, meal_plan_items, idempotency_keys mới |
| TC-MEAL-19 | Ghi served theo đồng ý | Tích hợp API | FR-15-26, BR-CONSENT-03, UC15 | Người có và không có đồng ý personalization | Tạo mâm 3 món | Có đồng ý: 3 interactions served có position, ranker_version_id, propensity; không đồng ý: 0 |
| TC-MEAL-20 | Nhận mâm | Tích hợp API | FR-15-27, FR-15-32, FR-15-33, UC15 | Mâm proposed; mâm cooked; mâm abandoned; mâm expired | `POST /meal-plans/{id}/accept` hai lần trên mâm proposed; một lần trên mỗi mâm còn lại | Lần một accepted, 200; lần hai 200, `updated_at` không đổi; cooked, abandoned, expired: 409, trạng thái không đổi |
| TC-MEAL-21 | Đọc mâm theo chủ và mâm mới nhất | Bảo mật | FR-15-28, FR-15-34, FR-15-35, UC15 | A có 2 mâm, B chưa có mâm | B gọi `GET /meal-plans/{id}` và accept mâm của A; A và B gọi `GET /meal-plans/latest` | B: 404 cả hai và latest 404; A: latest là mâm created_at mới nhất |
| TC-MEAL-22 | Tự áp thay thế chỉ từ bảng tra đã duyệt | Tích hợp API | FR-15-29, BR-ALG-01, BR-DIET-01, UC15 | Món cần hành tây; kho có hành tím (cặp curated) và hẹ (cặp không curated); cặp curated thứ ba là đồ dị ứng | Tạo mâm | Chỉ hành tím được áp, origin=lookup; không áp cặp không curated hoặc đồ dị ứng |
| TC-MEAL-23 | Kiểm yêu cầu đổi món | Tích hợp API | FR-16-01, FR-16-02, FR-16-03, BR-SWAP-01, UC16 | Mâm proposed của A; mâm cooked; món swapped_out | `POST /meal-plans/{id}/items/{itemId}/swap` không lý do; lý do lạ; itemId của mâm khác; mâm cooked; món swapped_out | 422; 422; 404; 409; 409; mâm không đổi |
| TC-MEAL-24 | Lũy đẳng đổi món | Tích hợp API | FR-16-04, UC16 | Key K | Gửi swap hai lần cùng key | Phản hồi lần hai trùng lần một; chỉ một dòng swapped_out mới |
| TC-MEAL-25 | Đổi món giữ các slot khác | Tích hợp API | FR-16-05, FR-16-06, BR-SWAP-01, UC16 | Mâm 3 món; đã đổi món canh một lần | Đổi canh lần hai | Món mặn và rau giữ recipe_id; món mới cùng slot canh, khác cả hai món canh trước |
| TC-MEAL-26 | Ứng viên đổi món qua đủ ràng buộc | Tích hợp API | FR-16-07, FR-16-08, FR-16-09, BR-ALG-01, BR-TRAY-04, BR-TRAY-05, BR-TRAY-08, UC16 | Mâm có người ăn cùng dị ứng; kho vừa đủ; lô ghim | Đổi món nhiều lần với kho món tổng hợp; so với duyệt vét cạn | Món mới không dị ứng (kể cả coeater), mâm sau đổi khả thi, makespan ≤ max_minutes, lô ghim ≥ 50%; là ứng viên có hàm mục tiêu lớn nhất |
| TC-MEAL-27 | Ghi đổi món và tính lại | Tích hợp API | FR-16-10, FR-16-11, UC16 | Mâm có e_target_kcal = 600 | Đổi món | Dòng cũ swapped_out có swap_reason; dòng mới active, replaced_item_id = dòng cũ; kcal_low/high, rice_bowls_per_person, reason_vi tính lại; e_target_kcal giữ 600 |
| TC-MEAL-28 | Tín hiệu gu khi đổi món | Tích hợp API | FR-16-12, FR-16-13, BR-SWAP-01, BR-CONSENT-03, UC16 | Người có đồng ý; người không | Đổi với từng lý do | Có đồng ý: 1 swapped có swap_reason + 1 served; 0 disliked với mọi lý do; không đồng ý: 0 interactions |
| TC-MEAL-29 | Hết ứng viên đổi món | Tích hợp API | FR-16-14, UC16 | Kho món slot rau chỉ có 1 món | Đổi món rau | 422 `no_alternative`, mâm giữ nguyên |
| TC-MEAL-30 | Liệt kê nguyên liệu thiếu | Tích hợp API | FR-17-01, FR-17-02, BR-TRAY-04, UC17 | Món cần 300 g thịt, kho 200 g khả dụng; món khác cùng mâm dùng 50 g thịt | `GET /meal-plans/{id}/items/{itemId}/substitutes`; gọi lại với ingredient_id là gia vị | Thịt thiếu 150 g; với ingredient_id có gợi ý cho đúng gia vị đó |
| TC-MEAL-31 | Số lượng, thứ tự và nhóm của gợi ý | Tích hợp API | FR-17-03, FR-17-04, FR-17-05, UC17 | Có 2 cặp bảng tra (một khớp ngữ cảnh), 5 lân cận embedding, nguyên liệu khác nhóm, nguyên liệu is_active=false | Lấy gợi ý | ≤ 3 gợi ý; cặp khớp ngữ cảnh trước, theo score giảm; chỉ cùng food_group_code, active, khác gốc |
| TC-MEAL-32 | Gợi ý thay thế qua lọc dị ứng và chế độ ăn | Tích hợp API | FR-17-06, FR-17-10, BR-ALG-01, BR-DIET-01, UC17 | Gợi ý ứng viên là tôm, A02 dị ứng giáp xác; người ăn cùng dị ứng trứng | Lấy gợi ý; gửi `POST /meal-plans/{id}/items/{itemId}/substitutions` với tôm | Không có tôm, trứng trong gợi ý; POST 422, không ghi |
| TC-MEAL-33 | Không có mô hình thay thế vẫn gợi ý | Tích hợp API | FR-17-07, UC17 | Xoá con trỏ substitution trong model_deployments | Lấy gợi ý | 200; nguồn chỉ là bảng tra và kNN dinh dưỡng |
| TC-MEAL-34 | Lượng và cờ kho của gợi ý | Đơn vị | FR-17-08, FR-17-09, BR-QTY-02, BR-FRESH-04, UC17 | need 120 g, ratio 1,5; đồ thay đếm được 50 g/đơn vị; lô thay ở mức Kiểm tra | Tính gợi ý | Lượng 180 g → 200 g (4 đơn vị); cờ có trong kho = false, khoảng không gồm lô Kiểm tra |
| TC-MEAL-35 | Chọn thay thế và tính lại calo | Tích hợp API | FR-17-11, FR-17-12, BR-NUT-05, UC17 | Món có kcal_per_person = 300 | Chọn thay A rồi chọn lại B cho cùng nguyên liệu gốc | Đúng 1 dòng meal_plan_item_substitutions (B), grams và origin đúng; kcal_per_person và kcal_low/high tính lại theo B |
| TC-MEAL-36 | Quyền và trạng thái ở UC17 | Bảo mật | FR-17-13, UC17 | Mâm của A; mâm cooked | B gọi hai endpoint thay thế trên mâm của A; A gọi trên mâm cooked | 404; 409 |
| TC-MEAL-37 | Đưa đồ thiếu vào danh sách đi chợ | Tích hợp API | FR-17-14, UC17 | Thịt thiếu 150 g | Bấm "Thêm vào danh sách đi chợ" (`POST /shopping-items`) | Dòng shopping_items qty_g=150, source_meal_plan_item_id = món |
| TC-MEAL-38 | Ghép mâm khi chưa có hồ sơ | Tích hợp API | FR-15-36, BR-CONSENT-02, UC15 | Người dùng mới chưa có hồ sơ (không có `profiles`, `user_settings`); kho đủ một mâm | `POST /meal-plans` | 201; `e_target_kcal` NULL; lịch nấu tính với 2 họng bếp; không lỗi 409 |
| TC-MEAL-39 | Mâm cũ hết hiệu lực khi tạo mâm mới cùng bữa | Tích hợp API | FR-15-37, FR-15-38, UC15 | Mâm M1 proposed bữa tối; mâm M2 accepted bữa trưa không có phiên nấu; mâm M3 accepted bữa trưa có phiên nấu in_progress (người khác, cùng dữ liệu) | Tạo mâm mới bữa tối; tạo mâm mới bữa trưa cho từng người | M1 expired; M2 abandoned; M3 vẫn accepted; mâm mới đều proposed |
| TC-MEAL-40 | Mâm hết hiệu lực khi qua giờ bữa | Tích hợp API | FR-15-39, FR-15-41, UC15 | Đồng hồ giả; mâm trưa proposed tạo 11:00; mâm tối accepted không có phiên nấu; mâm tối accepted có phiên nấu in_progress từ 23:50 | Đọc mâm trưa lúc 15:01 và gửi accept; đọc hai mâm tối lúc 00:05 hôm sau | Mâm trưa expired, accept 409; mâm tối không có phiên nấu abandoned; mâm tối có phiên nấu vẫn accepted |

### 5.8. Danh sách đi chợ (UC18) — nhóm `SHOP`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-SHOP-01 | Đọc danh sách đi chợ | Tích hợp API | FR-18-01, UC18 | A có 30 dòng open, 5 bought; B có dòng | `GET /shopping-items`; lọc bought; phân trang limit 10 | Chỉ dòng của A, mặc định open; lọc đúng; keyset (created_at, id) không trùng, không sót |
| TC-SHOP-02 | Tạo dòng và kiểm dữ liệu | Tích hợp API | FR-18-02, FR-18-03, FR-18-04, UC18 | Nguyên liệu active và inactive | POST hợp lệ; ingredient lạ; inactive; qty_g 0; note 201 ký tự | 201 status=open; các trường hợp còn lại 422 |
| TC-SHOP-03 | Gộp dòng trùng | Tích hợp API | FR-18-05, UC18 | Dòng open cùng ingredient, source NULL | POST lại cùng ingredient, source NULL, qty khác | 200, cập nhật dòng cũ, không dòng mới |
| TC-SHOP-04 | Chống BOLA ở danh sách đi chợ | Bảo mật | FR-18-06, FR-18-09, UC18 | Món mâm và dòng của A | B POST với source_meal_plan_item_id của A; B PATCH dòng của A | 404 cả hai |
| TC-SHOP-05 | Chuyển trạng thái và sửa | Tích hợp API | FR-18-07, FR-18-08, FR-18-10, UC18 | Dòng open | `PATCH /shopping-items/{id}` bought hai lần; bought→dropped; sửa qty khi bought; về open | bought; lần hai cùng 200; bought→dropped 409; sửa khi bought 409; →open được |
| TC-SHOP-06 | Mua xong không đổi kho | Tích hợp API | FR-18-11, UC18 | Dòng open | Chuyển bought; đếm pantry_lots | Không đổi |
| TC-SHOP-07 | Tìm nguyên liệu theo tên và đồng nghĩa | Tích hợp API | FR-18-12, UC18 | `ingredient_synonyms` có "cà chua" ↔ "tomato"; một nguyên liệu inactive | `GET /ingredients?q=tomato`; tìm tên inactive | Trả cà chua; không trả nguyên liệu inactive |

### 5.9. Nấu, nấu xong, hoàn tác (UC19–UC21) — nhóm `COOK`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-COOK-01 | Tạo phiên nấu | Tích hợp API | FR-19-01, FR-19-02, UC19 | Mâm accepted của A; mâm proposed; mâm của B | `POST /cook-sessions` cho từng mâm; tạo phiên thứ hai cho mâm accepted | Chỉ mâm accepted của A tạo được; proposed 409 `meal_plan_not_accepted`; mâm B 404; phiên thứ hai 409 `cook_session_in_progress` |
| TC-COOK-02 | Lũy đẳng tạo phiên | Tích hợp API | FR-19-03, FR-19-04, UC19 | Key K | Gửi hai lần cùng thân; K với serve_at khác | Nguyên văn, 1 phiên; 422 `idempotency_key_reused` |
| TC-COOK-03 | Lịch nấu CP-SAT hợp lệ | Tích hợp API | FR-19-05, FR-19-06, FR-19-07, FR-19-08, FR-19-09, BR-COOK-01, UC19 | Mâm 3 món có một món xào; burners 2 | Tạo phiên; đọc cook_schedule_entries | Không hai bước active chồng; ≤ 2 bước uses_burner đồng thời; step_no theo thứ tự; mọi món xong trong [serve_at − 300 s; serve_at]; món xào xong cuối |
| TC-COOK-04 | Lịch vượt thời gian chọn | Tích hợp API | FR-19-10, BR-TRAY-05, UC19 | max_minutes 30, makespan tối thiểu 38 phút | Tạo phiên không xác nhận; xác nhận | Lần 1 báo vượt 8 phút, không tạo phiên; lần 2 tạo |
| TC-COOK-05 | Lập lịch từ đúng bản món đã dùng | Tích hợp API | FR-19-11, BR-CATALOG-01, UC19 | Món trong mâm đã bị retired sau khi có bản mới | Tạo phiên | Lịch dùng recipe_steps của bản cũ |
| TC-COOK-06 | Bỏ dở phiên | Tích hợp API | FR-19-12, UC19 | Phiên in_progress | `POST /cook-sessions/{id}/abandon` | abandoned; kho không đổi |
| TC-COOK-07 | Bỏ sự kiện viewed khi chưa đồng ý | Tích hợp API | FR-19-13, BR-CONSENT-03, UC19 | Người không đồng ý personalization | `POST /events` type=viewed | 202/200 nhưng 0 dòng interactions |
| TC-COOK-08 | Nấu xong là một giao dịch | Tích hợp API | FR-20-01, FR-20-02, BR-COOK-02, UC20 | Phiên in_progress; tiêm lỗi ở bước ghi interactions | `POST /cook-sessions/{id}/complete` có lỗi; không lỗi | Có lỗi: phiên, mâm, kho như cũ; không lỗi: phiên completed, mâm cooked, giao dịch kho ghi cùng lúc |
| TC-COOK-09 | Nấu xong lũy đẳng | Tích hợp API | FR-20-03, FR-20-04, BR-COOK-02, UC20 | Phiên in_progress | Complete hai lần cùng key; lần ba key khác | Lần hai nguyên văn; lần ba không trừ kho thêm; tổng giao dịch cook_deduct như một lần |
| TC-COOK-10 | Lượng trừ kho | Đơn vị | FR-20-05, FR-20-06, BR-TRAY-02, BR-QTY-02, UC20 | Mâm n = 3, hai món dùng trứng; một món nhận thay hành tím cho hành tây | Tính danh sách trừ | Trứng cộng dồn rồi làm tròn lên theo quả; trừ hành tím, không trừ hành tây |
| TC-COOK-11 | Thứ tự lô và giao dịch trừ | Tích hợp API | FR-20-07, FR-20-08, FR-20-09, BR-PANTRY-02, UC20 | Ba lô cà chua u = 0,9 (100 g), 0,6 (200 g), 1,2 Kiểm tra (300 g); cần 250 g | Complete | Trừ 100 g lô 0,9 rồi 150 g lô 0,6; không đụng lô Kiểm tra; mỗi giao dịch cook_deduct có ref_type=cook_session, ref_id, urgency_at_event |
| TC-COOK-12 | Kho không đủ khi nấu xong | Tích hợp API | FR-20-10, UC20 | Cần 250 g, kho còn 100 g | Complete | 200; trừ về 0; phản hồi nêu thiếu 150 g |
| TC-COOK-13 | Tương tác khi nấu xong | Tích hợp API | FR-20-11, FR-20-12, FR-20-13, BR-COOK-02, BR-CONSENT-03, UC20 | Mâm 3 món; người có và không có đồng ý | Complete với chấm liked món 1, disliked món 2, không chấm món 3 | Có đồng ý: 3 cooked, 1 liked, 1 disliked; không đồng ý: 0 interactions nhưng kho vẫn trừ, trạng thái vẫn chuyển |
| TC-COOK-14 | Cửa sổ hoàn tác 10 phút | Tích hợp API | FR-21-01, FR-21-02, BR-PANTRY-02, UC21 | Phiên completed; đồng hồ giả | `POST /cook-sessions/{id}/undo` tại completed_at + 600 s; phiên khác tại + 601 s | 600 s nhận, phiên reverted; 601 s 409 `undo_window_expired`, không ghi |
| TC-COOK-15 | Giao dịch đảo khôi phục kho | Tích hợp API | FR-21-03, FR-21-04, FR-21-05, UC21 | Phiên vừa completed làm một lô thành used_up | Undo | Mỗi cook_deduct có đúng 1 undo đối dấu trỏ reverses_id; lượng mọi lô về như trước; lô used_up về in_stock |
| TC-COOK-16 | Hoàn tác lũy đẳng và trạng thái mâm | Tích hợp API | FR-21-06, FR-21-07, UC21 | Phiên đã reverted | Undo lại | Không ghi giao dịch đảo lần hai; mâm ở accepted |
| TC-COOK-17 | Tương tác undone và rollback | Tích hợp API | FR-21-08, FR-21-09, UC21 | Người có đồng ý; tiêm lỗi ở bước đổi trạng thái mâm | Undo không lỗi; undo có lỗi | Không lỗi: undone cho mỗi cooked, dòng cooked còn nguyên; có lỗi: phiên, mâm, kho như trước |

### 5.10. Nhật ký tuần (UC22) — nhóm `JRNL`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-JRNL-01 | Tuần ISO và múi giờ | Tích hợp API | FR-22-01, FR-22-02, FR-22-08, UC22 | Phiên completed 2026-10-18 17:30 UTC (= 19/10 00:30 giờ VN) | `GET /journal?week=2026-W43`; `week=2026-W54` | 7 ngày thứ Hai 19/10 → Chủ nhật 25/10; bữa nằm ở 19/10; W54: 422 `invalid_iso_week` |
| TC-JRNL-02 | Chỉ tính phiên hoàn tất, dùng ảnh chụp | Tích hợp API | FR-22-03, FR-22-04, FR-22-05, UC22 | Phiên completed, reverted, abandoned; sửa recipe_nutrition sau khi nấu; một mâm e_target_kcal NULL | Đọc nhật ký | Chỉ phiên completed; kcal/người = `kcal_per_person` đã chụp của món + bát cơm × E_bát; mục tiêu/người từ `e_target_kcal` đã chụp (không nhân `persons`); ngày có NULL hiện "chưa có mục tiêu" |
| TC-JRNL-03 | Khoảng calo và nhãn xấp xỉ | Tích hợp API | FR-22-06, FR-22-10, BR-NUT-06, BR-TRAY-07, UC22 | Mâm đã hiệu chỉnh persons 3; mâm chưa hiệu chỉnh | Đọc nhật ký | Mâm 1 hiện [kcal_low; kcal_high] và nhãn "xấp xỉ"; mâm 2 hiện "đang hiệu chỉnh" |
| TC-JRNL-04 | Đếm lô gấp được dùng kịp | Tích hợp API | FR-22-07, UC22 | Trong ngày: cook_deduct trên lô u 0,3; 0,6; 0,95 (hai lần cùng lô); 1,1 | Đọc v_journal_days | 2 lô |
| TC-JRNL-05 | Nhật ký chỉ của người gọi | Bảo mật | FR-22-09, UC22 | A và B đều có phiên | A gọi `GET /journal` và `GET /meal-plans` | Không có dữ liệu của B |
| TC-JRNL-06 | Nhật ký so cùng đơn vị khi mâm nhiều người | Tích hợp API | FR-22-11, BR-NUT-04, BR-TRAY-07, UC22 | Một mâm dinner `persons = 3`, `e_target_kcal = 600`, Σ `kcal_per_person` = 280, `rice_bowls_per_person` = 1,5, E_bát = 200, phiên completed | `GET /journal` tuần đó | Ngày đó: kcal/người 580, mục tiêu/người 600, tỷ lệ 97%, nhãn "xấp xỉ" |

### 5.11. Khảo sát gu (UC23–UC24) — nhóm `SURV`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-SURV-01 | Đồng ý trước khi khảo sát | Tích hợp API | FR-23-01, FR-23-02, FR-23-03, FR-23-04, BR-CONSENT-01, UC23 | Form mở; bản điều khoản survey v2 hiện hành | `POST /survey/respondents` không đồng ý; với v1; với v2 | Không đồng ý: 422 `consent_required`, 0 dòng; v1: 409 `policy_outdated`; v2: 201, có policy_version_id, consented_at |
| TC-SURV-02 | Giao món khối không đầy đủ | Tính chất | FR-23-05, FR-23-06, FR-23-07, UC23 | Form 10 neo + 35 ngẫu nhiên; kho món 60/50/40 theo slot | Hypothesis: tạo 200 người tham gia với seed ngẫu nhiên | Mỗi người có đủ 10 neo + đúng 35 món published không trùng neo; số món mỗi slot lệch tỷ lệ kho ≤ 1; display_order là hoán vị khác nhau |
| TC-SURV-03 | Chấm điểm | Tích hợp API | FR-23-08, FR-23-09, FR-23-10, UC23 | Người tham gia có token | `PUT /survey/respondents/{id}/ratings/{recipeId}` 0, 6, 3, lại 3, đổi 4, never_eaten; món không được giao | 0 và 6: 422; 3 lặp lại như một; giá trị cuối 4; never_eaten → rating NULL; món không giao 404 |
| TC-SURV-04 | Món hay ăn và hoàn tất | Tích hợp API | FR-23-11, FR-23-12, UC23 | Còn 2 món chưa trả lời | PUT favorites 6 món; complete; trả lời đủ, complete | 6 món 422; complete lần 1 trả danh sách 2 món thiếu, completed_at NULL; lần 2 completed_at đặt |
| TC-SURV-05 | Không lưu định danh người tham gia | Tích hợp API | FR-23-13, UC23 | Gửi kèm header User-Agent, IP giả | Hoàn tất một khảo sát; quét mọi cột survey_* | Không có email, tên, số điện thoại, IP, user agent |
| TC-SURV-06 | Tạo phiếu khảo sát | Vận hành (CLI/job) | FR-24-01, FR-24-02, FR-24-03, FR-24-04, UC24 | Form v1 đang mở; kho món đủ | `tastoria survey create-form --anchors 10 --random 35`; chạy với N + M > số món published; với một slot không có món | Form mới có 10 neo khác nhau, published, phân tầng theo slot; v1 đóng trong cùng giao dịch; hai trường hợp lỗi bị từ chối, không ghi |
| TC-SURV-07 | Quyền và kiểm toán khảo sát | Bảo mật | FR-24-05, FR-24-06, UC24 | Tài khoản user, curator, ml_operator | Chạy create-form và gọi `GET /admin/surveys` với từng vai trò | Chỉ ml_operator được; mỗi lần create-form và export có 1 dòng audit_log (vai trò, hành động, entity_id) |
| TC-SURV-08 | Xuất kết quả khảo sát | Vận hành (CLI/job) | FR-24-07, FR-24-08, FR-24-09, UC24 | 3 người hoàn tất, 2 chưa | `tastoria survey export <form_version>` | Chỉ 3 người; không cột định danh ngoài respondent_id; manifest.json có version, thời điểm, is_open, số người, số điểm, sha256 khớp từng CSV |
| TC-SURV-09 | Thống kê đợt khảo sát | Tích hợp API | FR-24-10, UC24 | 2 form với số người khác nhau | `GET /admin/surveys` | Số người tham gia và hoàn tất đúng từng form |

### 5.12. Kho công thức và cặp thay thế (UC25–UC26) — nhóm `CAT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-CAT-01 | Nhập kho món tất cả hoặc không | Vận hành (CLI/job) | FR-25-01, FR-25-02, FR-25-03, UC25 | Bundle có 3 lỗi ở 2 tệp: slot=bun, kind=idle, role=main2 | `tastoria catalog import <bundle_dir>` | Thoát ≠ 0; liệt kê đủ 3 lỗi dạng tệp:dòng: mã lỗi: mô tả; 0 dòng ghi |
| TC-CAT-02 | Khai báo dị ứng của nguyên liệu | Vận hành (CLI/job) | FR-25-04, FR-25-05, BR-ALG-02, UC25 | Nguyên liệu thiếu khoá allergens; nguyên liệu allergens: []; nguyên liệu mã `mustard` | Nhập bundle | Thiếu khoá bị lỗi; danh sách rỗng hợp lệ; mã ngoài allergen_groups bị lỗi |
| TC-CAT-03 | Điều kiện dữ liệu nguyên liệu và món published | Vận hành (CLI/job) | FR-25-06, FR-25-07, FR-25-08, BR-QTY-02, UC25 | Nguyên liệu countable không có unit; có shelf_life_days không basis; món published 1 nguồn; bước nhảy số; minutes 0 | Nhập bundle | Mỗi trường hợp một lỗi chặn |
| TC-CAT-04 | Nhập lại lũy đẳng, đổi bản, không xoá cứng | Vận hành (CLI/job) | FR-25-09, FR-25-10, FR-25-11, BR-CATALOG-01, UC25 | Kho đã nhập bundle B | Nhập lại B; nhập B' sửa bước của món published X và bỏ nguyên liệu Y | Lần 1: 0 thay đổi, computed_at không đổi; B': bản X mới published, bản cũ retired; Y is_active=false; mâm cũ vẫn trỏ bản cũ |
| TC-CAT-05 | Tính dinh dưỡng món theo EuroFIR | Đơn vị | FR-25-12, FR-25-13, FR-25-14, BR-NUT-05, UC25 | Món 2 nguyên liệu: 200 g có refuse_pct 20, 100 g refuse 0; món rán ngập dầu | Tính recipe_nutrition | Khớp tính tay Σ w·EP/100·n (RF = 1); món rán áp hệ số hấp thu chất béo cho lipid_g và energy_kcal; computed_at, data_version ghi |
| TC-CAT-06 | Chặn nhập khi có vi phạm dị ứng | Vận hành (CLI/job) | FR-25-15, BR-ALG-01, UC25 | Bundle có món dùng tương (đậu nành) nhưng nguyên liệu khai thiếu nhóm, phát hiện qua đồng nghĩa | Nhập bundle | Kiểm toàn kho × mọi nhóm báo vi phạm; rollback; audit_log ghi lần chạy |
| TC-CAT-07 | Nhập cặp thay thế trong một giao dịch | Vận hành (CLI/job) | FR-26-01, FR-26-02, UC26 | Tệp 20 cặp, 1 tên nguyên liệu không khớp, 1 tên khớp 2 id | `tastoria catalog substitutes import <file>` | Báo 2 lỗi; 0 cặp ghi |
| TC-CAT-08 | Kiểm từng cặp thay thế | Vận hành (CLI/job) | FR-26-03, FR-26-04, FR-26-05, FR-26-06, UC26 | Cặp khác nhóm; cặp có nguyên liệu inactive; ratio 0; score 1,2; source rỗng; slot lạ; method lạ; hai dòng trùng khoá với slot rỗng | Nhập tệp | Mỗi trường hợp một lỗi chặn |
| TC-CAT-09 | Đồng bộ cặp curated | Vận hành (CLI/job) | FR-26-07, FR-26-08, FR-26-09, FR-26-10, UC26 | CSDL có cặp curated C1, C2 và cặp sinh tự động N1 | Nhập tệp gồm C1 (score đổi) và C3; nhập lại cùng tệp | C1 cập nhật, C3 thêm, C2 xoá, N1 không đổi; lần hai "0 thay đổi"; mỗi lần 1 dòng audit_log substitutes.import |

### 5.13. Yêu cầu dữ liệu và nhật ký kiểm toán phía quản trị (UC27) — nhóm `ADM`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-ADM-01 | Chỉ admin truy cập hàng đợi và nhật ký | Bảo mật | FR-27-01, UC27 | Token user, curator, ml_operator, admin | Gọi `GET /admin/data-requests`, `POST /admin/data-requests/{id}/resolve`, `GET /admin/audit-log` | Chỉ admin 200; còn lại 403 |
| TC-ADM-02 | Hàng đợi yêu cầu | Tích hợp API | FR-27-02, FR-27-03, FR-27-04, NFR-PRIV-01, BR-DSR-01, UC27 | 25 yêu cầu; một `export` nhận lúc T và một `correct` nhận lúc T, đều chưa đóng; đồng hồ giả | Lấy trang 1, 2 theo keyset lúc T + 24 giờ 1 phút và lúc T + 10 ngày 1 phút; lọc status, type | Lúc T + 24 h 1 phút chỉ `export` quá hạn và ở đầu; lúc T + 10 ngày 1 phút cả hai quá hạn; phân trang không trùng; không có cột sức khoẻ, nội dung hồ sơ |
| TC-ADM-03 | Chuyển trạng thái yêu cầu | Tích hợp API | FR-27-05, FR-27-06, FR-27-07, FR-27-08, UC27 | Yêu cầu received | → in_progress; → completed; completed → in_progress; rejected không note; gửi lại completed | acknowledged_at đặt ở lần đầu; completed_at đặt; chuyển ngược 409; rejected không note bị từ chối; gửi lại 200 không ghi mới |
| TC-ADM-04 | Chấp nhận hạn chế/phản đối rút đồng ý | Tích hợp API | FR-27-09, BR-CONSENT-04, UC27 | Yêu cầu object gắn personalization | Resolve completed | Một giao dịch: consent_events withdraw, token_version +1 |
| TC-ADM-05 | Kiểm toán thao tác nhân sự | Tích hợp API | FR-27-10, FR-27-11, UC27 | Admin xem danh sách, nhật ký, resolve | Đọc audit_log; lọc theo khoảng thời gian, actor, entity, action | Mỗi thao tác 1 dòng đủ actor_user_id, actor_role, action, entity, entity_id, request_id; bộ lọc và keyset đúng |
| TC-ADM-06 | Yêu cầu của chủ thể đã xoá | Tích hợp API | FR-27-12, BR-DSR-01, UC27 | dsr_requests user_id NULL | Liệt kê và resolve | Hiện subject_ref dạng hex; đóng được |

### 5.14. Vận hành mô hình (UC28–UC30) — nhóm `MLOP`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-MLOP-01 | Xuất dữ liệu huấn luyện theo đồng ý | Vận hành (CLI/job) | FR-28-01, FR-28-02, FR-28-03, BR-CONSENT-03, UC28 | Người có/không personalization; có/không photo_contribution; người deletion_requested; ảnh purged | `tastoria mlops export-training-data --since 2026-10-01` | Chỉ interactions của người đang đồng ý; ảnh chỉ contributed, chưa purge, chủ đang đồng ý; không có người chờ xoá |
| TC-MLOP-02 | Bí danh hoá | Vận hành (CLI/job) | FR-28-04, FR-28-05, FR-28-06, UC28 | Khoá HMAC K | Xuất hai lần; quét tệp | Không có user_id, email, cột `*_enc`; bí danh = HMAC(K, user_id) giống nhau giữa hai lần; thời điểm chỉ còn ngày (giờ VN) |
| TC-MLOP-03 | Phạm vi thời gian, trường giữ lại, danh sách thu hồi | Vận hành (CLI/job) | FR-28-07, FR-28-08, FR-28-09, UC28 | Tương tác trước và sau since; người rút đồng ý sau since; dsr delete completed | Xuất | Chỉ dòng ≥ since; giữ swap_reason, type, position, ranker_version_id, propensity; danh sách thu hồi có đúng các bí danh |
| TC-MLOP-04 | Manifest, ghi nguyên tử, khoá | Vận hành (CLI/job) | FR-28-10, FR-28-11, FR-28-12, UC28 | Khoá chưa cấu hình; khoá nằm trong thư mục đích; tiêm lỗi giữa chừng | Chạy ba trường hợp và một lần hợp lệ | Hai trường hợp khoá bị từ chối; lỗi giữa chừng không để tệp tên cuối; lần hợp lệ có manifest đủ số dòng, sha256, since, mã khoá, phiên bản mô hình; audit_log mọi lần |
| TC-MLOP-05 | Đăng ký mô hình | Vận hành (CLI/job) | FR-29-01, FR-29-02, FR-29-03, UC29 | Tệp ONNX | `tastoria mlops register detector <artifact> --metrics <json>`; đăng ký lại cùng tệp; cùng version tệp khác; name=segmenter | sha256 đúng; đăng ký lại trả bản cũ; tệp khác bị từ chối; name lạ bị từ chối |
| TC-MLOP-06 | Bản đồ lớp | Vận hành (CLI/job) | FR-29-04, FR-29-05, UC29 | Bản đồ có lỗ class_index; lớp không có trong vision_classes; mô hình freshness có lớp has_freshness_model=false | Đăng ký | Mỗi trường hợp bị từ chối; bản đồ hợp lệ lưu đủ model_version_classes |
| TC-MLOP-07 | Trạng thái candidate và dọn khi lỗi | Vận hành (CLI/job) | FR-29-06, FR-29-07, UC29 | Tiêm lỗi sau khi chép tệp | Đăng ký thành công; đăng ký có lỗi | Bản mới candidate có metrics, preprocess_version, mlflow_run_id; lỗi không để tệp trong models/ |
| TC-MLOP-08 | Cổng kiểm định | Mô hình | FR-29-08, FR-29-09, FR-29-10, FR-29-11, UC29 | Ứng viên kém hơn bản chạy 0,5 điểm (δ = 1); ứng viên kém 3 điểm; tập kiểm tra bị sửa; freshness thiếu hệ số nhiệt độ; bản validated | `tastoria mlops gate <name> <version>` | Lần 1 PASS → validated, có gate_report_key; lần 2 FAIL → rejected; tập bị sửa và thiếu hiệu chỉnh FAIL; bản không candidate bị từ chối |
| TC-MLOP-09 | Danh sách mô hình cho người vận hành | Tích hợp API | FR-29-12, UC29 | Có 3 phiên bản, 1 con trỏ | `GET /admin/models` với ml_operator và admin | ml_operator thấy name, version, status, created_at, metrics, con trỏ; admin 403; audit_log có register, gate |
| TC-MLOP-10 | Triển khai | Vận hành (CLI/job) | FR-30-01, FR-30-02, FR-30-03, FR-30-04, UC30 | Bản candidate; bản validated có tệp bị sửa; bản validated hợp lệ | `tastoria mlops deploy <name> <version>` từng bản; deploy lại bản đang chạy | Candidate và tệp sai sha256 bị từ chối; hợp lệ: previous = bản cũ, active = bản mới, switched_at, switched_by trong một giao dịch; deploy lại không đổi con trỏ |
| TC-MLOP-11 | Quay lui | Vận hành (CLI/job) | FR-30-05, FR-30-06, FR-30-11, NFR-REL-01.c, UC30 | Con trỏ có previous; con trỏ không có previous | `tastoria mlops rollback <name>`; đo từ lệnh tới `GET /readyz` 200 | Hoán đổi active/previous; không có previous bị từ chối; thời gian < 5 phút trên máy đích |
| TC-MLOP-12 | Nạp mô hình lúc khởi động và readyz | Tích hợp API | FR-30-07, FR-30-08, UC30 | Tệp mô hình đúng; tệp bị sửa một byte | Khởi động api và worker; gọi `GET /readyz` và `GET /healthz` | Tệp đúng: readyz 200; tệp sai: không nạp, readyz 503, healthz vẫn 200 |
| TC-MLOP-13 | Đóng dấu phiên bản và kiểm toán triển khai | Tích hợp API | FR-30-09, FR-30-10, UC30 | Sau deploy R2 | Tạo scan, mâm, sự kiện | detector_version_id, classifier_version_id, ranker_version_id ghi bản đang chạy; audit_log có deploy và rollback với bản cũ, bản mới |

### 5.15. Gán nhãn ảnh góp (UC31) — nhóm `LBL`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-LBL-01 | Chọn ảnh gửi gán nhãn | Vận hành (CLI/job) | FR-31-01, FR-31-02, FR-31-03, UC31 | Label Studio (A10) chạy trong compose; ảnh đủ và không đủ điều kiện; một người vừa rút đồng ý | `tastoria labeling push` | Chỉ ảnh contributed, chưa purge, chủ đang đồng ý; tác vụ của người rút bị gỡ; tác vụ chỉ có ảnh và scan_images.id |
| TC-LBL-02 | Tác vụ không trùng và ưu tiên ảnh bị sửa | Vận hành (CLI/job) | FR-31-04, FR-31-05, FR-31-06, UC31 | Ảnh có chip relabeled và ảnh chỉ kept | push hai lần | Không trùng tác vụ; ảnh có chip sửa xếp trước; khung từ detections gắn nhãn dự đoán |
| TC-LBL-03 | Kéo nhãn về | Vận hành (CLI/job) | FR-31-07, FR-31-08, FR-31-09, FR-31-10, UC31 | Nhãn có toạ độ 1,2; x1 ≥ x2; lớp lạ; ảnh vừa hết điều kiện | `tastoria labeling pull` | Loại các khung lỗi và nhãn của ảnh hết điều kiện; tệp nhãn trong contrib/ có sha256; audit_log ghi số tác vụ, số nhãn nhận/loại |

### 5.16. Tác vụ định kỳ (UC32–UC34) — nhóm `JOB`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-JOB-01 | Chọn ảnh quá hạn để xoá | Vận hành (CLI/job) | FR-32-01, FR-32-02, FR-32-03, FR-32-04, BR-RETAIN-01, NFR-PRIV-01.b, UC32 | Ảnh 29 ngày; 31 ngày; 31 ngày contributed chủ đang đồng ý; 5 ngày contributed chủ đã rút | `python -m tastoria.jobs.purge_images` (đồng hồ giả) | Xoá ảnh 31 ngày và ảnh của người đã rút; giữ ảnh 29 ngày và ảnh contributed đang đồng ý |
| TC-JOB-02 | Cách xoá ảnh | Vận hành (CLI/job) | FR-32-05, FR-32-06, FR-32-07, UC32 | Một tệp đã mất trên đĩa; một tệp không có quyền xoá | Chạy job | Dòng scan_images còn, purged_at đặt; tệp đã mất vẫn đặt purged_at; tệp lỗi không đặt purged_at, các ảnh khác vẫn xử lý, thoát ≠ 0 |
| TC-JOB-03 | Không chạy chồng và kiểm toán xoá ảnh | Vận hành (CLI/job) | FR-32-08, FR-32-09, UC32 | Một tiến trình đang giữ khoá tư vấn | Chạy tiến trình thứ hai; chạy bình thường | Lần hai thoát 0 không xử lý; lần có xử lý ghi 1 dòng audit retention.purge_images |
| TC-JOB-04 | Tạo và kiểm bản sao lưu | Vận hành (CLI/job) | FR-33-01, FR-33-02, FR-33-03, UC33 | rclone trỏ remote giả (thư mục cục bộ); khoá mã hoá có và không | `python -m tastoria.jobs.backup` | Bản pg_dump -Fc qua pg_restore --list; chỉ bản mã hoá ra remote; thiếu khoá từ chối chạy |
| TC-JOB-05 | Giữ bản sao lưu ≤ 14 ngày | Vận hành (CLI/job) | FR-33-04, FR-33-05, FR-33-07, BR-RETAIN-01, NFR-PRIV-01.b, UC33 | Remote giả có 20 bản ngày qua 20 ngày giả lập | Chạy 20 lần với đồng hồ giả; chạy hai lần trong một ngày | Sau mỗi lần tối đa 7 bản ngày + 1 bản tuần, không bản nào > 14 ngày; xoá bản cũ chỉ sau khi kích thước, checksum khớp; chạy lại trong ngày thay bản cùng ngày |
| TC-JOB-06 | Lỗi đẩy, khoá, dọn tệp, kiểm toán sao lưu | Vận hành (CLI/job) | FR-33-06, FR-33-08, FR-33-09, FR-33-10, UC33 | Remote giả lỗi 3 lần; một tiến trình đang chạy | Chạy job | Thử 3 lần rồi dừng, bản cũ còn nguyên; lần chạy chồng không xử lý; không còn dump chưa mã hoá; audit backup.create khi thành công, log JSON có mã lỗi khi thất bại |
| TC-JOB-07 | Sweeper lần quét kẹt | Vận hành (CLI/job) | FR-34-01, FR-34-02, FR-34-03, FR-34-06, FR-34-11, NFR-REL-01.d, UC34 | Scan processing 61 s attempts 1; processing 61 s attempts 3; processing 59 s; queued attempts 0 tạo cách 5 phút 1 giây; enqueue giả lỗi | `python -m tastoria.jobs.sweep` | Attempts 1: đưa lại hàng đợi, attempts vẫn 1; attempts 3: expired, error_code = timeout, có finished_at; 59 s không đụng; queued quá 5 phút: expired; enqueue lỗi giữ attempts và trạng thái; sweeper không đặt failed |
| TC-JOB-08 | Sweeper không ghi kho và không ghi đè worker | Tính chất | FR-34-04, FR-34-05, UC34 | Worker và sweeper chạy song song trên cùng scan (Hypothesis sinh thứ tự xen kẽ) | Lặp 200 lần | Không lần nào scan bị đưa từ done về failed; sweeper không ghi pantry_*; không đặt done hay confirmed |
| TC-JOB-09 | Dọn khoá lũy đẳng và token hết hạn | Vận hành (CLI/job) | FR-34-07, FR-34-08, UC34 | idempotency_keys 47 h và 49 h; refresh_tokens hết hạn, còn hạn đã thu hồi; password_resets hết hạn | Chạy sweeper | Xoá 49 h, giữ 47 h; xoá token hết hạn; giữ token còn hạn đã thu hồi (để phát hiện dùng lại) |
| TC-JOB-10 | Khoá và log sweeper | Vận hành (CLI/job) | FR-34-09, FR-34-10, FR-34-12, UC34 | Một sweeper đang chạy | Chạy sweeper thứ hai; chạy bình thường có 1 scan bị đặt expired; chạy khi không có scan nào bị đặt expired | Lần hai không xử lý; log JSON có số đưa lại, `scans_expired`, số dòng xoá theo bảng; đúng một dòng audit_log `sweep.scans_expired` khi có scan expired, không ghi khi không có |

### 5.17. Kiểm thử tính chất (Hypothesis) — nhóm `PROP`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-PROP-01 | 0 vi phạm dị ứng trên toàn kho món × mọi nhóm dị ứng | Tính chất | BR-ALG-01, BR-ALG-02, UC15, UC16, UC17, UC25 | Kho món thật đã nhập; 10 nhóm allergen_groups; CI | Với mỗi nhóm g và mỗi tập con 1–3 nhóm (Hypothesis) cho người dùng và người ăn cùng: sinh kho ngẫu nhiên, gọi ghép mâm, đổi món, gợi ý thay thế; duyệt thêm từng món × từng nhóm qua lọc cứng | 0 món, gia vị (is_staple), đồ tuỳ chọn hay đồ thay thế thuộc nhóm đã khai trong mọi kết quả; job CI fail nếu ≥ 1 vi phạm |
| TC-PROP-02 | 0 vi phạm chế độ ăn | Tính chất | BR-DIET-01, UC15, UC16, UC17 | diet chay và diet_exclusions thật | Hypothesis sinh kho và yêu cầu; ghép mâm, đổi món, thay thế | Không nguyên liệu nào thuộc food_group bị loại |
| TC-PROP-03 | Mâm trả về luôn khả thi kho | Tính chất | BR-TRAY-01, BR-TRAY-02, BR-TRAY-04, BR-TRAY-08, BR-QTY-01, UC15, UC16 | Kho món thật; Hypothesis sinh 30 lô, n ∈ [1, 6], 0–2 lô ghim | Gọi ghép mâm 1.000 lần (profile CI 200 lần) | Mỗi mâm trả về: cấu trúc slot đúng n; với mọi nguyên liệu không phải gia vị luôn có Σ need ≤ Σ g_min khả dụng (lô ≤ Dùng ngay); lô ghim dùng ≥ 50% g_min; khi trả no_feasible_tray thì vét cạn trên kho nhỏ cũng không có mâm |
| TC-PROP-04 | Lịch nấu luôn hợp lệ | Tính chất | BR-COOK-01, BR-TRAY-05, UC15, UC19 | Hypothesis sinh 2–3 món từ kho thật, burners ∈ [1, 4], serve_at | Gọi bộ lập lịch CP-SAT | Không hai bước active chồng; số bước uses_burner đồng thời ≤ burners; thứ tự step_no; mọi món xong trong 5 phút trước serve_at; món xào xong cuối; makespan bằng giá trị bộ ghép mâm dùng cho BR-TRAY-05 |
| TC-PROP-05 | Số dư kho và hoàn tác | Tính chất | BR-PANTRY-01, BR-PANTRY-02, BR-QTY-01, UC14, UC20, UC21 | Máy trạng thái Hypothesis (RuleBasedStateMachine) trên CSDL thật | Chuỗi ngẫu nhiên: thêm lô, sửa lượng, bỏ đồ, nấu xong, hoàn tác trong/ngoài 10 phút | Lượng hiển thị không âm; g_min ≤ g_max; hoàn tác ngay sau nấu xong đưa số dư về đúng trạng thái trước; giao dịch chỉ ghi thêm |
| TC-PROP-06 | Tính chất độ gấp | Tính chất | BR-FRESH-01, BR-FRESH-02, BR-FRESH-03, BR-FRESH-04, BR-FRESH-05, UC14 | Hypothesis sinh d, L, xác suất 4 lớp (tổng 1), acquired_basis | Tính u và nhãn | u_img ∈ [0,25; 1,2]; u không giảm theo thời gian đọc khi không có quan sát mới; nhãn đơn điệu theo u; nhãn Kiểm tra ⇒ available=false |
| TC-PROP-07 | Đổi món không quay lại món đã đổi | Tính chất | BR-SWAP-01, UC16 | Hypothesis sinh chuỗi 1–5 lần đổi trên một mâm | Đổi lần lượt các slot | Không món mới nào thuộc tập swapped_out của mâm; slot không bị đổi giữ nguyên recipe_id |
| TC-PROP-08 | Mục tiêu năng lượng có sàn và trong miền | Tính chất | BR-NUT-01, BR-NUT-02, BR-NUT-03, BR-NUT-04, UC11 | Hypothesis sinh giới, tuổi 18–100, cân nặng 35–200 kg, mức vận động, goal | Tính E và E_mâm | lose: E ≥ sàn theo giới; maintain: E = TEE; E_mâm trưa/tối = E × 0,35/0,30; không ngoại lệ |

### 5.18. Hợp đồng API (Schemathesis) — nhóm `CONT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-CONT-01 | Hợp đồng toàn bộ API khớp OpenAPI | Hợp đồng | UC01, UC02, UC03, UC04, UC05, UC06, UC07, UC08, UC09, UC10, UC11, UC12, UC13, UC14, UC15, UC16, UC17, UC18, UC19, UC20, UC21, UC22, UC23, UC24, UC27, UC29, UC30 | Compose đầy đủ với dữ liệu mẫu; `docs/api/openapi-v1.yaml`; token mỗi vai trò | Schemathesis `st run` mọi 70 endpoint (gồm `GET /healthz`, `GET /readyz`) với kiểm not_a_server_error, status_code_conformance, content_type_conformance, response_schema_conformance | 0 phản hồi 5xx; mọi phản hồi đúng schema; mọi lỗi là `application/problem+json` có `code` |
| TC-CONT-02 | Hợp đồng không trôi so với mã | Tĩnh/CI | NFR-MAINT-01, NFR-MAINT-01.e | CI | openapi-spec-validator trên openapi-v1.yaml; so OpenAPI sinh từ FastAPI với tệp trong repo; sinh client TypeScript cho app và biên dịch | Hợp lệ OpenAPI 3.1; diff rỗng; client biên dịch không lỗi |
| TC-CONT-03 | Mọi mã lỗi có câu tiếng Việt | Tĩnh/CI | NFR-USE-01.c | CI; danh sách `ProblemCode` trong OpenAPI; tệp chuỗi của app | So danh sách `code` với khoá chuỗi tiếng Việt của app; dò màn lỗi trong E2E | 100% `code` có câu tiếng Việt; không màn nào hiện mã kỹ thuật cho người dùng |

### 5.19. Bảo mật — nhóm `SEC`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-SEC-01 | Ma trận BOLA: A truy cập tài nguyên của B | Bảo mật | FR-06-08, FR-12-14, FR-14-16, FR-15-28, FR-16-02, FR-17-13, FR-18-09, FR-22-09, NFR-SEC-01.c, UC06, UC12, UC13, UC14, UC15, UC16, UC17, UC18, UC19, UC22 | Hai người A, B có đủ tài nguyên mỗi loại | A gọi mọi endpoint có tham số {id}/{itemId} bằng id của B (scan, ảnh scan, chip, lô, mâm, món mâm, danh sách đi chợ, phiên nấu, yêu cầu dữ liệu) | Mọi lần 404 `not_found` (không 403, không lộ tồn tại); không dòng nào của B đổi |
| TC-SEC-02 | Lũy đẳng khi gửi đôi và song song | Bảo mật | FR-12-06, FR-15-04, FR-16-04, FR-19-03, FR-20-03, FR-20-04, BR-COOK-02, NFR-REL-01.b, UC12, UC15, UC16, UC19, UC20 | Key giống nhau | Gửi 2 và 10 yêu cầu song song (asyncio) cùng key tới `POST /scans`, `POST /meal-plans`, swap, `POST /cook-sessions`, `POST /cook-sessions/{id}/complete` | Đúng một tác dụng mỗi trường hợp; các phản hồi còn lại trùng nguyên văn hoặc 409 đang xử lý; kho chỉ trừ một lần |
| TC-SEC-03 | Chống trùng sự kiện theo event_id | Bảo mật | BR-CONSENT-03, UC15, UC16, UC19, UC20 | Người có đồng ý personalization | Gửi `POST /events` cùng event_id hai lần và song song; gửi event_id của người khác | Đúng 1 dòng interactions; event_id trùng của người khác không ghi đè dòng cũ |
| TC-SEC-04 | Tải lên độc hại | Bảo mật | FR-12-02, FR-12-03, FR-12-04, FR-12-05, NFR-SEC-02.b, UC12 | Tệp ZIP đổi đuôi .jpg; polyglot JPEG+HTML; PNG 20000 × 20000 px nén còn ~100 KB; JPEG có GPS | Gửi qua `POST /scans`; theo dõi RAM worker | Giả đuôi và polyglot 415; ảnh 20000² 422 trước khi giải nén toàn bộ, RAM không vượt 512 MB; ảnh GPS lưu lại không còn EXIF/GPS |
| TC-SEC-05 | Phân quyền vai trò nhân sự | Bảo mật | FR-08-07, FR-24-05, FR-27-01, FR-29-12, NFR-SEC-01.d, UC08, UC24, UC27, UC29 | Token mỗi vai trò | Gọi mọi endpoint `/admin/*` với vai trò không đúng | 403; không có thao tác nào được ghi |
| TC-SEC-06 | Giả mạo JWT | Bảo mật | NFR-SEC-01, FR-02-09, UC02 | Access token hợp lệ | Đổi alg=none; đổi kid; ký bằng khoá khác; dùng token hết hạn 1 s; sửa claim sub | Mọi lần 401 |
| TC-SEC-07 | Token người tham gia khảo sát | Bảo mật | UC23 | Hai người tham gia R1, R2 | R1 dùng token của mình gọi `GET /survey/respondents/{id}` và chấm điểm cho id của R2 | 404; không ghi |
| TC-SEC-08 | Tệp nội bộ chỉ qua kiểm quyền | Bảo mật | FR-06-09, UC06, UC13 | nginx trong compose | Gọi trực tiếp location internal của nginx từ ngoài; gọi `GET /scans/{id}/images/{ordinal}` của chính mình | Truy cập trực tiếp 404; truy cập qua API 200 qua X-Accel-Redirect |
| TC-SEC-09 | Quét phụ thuộc và ranh giới module | Tĩnh/CI | NFR-MAINT-01 | CI | pip-audit, npm audit, import-linter theo deps của model.yaml, quét bí mật trong repo | Không lỗ hổng mức cao chưa xử lý; import-linter xanh |
| TC-SEC-10 | Bề mặt mạng của máy phục vụ | Bảo mật | NFR-SEC-02.c | Máy phục vụ đang chạy compose bản phát hành | Quét cổng từ máy ngoài (nmap 1–65535 TCP); đọc `compose.yaml` | Chỉ đi được qua Cloudflare Tunnel bằng HTTPS; không cổng nào mở ra ngoài; nginx bind `127.0.0.1`; không dịch vụ nào khác khai `ports` |

### 5.20. Đầu–cuối (Playwright web, Maestro Android) — nhóm `E2E`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-E2E-01 | Luồng chính trên web | E2E | UC01, UC09, UC12, UC13, UC15, UC19, UC20, UC22 | Playwright, compose, bộ phát hiện chạy ảnh vàng | Đăng ký → hồ sơ 60 giây → quét ảnh vàng → xác nhận → nhận mâm → nấu cả mâm → nấu xong → xem nhật ký | Mỗi bước qua; kho trừ đúng; nhật ký có bữa hôm nay |
| TC-E2E-02 | Luồng chính trên Android và outbox | E2E | BR-COOK-02, NFR-REL-01.b, UC12, UC15, UC20, UC21 | Maestro trên emulator Android; chụp bằng ảnh giả của camera | Chạy luồng TC-E2E-01; bật chế độ máy bay trước khi bấm nấu xong rồi bật lại; hoàn tác | Outbox gửi lại nấu xong đúng một lần sau khi có mạng; hoàn tác được trong 10 phút |
| TC-E2E-03 | Khảo sát không cần tài khoản | E2E | UC23 | Playwright; form mở | Mở link khảo sát → đồng ý → chấm hết → chọn 5 món → hoàn tất | Màn cảm ơn; respondent completed |
| TC-E2E-04 | Cài đặt quyền riêng tư | E2E | UC05, UC06, UC07, UC10 | Playwright | Rút personalization; tải dữ liệu (chờ job); xoá tài khoản | Công tắc tắt; tệp tải về mở được; sau xoá không đăng nhập được |
| TC-E2E-05 | Nền tảng chạy app | E2E | RB-06, UC01, UC12, UC15 | Emulator Android API 24 và API 34; Chrome, Firefox, Safari, Edge bản ổn định mới nhất | Chạy luồng TC-E2E-01 trên từng nền tảng | Mọi bước qua trên cả 6 cấu hình |

### 5.21. Khả năng truy cập — nhóm `A11Y`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-A11Y-01 | WCAG 2.2 AA và vùng chạm | E2E | NFR-A11Y-01, UC09, UC15 | Playwright + axe-core; Maestro đo kích thước phần tử | Chạy axe trên mọi màn ở chế độ sáng và tối; đo mọi phần tử chạm được | 0 vi phạm mức A/AA; mọi vùng chạm ≥ 44 × 44 dp; nhãn độ tươi có chữ, không chỉ màu |
| TC-A11Y-02 | Không chỉ dùng màu, đọc được bằng TalkBack | E2E | NFR-A11Y-01.b, BR-FRESH-05, UC13, UC14, UC22 | Điện thoại Android thật bật TalkBack; chế độ sáng và tối | Đi qua mọi màn ở SRS §3.1.1 bằng TalkBack; đo tương phản chữ bằng công cụ đo | Mọi nhãn độ tươi, trạng thái, cột biểu đồ có chữ đi kèm; mọi điều khiển có nhãn đọc được; tương phản chữ ≥ 4,5:1 ở cả hai chế độ |

### 5.22. Hiệu năng và tải (k6/Locust) — nhóm `PERF`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-PERF-01 | Độ trễ xử lý quét ở server | Tải | NFR-PERF-01, UC12 | `--cpus=2 --memory=4g`, 1 worker, ảnh 1.280 px thật | k6 5 người dùng ảo đồng thời, ≥ 300 lần quét; lấy enqueued_at → finished_at | p95 ≤ 3 s thì đạt, > 3 s thì không đạt; báo kèm p50, p99, số mẫu; lần quét expired đếm riêng |
| TC-PERF-02 | Độ trễ tạo mâm | Tải | NFR-PERF-02, UC15 | Kho 200 món, 30 lô | Locust 10 người dùng đồng thời, 10 phút, ≥ 300 yêu cầu `POST /meal-plans` | p95 ≤ 1 s; 0 lỗi 5xx |
| TC-PERF-03 | Quét đầu–cuối trên điện thoại | Tải | NFR-PERF-03, UC12 | Điện thoại Android thật, Wi-Fi và 4G | 30 lần quét mỗi mạng; ghi mốc phía app | Đạt khi p95 ≤ 8 s trên Wi-Fi và ≤ 12 s trên 4G; báo kèm p50 theo mạng |
| TC-PERF-04 | Độ trễ endpoint đọc | Tải | NFR-PERF-02.b, UC14, UC15, UC22 | MT-chuẩn; 20 người dùng, mỗi người 30 lô và 30 mâm | k6 20 người dùng đồng thời, 10 phút, trộn `GET /pantry/lots`, `GET /meal-plans/latest`, `GET /journal`, `GET /me/profile` | p95 mỗi endpoint ≤ 300 ms; 0 lỗi 5xx |
| TC-PERF-05 | Thời gian lập lịch nấu | Tải | NFR-PERF-02.c, BR-COOK-01, UC19 | MT-chuẩn; mâm 3 món, tổng ≤ 30 bước; ≥ 100 mâm khác nhau từ kho món thật | Gọi `POST /cook-sessions` cho từng mâm; đo thời gian server | p95 ≤ 2 s; khi bộ giải chạm giới hạn thời gian vẫn trả lịch khả thi |
| TC-PERF-06 | Tài nguyên trong giới hạn 2 vCPU / 4 GB | Tải | NFR-PERF-01.b | Chạy cùng lúc với TC-PERF-01 và TC-PERF-02 | `docker stats` ghi mỗi giây cho mọi container | Bộ nhớ đỉnh tổng ≤ 3,5 GB; không container nào bị OOM hoặc khởi động lại |

### 5.23. Tương đương mô hình ONNX và PyTorch — nhóm `ONNX`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-ONNX-01 | ONNX khớp PyTorch trên ảnh vàng | Mô hình | UC12, UC29 | Bộ 50 ảnh vàng cố định sha256; trọng số PyTorch và tệp ONNX cùng phiên bản | Chạy cả hai với cùng tiền xử lý; ghép khung theo Hungarian | Bộ phát hiện: cùng tập lớp, IoU khung ghép ≥ 0,99, \|Δconf\| ≤ 0,01; độ tươi: \|ΔP\| ≤ 1e-3; chạy trong cổng UC29 |
| TC-ONNX-02 | Tiền xử lý lúc phục vụ giống lúc huấn luyện | Mô hình | UC12, UC29 | preprocess_version của mô hình | Băm tensor đầu vào từ đường huấn luyện và đường worker trên ảnh vàng | Hai băm trùng nhau |

### 5.24. Độ tin cậy: sao lưu, khôi phục, mạng chập chờn, quay lui — nhóm `REL`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-REL-01 | Diễn tập khôi phục | Vận hành (CLI/job) | NFR-REL-01, UC33 | Bản sao lưu mới nhất trên Drive | Dựng máy sạch, tải, giải mã, pg_restore, chạy migrate và smoke test | RPO ≤ 24 h (tuổi bản sao lưu), RTO ≤ 2 h; ghi biên bản diễn tập |
| TC-REL-02 | Không mất, không nhân đôi thao tác khi mạng chập chờn | E2E | NFR-REL-01.b, BR-COOK-02, BR-SCAN-02, UC12, UC20 | Maestro trên emulator; proxy tiêm lỗi mạng (ngắt ngẫu nhiên trước/sau khi server nhận) | 100 lần ngắt mạng ngẫu nhiên khi gửi quét, nấu xong, sự kiện; để outbox gửi lại | 0 bản ghi trùng (`scans`, giao dịch kho, `interactions`); 0 thao tác mất sau khi có mạng lại |
| TC-REL-03 | Quay lui mô hình dưới 5 phút | Vận hành (CLI/job) | NFR-REL-01.c, UC30 | MT-chuẩn; hai bản detector đã triển khai lần lượt | Chạy `tastoria mlops rollback detector`, bấm giờ tới khi `GET /readyz` trả 200 với bản trước | < 5 phút; scan mới ghi `detector_version_id` của bản trước |
| TC-REL-04 | Không lần quét nào kẹt vô hạn | Vận hành (CLI/job) | NFR-REL-01.d, FR-34-11, UC12, UC34 | Compose thật; dừng worker giữa job (docker kill) ở 20 lần quét | Để scheduler chạy sweeper mỗi phút, theo dõi trạng thái | Mọi lần quét rời `queued`/`processing` trong ≤ 6 phút kể từ `created_at` (về `done` sau khi chạy lại hoặc `expired`) |

### 5.25. Khả năng bảo trì — nhóm `MAINT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-MAINT-01 | Độ phủ và ranh giới module | Tĩnh/CI | NFR-MAINT-01 | CI | pytest --cov cho meal, pantry, profile, cooking; lint-imports | Độ phủ dòng ≥ 80% và độ phủ nhánh ≥ 80%, đo riêng từng module meal, pantry, profile, cooking; import-linter xanh; CI đỏ nếu không đạt |
| TC-MAINT-02 | Truy vết quy tắc và yêu cầu | Tĩnh/CI | NFR-MAINT-01.b | CI | Chạy `check_refs.py` và `gen_traceability.py --strict` | 0 mã lạ; mỗi BR có ≥ 1 TC; 0 ô trống trong ma trận |
| TC-MAINT-03 | Tái lập mô hình | Kiểm tra quy trình | NFR-MAINT-01.c, UC29 | Mọi bản trong `model_versions` | Đối chiếu từng bản với sổ MLflow | 100% bản có `mlflow_run_id`; mỗi run ghi commit, sha256 dữ liệu, seed, danh sách id test, phiên bản thư viện |
| TC-MAINT-04 | Quan sát được | Tích hợp API | NFR-MAINT-01.d | Compose; bắt log JSON | Gọi 20 endpoint bất kỳ, gồm một lỗi 500 giả lập; gọi `GET /healthz`, `GET /readyz` | Mọi yêu cầu có dòng log JSON mang `request_id` trùng header phản hồi; `healthz`, `readyz` phản hồi ≤ 1 s |

### 5.26. Chấp nhận người dùng — nhóm `UAT`

| Mã | Mục tiêu | Loại | Tham chiếu (FR/BR/UC/NFR) | Tiền điều kiện | Bước | Kết quả mong đợi |
|---|---|---|---|---|---|---|
| TC-UAT-01 | Thang SUS | UAT | NFR-USE-01, UC09, UC12, UC15, UC19 | 8–10 người thử thật, app bản phát hành thử | Làm 5 nhiệm vụ rồi điền bảng SUS 10 câu tiếng Việt | Điểm SUS trung bình ≥ 68, báo kèm khoảng tin cậy 95% |
| TC-UAT-02 | Tỷ lệ hoàn thành nhiệm vụ | UAT | NFR-USE-01, UC09, UC12, UC13, UC15, UC16, UC19, UC20 | Như TC-UAT-01 | Nhiệm vụ: lập hồ sơ; quét tủ và sửa chip; nhận mâm và đổi một món; nấu cả mâm; bấm nấu xong | ≥ 80% người hoàn thành mỗi nhiệm vụ không cần trợ giúp; ghi thời gian, lỗi, trích lời |
| TC-UAT-03 | Hồ sơ 60 giây | UAT | NFR-USE-01.b, UC09 | Như TC-UAT-01 | Người thử làm UC09 từ màn đồng ý tới Trang chủ; mốc thời gian phía app | Trung vị thời gian hoàn thành ≤ 60 s; báo kèm số người và phân vị 80 |

## 6. Rủi ro kiểm thử

| Mã | Rủi ro | Ảnh hưởng | Xử lý |
|---|---|---|---|
| R-01 | Thiếu dữ liệu người thật (ảnh vàng, người thử UAT 8–10 người, kho món đủ 150 món) | TC-ONNX-01, TC-PERF-01, TC-UAT-01, TC-UAT-02, TC-PROP-01 trên kho thật không chạy được hoặc chạy trên mẫu nhỏ | Ca cơ chế chạy trên dữ liệu tổng hợp; báo cáo ghi rõ số mẫu thực có; không sinh giả kết quả |
| R-02 | Kiểm thử tính chất chậm (CP-SAT, toàn kho món) | CI quá 15 phút, người làm tắt ca | Profile `ci` 200 ví dụ với giới hạn thời gian CP-SAT; profile `nightly` 2.000 ví dụ; phần vét cạn món × nhóm dị ứng luôn chạy đủ |
| R-03 | Ca phụ thuộc thời gian thực dễ chập chờn (long-poll, khoá 15 phút, cửa sổ hoàn tác, TTL 48 giờ) | Ca đỏ ngẫu nhiên, mất tin cậy | freezegun và đồng hồ tiêm vào service; chỉ TC-SCAN-05 dùng thời gian thật với dung sai ± 0,5 s |
| R-04 | Mô hình thật chưa có khi chạy E2E và tải | Độ trễ đo không đại diện | Dùng bản ONNX tiền huấn luyện trên dữ liệu công khai cùng kiến trúc; đo lại khi có bản `validated` |
| R-05 | Máy staging dùng chung GPU và CPU với job khác | Số đo tải lệch | Giới hạn `--cpus=2 --memory=4g`, chạy ngoài giờ huấn luyện, ghi tải nền của máy cùng kết quả |
| R-06 | Đặc tả OpenAPI và mã trôi nhau | Schemathesis xanh trên đặc tả cũ | TC-CONT-02 so đặc tả sinh từ mã với tệp trong repo ở mỗi PR |
| R-07 | Ngưỡng nhãn độ tươi và hệ số h (BR-NUT-06) chưa khoá | Giá trị mong đợi ở ca biên đổi | Ca đọc ngưỡng từ cấu hình; khi khoá ngưỡng thì cập nhật fixture và ghi phiên bản tham số |
| R-08 | Emulator khác thiết bị thật (camera, secure-store, mạng) | Lỗi chỉ có trên máy thật lọt qua | TC-PERF-03 và UAT chạy trên điện thoại thật; một vòng Maestro trên máy thật trước phát hành |
| R-09 | Dịch vụ ngoài (Drive, Label Studio, SMTP) không ổn định | Ca vận hành đỏ vì môi trường | CI dùng remote cục bộ, Mailpit, Label Studio trong compose; chỉ diễn tập TC-REL-01 dùng Drive thật |
| R-10 | Kiểm thử chạm dữ liệu cá nhân thật | Vi phạm chính BR mà hệ thống phải giữ | Cấm bản sao production trong kiểm thử; ảnh vàng chỉ từ người đã đồng ý góp ảnh; UAT dùng tài khoản thử |
