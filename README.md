# Tastoria

Gợi ý một mâm cơm Việt từ đồ có trong tủ lạnh: chụp ảnh hoặc nhập tay nguyên liệu, kho theo lô có độ gấp, ghép mâm
mặn–rau–canh theo kho và hồ sơ, lịch nấu cả mâm, nhật ký. Bản chạy thật: <https://tastoria.ctslab.net> (APK Android
ở trang giới thiệu).

| Thư mục | Nội dung |
|---|---|
| `backend/` | FastAPI modular monolith, PostgreSQL 18 + pgvector, Valkey, worker RQ chạy bộ phát hiện ONNX — `backend/README.md` |
| `app/` | Expo (Android + web) — `app/README.md` |
| `ml/` | Học máy và thị giác máy tính (`tastoria_ml`), kiểm thử `ml/tests/` |
| `data/kb/` | Kho món, nguyên liệu, dữ liệu tham chiếu, bảng lớp thị giác — nạp bằng `tastoria catalog import data/kb` |
| `data/processed/` | Kết quả máy đọc được (JSON, manifest); ảnh và mô hình không nằm trong git |
| `deploy/` | Docker Compose, nginx, Cloudflare Tunnel, sao lưu — `deploy/README.md` |
| `db/` | `schema.sql` (migration 0001) và bộ sinh từ điển dữ liệu |
| `docs/` | Phân tích thiết kế (`docs/sad/`), API (`docs/api/openapi-v1.yaml`, 70 thao tác), báo cáo môn (`docs/reports/`) |
| `landing/` | Trang giới thiệu tĩnh |

Lớp thị giác: nguồn duy nhất là `data/kb/vision_classes.yaml` (22 lớp phân tích + 15 lớp thêm ngày 30/10/2026 = 37
dòng của bảng `vision_classes`). Mô hình đang chạy (`deploy/models/detector`, YOLO26n) nhận 13 lớp: cá, tôm, trứng,
cà chua, cà rốt, khoai tây, bắp cải, súp lơ, bí đỏ, bí đao, mướp đắng, đậu que, nấm. Đồ ăn vặt (nhóm `do_an_vat`) vào
kho được nhưng không bao giờ vào mâm.

Kiểm thử (05/11/2026): `uv run --package tastoria-backend pytest backend/tests -q` → 347 passed;
`CUDA_VISIBLE_DEVICES= uv run --package tastoria-ml pytest ml/tests -q` → 254 passed, 1 skipped.

Đối chiếu tài liệu với mã và dọn tệp mô hình: `docs/KHOP-TAI-LIEU.md`.
