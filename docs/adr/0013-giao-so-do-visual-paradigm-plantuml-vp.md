# ADR 0013 — Giao sơ đồ cho Visual Paradigm qua plugin PlantUML-VP và Reverse DDL

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: toàn bộ sơ đồ UML (`docs/uml/`), ERD (`docs/erd/`), `db/schema.sql`, `db/schema_vp.sql`, bộ nhập `docs/vp-import-kit/`
- Thay cho: v1 (không có sản phẩm phân tích thiết kế; review:sad#1)

## Bối cảnh

Môn phân tích thiết kế yêu cầu sơ đồ trong Visual Paradigm (VP) và tệp `.vpp`. Việc soạn thảo diễn ra trên máy chủ Linux không có giao diện; người dùng dựng `.vpp` trên máy Windows/macOS. Tình trạng VP 10/2026 (R3 §1):

- VP Community Edition (CE) 18.1 miễn phí cho mục đích phi thương mại; ảnh xuất có watermark một dòng.
- Bộ nhập sẵn có của VP: XML, VP project, Excel, XMI, BPMN, Visio, Rose, ERwin…; **không có PlantUML**. Một bài marketing của VP nói PlantUML được ánh xạ vào meta-model nhưng không có đường dẫn menu; coi như không có.
- Plugin bên thứ ba **PlantUML-VP** (MIT) chuyển hai chiều cho sơ đồ lớp, use case, tuần tự, thành phần, triển khai, trạng thái, hoạt động (hoạt động chỉ cú pháp mới); plugin chạy ở mọi edition kể cả CE. Tương thích với VP 18.1 chưa được xác minh.
- Reverse DDL (Tools > DB > Reverse DDL, có tuỳ chọn "Generate ERD") thuộc Standard trở lên (hoặc bản dùng thử 30 ngày). Parser DDL của VP có nhận `vector`, `jsonb`, cột identity hay không chưa được xác minh.
- Định dạng `.vpp` không được công bố; nhân viên VP khuyên không thao tác trực tiếp. Không sinh `.vpp` bằng script.

## Các phương án

1. **Vẽ tay mọi sơ đồ trong VP.** Chắc chắn nhập được. Tốn công, không kiểm tự động, dễ lệch `model.yaml`.
2. **Sinh XMI và nhập qua Project > Import > XMI.** Cần Modeler trở lên; XMI không có dữ liệu sơ đồ có thể chỉ tạo phần tử mô hình mà không có sơ đồ; XMI của PlantUML ở mức alpha và chỉ cho sơ đồ lớp.
3. **PlantUML làm nguồn, nhập bằng plugin PlantUML-VP; ERD bằng Reverse DDL từ `db/schema_vp.sql`.**
4. **Sinh trực tiếp tệp `.vpp`.** Định dạng không công bố; có thể hỏng dự án.

## Quyết định

Chọn **phương án 3**, giữ phương án 1 làm dự phòng.

- Mỗi sơ đồ là một tệp `.puml`, một sơ đồ mỗi tệp, bắt đầu `@startuml` (ERD Chen dùng `@startchen`), có `title`; không `!include`, không sprite/icon/theme; sơ đồ hoạt động dùng cú pháp mới. Tên tệp `docs/uml/<loai>/<MA>-<slug>.puml`.
- Render trên máy chủ bằng PlantUML 1.2024.8 + Graphviz ra SVG/PNG ở `docs/uml/out/<loai>/` (ERD ở `docs/uml/out/erd/`). Mỗi tệp phải render được (mã thoát 0, SVG không chứa "Syntax Error"); ảnh này không có watermark, dùng cho báo cáo.
- Mọi mã trong sơ đồ lấy từ `docs/sad/model.yaml`; `check_refs.py` báo mã lạ.
- ERD vật lý:
  - `db/schema.sql` là DDL PostgreSQL 18 + pgvector đầy đủ.
  - `db/schema_vp.sql` là bản cho VP: enum → `text` + CHECK, `vector` → `bytea` kèm chú thích, bỏ view, extension và unique một phần.
  - Người dùng chạy Tools > DB > Reverse DDL, chọn PostgreSQL, bật "Generate ERD", trong bản dùng thử 30 ngày hoặc với giấy phép Standard/academic. Làm mọi bước cần bản dùng thử trong một đợt.
  - Dự phòng: Reverse Database qua JDBC tới một Postgres cục bộ; nếu chỉ có CE thì vẽ ERD bằng công cụ ERD của CE theo ảnh render.
- Bộ nhập `docs/vp-import-kit/` gồm các tệp `.puml`, `schema_vp.sql`, ảnh render và hướng dẫn từng bước (nhập một tệp nhỏ trước, rồi cả thư mục, rồi chỉnh bố cục).
- Đặc tả use case viết thành bảng trong báo cáo, vì trình soạn flow-of-events của VP cần Standard trở lên.

## Hệ quả

Tích cực:
- Sơ đồ là văn bản: review được bằng diff, kiểm tự động, sinh lại khi `model.yaml` đổi.
- Báo cáo có ảnh không watermark ngay cả khi VP chỉ có CE.
- Một nguồn cho cả báo cáo và `.vpp`.

Tiêu cực, cần theo dõi:
- Plugin PlantUML-VP chưa được thử trên VP 18.1; nếu không chạy, phải vẽ lại tay từ ảnh render.
- Cú pháp phải giới hạn ở tập plugin hỗ trợ; một số ký pháp UML (ví dụ một số dạng ghi chú, ràng buộc OCL) có thể mất khi nhập.
- Bố cục sau khi nhập phải chỉnh tay trong VP.
- ERD trong VP cần edition trả phí hoặc bản dùng thử; CE sau khi đã dùng tính năng dùng thử xử lý dự án ra sao chưa rõ.
- Watermark CE trên ảnh xuất từ VP: hỏi giảng viên có chấp nhận không.

## Căn cứ

- R3 §1 và khuyến nghị "plan for handing over .vpp-ready material": [03-cong-nghe-vpp-phan-tich-thiet-ke.md §1](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#1-getting-diagrams-into-visual-paradigm-vp), [khuyến nghị](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#recommendation-plan-for-handing-over-vpp-ready-material); rủi ro 1–6: [Risks / unknowns](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#risks--unknowns).
- review:sad#1 (chưa có sản phẩm phân tích thiết kế): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §12 mục 7; kế hoạch S1, Global Constraints: [2026-10-17-s1-phan-tich-thiet-ke.md](../superpowers/plans/2026-10-17-s1-phan-tich-thiet-ke.md).
- VP CE: https://www.visual-paradigm.com/editions/community/ ; so sánh edition: https://www.visual-paradigm.com/support/edition-comparison.jsp ; Reverse DDL: https://www.visual-paradigm.com/support/documents/vpuserguide/3563/3587/85425_reverseengin.html ; plugin PlantUML-VP: https://github.com/nbourdi/PlantUML-VP-Plugin (R3 mở ngày 17/10/2026).
