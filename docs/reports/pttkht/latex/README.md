# Biên dịch báo cáo Tastoria bằng LaTeX

Nguồn chính: `Bao-cao-Tastoria.tex`. Nội dung theo chương ở `Bao-cao-Tastoria/chapter-00.tex` … `chapter-07.tex`; trang bìa và phân công ở `Bao-cao-Tastoria/cover.tex`.

Các phụ lục có tệp gốc riêng: `Phu-luc-A-Use-Cases.tex`, `Phu-luc-B-Co-so-du-lieu.tex`, `Ma-tran-truy-vet.tex`. Mỗi tài liệu dùng chung `preamble.tex` và thư mục `assets/`.

## Build

```bash
cd /home/namnx/NamBuw/PTTKHT/Tastoria/latex
bash build.sh
# Hoặc chỉ báo cáo chính:
bash build.sh Bao-cao-Tastoria
```

Cần pdfLaTeX, bộ font tiếng Việt T5/VnTeX, TeX Gyre Termes và các gói được liệt kê trong preamble.tex. Môi trường hiện tại đã biên dịch thành công. Build chạy ba lượt để cập nhật mục lục, danh mục hình/bảng và tham chiếu. Đầu ra ở `build/` và được chép sang thư mục báo cáo cấp trên.

Có thể chỉnh trực tiếp tệp .tex rồi chạy build.sh; không cần Python, Markdown hoặc Visual Paradigm để biên dịch bộ nguồn đã bàn giao. Sơ đồ trong assets là PDF vector chuyển từ SVG xuất bởi VP, giữ màu và watermark. Ảnh giao diện là PNG.

`generate.py` là công cụ chuyển đổi ban đầu từ bản Markdown, cần Python markdown, BeautifulSoup, Pillow và rsvg-convert. Không chạy lại công cụ này sau khi sửa trực tiếp LaTeX nếu chưa sao lưu: nó ghi đè tệp .tex theo Markdown.

Bản PDF sinh từ LaTeX là bản trình bày chính. Các bản Word/HTML được giữ từ quy trình trước; số trang và kiểu dàn trang của chúng không đồng nhất với LaTeX.
