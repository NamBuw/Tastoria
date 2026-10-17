# ADR 0001 — Modular monolith và ranh giới module (cưỡng chế bằng import-linter)

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: toàn bộ backend; module M01–M16 trong `docs/sad/model.yaml`
- Thay cho: v1 §6 ("modular monolith … vẫn tách được thành dịch vụ sau này", chỉ là tuyên bố)

## Bối cảnh

Backend Tastoria do một nhóm sinh viên viết và vận hành trên một máy chủ lab (Docker Compose). Các luồng lõi cắt ngang nhiều miền: ghép mâm (UC15) đọc kho, hồ sơ, kho món và tín hiệu đồng ý; nấu xong (UC20) trừ kho, ghi tương tác và đổi trạng thái mâm; xác nhận quét (UC13) ghi lô kho từ chip.

Bản v1 nói "modular monolith" nhưng không có quy tắc phụ thuộc, không có giao diện công khai, không nói module nào sở hữu bảng nào. Worker ghi thẳng vào bảng quét. Câu "chỉ module profile đọc cột sức khoẻ" mâu thuẫn với chính luồng ghép mâm cần dị ứng và năng lượng mâm (review:backend_ops#9). Giám khảo môn PTƯD và phân tích thiết kế sẽ hỏi ranh giới được kiểm chứng bằng cách nào.

Yếu tố quyết định:
- Một người vận hành, một máy, ít dịch vụ phải giám sát.
- Giao dịch nhiều module phải nguyên tử (xem ADR 0007).
- Ranh giới phải kiểm được tự động trong CI, không dựa vào kỷ luật.
- Sơ đồ thành phần UML phải khớp mã nguồn.

## Các phương án

1. **Monolith không chia module.** Nhanh nhất lúc đầu. Không có ranh giới để vẽ sơ đồ thành phần hay kiểm. Mã mâm cơm và mã kho dễ dính vào nhau.
2. **Modular monolith, ranh giới cưỡng chế bằng import-linter.** Một tiến trình, một cơ sở dữ liệu. Mỗi module là một package Python có `service.py` là giao diện công khai. Phụ thuộc giữa module lấy đúng từ `modules[].deps` trong `model.yaml`.
3. **Microservice (mỗi miền một dịch vụ).** Ranh giới cứng. Mất giao dịch cục bộ cho nấu xong và xác nhận quét, phải thêm saga hoặc outbox, nhân số container, log và cấu hình lên nhiều lần. Không hợp quy mô nhóm.
4. **Modular monolith, mỗi module một schema PostgreSQL và một role DB riêng.** Mạnh hơn phương án 2 ở tầng dữ liệu. Phức tạp hoá migration và khoá ngoại xuyên module (ví dụ `interactions` → `meal_plans`), và FK chéo schema vẫn phải cấp quyền.

## Quyết định

Chọn **phương án 2**.

- 16 module theo `model.yaml`: M01 `core`, M02 `identity`, M03 `privacy`, M04 `catalog`, M05 `profile`, M06 `pantry`, M07 `mlops`, M08 `scan`, M09 `events`, M10 `substitute`, M11 `meal`, M12 `cooking`, M13 `journal`, M14 `survey`, M15 `admin`, M16 `jobs`. Đồ thị phụ thuộc không có vòng.
- Mỗi module có `service.py` (hàm công khai nhận và trả DTO), `models.py` (bảng thuộc module, theo cột `module` của từng bảng trong `model.yaml`), `repo.py`, `api.py`. Module khác chỉ được import `tastoria.<module>.service` (và `tastoria.<module>.dto`).
- Cưỡng chế trong CI bằng import-linter, các contract được **sinh tự động từ `model.yaml`** để sơ đồ, tài liệu và mã không lệch nhau:
  - `forbidden`: module X không được import module nào ngoài `deps` của X.
  - `protected`: `tastoria.<m>.models`, `repo`, `api` chỉ được import từ bên trong `tastoria.<m>`.
  - `acyclic_siblings` trên `tastoria.*` để chặn vòng mới.
- Mỗi bảng có đúng một module sở hữu; chỉ module đó ghi bảng. Module khác đọc qua service. Ngoại lệ duy nhất: view chỉ đọc `v_journal_days` của M13 `journal` đọc bảng của `meal`, `cooking`, `pantry` và `profile`; view được coi là hợp đồng đọc được công bố, được ghi rõ trong sơ đồ thành phần.
- Worker RQ và API build từ **cùng một image**, khác lệnh khởi động, nên mã và migration luôn cùng phiên bản. Worker gọi `scan.service` để ghi kết quả, không ghi bảng trực tiếp.
- Các thao tác cần dữ liệu của mọi module (UC06 tải dữ liệu, UC07 xoá tài khoản) dùng **đảo phụ thuộc**: M03 `privacy` định nghĩa giao diện `SubjectDataHandler` (`export(user_id)`, `erase(user_id)`); từng module đăng ký bộ xử lý của mình ở gốc lắp ráp ứng dụng (`tastoria.app`), nên `privacy` không import module nghiệp vụ.

## Hệ quả

Tích cực:
- Ranh giới kiểm được: import-linter đỏ thì CI đỏ (NFR-MAINT-01).
- Nấu xong và xác nhận quét vẫn là một giao dịch DB (ADR 0007).
- Sơ đồ thành phần và sơ đồ gói vẽ thẳng từ `modules[].deps`.

Tiêu cực, cần theo dõi:
- import-linter chỉ kiểm import tĩnh. Truy vấn SQL viết tay đọc bảng của module khác không bị bắt; bù bằng quy ước "mỗi module chỉ khai báo ORM cho bảng của mình" và review mã.
- Tất cả module chung một role DB; một lỗi SQL injection ở bất kỳ module nào chạm được mọi bảng. Cột sức khoẻ vẫn được mã hoá ở tầng ứng dụng (ADR 0005), nên rò bảng `profiles` không lộ giá trị.
- Hai phụ thuộc trong `model.yaml` có vẻ còn thiếu so với luồng thật (ghi ở "Đề xuất bổ sung mô hình" của báo cáo task): M12 `cooking` cần số họng bếp từ `user_settings` (thuộc `profile`) để chụp vào `cook_sessions.burners`; bộ xếp lịch dùng chung cho kiểm BR-TRAY-05 (ở `meal`) và lịch nấu (ở `cooking`) chưa có chỗ đặt không tạo vòng (xem ADR 0009).
- Khi cần tách dịch vụ thật, ranh giới service đã có, nhưng các giao dịch UoW phải viết lại thành saga. Không làm trong v2.

## Căn cứ

- review:backend_ops#9 (ranh giới chỉ được tuyên bố), review:sad#7 (truy vết UC ↔ module ↔ bảng có ô trống): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §8 "Kiến trúc backend": [2026-10-17-tastoria-thiet-ke-v2.md](../superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md).
- Nguồn sự thật module và phụ thuộc: [model.yaml](../sad/model.yaml) (`modules`, `tables[].module`).
- import-linter, các loại contract `forbidden`, `protected`, `layers`, `independence`, `acyclic_siblings`: https://import-linter.readthedocs.io/en/stable/contract_types/ (mở ngày 17/10/2026).
