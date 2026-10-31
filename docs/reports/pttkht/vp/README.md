# Sinh mô hình Visual Paradigm cho Tastoria

Dùng bản generator mới từ `PTTKHT/DesignV2/vp` (28/10/2026), không dùng bộ PlantUML-VP cũ.

- `gen_tastoria.py`: đặc tả mô hình và bố cục Tastoria.
- `spec_lib.py`, `gen_beh.py`, `check_svg.py`: thư viện từ DesignV2.
- Plugin thực thi: `~/opt/vp/tools/pttkht-uml-plugin/src/pttkht/uml/UmlPlugin.java` (28/10/2026), plugin ID `pttkht.uml`.
- `Tastoria.vpp`: dự án VP chứa phần tử mô hình và quan hệ thật, có thể sửa bằng VP.
- `../fig/png`, `../fig/svg`: ảnh xuất bằng chính Visual Paradigm CE 18.1; giữ watermark của CE.

Chạy:

```bash
python3 gen_tastoria.py
bash ./run.sh "$PWD/spec_tastoria.tsv" "$PWD/Tastoria.vpp" "$PWD/../fig/png"
~/opt/vp/tools/pttkht-uml-plugin/export.sh "$PWD/Tastoria.vpp" "$PWD/../fig/svg" svg
python3 check_svg.py ../fig/svg
```

Script run.sh tạo lại đường dẫn dự án đầu ra; không trỏ vào dự án đã chỉnh tay. Sao lưu thành tên khác trước khi tái sinh.

Phân biệt mô hình: DM là lớp miền phân tích; AR là phân tầng với stereotype; DB là cấu trúc bảng dùng UML class «table» và association có bội số, không gọi là Chen hay Crow's Foot. SQ dùng lifeline/message/activation/combined fragment thật của VP. UC dùng Include/Extend thật, không gõ chữ trên một đường thường.

Màu giữ nguyên DesignV2/VP: #7ACFF5. Không chỉnh màu ảnh sau export. check_svg.py được sửa đúng một nhận diện: khung System được nhận từ modelType=System nên cạnh actor–UC qua biên hệ thống không bị báo nhầm là xuyên vật cản. Các kiểm tra chồng chữ/hình khác giữ nguyên.

Bản theo pha bổ sung `analysis_v2.py`: CL09/13/15/20/30, DS02/03 và SQ03, tổng cộng 39 sơ đồ. Các lớp BCE hiển thị dạng lớp có stereotype bằng `setDisplayAsRobustnessAnalysisIcon(false)` để giữ đầy đủ thuộc tính. Kiểm tra nhãn rút gọn được bổ sung trong `../verify_delivery.py`.
