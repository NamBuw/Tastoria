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
- `vp/Tastoria.vpp`: 39 sơ đồ Visual Paradigm chỉnh sửa được.
- `fig/`: bản xuất VP và ảnh giao diện; `latex/assets/`: hình dùng để biên dịch độc lập.
- `evidence/`: kết quả kiểm tra tài liệu; không phải kết quả kiểm thử ứng dụng.

Word và Markdown giữ nội dung biên tập trước dàn trang LaTeX. PDF từ LaTeX là bản trình bày hiện hành. Bộ sinh mô hình trong vp dùng plugin PTTKHT cài riêng ở máy tác giả; không cần plugin để mở .vpp hoặc biên dịch LaTeX.
