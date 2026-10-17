# S1 — Bộ phân tích thiết kế hệ thống: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo đủ bộ sản phẩm phân tích thiết kế hệ thống cho Tastoria (SRS, đặc tả use case, toàn bộ UML, ERD chuẩn hoá đến BCNF, DDL chạy được, OpenAPI, kế hoạch kiểm thử, ADR, đánh giá tác động dữ liệu cá nhân, ma trận truy vết, bộ nhập Visual Paradigm), nhất quán tuyệt đối với `docs/sad/model.yaml`.

**Architecture:** `docs/sad/model.yaml` là nguồn sự thật duy nhất (mã actor, UC, module, bảng, cột, endpoint). Mọi tài liệu và sơ đồ sinh ra phải dùng đúng mã trong đó. Sơ đồ viết bằng PlantUML (nhập vào Visual Paradigm qua plugin PlantUML-VP); ERD vật lý sinh từ `db/schema.sql` (Visual Paradigm: Tools > DB > Reverse DDL với `db/schema_vp.sql`). Kiểm tra tự động bằng script trong `docs/sad/tools/`.

**Tech Stack:** PlantUML 1.2024.8 + Graphviz (có sẵn), PostgreSQL 18 + pgvector 0.8 (Docker `pgvector/pgvector:pg18`), Python 3.12 (uv) cho script kiểm tra, OpenAPI 3.1.

**Spec:** `docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md` (BR ở §4, NFR ở §11, danh mục sản phẩm ở §12) + `docs/sad/model.yaml`.

## Global Constraints

- Không tạo mã mới cho actor/UC/module/bảng/endpoint ngoài `model.yaml`. Thiếu thì ghi vào mục "Đề xuất bổ sung mô hình" trong báo cáo của task, không tự sửa `model.yaml`.
- Văn bản tiếng Việt, giọng mô tả thẳng; định danh kỹ thuật (tên bảng, cột, endpoint) giữ nguyên tiếng Anh.
- PlantUML tương thích plugin PlantUML-VP: mỗi tệp một sơ đồ, bắt đầu `@startuml` (ERD Chen dùng `@startchen`), có `title`; không `!include`, không sprite/icon, không theme; sơ đồ hoạt động dùng cú pháp mới. Tên tệp `docs/uml/<loai>/<MA>-<slug>.puml`.
- Mỗi tệp PlantUML phải render được: `plantuml -tsvg -o <thư mục out tuyệt đối> <tệp>` thoát mã 0 và SVG không chứa "Syntax Error". Ảnh SVG lưu ở `docs/uml/out/<loai>/`.
- Không chạy `git commit`. Không sửa tệp ngoài phạm vi task.
- FR đánh mã `FR-<số UC 2 chữ số>-<số thứ tự 2 chữ số>` (ví dụ `FR-12-03`); ca kiểm thử `TC-<nhóm>-<số>`.

## Review Focus

1. Một UC dùng endpoint hoặc bảng không có trong `model.yaml` → `check_refs.py` báo lỗi; test `test_unknown_ids_fail`.
2. Cột trong DDL lệch `model.yaml` (thiếu cột, sai NULL) → `test_ddl.sh` so số bảng và danh sách cột với `model.yaml`.
3. Sơ đồ render được trên máy nhưng plugin VP không đọc được (cú pháp lạ) → giới hạn cú pháp ở Global Constraints; reviewer kiểm.
4. Ma trận truy vết có ô trống (UC không có FR, FR không có TC, bảng không UC nào dùng) → `gen_traceability.py` in danh sách ô trống, phải bằng 0.
5. Phi chuẩn hoá không được giải thích → `04-chuan-hoa.md` có mục riêng cho từng trường hợp, reviewer CSDL kiểm.

---

### Task 1: Công cụ kiểm tra (`docs/sad/tools/`)
**Files:** `render.sh`, `check_refs.py`, `test_ddl.sh`, `gen_traceability.py`, `tests/test_tools.py`
- `render.sh [pattern]`: render mọi `docs/uml/**/*.puml` → `docs/uml/out/**.svg` và `.png`; thoát ≠ 0 nếu có lỗi.
- `check_refs.py`: đọc `model.yaml`, quét `docs/sad/**/*.md` và `docs/uml/**/*.puml`, báo mã A/UC/BR/NFR/bảng/endpoint không tồn tại; kiểm front-matter UC.
- `test_ddl.sh`: chạy container pgvector pg18 tạm, áp `db/schema.sql`, so tên bảng + cột với `model.yaml`, xoá container.
- `gen_traceability.py`: sinh `docs/sad/08-ma-tran-truy-vet.md` (UC → FR → endpoint/CLI → module → bảng → TC) và in ô trống.
- Test: `uv run --with pyyaml --with pytest pytest docs/sad/tools/tests -q` với fixture mô hình nhỏ, gồm `test_unknown_ids_fail`.

### Task 2: Đặc tả use case (5 nhóm song song: UC01–08, UC09–14, UC15–18, UC19–24, UC25–34)
**Files:** `docs/sad/use-cases/UCxx.md` (front-matter: id, name, package, primary_actor, secondary_actors, priority, rules, endpoints, tables, frs, tests=[])
- Mẫu Cockburn tiếng Việt, đủ luồng ngoại lệ (mất mạng, thiếu đồng ý, không khả thi, quá thời gian, gửi lại lũy đẳng). FR nguyên tử, có tiêu chí chấp nhận Given/When/Then.
- Kiểm: `check_refs.py` sạch cho các tệp của nhóm.

### Task 3: CSDL vật lý (`db/schema.sql`, `db/schema_vp.sql`, `docs/sad/05-tu-dien-du-lieu.md`)
- DDL PostgreSQL 18 + pgvector đúng `model.yaml`: enum, PK/FK/UQ/CHECK, unique một phần, chỉ mục cho truy vấn nóng, 3 view, `COMMENT ON` mọi bảng và cột.
- `test_ddl.sh` xanh; từ điển dữ liệu sinh từ catalog PostgreSQL (không gõ tay).
- `schema_vp.sql`: bản cho Visual Paradigm (enum → text + CHECK, vector → bytea, bỏ view, extension, unique một phần).

### Task 4: ERD và chuẩn hoá (sau Task 3)
**Files:** `docs/erd/ERD00-khai-niem-chen.puml`, `docs/erd/ERD01..07-*.puml` (chân quạ theo nhóm module + tổng quan), `docs/sad/04-chuan-hoa.md`
- Chen: thực thể và quan hệ chính với bội số; chân quạ: mọi bảng, PK/FK, bội số min..max hai đầu khớp DDL.
- Chuẩn hoá: từng bảng ghi khoá ứng viên, phụ thuộc hàm không tầm thường, dạng chuẩn đạt được (đến BCNF) và lý do; mục riêng cho mọi phi chuẩn hoá có kiểm soát.

### Task 5: UML hành vi (3 nhóm song song)
- 5a Use case: tổng quan + 10 gói (`docs/uml/usecase/`); hoạt động có làn AD01–AD06 (`docs/uml/activity/`).
- 5b Tuần tự SD01–SD10 (`docs/uml/sequence/`).
- 5c Máy trạng thái ST01–ST08 theo `model.yaml.state_machines` (`docs/uml/state/`).

### Task 6: UML cấu trúc
- Lớp miền (phân tích), lớp BCE cho UC12–13, UC15, UC20, lớp thiết kế cho module meal, pantry, scan, cooking; thành phần (module + giao diện + phụ thuộc theo `model.yaml`); gói; triển khai (`docs/uml/class/`, `component/`, `package/`, `deployment/`).

### Task 7: Hợp đồng API (`docs/api/openapi-v1.yaml`)
- OpenAPI 3.1 cho 70 endpoint: schema, lỗi `application/problem+json` (RFC 9457) với `code`, bảo mật bearer, header `Idempotency-Key`, phân trang keyset; kiểm bằng `openapi-spec-validator`.

### Task 8: ADR và đánh giá tác động dữ liệu cá nhân
- `docs/adr/0001…0013-*.md` (MADR), `docs/sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md` (bản nháp theo Luật 91/2025 và NĐ 356/2025, ghi rõ cần rà soát pháp lý).

### Task 9: SRS (sau Task 2)
- `docs/sad/01-SRS.md` theo ISO/IEC/IEEE 29148:2018; bảng FR tổng hợp từ front-matter UC (script), NFR có điều kiện đo, BR có tiêu chí chấp nhận; `docs/sad/00-thuat-ngu.md`.

### Task 10: Kế hoạch kiểm thử (sau Task 2)
- `docs/sad/06-ke-hoach-kiem-thu.md`: chiến lược theo tầng, danh mục TC gắn BR/FR/UC; điền `tests:` vào front-matter UC.

### Task 11: Ma trận truy vết và kiểm tra chéo (sau Task 1–10)
- Chạy `check_refs.py`, `render.sh`, `test_ddl.sh`, `gen_traceability.py`; số ô trống = 0, số mã lạ = 0.

### Task 12: Soi phản biện (3 giám khảo: ký pháp UML, thiết kế CSDL, chất lượng yêu cầu) → sửa theo vùng → kiểm lại Task 11.

### Task 13: Bộ nhập Visual Paradigm + báo cáo tổng hợp
- `docs/vp-import-kit/HUONG-DAN.md` + `make_kit.sh` (đóng gói `.puml` + `schema_vp.sql`); `docs/sad/BaoCao_PhanTichThietKe.md` gom toàn bộ với hình SVG.

## Done when
Task 11 sạch (0 mã lạ, 0 ô trống, mọi sơ đồ render, DDL áp được), giám khảo không còn phát hiện critical/major chưa xử lý, bộ nhập VP đóng gói được.
