# Hướng dẫn dựng dự án Visual Paradigm cho Tastoria

Tài liệu này hướng dẫn dựng tệp `Tastoria.vpp` trên máy Windows hoặc macOS từ bộ nhập `tastoria-vp-kit.zip`. Cách làm theo ADR 0013 (`docs/adr/0013-giao-so-do-visual-paradigm-plantuml-vp.md`): sơ đồ UML nhập bằng plugin PlantUML-VP, ERD vật lý dựng bằng Reverse DDL từ `db/schema_vp.sql`.

Thời gian dự kiến: 2–4 giờ, phần lớn là chỉnh bố cục sau khi nhập.

## 1. Nội dung bộ nhập

Giải nén `tastoria-vp-kit.zip` ra một thư mục không có dấu cách và không có dấu tiếng Việt trong đường dẫn, ví dụ `C:\tastoria-vp-kit` hoặc `~/tastoria-vp-kit`.

| Thư mục / tệp | Nội dung | Số tệp |
|---|---|---|
| `HUONG-DAN.md` | Tài liệu này | 1 |
| `docs/uml/usecase/` | UCD00 tổng quan và UCD01–UCD10 theo gói PK1–PK10 | 11 |
| `docs/uml/activity/` | AD01–AD06 (có làn, cú pháp mới) | 6 |
| `docs/uml/sequence/` | SD01–SD10 | 10 |
| `docs/uml/state/` | ST01–ST08 | 8 |
| `docs/uml/class/` | CL01 (miền), CL02–CL04 (BCE), CL05–CL08 (thiết kế) | 8 |
| `docs/uml/component/` | CP01 | 1 |
| `docs/uml/package/` | PG01 | 1 |
| `docs/uml/deployment/` | DP01 | 1 |
| `docs/uml/context/` | CTX01 (sơ đồ ngữ cảnh) | 1 |
| `docs/erd/` | ERD00 (Chen), ERD01–ERD07 (chân quạ theo nhóm module), ERD08 (tổng quan 62 bảng) | 9 |
| `db/schema_vp.sql` | DDL PostgreSQL đã giản lược cho parser của VP (62 bảng) | 1 |
| `docs/uml/out/<loai>/` | Ảnh SVG và PNG render sẵn của mọi sơ đồ trên, không watermark | 56 + 56 |

Ảnh trong `docs/uml/out/` là bản đối chiếu: sau khi nhập vào VP, so từng sơ đồ với ảnh tương ứng để biết có mất phần tử nào không. Nếu plugin không chạy, đây là bản để vẽ lại tay.

## 2. Cài Visual Paradigm Community Edition 18.1

1. Tải VP Community Edition 18.1 ở https://www.visual-paradigm.com/download/community.jsp. Chọn bản Windows 64-bit (`.exe`) hoặc macOS (`.dmg`, chọn đúng Apple Silicon hay Intel nếu trang có tách).
2. Cài đặt:
   - Windows: chạy tệp `.exe`, để thư mục cài mặc định (thường là `C:\Program Files\Visual Paradigm CE 18.1`).
   - macOS: mở `.dmg`, kéo Visual Paradigm vào Applications. Lần mở đầu nếu macOS chặn thì vào System Settings > Privacy & Security, bấm "Open Anyway".
3. Mở VP. Ở hộp thoại chọn edition, chọn **Community Edition**, điền họ tên và email, bấm gửi yêu cầu kích hoạt. VP gửi mã kích hoạt qua email; dán mã vào hộp thoại để kích hoạt. CE miễn phí cho mục đích phi thương mại (học tập).
4. Tạo dự án mới: Project > New, đặt tên `Tastoria`, lưu thành `Tastoria.vpp`. Sao một bản dự phòng `Tastoria-trong.vpp` ngay lúc này để quay lại nếu bước nhập làm hỏng dự án.

Nếu cần Reverse DDL (mục 5) mà chưa có giấy phép Standard, có thể chọn bản dùng thử 30 ngày thay cho CE ở bước 3. Xem mục 5 trước khi quyết định.

## 3. Cài plugin PlantUML-VP

Plugin: https://github.com/nbourdi/PlantUML-VP-Plugin (giấy phép MIT), bản phát hành v1.0.0. Plugin chạy được ở mọi edition, kể cả CE.

1. Mở trang Releases của repo, tải tệp `.zip` của bản v1.0.0. Không giải nén.
2. Trong VP: **Help > Install Plugin**.
3. Chọn cài từ tệp zip của plugin, bấm **Next**, trỏ tới tệp `.zip` vừa tải.
4. Khởi động lại VP.
5. Cách thay thế nếu bước 2–3 báo lỗi: giải nén zip, chép thư mục plugin vào thư mục `plugins` mà hộp thoại Install Plugin hiển thị, rồi khởi động lại VP.

Sau khi khởi động lại, plugin thêm mục lệnh PlantUML (nhập/xuất) vào giao diện VP. README của plugin không ghi đường dẫn menu cụ thể; tìm mục có chữ "PlantUML" trên thanh công cụ hoặc trong tab Plugins/Tools.

**Cách nhập bằng dòng lệnh** (dùng khi không tìm thấy mục menu, hoặc để nhập cả thư mục một lần). Đóng VP trước khi chạy.

1. Chép `Plugin.bat` (Windows) hoặc `Plugin.sh` (macOS) từ `<thư mục cài VP>/scripts` sang `<thư mục cài VP>/bin`.
2. Chạy trong `<thư mục cài VP>/bin`, ví dụ trên Windows:

   ```
   Plugin.bat -project "C:/tastoria-vp-kit/Tastoria.vpp" -pluginid "plugins.plantUML" -pluginargs -action "import" -path "C:/tastoria-vp-kit/docs/uml/state"
   ```

   Trên macOS thay `Plugin.bat` bằng `./Plugin.sh` và dùng đường dẫn kiểu `/Users/<ten>/tastoria-vp-kit/...`.

## 4. Nhập sơ đồ UML

Làm theo đúng thứ tự dưới đây. Lưu dự án (Ctrl+S / Cmd+S) sau mỗi bước.

### 4.1. Thử một tệp nhỏ trước

Nhập `docs/uml/state/ST03-cook-session.puml` (máy trạng thái 4 trạng thái). Kiểm:

- VP tạo một sơ đồ State Machine mới, tên lấy từ `title`.
- Đủ 4 trạng thái `in_progress`, `completed`, `reverted`, `abandoned` và các chuyển trạng thái có nhãn, so với `docs/uml/out/state/ST03-cook-session.png`.

Nếu bước này lỗi hoặc ra sơ đồ rỗng, dừng lại: plugin không chạy được trên bản VP này. Chuyển sang mục 4.4.

### 4.2. Nhập theo thư mục

Nhập lần lượt từng thư mục, kiểm từng thư mục xong mới sang thư mục sau:

1. `docs/uml/state/` (8 tệp)
2. `docs/uml/usecase/` (11 tệp)
3. `docs/uml/activity/` (6 tệp)
4. `docs/uml/sequence/` (10 tệp)
5. `docs/uml/class/` (8 tệp)
6. `docs/uml/component/`, `docs/uml/package/`, `docs/uml/deployment/` (mỗi thư mục 1 tệp)
7. `docs/uml/context/CTX01-ngu-canh.puml`: sơ đồ ngữ cảnh viết bằng ký pháp use case/thành phần; nếu plugin không nhận thì vẽ lại tay theo ảnh hoặc chỉ dùng ảnh SVG trong báo cáo.

Không nhập `docs/erd/*.puml` bằng plugin: plugin không hỗ trợ ERD. Các tệp này chỉ để render ảnh cho báo cáo; ERD trong VP dựng ở mục 5.

Gom sơ đồ vào model theo loại (chuột phải trong Model Explorer > New Model): `01 Use case`, `02 Hoat dong`, `03 Tuan tu`, `04 Trang thai`, `05 Lop`, `06 Thanh phan - Goi - Trien khai`, `07 ERD`.

### 4.3. Chỉnh bố cục

Plugin đặt phần tử theo bố cục tự động của VP nên thường chồng nhau.

1. Mở từng sơ đồ, dùng Diagram > Layout (hoặc chuột phải nền sơ đồ > Layout) và thử bố cục Hierarchic hoặc Orthogonal.
2. Kéo tay cho giống ảnh SVG/PNG tương ứng: actor ở bên trái, use case trong khung hệ thống; làn của sơ đồ hoạt động theo thứ tự như ảnh.
3. Kiểm từng sơ đồ với ảnh render: số phần tử, nhãn quan hệ `<<include>>`/`<<extend>>`, bội số ở sơ đồ lớp, điều kiện gác ở sơ đồ hoạt động và trạng thái. Phần tử nào mất thì thêm tay.
4. Không đổi tên phần tử. Mọi mã (A01–A10, UC01–UC34, M01–M16, tên bảng, endpoint) phải giữ đúng như trong `docs/sad/model.yaml`.

### 4.4. Khi plugin không chạy

Vẽ lại tay trong CE theo ảnh PNG trong `docs/uml/out/`. Ưu tiên theo thứ tự: UCD00, UCD04, UCD05, UCD06; AD01, AD02; SD01, SD03, SD06; ST01–ST03; CL01; CP01; DP01. Các sơ đồ còn lại dùng ảnh SVG trong báo cáo.

## 5. ERD: Reverse DDL từ `db/schema_vp.sql`

Reverse DDL có trong Standard trở lên hoặc bản dùng thử 30 ngày; CE không có. Làm mọi việc cần bản dùng thử trong cùng một đợt, vì chưa rõ CE xử lý dự án ra sao sau khi đã dùng tính năng của bản thử.

1. Mở `Tastoria.vpp` bằng VP Standard hoặc bản dùng thử.
2. **Tools > DB > Reverse DDL...**
3. Chọn tệp `db/schema_vp.sql` trong thư mục bộ nhập.
4. Database: **PostgreSQL**.
5. Bật **Generate ERD**, bấm OK.
6. VP tạo các thực thể và một ERD. Kiểm:
   - Đủ 62 bảng (Model Explorer hoặc đếm thực thể).
   - Khoá chính, khoá ngoại, khoá ghép (ví dụ `food_nutrients (source_id, source_code) → food_items`) có trên sơ đồ; so với `docs/uml/out/erd/ERD08-tong-quan.svg`.
   - Kiểu cột: `schema_vp.sql` đã đổi enum thành `text` + CHECK, `vector(100)` thành `bytea`, `citext` thành `text`, identity thành `bigserial`; bỏ view, extension, trigger, chỉ mục một phần. Bản đầy đủ ở `db/schema.sql` trong repo, phần khác biệt ghi ở đầu `schema_vp.sql`.
7. ERD 62 bảng trên một trang rất rộng. Tách thành các ERD con giống ERD01–ERD07: tạo ERD mới, kéo các thực thể của nhóm module từ Model Explorer vào (xem nhóm bảng trong tiêu đề từng ảnh `docs/uml/out/erd/ERD0x-*.svg`).
8. Lưu dự án.

**Nếu không có Standard hoặc bản dùng thử:**

- Cách 1 (cần Standard): Tools > DB > Reverse Database qua JDBC tới một PostgreSQL cục bộ đã nạp `schema_vp.sql`.
- Cách 2 (CE): vẽ ERD bằng công cụ Entity Relationship Diagram của CE theo ảnh `docs/uml/out/erd/ERD01`–`ERD07`. Vẽ ít nhất ERD tổng quan với tên bảng, PK, FK; cột chi tiết để ở từ điển dữ liệu (`docs/sad/05-tu-dien-du-lieu.md`).
- ERD Chen (ERD00) không có trong VP; dùng ảnh `docs/uml/out/erd/ERD00-khai-niem-chen.svg`.

## 6. Giới hạn đã biết

| Giới hạn | Hệ quả | Cách xử lý |
|---|---|---|
| Plugin PlantUML-VP v1.0.0 chưa được thử trên VP 18.1 | Có thể không cài được hoặc nhập thiếu | Thử một tệp trước (mục 4.1); không được thì vẽ tay (mục 4.4) |
| Plugin chỉ đọc sơ đồ hoạt động viết bằng cú pháp mới | Sơ đồ hoạt động cú pháp cũ không nhập được | AD01–AD06 đã viết bằng cú pháp mới; nếu tự sửa tệp thì giữ cú pháp mới (`start`, `:hành động;`, `if (...) then`, `|Làn|`) |
| Plugin không hỗ trợ ERD | `docs/erd/*.puml` không nhập được | ERD dựng bằng Reverse DDL (mục 5) |
| Một số ký pháp mất khi nhập (ghi chú, ràng buộc trong ngoặc nhọn, stereotype lạ) | Sơ đồ VP thiếu chi tiết so với ảnh | Thêm tay theo ảnh render |
| CE thêm watermark một dòng vào ảnh xuất và bản in | Ảnh xuất từ VP CE có dòng chữ của VP | Dùng ảnh SVG trong `docs/uml/out/` cho báo cáo (không watermark); hỏi giảng viên có chấp nhận ảnh có watermark không |
| Reverse DDL cần Standard hoặc bản dùng thử | CE không dựng ERD tự động | Dùng bản thử 30 ngày trong một đợt, hoặc vẽ tay (mục 5) |
| Parser DDL của VP chưa được thử với `schema_vp.sql` | Có thể báo lỗi một số câu lệnh | Đọc dòng lỗi, xoá câu lệnh đó khỏi một bản sao của `schema_vp.sql` (thường là `COMMENT ON` hoặc CHECK phức tạp), chạy lại; ghi lại những gì đã bỏ |
| Trình soạn flow-of-events và sinh đặc tả use case cần Standard | Không đưa đặc tả Cockburn vào VP bằng CE | Đặc tả use case nằm trong báo cáo (`docs/sad/use-cases/`, `docs/sad/BaoCao_PhanTichThietKe.md`) |

## 7. Xuất ảnh từ VP

- Một sơ đồ: mở sơ đồ, chuột phải nền > Export > Export as Image (hoặc File/Project > Export > Active Diagram as Image), chọn PNG hoặc SVG.
- Cả dự án: **Project > Export > Diagrams to Images...**, chọn các sơ đồ, định dạng PNG (độ phân giải 150–200 DPI) hoặc SVG, chọn thư mục đích.
- Đặt tên ảnh theo mã sơ đồ (`UCD00.png`, `SD03.png`, …) để khớp với báo cáo.

## 8. Nộp những gì

1. `Tastoria.vpp` đã lưu, mở lại được, có đủ các sơ đồ đã nhập hoặc vẽ lại và ERD.
2. Báo cáo phân tích thiết kế `docs/sad/BaoCao_PhanTichThietKe.md` (xuất PDF hoặc Word nếu môn yêu cầu) cùng các tài liệu nó dẫn tới: SRS, đặc tả use case, chuẩn hoá, từ điển dữ liệu, kế hoạch kiểm thử, đánh giá tác động dữ liệu cá nhân, ma trận truy vết, ADR, OpenAPI.
3. Ảnh sơ đồ: dùng SVG/PNG trong `docs/uml/out/` (không watermark). Nếu giảng viên yêu cầu ảnh xuất từ VP thì nộp thêm thư mục ảnh xuất ở mục 7.
4. `db/schema.sql` (bản đầy đủ) và `db/schema_vp.sql` (bản đã nạp vào VP).
5. Ghi chú ngắn những sơ đồ phải vẽ tay hoặc bị mất chi tiết khi nhập, nếu có.

Trước khi nộp, đọc lại `docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md` §13 mục 5: phiên bản VP dùng được (Community hay Standard/bản thử) quyết định cách dựng ERD.
