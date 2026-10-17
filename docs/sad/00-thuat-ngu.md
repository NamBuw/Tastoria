# Thuật ngữ và chữ viết tắt — Tastoria

Tài liệu này là mục 1.3 của [SRS](01-SRS.md). Mọi tài liệu phân tích thiết kế dùng thuật ngữ theo đúng nghĩa ở đây. Định danh kỹ thuật (bảng, cột, endpoint, enum) giữ nguyên tiếng Anh như trong `docs/sad/model.yaml`. Tham số in đậm trong cột "Định nghĩa" là giá trị mặc định nằm trong bảng cấu hình, đổi được (thiết kế v2 §4).

## 1. Thuật ngữ nghiệp vụ

| Thuật ngữ | Định nghĩa | Định danh / quy tắc liên quan |
|---|---|---|
| Mâm, mâm cơm | Một bữa ăn đề xuất cho một bữa (trưa hoặc tối) gồm cơm và 2 hoặc 3 món ở các slot khác nhau. Mỗi lần hệ thống chỉ đề xuất một mâm; muốn khác thì đổi từng món. | `meal_plans`; BR-TRAY-01 |
| Món | Một công thức nấu trong kho món, thuộc đúng một slot, có nguyên liệu tính bằng gam lúc mua cho `servings` khẩu phần và các bước nấu. Món đã `published` là bất biến. | `recipes`, `recipe_ingredients`, `recipe_steps`; BR-CATALOG-01 |
| Slot | Vị trí của món trong mâm: `man` (món mặn), `rau` (món rau), `canh` (món canh). Mâm 1 người có 2 slot (mặn + rau hoặc canh); mâm từ 2 người có đủ 3 slot. | `recipes.slot`, `meal_plan_items.slot`; BR-TRAY-01 |
| Cơm (biến liên tục) | Cơm không phải một món mà là lượng bù năng lượng: số bát/người = clip((E_mâm − E_món/người) / E_bát, **0,5**, **3**), làm tròn 0,5 bát; E_bát tính cho **150 g** cơm. | `meal_plans.rice_bowls_per_person`; BR-TRAY-03 |
| Người ăn cùng | Người ăn chung bữa với người dùng nhưng không có tài khoản. Hệ thống không lưu danh tính của họ; người dùng khai nhóm dị ứng của họ cho từng bữa. Không phải actor của hệ thống. | `meal_plan_coeater_allergens`; BR-ALG-01 |
| Ghim lô ("phải dùng") | Người dùng chọn tối đa **2** lô mà mâm phải dùng ít nhất **50%** lượng g_min. | `meal_plan_pins`; BR-TRAY-08 |
| Đổi món | Thay món ở một slot bằng cách giải lại bài toán ghép mâm với các slot còn lại cố định, loại các món đã bị đổi ra trong mâm này; kèm một lý do. | `meal_plan_items.status = swapped_out`, `swap_reason`; BR-SWAP-01 |
| Thay thế nguyên liệu ("Thiếu gì?") | Gợi ý nguyên liệu khác cùng nhóm thực phẩm để bù nguyên liệu thiếu của một món, đã qua lọc cứng dị ứng/chế độ ăn. | `substitution_pairs`, `meal_plan_item_substitutions` |
| Danh sách đi chợ | Danh sách nguyên liệu người dùng cần mua, thêm từ "Thiếu gì?" hoặc khi không có mâm khả thi. | `shopping_items`; BR-TRAY-06 |
| Quét toàn tủ (`fridge`) | Chế độ quét chụp toàn bộ tủ lạnh; lô không thấy trong lần quét chuyển `not_seen` và hỏi người dùng. | `scans.mode`; BR-PANTRY-03 |
| Quét đồ vừa mua (`haul`) | Chế độ quét túi đồ vừa mua: chỉ thêm lô mới, ngày mua = hôm nay. | `scans.mode`; BR-PANTRY-03 |
| Ngăn (`shelf_group`) | Nhóm ảnh chụp cùng một ngăn. Cùng ngăn thì số đếm của lớp lấy max giữa các ảnh; khác ngăn thì cộng. | `scan_images.shelf_group`; BR-SCAN-01 |
| Chip | Một dòng kết quả quét hiển thị cho người dùng: một nguyên liệu, số đếm hoặc mức lượng, gợi ý độ tươi. Người dùng giữ, đổi nhãn, sửa hoặc xoá chip; sửa chip không ghi kho. | `scan_items`; BR-SCAN-02 |
| Xác nhận quét | Thao tác duy nhất ghi kết quả quét vào kho, lũy đẳng, chỉ hợp lệ từ trạng thái `done`. | `POST /scans/{id}/confirm`; BR-SCAN-02 |
| Kho | Tập các lô nguyên liệu của một người dùng. Lượng hiện tại không lưu mà tính từ giao dịch. | `pantry_lots`, `pantry_transactions`, `v_pantry_lot_balance` |
| Lô | Một lần nhập một nguyên liệu vào kho, có lượng ban đầu dạng khoảng, ngày mua (`acquired_at`) và trạng thái riêng. Thêm đồ lần nữa tạo lô mới, không cộng dồn vào lô cũ. | `pantry_lots`; BR-PANTRY-01 |
| Giao dịch kho | Một thay đổi lượng của một lô (thêm từ quét, trừ khi nấu, sửa tay, bỏ đi, hoàn tác). Chỉ ghi thêm, không sửa, không xoá. | `pantry_transactions`; BR-PANTRY-02 |
| Lượng dạng khoảng [g_min, g_max] | Lượng nguyên liệu tính bằng gam khối lượng lúc mua, lưu dạng khoảng vì quy đổi từ số đếm hoặc mức ít/vừa/nhiều không chính xác. Kiểm khả thi dùng cận dưới g_min. | BR-QTY-01, BR-TRAY-04 |
| Gam lúc mua | Khối lượng nguyên liệu như khi mua, chưa trừ phần thải bỏ. Phần ăn được tính qua EP. | BR-QTY-01, BR-NUT-05 |
| Mức ít / vừa / nhiều | Ba mức lượng ước cho đồ không đếm được; quy đổi sang khoảng gam theo nhóm thực phẩm. | `qty_levels`; BR-QTY-02 |
| Đồ đếm được | Nguyên liệu tính theo cái/quả/bó…; quy đổi sang gam qua bảng đơn vị (ví dụ 1 quả trứng gà = **50 g**) và làm tròn lên khi tính lượng cần. | `ingredient_units`; BR-QTY-02, BR-TRAY-02 |
| Gia vị luôn có (`is_staple`) | Nguyên liệu coi như luôn có trong bếp (muối, nước mắm…), được miễn kiểm kho nhưng **không** miễn kiểm dị ứng. | `ingredients.is_staple`; BR-ALG-01, BR-TRAY-04 |
| Lượng khả dụng | Tổng cận dưới lượng của các lô `in_stock` có độ gấp ≤ "dùng ngay"; lô ở mức "kiểm tra trước khi dùng" không được tính. | BR-TRAY-04, BR-FRESH-04 |
| Độ gấp u | Chỉ số cho biết lô cần dùng gấp tới đâu, tính lúc đọc, không lưu. u_time = d / L (d = số ngày từ `acquired_at`, L = thời hạn ngăn mát); u_img = Σ_c P(c)·m(c); cách kết hợp hai giá trị theo BR-FRESH-03. | BR-FRESH-01..05 |
| u_time | Thành phần thời gian của độ gấp: d / L. | BR-FRESH-01 |
| u_img | Thành phần ảnh của độ gấp: kỳ vọng của trọng số m(c) theo xác suất đã hiệu chỉnh của bộ phân loại độ tươi, với m(tươi) = **0,25**, m(dùng sớm) = **0,65**, m(dùng ngay) = **0,9**, m(kiểm tra) = **1,2**. | `pantry_lots.p_*`, `detections.p_*`; BR-FRESH-02 |
| Nhãn độ tươi | Bốn mức hiển thị suy từ u: tươi (u < **0,5**), nên dùng sớm ([0,5; 0,8)), dùng ngay ([0,8; 1,0]), kiểm tra trước khi dùng. Luôn có chữ kèm chấm màu; là gợi ý chất lượng, không kết luận an toàn thực phẩm. | BR-FRESH-04, BR-FRESH-05 |
| Mức "kiểm tra trước khi dùng" | Mức thứ tư của nhãn độ tươi: u > 1,0 hoặc lớp "kiểm tra" có xác suất lớn nhất. Lô ở mức này không tính vào lượng khả dụng, không được thưởng trong hàm mục tiêu, chip buộc người dùng xác nhận. Người dùng xác nhận vẫn dùng được thì ghi `user_checked_at`. | `pantry_lots.user_checked_at`; BR-FRESH-04 |
| Đồ gấp | Lô có u ∈ [0,5; 1,0]; được thưởng trong hàm mục tiêu ghép mâm qua U(m). | §6.2 thiết kế v2 |
| Lô `not_seen` | Lô không xuất hiện trong lần quét toàn tủ gần nhất; hệ thống hỏi người dùng thay vì tự xoá. | `pantry_lots.status`; BR-PANTRY-03 |
| BMR | Năng lượng chuyển hoá cơ bản (kcal/ngày), mặc định theo phương trình FAO/WHO/UNU 1985 theo cân nặng. | BR-NUT-01 |
| PAL | Hệ số mức hoạt động thể lực: nhẹ **1,50**, trung bình **1,75**, nặng **2,00**. | BR-NUT-02 |
| TEE | Tổng năng lượng tiêu hao/ngày = BMR × PAL. | BR-NUT-02 |
| E (mục tiêu năng lượng ngày) | Năng lượng mục tiêu/ngày: TEE (giữ cân), TEE − **500** không dưới **1.200** nữ / **1.500** nam (giảm cân), hoặc giá trị chuyên gia đặt (ghi đè mọi công thức). | `profiles.kcal_target`, `kcal_source`; BR-NUT-03 |
| E_mâm | Năng lượng mục tiêu cho một bữa của một người: E × s, s = **0,35** bữa trưa, **0,30** bữa tối. `meal_plans.e_target_kcal` lưu giá trị theo một người này; mục tiêu nhóm = E_mâm × n (xấp xỉ) chỉ tính lúc hiển thị. | `meal_plans.e_target_kcal`; BR-NUT-04, BR-TRAY-07 |
| "Chưa rõ hạn" (u không xác định) | Lô không có thời hạn ngăn mát (L NULL) và không có ảnh độ tươi nên không tính được u. Lô vẫn khả dụng, không được thưởng trong hàm mục tiêu. | BR-FRESH-02, FR-14-05, FR-15-16 |
| Hết hiệu lực mâm | Mâm `proposed` chuyển `expired`, mâm `accepted` chưa nấu chuyển `abandoned` khi người dùng tạo mâm mới cho cùng bữa hoặc khi qua giờ kết thúc bữa. | FR-15-37, FR-15-38, FR-15-39, FR-15-41; ST02 |
| EP (phần ăn được) | Tỷ lệ phần ăn được của nguyên liệu = 100 − tỷ lệ thải bỏ, lấy từ bảng thành phần thực phẩm. | `food_items.refuse_pct`; BR-NUT-05 |
| RF (hệ số giữ lại) | Hệ số giữ lại dinh dưỡng sau chế biến; v2 dùng RF = 1 cho năng lượng và chất sinh năng lượng. | BR-NUT-05 |
| Khoảng calo | Calo món/mâm hiển thị dạng khoảng; nửa độ rộng = phân vị 80 của sai số tương đối khi so ≥ 30 món với Viện Dinh dưỡng. Chưa đo xong thì hiện "đang hiệu chỉnh". | `meal_plans.kcal_low`, `kcal_high`; BR-NUT-06 |
| Lịch nấu | Thứ tự và thời điểm bắt đầu các bước nấu của cả mâm, giải bằng CP-SAT với ràng buộc một người nấu, số họng bếp và thứ tự bước. | `cook_schedule_entries`; BR-COOK-01 |
| Bước chủ động / thụ động | Bước chủ động cần người nấu thao tác (thái, xào); bước thụ động chạy tự (ninh, hầm). Một người nấu không làm hai bước chủ động cùng lúc. | `recipe_steps.kind`; BR-COOK-01 |
| Họng bếp | Số bước chiếm bếp được chạy đồng thời, mặc định **2**, người dùng đặt 1–4. | `user_settings.burners`; BR-COOK-01 |
| Makespan | Thời gian từ lúc bắt đầu bước đầu tiên tới lúc xong bước cuối cùng của lịch nấu. Mâm hợp lệ có makespan ≤ thời gian tối đa người dùng chọn. | `meal_plans.max_minutes`; BR-TRAY-05 |
| Phiên nấu | Một lần người dùng nấu một mâm theo lịch nấu, từ lúc bắt đầu tới nấu xong, hoàn tác hoặc bỏ. | `cook_sessions` |
| Nấu xong một chạm | Thao tác kết thúc phiên nấu: trừ kho theo lô gấp nhất trước, ghi tương tác, chuyển trạng thái trong một giao dịch. | `POST /cook-sessions/{id}/complete`; BR-COOK-02 |
| Hoàn tác trừ kho | Đảo các giao dịch trừ kho của một phiên nấu trong **10 phút** bằng giao dịch đảo trỏ `reverses_id`. | BR-PANTRY-02 |
| Nhật ký tuần | Tổng hợp theo ngày địa phương: số mâm đã nấu, kcal/người, mục tiêu ảnh chụp, số lô gấp được dùng kịp. Chỉ đọc. | `v_journal_days` |
| 5 món hay ăn | Tối đa 5 món người dùng (hoặc người khảo sát) chọn là món hay ăn; dùng khởi động lạnh cho xếp hạng gu. | `user_favorite_recipes`, `survey_favorites` |
| Khảo sát gu (khối không đầy đủ) | Mỗi người tham gia chấm một tập con món: các món neo chung (mặc định 10) cộng các món ngẫu nhiên phân tầng (mặc định 35), điểm 1–5 hoặc "chưa ăn bao giờ". | `survey_forms`, `survey_assignments`, `survey_ratings` |
| Món neo | Món mọi người tham gia khảo sát của cùng một phiếu đều chấm, để nối thang điểm giữa người. | `survey_form_anchors` |
| Tương tác | Sự kiện hành vi của người dùng với món (served, viewed, swapped, cooked, liked, disliked, undone), chỉ ghi khi có đồng ý `personalization`. | `interactions`; BR-CONSENT-03 |
| Dòng lý do | Một câu giải thích vì sao hệ thống chọn mâm này, lấy từ thành phần đóng góp chuẩn hoá lớn nhất so với mâm tốt nhì. | `meal_plans.reason_vi` |
| Kho món (catalog) | Tập món, nguyên liệu, nhóm thực phẩm, dinh dưỡng và dữ liệu tham chiếu do người biên soạn nhập qua CLI. | module `catalog` |
| Bundle | Thư mục YAML/CSV món, nguyên liệu mà người biên soạn nhập bằng `tastoria catalog import <bundle_dir>`. | UC25 |

## 2. Thuật ngữ quyền riêng tư và pháp lý

| Thuật ngữ | Định nghĩa | Định danh / quy tắc liên quan |
|---|---|---|
| Đồng ý theo mục đích | Mỗi mục đích xử lý dữ liệu có một đồng ý riêng, không tích sẵn, gắn với phiên bản điều khoản; im lặng không được coi là đồng ý. Bốn mục đích: `health_profile`, `personalization`, `photo_contribution`, `survey`. | `consent_purposes`, `policy_versions`; BR-CONSENT-01 |
| Nhật ký đồng ý chỉ ghi thêm | Mỗi lần cấp hoặc rút đồng ý ghi một sự kiện mới; trạng thái hiện tại là sự kiện mới nhất của mỗi mục đích. | `consent_events`, `v_current_consents` |
| Rút đồng ý | Thao tác có hiệu lực ngay (tăng `users.token_version`) và kéo theo xoá dữ liệu của mục đích đó trong ≤ 24 giờ. | BR-CONSENT-04 |
| Dữ liệu cá nhân nhạy cảm | Dữ liệu thuộc danh mục nhạy cảm theo Luật 91/2025/QH15 và NĐ 356/2025; ở Tastoria gồm chỉ số cơ thể (sức khoẻ) và lịch sử tương tác dùng cá nhân hoá. | BR-CONSENT-01 |
| Chủ thể dữ liệu | Người mà dữ liệu cá nhân nói về; ở Tastoria là A02 và A03. | — |
| Yêu cầu của chủ thể dữ liệu (DSR) | Yêu cầu truy cập, tải về, sửa, xoá, rút đồng ý, hạn chế hoặc phản đối xử lý; hệ thống tự hoàn tất ≤ 24 giờ. | `dsr_requests`; BR-DSR-01 |
| `subject_ref` | HMAC-SHA256 của `user_id`, giữ trong `dsr_requests` làm bằng chứng đã xử lý yêu cầu sau khi tài khoản bị xoá. | `dsr_requests.subject_ref` |
| Bí danh hoá | Thay định danh trực tiếp (`user_id`) bằng giá trị HMAC-SHA256 với khoá giữ riêng, làm thô thông tin gần định danh. Dữ liệu bí danh hoá **vẫn là dữ liệu cá nhân** vì bên giữ khoá có thể nối lại; khác với khử nhận dạng (Luật 91/2025 Điều 2 khoản 11). | UC28 |
| Mã hoá cột sức khoẻ | Các cột `*_enc` trong `profiles` mã hoá AES-GCM ở tầng ứng dụng, có `enc_key_id`; chỉ module `profile` giải mã, mỗi lần giải mã ghi `audit_log`. | ADR 0005 |
| Nhật ký kiểm toán | Bảng chỉ ghi thêm ghi mỗi lần giải mã cột sức khoẻ và mỗi thao tác nhân sự. | `audit_log` |
| Thời hạn lưu giữ | Ảnh quét gốc xoá sau **30 ngày** trừ khi đã đồng ý góp ảnh; bản sao lưu giữ ≤ **14 ngày**. | BR-RETAIN-01 |
| Góp ảnh | Người dùng đồng ý `photo_contribution` để ảnh quét được giữ lại phục vụ gán nhãn và huấn luyện. | `scan_images.contributed` |

## 3. Thuật ngữ kỹ thuật

| Thuật ngữ | Định nghĩa | Định danh / quy tắc liên quan |
|---|---|---|
| Lũy đẳng (idempotent) | Gửi lại cùng một yêu cầu nhiều lần cho cùng kết quả như gửi một lần. Tastoria dùng header `Idempotency-Key` (giữ 48 giờ, so `request_sha256`) cho POST quét, mâm, đổi món, phiên nấu, nấu xong; dùng `event_id` do app sinh cho `POST /events`. | `idempotency_keys`; ADR 0007 |
| Unit of Work | Mẫu gom mọi thay đổi của một thao tác nghiệp vụ nhiều module (nấu xong, xác nhận quét) vào một giao dịch CSDL: hoặc tất cả được ghi, hoặc không gì được ghi. | module `core`; ADR 0007 |
| Modular monolith | Một ứng dụng triển khai đơn khối, chia module có ranh giới rõ; module khác chỉ gọi qua `service.py`, phụ thuộc cho phép khai trong `model.yaml`, cưỡng chế bằng `import-linter`. | M01–M16; ADR 0001 |
| Job quét | Việc suy luận ảnh chạy bất đồng bộ trong worker (Valkey + RQ); trạng thái `queued` → `processing` → `done`, `failed` hoặc `expired`; timeout 30 giây, thử lại tối đa 2 lần. | `scans.status` |
| Long-poll | App gọi `GET /scans/{id}?wait=10`; server giữ kết nối tới khi trạng thái đổi hoặc hết 10 giây. | UC12 |
| Sweeper | Tác vụ định kỳ mỗi phút dọn job quét kẹt, token và khoá lũy đẳng hết hạn. | UC34 |
| BOLA | Broken Object Level Authorization: truy cập đối tượng của người khác bằng cách đổi `{id}`. Mọi truy vấn theo `{id}` lọc theo chủ sở hữu và trả 404 khi không thuộc người gọi. | §8 thiết kế v2 |
| Access token / refresh token | Access token là JWT sống 15 phút có `kid`; refresh token là chuỗi ngẫu nhiên sống 30 ngày, lưu dạng băm, xoay vòng theo family; dùng lại token đã thu hồi thì thu hồi cả family. | `refresh_tokens`; ADR 0004 |
| `token_version` | Số phiên bản phiên của tài khoản; tăng lên thì mọi access token cũ mất hiệu lực (đăng xuất mọi thiết bị, rút đồng ý). | `users.token_version` |
| RFC 9457 (problem details) | Định dạng lỗi `application/problem+json` có trường `code` ổn định mà app dựa vào để xử lý. | module `core` |
| Phân trang keyset | Phân trang theo cặp (`created_at`, `id`) thay cho offset. | §8 thiết kế v2 |
| `X-Accel-Redirect` | Cơ chế API kiểm quyền rồi giao việc trả tệp cho location internal của nginx. | ADR 0002 |
| Outbox (phía app) | Hàng đợi trong app giữ yêu cầu nấu xong, sự kiện, sửa chip khi mất mạng và gửi lại với cùng khoá lũy đẳng. | §9 thiết kế v2 |
| Phiên bản mô hình | Một bản mô hình đã đăng ký (detector, freshness, ranker, substitution) có sha256, bản đồ lớp, chỉ số và trạng thái. | `model_versions` |
| Con trỏ triển khai | Dòng duy nhất cho mỗi loại mô hình trỏ tới bản đang chạy và bản trước; triển khai và quay lui = đổi con trỏ. | `model_deployments` |
| Cổng kiểm định (gate) | Bước so chỉ số của bản ứng viên với ngưỡng và với bản đang chạy trước khi cho phép triển khai. | `tastoria mlops gate <name> <version>`; UC29 |
| Lớp thị giác | Một lớp mà bộ phát hiện nhận ra (~20 lớp), ánh xạ nhiều–nhiều tới nguyên liệu, có định nghĩa "một thể hiện" (quả, bó/túi, gói). | `vision_classes`, `vision_class_ingredients` |
| Hiệu chỉnh nhiệt độ | Kỹ thuật chia logit cho một hằng số học trên tập validation để xác suất đầu ra của bộ phân loại độ tươi sát tần suất thật. | BR-FRESH-02 |
| ONNX | Định dạng mô hình trung lập; worker suy luận bằng `onnxruntime`, không cài `ultralytics` trong image phục vụ. | ADR 0011 |
| CP-SAT | Bộ giải ràng buộc của OR-Tools dùng lập lịch nấu. | ADR 0009 |
| MoSCoW | Mức ưu tiên yêu cầu: M (Must, bắt buộc), S (Should, nên có), C (Could, có thì tốt), W (Won't, không làm ở bản này). | SRS §3.2 |
| Given/When/Then | Mẫu tiêu chí chấp nhận: điều kiện ban đầu, hành động, kết quả quan sát được. | SRS §3.2, §3.3 |
| Mức mục tiêu (Cockburn) | Mục tiêu người dùng: việc tác nhân làm xong trong một lần, có giá trị tự thân. Mục tiêu con (subfunction): UC chỉ chạy bên trong luồng của UC khác, và đăng nhập. | SRS §2.2 |
| Điều khoản con NFR | Yêu cầu phi chức năng bổ sung viết dưới một mã NFR có trong `model.yaml`, dạng `NFR-<ĐẶC TÍNH>-<số>.<chữ>`; là yêu cầu bắt buộc như điều khoản gốc. | SRS §3.4 |
| TBD | Điểm chưa chốt của yêu cầu, có mã `TBD-nn`, người quyết và hạn. | SRS Phụ lục C |
| RPO / RTO | Recovery Point Objective: lượng dữ liệu tối đa được phép mất khi khôi phục; Recovery Time Objective: thời gian tối đa để hệ thống chạy lại. | NFR-REL-01 |
| p50 / p95 | Phân vị 50 / 95 của phân phối độ trễ đo được. | NFR-PERF-01..03 |
| SUS | System Usability Scale: bảng 10 câu cho điểm khả dụng 0–100. | NFR-USE-01 |
| WCAG 2.2 AA | Bộ tiêu chí truy cập nội dung web của W3C, phiên bản 2.2, mức AA. | NFR-A11Y-01 |

## 4. Chữ viết tắt

| Viết tắt | Đầy đủ |
|---|---|
| ADR | Architecture Decision Record — bản ghi quyết định kiến trúc (`docs/adr/`) |
| API | Application Programming Interface |
| BCE | Boundary–Control–Entity (lớp phân tích) |
| BCNF | Boyce–Codd Normal Form |
| BR | Business Rule — quy tắc nghiệp vụ |
| CLI | Command-Line Interface |
| CSDL | Cơ sở dữ liệu |
| DSR | Data Subject Request — yêu cầu của chủ thể dữ liệu |
| ERD | Entity–Relationship Diagram |
| FR | Functional Requirement — yêu cầu chức năng (mã `FR-<UC>-<số>`) |
| NĐ | Nghị định |
| NFR | Non-Functional Requirement — yêu cầu phi chức năng |
| PDPL | Luật Bảo vệ dữ liệu cá nhân, Luật số 91/2025/QH15 |
| SRS | Software Requirements Specification — đặc tả yêu cầu phần mềm |
| TC | Test Case — ca kiểm thử (mã `TC-<nhóm>-<số>`) |
| UC | Use Case |
| UoW | Unit of Work |
