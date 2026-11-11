# Báo cáo PTTKHT — Tastoria

Bản trình bày chính: [Bao-cao-Tastoria.pdf](Bao-cao-Tastoria.pdf). Nguồn LaTeX: [latex/Bao-cao-Tastoria.tex](latex/Bao-cao-Tastoria.tex); các chương và bìa ở `latex/Bao-cao-Tastoria/`.

Báo cáo theo các pha: khảo sát, yêu cầu, phân tích, thiết kế, hiện thực/kiểm thử và đánh giá. Bảng phân công chỉ ở trang đầu, bìa theo mẫu DesignV2 của PTTKHT. Thông tin nhóm chưa xác nhận được để trống.

## Biên dịch PDF

Từ thư mục này:

```bash
bash latex/build.sh
# Chỉ báo cáo chính:
bash latex/build.sh Bao-cao-Tastoria
```

Cần pdfLaTeX, VnTeX/T5 và các gói trong `latex/preamble.tex`. Script biên dịch ba lượt từ .tex, không cần Markdown hay Visual Paradigm. Chỉnh trực tiếp các tệp .tex rồi build. `latex/generate.py` là công cụ chuyển đổi ban đầu từ Markdown; không chạy lại nếu muốn giữ chỉnh sửa LaTeX.

## Phụ lục và mô hình

- Phụ lục A: 34 UC thuộc 10 phân hệ.
- Phụ lục B: cấu trúc bảng và ràng buộc.
- Ma trận truy vết: UC, tác nhân, giao tiếp và dữ liệu.
- `vp/Tastoria.vpp`: 104 sơ đồ UML Visual Paradigm (use case, ngữ cảnh, tuần tự, hoạt động, trạng thái, lớp, thành phần, triển khai, gói, Chen, tổng quan bảng); `vp/Tastoria-ERD.vpp`: 17 ERD chi tiết với bảng, cột, PK/FK thật của VP. Tổng 121 sơ đồ, trùng 1:1 mã và nội dung với bộ PlantUML `docs/uml`, `docs/erd`.
- `fig/`: bản xuất VP và ảnh giao diện; `latex/assets/`: hình dùng để biên dịch độc lập.
- `evidence/`: kết quả kiểm tra tài liệu; không phải kết quả kiểm thử ứng dụng.

Word và Markdown giữ nội dung biên tập trước dàn trang LaTeX. PDF từ LaTeX là bản trình bày hiện hành. Bộ sinh mô hình trong vp dùng plugin PTTKHT cài riêng ở máy tác giả; không cần plugin để mở .vpp hoặc biên dịch LaTeX.

## Bộ sơ đồ và bảng đổi mã

Mọi sơ đồ sinh từ một nguồn: `docs/sad/tools/diagrams/model.py`. Từ đó `gen_puml.py` ghi PlantUML và `vp/gen_tastoria.py` ghi spec cho plugin VP `pttkht.uml`; ERD chi tiết đi qua `docs/vp-import-kit/tools/ddl_to_spec.py` và plugin `tastoria.erd` (`vp/run_erd.sh`). Mỗi sơ đồ một ý: tuần tự ≤ 5 lifeline, ≤ 12 thông điệp, ≤ 1 fragment; hoạt động ≤ 10 hành động; use case ≤ 8 UC; lớp ≤ 6 lớp, ≤ 5 thành phần; thành phần/triển khai ≤ 8 hộp; ERD chi tiết ≤ 8 bảng. Bố cục đặt tay theo lưới, không dùng bố cục tự động của VP; `vp/check_svg.py` phải báo 0 lỗi.

Bản VP cũ (39 sơ đồ) giữ ở `vp/Tastoria-v1-39so-do.vpp.bak` (không commit).

| Mã cũ | Mã mới |
|---|---|
| UCD00 / VP UC00 | UCD00a, UCD00b |
| VP UC01–UC08, PK01–PK10 | UCD01–UCD10 (theo gói PK1–PK10) |
| VP UC02 | UCD05 (UC16, UC17, UC18 mở rộng UC15) |
| CTX01 | CTX01a, CTX01b |
| SD01 | SD01a gửi ảnh, SD01b worker nhận diện, SD01c app chờ kết quả, SD01d dọn lần quét kẹt |
| SD02 / VP SQ03 | SD02a sửa chip, SD02b xác nhận vào kho, SD02c bỏ lần quét |
| SD03 | SD03a tạo mâm, SD03b nhận mâm |
| SD04 | SD04 |
| SD05 | SD05a xem gợi ý, SD05b chọn thay thế, SD05c thêm đi chợ |
| SD06 / VP SQ01, SQ02 | SD06a mở phiên nấu, SD06b nấu xong, SD06c hoàn tác |
| SD07 | SD07a rút đồng ý, SD07b xoá dữ liệu mục đích |
| SD08 | SD08 |
| SD09 | SD09a gửi yêu cầu, SD09b tạo tệp, SD09c tải tệp |
| SD10 | SD10a đăng ký, SD10b kiểm định, SD10c triển khai, SD10d quay lui |
| AD01 / VP AD01, AD02 | AD01a quét–xác nhận, AD01b nhận–điều chỉnh mâm, AD01c nấu–hoàn tất |
| AD02 | AD02a lọc món–chuẩn bị kho, AD02b duyệt tổ hợp–chọn mâm |
| AD03 | AD03a kiểm tra điều kiện, AD03b ghi kho từ chip |
| AD04 / VP CL30 | AD04a thu thập dữ liệu, AD04b gán nhãn–huấn luyện, AD04c đăng ký–triển khai |
| AD05 | AD05 |
| AD06 | AD06a tham gia khảo sát, AD06b quản lý đợt |
| VP AD03 (hoàn tác) | ST03 (trạng thái phiên nấu) và AD01c |
| ST01–ST08 | ST01–ST08 (trước đây không có trong VP) |
| CL01 / VP DM01, DM02, CL09 | CL01a–CL01i (DM01 → CL01e, DM02 → CL01g, CL09 → CL01a) |
| CL02 / VP CL13 | CL02a, CL02b |
| CL03 / VP CL15 | CL03a, CL03b |
| CL04 / VP CL20 | CL04a, CL04b |
| CL05 / VP DS03 | CL05a, CL05b |
| CL06 | CL06a, CL06b |
| CL07 / VP DS02 | CL07a, CL07b |
| CL08 / VP DS01 | CL08a, CL08b |
| CP01 / VP AR01 | CP01a–CP01e |
| DP01 | DP01a–DP01c |
| PG01 | PG01a–PG01c |
| ERD00 | ERD00a–ERD00h (Chen theo mảng) |
| ERD01 | ERD01a, ERD01b |
| ERD02 | ERD02 |
| ERD03 | ERD03a–ERD03c |
| ERD04 / phần VP DB02 | ERD04a, ERD04b |
| ERD05 / VP DB01, DB03 | ERD05a kho, ERD05b quét |
| ERD06 / phần VP DB02 | ERD06a–ERD06e |
| ERD07 | ERD07a, ERD07b |
| ERD08 | ERD08 (chỉ tên bảng, theo nhóm) |
