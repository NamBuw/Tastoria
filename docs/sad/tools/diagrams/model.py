"""Bộ sơ đồ UML/ERD của Tastoria: nguồn duy nhất cho cả PlantUML (docs/uml, docs/erd) và Visual Paradigm.

Mỗi sơ đồ chỉ thể hiện một việc. Giới hạn: tuần tự ≤ 5 lifeline, ≤ 12 thông điệp, ≤ 1 fragment;
hoạt động ≤ 10 hành động; use case ≤ 8 UC; lớp ≤ 6 lớp, ≤ 5 thành phần mỗi lớp; thành phần/triển khai ≤ 8 hộp;
ERD chi tiết ≤ 8 bảng; ERD tổng quan chỉ tên bảng. Kiểm bằng check() ở cuối tệp.

Sinh:  python3 docs/sad/tools/diagrams/gen_puml.py      (PlantUML)
       python3 docs/reports/pttkht/vp/gen_tastoria.py    (spec cho plugin VP pttkht.uml)
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
META = yaml.safe_load((ROOT / "docs/sad/model.yaml").read_text())
ACTOR = {a["id"]: a["name"] for a in META["actors"]}
UCS = {u["id"]: u for u in META["use_cases"]}


def ucname(uid):
    return re.sub(r"\s*\(.*\)$", "", UCS[uid]["name"])


DIAGRAMS = []   # theo thứ tự xuất


def D(kind, did, slug, title, **kw):
    d = dict(kind=kind, id=did, slug=slug, title=title, **kw)
    DIAGRAMS.append(d)
    return d


# =====================================================================  USE CASE
def uc_diagram(did, slug, title, ucs, primary=None, extra_actors=()):
    """ucs: danh sách mã UC. Actor lấy từ model.yaml; include/extend chỉ vẽ khi cả hai đầu có mặt."""
    actors, links = [], []
    for u in ucs:
        for a in [UCS[u]["primary"]] + UCS[u].get("secondary", []):
            if a not in actors:
                actors.append(a)
            links.append((a, u))
    for a in extra_actors:
        if a not in actors:
            actors.append(a)
    rels = []
    for u in ucs:
        for r in UCS[u].get("rels", []):
            if "include" in r and r["include"] in ucs:
                rels.append(("include", u, r["include"], None))
            if "extend" in r and r["extend"] in ucs:
                rels.append(("extend", u, r["extend"], r.get("condition")))
    gens = []
    if "A01" in actors and "A02" in actors:
        gens.append(("A02", "A01"))
    # actor chỉ nối qua include/extend thì không vẽ đường trực tiếp tới UC được include
    return D("uc", did, slug, title, actors=actors, ucs=list(ucs), links=links, rels=rels, gens=gens)


uc_diagram("UCD00a", "tong-quan-nguoi-dung", "UCD00a — Tổng quan: chức năng chính của khách và người dùng",
           ["UC01", "UC02", "UC09", "UC12", "UC15", "UC19", "UC20", "UC22"])
uc_diagram("UCD00b", "tong-quan-nhan-su", "UCD00b — Tổng quan: chức năng của nhân sự và tác nhân hệ thống",
           ["UC23", "UC25", "UC27", "UC28", "UC29", "UC30", "UC31", "UC33"])
for i, pk in enumerate(META["packages"], 1):
    items = [u["id"] for u in META["use_cases"] if u["pkg"] == pk["id"]]
    slug = {1: "tai-khoan-bao-mat", 2: "quyen-rieng-tu", 3: "ho-so-muc-tieu", 4: "kho-quet", 5: "mam-com",
            6: "nau-nhat-ky", 7: "khao-sat-gu", 8: "quan-tri-noi-dung-du-lieu", 9: "van-hanh-mo-hinh",
            10: "tac-vu-dinh-ky"}[i]
    uc_diagram(f"UCD{i:02d}", slug, f"UCD{i:02d} — Gói {pk['id']} {pk['name']}", items)


# =====================================================================  NGỮ CẢNH
D("ctx", "CTX01a", "ngu-canh-con-nguoi", "CTX01a — Ngữ cảnh: người dùng và nhân sự",
  center="Hệ thống Tastoria",
  left=[("A01", "xem landing, đăng ký, đăng nhập"), ("A02", "ảnh tủ lạnh, hồ sơ / mâm, lịch nấu"),
        ("A03", "điểm gu món (ẩn danh)")],
  right=[("A04", "xử lý yêu cầu dữ liệu"), ("A05", "nhập kho món (CLI)"),
         ("A06", "mô hình, đợt khảo sát (CLI)"), ("A07", "nhãn ảnh góp")])
D("ctx", "CTX01b", "ngu-canh-he-thong-ngoai", "CTX01b — Ngữ cảnh: tác nhân thời gian và hệ thống ngoài",
  center="Hệ thống Tastoria",
  left=[("A08", "kích hoạt tác vụ định kỳ")],
  right=[("A09", "thư đặt lại mật khẩu"), ("A10", "ảnh cần gán nhãn / nhãn"),
         ("DRIVE", "bản sao lưu (rclone)")],
  extra={"DRIVE": "Kho sao lưu ngoài (Google Drive)"})


# =====================================================================  TUẦN TỰ
U = ("U", "actor", "Người dùng")
APP = ("APP", "boundary", "App")
DB = ("DB", "entity", "CSDL")
Q = ("Q", "entity", "Hàng đợi (Valkey)")
FS = ("FS", "entity", "Kho tệp")


def api(m):
    return ("API", "control", f"API ({m})")


def m(a, b, label, ret=False):
    return ("m", a, b, label, "ret" if ret else "call")


def frag(op, *operands):
    return ("frag", op, list(operands))


def sq(did, slug, title, lls, items):
    return D("seq", did, slug, title, lls=list(lls), items=list(items))


# --- SD01 quét ảnh (tách 4)
sq("SD01a", "gui-anh-quet", "SD01a — Gửi ảnh quét (UC12)", [U, APP, api("scan"), DB, Q], [
    m("U", "APP", "chọn chế độ, chụp 1–2 ảnh"),
    m("APP", "API", "gửi ảnh quét (khóa lũy đẳng)"),
    frag("alt",
         ("ảnh quá cỡ hoặc không phải JPEG", [m("API", "APP", "từ chối: ảnh không hợp lệ", True)]),
         ("ảnh hợp lệ", [m("API", "DB", "tra khóa lũy đẳng"),
                         m("API", "DB", "lưu ảnh đã làm sạch, lần quét «queued»"),
                         m("API", "Q", "đưa job nhận diện vào hàng đợi"),
                         m("API", "APP", "202: đã nhận, đang xử lý", True)])),
    m("APP", "U", "hiện «đang nhận diện»", True)])
sq("SD01b", "worker-nhan-dien", "SD01b — Worker nhận diện nguyên liệu (UC12)",
   [Q, ("WK", "control", "Worker (scan)"), FS, DB], [
    m("Q", "WK", "giao job nhận diện"),
    m("WK", "DB", "lần quét → «processing»"),
    m("WK", "FS", "đọc ảnh quét"),
    m("FS", "WK", "ảnh", True),
    frag("alt",
         ("nhận diện thành công", [m("WK", "DB", "ghi chip và khung phát hiện; → «done»"),
                                   m("WK", "Q", "thông báo «done»")]),
         ("lỗi, còn lượt thử", [m("WK", "Q", "xếp lại job")]),
         ("lỗi lần thứ 3", [m("WK", "DB", "lần quét → «failed»"),
                            m("WK", "Q", "thông báo «failed»")]))])
sq("SD01c", "cho-ket-qua-quet", "SD01c — App chờ kết quả quét (UC12)", [U, APP, api("scan"), Q, DB], [
    frag("loop", ("đến khi done, failed hoặc expired", [
        m("APP", "API", "hỏi trạng thái (chờ tối đa 10 s)"),
        m("API", "DB", "đọc lần quét của người gọi"),
        m("API", "Q", "chờ thông báo của lần quét"),
        m("Q", "API", "thông báo hoặc hết 10 s", True),
        m("API", "APP", "trạng thái, chip khi đã xong", True)])),
    m("APP", "U", "hiện chip để xác nhận (UC13)", True)])
sq("SD01d", "don-lan-quet-ket", "SD01d — Dọn lần quét bị kẹt (UC34)",
   [("CRON", "actor", "Bộ lập lịch"), ("JOB", "control", "Tác vụ dọn (jobs)"), DB, Q], [
    m("CRON", "JOB", "chạy mỗi phút"),
    m("JOB", "DB", "tìm lần quét chưa vào hàng đợi"),
    m("DB", "JOB", "danh sách lần quét", True),
    frag("loop", ("mỗi lần quét đó", [m("JOB", "Q", "đưa lại job nhận diện"),
                                      m("JOB", "DB", "ghi thời điểm vào hàng đợi")])),
    m("JOB", "DB", "kẹt quá 60 s → «expired»"),
    m("JOB", "Q", "thông báo «expired»")])

# --- SD02 xác nhận quét (tách 3)
sq("SD02a", "sua-chip", "SD02a — Sửa chip nguyên liệu (UC13)", [U, APP, api("scan"), DB], [
    m("U", "APP", "mở kết quả quét"),
    m("APP", "API", "lấy chip và ảnh"),
    m("API", "APP", "chip, ảnh", True),
    frag("loop", ("còn chip cần sửa", [
        m("U", "APP", "đổi nhãn, số lượng hoặc xoá chip"),
        m("APP", "API", "gửi sửa chip"),
        m("API", "DB", "cập nhật chip (chưa ghi kho)"),
        m("API", "APP", "chip đã sửa", True)]))])
sq("SD02b", "xac-nhan-vao-kho", "SD02b — Xác nhận kết quả quét vào kho (UC13)",
   [U, APP, api("scan"), ("PAN", "control", "pantry"), DB], [
    m("U", "APP", "bấm Xác nhận"),
    m("APP", "API", "xác nhận lần quét"),
    m("API", "DB", "khoá lần quét, kiểm tra chủ và trạng thái"),
    frag("alt",
         ("đã xác nhận trước đó", [m("API", "APP", "trả lại kết quả cũ", True)]),
         ("chưa xong hoặc còn chip cần kiểm tra", [m("API", "APP", "409 / 422", True)]),
         ("hợp lệ", [m("API", "PAN", "tạo lô từ chip (mỗi chip một lô)"),
                     m("PAN", "DB", "ghi lô và giao dịch nhập kho"),
                     m("API", "PAN", "đánh dấu lô không thấy (chế độ toàn tủ)"),
                     m("API", "DB", "lần quét → «confirmed»; commit"),
                     m("API", "APP", "danh sách lô mới", True)])),
    m("APP", "U", "hiện kho đã cập nhật", True)])
sq("SD02c", "bo-lan-quet", "SD02c — Bỏ kết quả quét (UC13)", [U, APP, api("scan"), DB], [
    m("U", "APP", "bỏ kết quả quét"),
    m("APP", "API", "bỏ lần quét"),
    m("API", "DB", "«done» → «discarded»"),
    frag("alt",
         ("đã chuyển, hoặc đã bỏ từ trước", [m("API", "APP", "200 đã bỏ", True)]),
         ("đã xác nhận hoặc chưa xong", [m("API", "APP", "409 sai trạng thái", True)])),
    m("APP", "U", "về màn hình kho", True)])

# --- SD03 mâm cơm (tách 2)
PRO = ("PRO", "control", "Hồ sơ & kho")
sq("SD03a", "tao-mam", "SD03a — Tạo mâm cơm hôm nay (UC15)", [U, APP, api("meal"), PRO, DB], [
    m("U", "APP", "chọn bữa, số người, thời gian"),
    m("APP", "API", "tạo mâm (khóa lũy đẳng)"),
    m("API", "PRO", "lấy ràng buộc bữa"),
    m("PRO", "API", "dị ứng, chế độ ăn, kcal mục tiêu", True),
    m("API", "PRO", "lấy lô khả dụng"),
    m("PRO", "API", "khoảng gam, độ gấp", True),
    m("API", "DB", "đọc món đã xuất bản"),
    frag("alt",
         ("có mâm khả thi", [m("API", "DB", "lưu mâm «proposed», khóa lũy đẳng"),
                             m("API", "APP", "mâm, dòng lý do, số bát cơm", True)]),
         ("không có mâm khả thi", [m("API", "APP", "422: nguyên liệu còn thiếu", True)])),
    m("APP", "U", "hiện kết quả", True)])
sq("SD03b", "nhan-mam", "SD03b — Nhận mâm cơm (UC15)", [U, APP, api("meal"), DB], [
    m("U", "APP", "bấm Nhận mâm"),
    m("APP", "API", "nhận mâm"),
    m("API", "DB", "«proposed» → «accepted» (đúng chủ)"),
    frag("alt",
         ("cập nhật được", [m("API", "APP", "200 mâm đã nhận", True)]),
         ("không thấy hoặc sai trạng thái", [m("API", "APP", "409 sai trạng thái", True)])),
    m("APP", "U", "hiện nút «Nấu cả mâm»", True)])

sq("SD04", "doi-mon", "SD04 — Đổi một món trong mâm (UC16)", [U, APP, api("meal"), PRO, DB], [
    m("U", "APP", "chọn món cần đổi và lý do"),
    m("APP", "API", "đổi món (khóa lũy đẳng)"),
    m("API", "DB", "khoá mâm, kiểm tra món đang dùng"),
    m("API", "PRO", "lấy ràng buộc và lô khả dụng"),
    m("PRO", "API", "ràng buộc, lô", True),
    frag("alt",
         ("có món thay", [m("API", "DB", "món cũ «swapped_out», thêm món mới"),
                          m("API", "APP", "mâm đã cập nhật", True)]),
         ("không còn ứng viên", [m("API", "APP", "422 không còn món thay", True)])),
    m("APP", "U", "hiện mâm", True)])

# --- SD05 thay thế (tách 3)
SUB = ("SUB", "control", "substitute")
sq("SD05a", "xem-goi-y-thay-the", "SD05a — Xem gợi ý thay thế nguyên liệu thiếu (UC17)",
   [U, APP, api("meal"), SUB, DB], [
    m("U", "APP", "bấm «Thiếu gì?»"),
    m("APP", "API", "lấy thay thế cho món"),
    m("API", "SUB", "gợi ý cho nguyên liệu thiếu"),
    frag("loop", ("mỗi nguyên liệu thiếu", [
        m("SUB", "DB", "tra cặp thay thế, lọc dị ứng, chế độ ăn"),
        m("DB", "SUB", "ứng viên", True)])),
    m("SUB", "API", "tối đa 3 gợi ý", True),
    m("API", "APP", "gợi ý", True),
    m("APP", "U", "hiện gợi ý", True)])
sq("SD05b", "chon-thay-the", "SD05b — Chọn một thay thế (UC17)", [U, APP, api("meal"), SUB, DB], [
    m("U", "APP", "chọn một gợi ý"),
    m("APP", "API", "ghi thay thế cho món"),
    m("API", "SUB", "kiểm tra cặp được phép"),
    m("SUB", "API", "đạt / vi phạm", True),
    frag("alt",
         ("vi phạm dị ứng, chế độ ăn hoặc khác nhóm", [m("API", "APP", "422 không hợp lệ", True)]),
         ("hợp lệ", [m("API", "DB", "ghi thay thế đã chọn"),
                     m("API", "APP", "món đã cập nhật", True)])),
    m("APP", "U", "hiện món", True)])
sq("SD05c", "them-di-cho", "SD05c — Thêm nguyên liệu thiếu vào danh sách đi chợ (UC18)",
   [U, APP, api("substitute"), DB], [
    m("U", "APP", "chọn «Mua thêm»"),
    m("APP", "API", "thêm mục đi chợ"),
    m("API", "DB", "ghi mục đi chợ «open»"),
    m("API", "APP", "mục đã thêm", True),
    m("APP", "U", "hiện danh sách đi chợ", True)])

# --- SD06 nấu (tách 3)
sq("SD06a", "mo-phien-nau", "SD06a — Mở phiên nấu và lập lịch (UC19)",
   [U, APP, api("cooking"), ("MEAL", "control", "meal + catalog"), DB], [
    m("U", "APP", "«Nấu cả mâm», chọn giờ dọn"),
    m("APP", "API", "mở phiên nấu (khóa lũy đẳng)"),
    m("API", "MEAL", "lấy mâm để nấu (kiểm tra chủ)"),
    m("MEAL", "API", "mâm, các bước nấu", True),
    frag("alt",
         ("mâm chưa nhận hoặc đã có phiên", [m("API", "APP", "409 sai trạng thái", True)]),
         ("mâm «accepted»", [m("API", "DB", "ghi phiên «in_progress» và lịch các bước"),
                             m("API", "APP", "201 lịch nấu", True)])),
    m("APP", "U", "hiện lịch nấu (chạy được khi mất mạng)", True)])
sq("SD06b", "nau-xong", "SD06b — Nấu xong một chạm (UC20)",
   [U, APP, api("cooking"), ("PAN", "control", "pantry"), DB], [
    m("U", "APP", "bấm «Nấu xong», đánh giá món"),
    m("APP", "API", "hoàn tất phiên (khóa lũy đẳng)"),
    m("API", "DB", "tra phản hồi đã lưu theo khóa"),
    frag("alt",
         ("khóa đã dùng (gửi lại)", [m("API", "APP", "phản hồi đã lưu, không trừ kho lần hai", True)]),
         ("khóa mới, phiên «in_progress»", [
             m("API", "PAN", "trừ kho, lô gấp nhất trước"),
             m("PAN", "DB", "ghi giao dịch trừ kho"),
             m("API", "DB", "phiên «completed», mâm «cooked», ghi tương tác"),
             m("API", "DB", "lưu phản hồi lũy đẳng; commit"),
             m("API", "APP", "200 lượng đã trừ, hạn hoàn tác", True)])),
    m("APP", "U", "hiện kết quả và nút Hoàn tác", True)])
sq("SD06c", "hoan-tac", "SD06c — Hoàn tác trừ kho (UC21)",
   [U, APP, api("cooking"), ("PAN", "control", "pantry"), DB], [
    m("U", "APP", "bấm «Hoàn tác»"),
    m("APP", "API", "hoàn tác phiên"),
    m("API", "DB", "khoá phiên, đọc thời điểm hoàn tất"),
    frag("alt",
         ("«completed» và còn trong 10 phút", [
             m("API", "PAN", "đảo giao dịch trừ kho của phiên"),
             m("PAN", "DB", "ghi giao dịch đảo; lô có lại lượng"),
             m("API", "DB", "phiên «reverted», mâm về «accepted»"),
             m("API", "APP", "200 đã hoàn tác", True)]),
         ("đã quá 10 phút", [m("API", "APP", "409 hết hạn hoàn tác", True)])),
    m("APP", "U", "hiện kho", True)])

# --- SD07 đồng ý (tách 2)
sq("SD07a", "rut-dong-y", "SD07a — Rút đồng ý theo mục đích (UC05)", [U, APP, api("privacy"), DB, Q], [
    m("U", "APP", "tắt một mục đích"),
    m("APP", "API", "rút đồng ý"),
    m("API", "DB", "đọc đồng ý hiện hành"),
    frag("alt",
         ("mục đích bắt buộc hoặc chưa đồng ý", [m("API", "APP", "không đổi", True)]),
         ("đang đồng ý", [m("API", "DB", "ghi sự kiện rút, vô hiệu token, tạo yêu cầu"),
                          m("API", "Q", "đưa job xoá dữ liệu mục đích"),
                          m("API", "APP", "202 đã ghi nhận", True)])),
    m("APP", "U", "báo đã rút; làm mới phiên", True)])
sq("SD07b", "xoa-du-lieu-muc-dich", "SD07b — Xoá dữ liệu của mục đích đã rút (UC05)",
   [Q, ("WK", "control", "Worker (privacy)"), DB, FS], [
    m("Q", "WK", "giao job xoá (mục đích)"),
    m("WK", "DB", "yêu cầu → «in_progress»"),
    frag("alt",
         ("health_profile", [m("WK", "DB", "xoá cột sức khoẻ mã hoá")]),
         ("personalization", [m("WK", "DB", "xoá tương tác cá nhân hoá")]),
         ("photo_contribution", [m("WK", "FS", "xoá ảnh đã góp"),
                                 m("WK", "DB", "bỏ cờ góp ảnh")])),
    m("WK", "DB", "yêu cầu → «completed» (≤ 24 giờ)")])

sq("SD08", "lam-moi-token", "SD08 — Làm mới phiên bằng refresh token xoay vòng (UC02)",
   [APP, api("identity"), DB], [
    m("APP", "API", "làm mới phiên (refresh token)"),
    m("API", "DB", "khoá và tra token theo băm"),
    frag("alt",
         ("token đã thu hồi (bị dùng lại)", [m("API", "DB", "thu hồi cả họ token"),
                                            m("API", "APP", "401 đăng nhập lại", True)]),
         ("hết hạn hoặc tài khoản chờ xoá", [m("API", "APP", "401", True)]),
         ("hợp lệ", [m("API", "DB", "thu hồi token cũ, cấp token mới cùng họ"),
                     m("API", "APP", "access token và refresh token mới", True)]))])

# --- SD09 tải dữ liệu (tách 3)
sq("SD09a", "yeu-cau-tai-du-lieu", "SD09a — Gửi yêu cầu tải dữ liệu cá nhân (UC06)",
   [U, APP, api("privacy"), DB, Q], [
    m("U", "APP", "«Tải dữ liệu của tôi»"),
    m("APP", "API", "tạo yêu cầu export"),
    m("API", "DB", "tìm yêu cầu export đang mở"),
    frag("alt",
         ("đã có yêu cầu đang mở", [m("API", "APP", "trả yêu cầu đang mở", True)]),
         ("chưa có", [m("API", "DB", "ghi yêu cầu «received»"),
                      m("API", "Q", "đưa job xuất dữ liệu"),
                      m("API", "APP", "202 mã yêu cầu", True)])),
    m("APP", "U", "báo đang chuẩn bị tệp", True)])
sq("SD09b", "worker-tao-tep-xuat", "SD09b — Worker tạo tệp dữ liệu cá nhân (UC06)",
   [Q, ("WK", "control", "Worker (privacy)"), DB, FS], [
    m("Q", "WK", "giao job xuất"),
    m("WK", "DB", "yêu cầu → «in_progress»"),
    m("WK", "DB", "đọc dữ liệu của người dùng theo danh mục"),
    m("DB", "WK", "bản ghi (giải mã cột sức khoẻ)", True),
    m("WK", "FS", "ghi tệp ZIP (JSON + ảnh)"),
    m("WK", "DB", "yêu cầu → «completed», ghi khoá tệp")])
sq("SD09c", "tai-tep-du-lieu", "SD09c — Theo dõi và tải tệp dữ liệu (UC06)",
   [U, APP, api("privacy"), DB, FS], [
    frag("loop", ("đến khi «completed»", [
        m("APP", "API", "xem trạng thái yêu cầu"),
        m("API", "DB", "đọc yêu cầu của người gọi"),
        m("API", "APP", "trạng thái", True)])),
    m("U", "APP", "bấm Tải về"),
    m("APP", "API", "tải tệp kết quả"),
    m("API", "FS", "đọc tệp theo khoá"),
    m("API", "APP", "tệp ZIP", True)])

# --- SD10 mô hình (tách 4)
OP = ("OP", "actor", "Người vận hành mô hình")
CLI = ("CLI", "boundary", "CLI tastoria")
ML = ("ML", "control", "mlops")
SVC = ("SVC", "control", "api + worker")
sq("SD10a", "dang-ky-mo-hinh", "SD10a — Đăng ký phiên bản mô hình (UC29)", [OP, CLI, ML, FS, DB], [
    m("OP", "CLI", "mlops register <tên> <tệp> --metrics"),
    m("CLI", "ML", "đăng ký (tệp, số đo)"),
    m("ML", "DB", "tra trùng (tên, phiên bản)"),
    frag("alt",
         ("đã có", [m("ML", "CLI", "lỗi: phiên bản đã tồn tại", True)]),
         ("chưa có", [m("ML", "FS", "chép tệp ONNX vào models/"),
                      m("ML", "DB", "tạo phiên bản «candidate», sha256"),
                      m("ML", "CLI", "mã phiên bản", True)])),
    m("CLI", "OP", "kết quả", True)])
sq("SD10b", "kiem-dinh-mo-hinh", "SD10b — Kiểm định phiên bản mô hình (UC29)", [OP, CLI, ML, FS, DB], [
    m("OP", "CLI", "mlops gate <tên> <phiên bản>"),
    m("CLI", "ML", "kiểm định"),
    m("ML", "FS", "chạy hai bản trên tập test khoá"),
    m("ML", "FS", "ghi báo cáo kiểm định"),
    frag("alt",
         ("không kém hơn biên cho phép", [m("ML", "DB", "→ «validated»")]),
         ("kém hơn", [m("ML", "DB", "→ «rejected»")])),
    m("ML", "CLI", "kết quả kiểm định", True),
    m("CLI", "OP", "đạt / không đạt", True)])
sq("SD10c", "trien-khai-mo-hinh", "SD10c — Triển khai phiên bản mô hình (UC30)", [OP, CLI, ML, DB, SVC], [
    m("OP", "CLI", "mlops deploy <tên> <phiên bản>"),
    m("CLI", "ML", "triển khai"),
    m("ML", "DB", "đọc trạng thái phiên bản"),
    frag("alt",
         ("chưa «validated»", [m("ML", "CLI", "từ chối", True)]),
         ("«validated»", [m("ML", "DB", "đổi con trỏ triển khai, giữ bản trước"),
                          m("ML", "SVC", "khởi động lại api và worker"),
                          m("SVC", "DB", "đọc con trỏ, nạp mô hình, kiểm sha256"),
                          m("ML", "CLI", "đã triển khai", True)])),
    m("CLI", "OP", "kết quả", True)])
sq("SD10d", "quay-lui-mo-hinh", "SD10d — Quay lui phiên bản mô hình (UC30)", [OP, CLI, ML, DB, SVC], [
    m("OP", "CLI", "mlops rollback <tên>"),
    m("CLI", "ML", "quay lui"),
    m("ML", "DB", "đọc bản trước"),
    frag("alt",
         ("không có bản trước", [m("ML", "CLI", "lỗi: không có đích quay lui", True)]),
         ("có bản trước", [m("ML", "DB", "đổi chỗ bản đang chạy và bản trước"),
                           m("ML", "SVC", "khởi động lại api và worker"),
                           m("ML", "CLI", "đã quay lui (< 5 phút)", True)])),
    m("CLI", "OP", "kết quả", True)])


# =====================================================================  HOẠT ĐỘNG
def a(lane, text):
    return ("a", lane, text)


def IF(lane, q, yes, yes_items, no, no_items):
    """Nhánh yes đi tiếp ở cột chính, nhánh no ở cột phụ; nhánh kết thúc bằng STOP thì không gộp."""
    return ("if", lane, q, yes, list(yes_items), no, list(no_items))


def WHILE(lane, q, yes, body, no):
    return ("while", lane, q, yes, list(body), no)


STOP = ("stop",)


def ad(did, slug, title, lanes, items):
    return D("act", did, slug, title, lanes=list(lanes), items=list(items))


ad("AD01a", "quet-va-xac-nhan", "AD01a — Quét và xác nhận nguyên liệu (UC12, UC13)",
   ["Người dùng", "App", "Hệ thống"], [
    a("Người dùng", "Chọn chế độ quét, chụp 1–2 ảnh"),
    a("App", "Nén ảnh, gửi yêu cầu quét"),
    a("Hệ thống", "Kiểm tra ảnh, tạo lần quét"),
    a("Hệ thống", "Nhận diện nguyên liệu (worker)"),
    IF("Hệ thống", "Nhận diện thành công?", "có", [], "không",
       [a("App", "Báo lỗi, mời quét lại"), STOP]),
    a("App", "Hiện chip nguyên liệu"),
    WHILE("Người dùng", "Còn chip cần sửa?", "có", [a("Người dùng", "Sửa tên, số lượng hoặc xoá chip")], "không"),
    a("Người dùng", "Bấm Xác nhận"),
    a("Hệ thống", "Ghi lô và giao dịch nhập kho"),
    a("App", "Hiện kho đã cập nhật")])
ad("AD01b", "nhan-va-dieu-chinh-mam", "AD01b — Nhận và điều chỉnh mâm cơm (UC15–UC18)",
   ["Người dùng", "App", "Hệ thống"], [
    a("Người dùng", "Chọn bữa, số người, thời gian tối đa"),
    a("Hệ thống", "Ghép mâm từ kho và hồ sơ (AD02a, AD02b)"),
    IF("Hệ thống", "Có mâm khả thi?", "có", [], "không",
       [a("App", "Hiện nguyên liệu còn thiếu"), a("Người dùng", "Thêm vào danh sách đi chợ"), STOP]),
    a("App", "Hiện mâm và dòng lý do"),
    WHILE("Người dùng", "Muốn điều chỉnh mâm?", "có",
          [a("Người dùng", "Đổi món hoặc chọn thay thế"), a("Hệ thống", "Cập nhật mâm")], "không"),
    a("Người dùng", "Nhận mâm"),
    a("Hệ thống", "Mâm chuyển sang «accepted»")])
ad("AD01c", "nau-va-hoan-tat", "AD01c — Nấu cả mâm và hoàn tất bữa (UC19–UC21)",
   ["Người dùng", "App", "Hệ thống"], [
    a("Người dùng", "Bấm «Nấu cả mâm», chọn giờ dọn"),
    a("Hệ thống", "Lập lịch nấu theo số họng bếp"),
    a("App", "Hiện lịch các bước"),
    a("Người dùng", "Nấu theo lịch"),
    a("Người dùng", "Bấm «Nấu xong», đánh giá món"),
    a("Hệ thống", "Trừ kho, lô gấp nhất trước"),
    a("App", "Hiện lượng đã trừ và nút Hoàn tác"),
    IF("Người dùng", "Hoàn tác trong 10 phút?", "không", [], "có",
       [a("Hệ thống", "Ghi giao dịch đảo, mâm về «accepted»")]),
    a("App", "Cập nhật kho và nhật ký")])
ad("AD02a", "loc-mon-va-chuan-bi-kho", "AD02a — Ghép mâm: lọc món và chuẩn bị kho (UC15)",
   ["meal", "profile", "pantry"], [
    a("meal", "Nhận bữa, số người, thời gian"),
    a("profile", "Lấy dị ứng, chế độ ăn, kcal mục tiêu"),
    a("pantry", "Đọc lô khả dụng, khoảng gam"),
    a("pantry", "Tính độ gấp từng lô"),
    a("pantry", "Loại lô «kiểm tra trước khi dùng»"),
    a("meal", "Kiểm tra lô ghim (tối đa 2)"),
    a("meal", "Lọc cứng món theo dị ứng, chế độ ăn"),
    a("meal", "Xếp hạng gu từng món"),
    a("meal", "Xác định cấu trúc mâm theo số người")])
ad("AD02b", "ghep-va-chon-mam", "AD02b — Ghép mâm: duyệt tổ hợp và chọn mâm (UC15)",
   ["meal", "events"], [
    a("meal", "Chọn K món điểm cao mỗi slot"),
    WHILE("meal", "Còn tổ hợp?", "có", [a("meal", "Kiểm tra đủ kho, ước lượng thời gian nấu"),
                                        a("meal", "Giữ tổ hợp khả thi kèm điểm")], "không"),
    IF("meal", "Có mâm khả thi?", "có", [], "không",
       [a("meal", "Nới ràng buộc; hết bước nới thì trả 422"), STOP]),
    a("meal", "Chọn mâm điểm cao nhất"),
    a("meal", "Sinh dòng lý do, số bát cơm"),
    a("meal", "Lưu mâm «proposed»"),
    a("events", "Ghi tương tác «served» nếu có đồng ý"),
    a("meal", "Trả mâm cơm")])
ad("AD03a", "kiem-tra-xac-nhan-quet", "AD03a — Xác nhận quét: kiểm tra điều kiện (UC13)",
   ["App", "scan"], [
    a("App", "Gửi xác nhận lần quét"),
    a("scan", "Khoá lần quét của người gọi"),
    IF("scan", "Tìm thấy?", "có", [], "không", [a("scan", "Trả 404"), STOP]),
    IF("scan", "Đã xác nhận?", "chưa", [], "rồi", [a("scan", "Trả lại kết quả cũ"), STOP]),
    IF("scan", "Ở trạng thái done?", "có", [], "không", [a("scan", "Trả 409"), STOP]),
    IF("scan", "Còn chip cần kiểm tra?", "không", [], "còn", [a("scan", "Trả 422"), STOP]),
    a("scan", "Ghi kho từ chip (AD03b)")])
ad("AD03b", "ghi-kho-tu-chip", "AD03b — Xác nhận quét: ghi kho từ chip (UC13)",
   ["scan", "pantry", "catalog"], [
    a("scan", "Lấy các chip chưa xoá"),
    WHILE("scan", "Còn chip chưa quy đổi?", "còn", [a("catalog", "Tra gam mỗi đơn vị hoặc mức lượng"),
                                                     a("pantry", "Tính khoảng gam của chip")], "hết"),
    a("pantry", "Tạo mỗi chip một lô «in_stock»"),
    a("pantry", "Ghi giao dịch nhập kho"),
    IF("scan", "Chế độ toàn tủ?", "không", [], "có", [a("pantry", "Lô không thấy → «not_seen»")]),
    a("scan", "Lần quét → «confirmed»; commit")])
ad("AD04a", "thu-thap-du-lieu", "AD04a — Thu thập và xuất dữ liệu huấn luyện (UC12, UC28)",
   ["Người dùng", "Hệ thống", "Người vận hành mô hình"], [
    a("Người dùng", "Gửi ảnh quét"),
    IF("Hệ thống", "Đồng ý góp ảnh?", "có", [a("Hệ thống", "Chép ảnh sang kho góp")], "không",
       [a("Hệ thống", "Chỉ lưu ảnh tạm (30 ngày)")]),
    a("Người dùng", "Sửa chip khi xác nhận"),
    a("Hệ thống", "Ghi thao tác sửa làm nhãn yếu"),
    a("Người vận hành mô hình", "Chạy xuất dữ liệu huấn luyện"),
    a("Hệ thống", "Lọc theo đồng ý hiện hành"),
    a("Hệ thống", "Bí danh hoá mã người dùng")])
ad("AD04b", "gan-nhan-va-huan-luyen", "AD04b — Gán nhãn và huấn luyện mô hình (UC31)",
   ["Người vận hành mô hình", "Người gán nhãn", "Máy GPU lab"], [
    a("Người vận hành mô hình", "Đẩy ảnh chọn theo học chủ động"),
    a("Người gán nhãn", "Gán khung và nhãn độ tươi"),
    a("Người vận hành mô hình", "Kéo nhãn về"),
    a("Máy GPU lab", "Kiểm GPU rảnh, một job một lúc"),
    a("Máy GPU lab", "Huấn luyện có giới hạn bộ nhớ"),
    a("Máy GPU lab", "Ghi run vào MLflow"),
    a("Máy GPU lab", "Xuất ONNX")])
ad("AD04c", "dang-ky-trien-khai", "AD04c — Đăng ký, kiểm định và triển khai mô hình (UC29, UC30)",
   ["Người vận hành mô hình", "Hệ thống", "Worker"], [
    a("Người vận hành mô hình", "Đăng ký phiên bản"),
    a("Hệ thống", "So với bản đang chạy trên tập test khoá"),
    IF("Hệ thống", "Đạt cổng?", "đạt", [], "không", [a("Hệ thống", "Đánh dấu «rejected»"), STOP]),
    a("Hệ thống", "Đánh dấu «validated»"),
    a("Người vận hành mô hình", "Triển khai"),
    a("Hệ thống", "Đổi con trỏ, khởi động lại"),
    a("Worker", "Nạp ONNX, kiểm sha256"),
    IF("Người vận hành mô hình", "Bản mới có sự cố?", "không", [], "có",
       [a("Người vận hành mô hình", "Quay lui về bản trước")])])
ad("AD05", "xoa-tai-khoan", "AD05 — Xoá tài khoản và toàn bộ dữ liệu (UC07)",
   ["Người dùng", "App", "Hệ thống", "Worker"], [
    a("Người dùng", "Chọn Xoá tài khoản"),
    a("App", "Hiện hậu quả, hỏi xác nhận"),
    IF("Người dùng", "Xác nhận xoá?", "có", [], "không", [STOP]),
    a("App", "Gửi yêu cầu xoá"),
    a("Hệ thống", "Ghi yêu cầu, thu hồi mọi phiên"),
    a("Hệ thống", "Đưa job xoá vào hàng đợi"),
    a("Worker", "Xoá ảnh và tệp xuất"),
    a("Worker", "Xoá dữ liệu trong CSDL"),
    a("Worker", "Giữ bằng chứng ẩn danh, đóng yêu cầu")])
ad("AD06a", "tham-gia-khao-sat", "AD06a — Tham gia khảo sát gu (UC23)",
   ["Người tham gia khảo sát", "Hệ thống"], [
    a("Người tham gia khảo sát", "Mở link khảo sát"),
    a("Hệ thống", "Hiện điều khoản khảo sát"),
    IF("Người tham gia khảo sát", "Đồng ý?", "có", [], "không",
       [a("Người tham gia khảo sát", "Rời trang, không lưu gì"), STOP]),
    a("Hệ thống", "Tạo người tham gia ẩn danh, giao 45 món"),
    WHILE("Người tham gia khảo sát", "Còn món?", "còn",
          [a("Người tham gia khảo sát", "Chấm món 1–5"), a("Hệ thống", "Lưu điểm")], "hết"),
    a("Người tham gia khảo sát", "Chọn 5 món hay ăn"),
    a("Hệ thống", "Lưu, đánh dấu hoàn tất")])
ad("AD06b", "quan-ly-dot-khao-sat", "AD06b — Quản lý đợt khảo sát (UC24)",
   ["Người vận hành mô hình", "Hệ thống"], [
    a("Người vận hành mô hình", "Tạo phiếu: 10 món neo, 35 ngẫu nhiên"),
    a("Hệ thống", "Lưu phiếu, mở phiếu"),
    a("Người vận hành mô hình", "Theo dõi số người tham gia"),
    a("Người vận hành mô hình", "Xuất kết quả"),
    a("Hệ thống", "Xuất điểm, món hay ăn theo người tham gia")])


# =====================================================================  TRẠNG THÁI
def st(did, slug, title, states, trans, grid):
    """states: [(khoá, tên, hành động entry hoặc None)]; '*' = khởi đầu; khoá bắt đầu bằng 'c' + kiểu choice.
    grid: khoá -> (cột, hàng) cho bố cục VP."""
    return D("state", did, slug, title, states=list(states), trans=list(trans), grid=grid)


st("ST01", "scan", "ST01 — Trạng thái lần quét (Scan)",
   [("queued", "queued", None), ("processing", "processing", None), ("cErr", "<<choice>>", None),
    ("done", "done", None), ("failed", "failed", None), ("expired", "expired", None),
    ("confirmed", "confirmed", None), ("discarded", "discarded", None)],
   [("*", "queued", "tạo lần quét"), ("queued", "processing", "worker nhận job"),
    ("processing", "done", "nhận diện xong"), ("processing", "cErr", "lỗi nhận diện"),
    ("cErr", "queued", "[còn lượt thử]"), ("cErr", "failed", "[lần thứ 3]"),
    ("queued", "expired", "quá 60 s"), ("done", "confirmed", "xác nhận"), ("done", "discarded", "bỏ")],
   {"*": (0, 0), "queued": (0, 1), "processing": (1, 1), "done": (2, 1), "cErr": (1, 2),
    "failed": (1, 3), "expired": (0, 3), "confirmed": (3, 0), "discarded": (3, 2)})
st("ST02", "meal-plan", "ST02 — Trạng thái mâm cơm (MealPlan)",
   [("proposed", "proposed", None), ("accepted", "accepted", None), ("cooked", "cooked", None),
    ("abandoned", "abandoned", None), ("expired", "expired", None)],
   [("*", "proposed", "tạo mâm"), ("proposed", "accepted", "nhận mâm"),
    ("proposed", "expired", "tạo mâm mới / hết giờ bữa"), ("accepted", "cooked", "phiên nấu hoàn tất"),
    ("cooked", "accepted", "hoàn tác [≤ 10 phút]"), ("accepted", "abandoned", "tạo mâm mới / hết giờ bữa")],
   {"*": (0, 0), "proposed": (0, 1), "accepted": (1, 1), "cooked": (2, 1), "expired": (0, 2),
    "abandoned": (1, 2)})
st("ST03", "cook-session", "ST03 — Trạng thái phiên nấu (CookSession)",
   [("in_progress", "in_progress", "lập lịch nấu"), ("completed", "completed", "trừ kho"),
    ("reverted", "reverted", None), ("abandoned", "abandoned", None), ("sealed", "sealed", None)],
   [("*", "in_progress", "mở phiên"), ("in_progress", "completed", "nấu xong"),
    ("completed", "reverted", "hoàn tác [≤ 10 phút]"), ("completed", "sealed", "sau 10 phút"),
    ("in_progress", "abandoned", "bỏ phiên")],
   {"*": (0, 0), "in_progress": (0, 1), "completed": (1, 1), "reverted": (2, 1), "sealed": (1, 2),
    "abandoned": (0, 2)})
st("ST04", "consent", "ST04 — Trạng thái đồng ý theo mục đích (Consent)",
   [("none", "none", None), ("granted", "granted", None), ("withdrawn", "withdrawn", "xoá dữ liệu ≤ 24 giờ"),
    ("superseded", "superseded", "hỏi lại đồng ý")],
   [("*", "none", "đăng ký tài khoản"), ("none", "granted", "đồng ý"), ("granted", "withdrawn", "rút"),
    ("withdrawn", "granted", "đồng ý lại"), ("granted", "superseded", "có điều khoản mới"),
    ("superseded", "granted", "đồng ý bản mới"), ("superseded", "withdrawn", "rút")],
   {"*": (0, 0), "none": (0, 1), "granted": (1, 1), "withdrawn": (2, 1), "superseded": (1, 2)})
st("ST05", "pantry-lot", "ST05 — Trạng thái lô kho (PantryLot)",
   [("in_stock", "in_stock", None), ("not_seen", "not_seen", "hỏi lô còn không"),
    ("used_up", "used_up", None), ("discarded", "discarded", None)],
   [("*", "in_stock", "xác nhận quét / thêm tay"), ("in_stock", "not_seen", "quét toàn tủ không thấy"),
    ("not_seen", "in_stock", "xác nhận còn / thấy lại"), ("not_seen", "discarded", "bỏ"),
    ("in_stock", "discarded", "bỏ"), ("in_stock", "used_up", "hết lượng"),
    ("used_up", "in_stock", "hoàn tác nấu")],
   {"*": (0, 0), "in_stock": (1, 1), "not_seen": (0, 2), "used_up": (2, 1), "discarded": (1, 3)})
st("ST06", "account", "ST06 — Trạng thái tài khoản (Account)",
   [("active", "active", None), ("locked", "locked", "khoá 15 phút"),
    ("deletion_requested", "deletion_requested", "thu hồi mọi phiên"), ("deleted", "deleted", None)],
   [("*", "active", "đăng ký"), ("active", "locked", "sai mật khẩu lần 5"), ("locked", "active", "sau 15 phút"),
    ("active", "deletion_requested", "yêu cầu xoá"), ("locked", "deletion_requested", "yêu cầu xoá"),
    ("deletion_requested", "deleted", "job xoá xong [≤ 24 giờ]"), ("deleted", "#", "")],
   {"*": (0, 0), "active": (0, 1), "locked": (1, 1), "deletion_requested": (0, 2), "deleted": (0, 3),
    "#": (1, 3)})
st("ST07", "model-version", "ST07 — Trạng thái phiên bản mô hình (ModelVersion)",
   [("candidate", "candidate", None), ("cGate", "<<choice>>", None), ("validated", "validated", None),
    ("rejected", "rejected", None), ("active", "active", "nạp ở api, worker"), ("retired", "retired", None)],
   [("*", "candidate", "đăng ký"), ("candidate", "cGate", "kiểm định"), ("cGate", "validated", "[đạt]"),
    ("cGate", "rejected", "[không đạt]"), ("validated", "active", "triển khai / quay lui"),
    ("active", "validated", "bị thay / quay lui"), ("validated", "retired", "rời vị trí bản trước")],
   {"*": (0, 0), "candidate": (0, 1), "cGate": (1, 1), "validated": (2, 1), "rejected": (1, 2),
    "active": (3, 1), "retired": (2, 2)})
st("ST08", "dsr-request", "ST08 — Trạng thái yêu cầu dữ liệu (DsrRequest)",
   [("received", "received", None), ("in_progress", "in_progress", None), ("completed", "completed", None),
    ("rejected", "rejected", None)],
   [("*", "received", "gửi yêu cầu"), ("received", "in_progress", "worker nhận job"),
    ("in_progress", "completed", "job xong / nhân sự xử lý"), ("in_progress", "rejected", "nhân sự từ chối"),
    ("received", "completed", "nhân sự chấp nhận"), ("received", "rejected", "nhân sự từ chối")],
   {"*": (0, 0), "received": (0, 1), "in_progress": (1, 1), "completed": (2, 1), "rejected": (1, 2)})


# =====================================================================  LỚP
def C(key, name, attrs=(), ops=(), st=None):
    return (key, name, list(attrs), list(ops), st)


def cl(did, slug, title, classes, rels, grid, kind="class"):
    """rels: (kiểu, a, b, nhãn, bội số a, bội số b); kiểu: assoc | comp | dep | gen."""
    return D(kind, did, slug, title, classes=list(classes), rels=list(rels), grid=grid)


TK = C("TK", "Tài khoản", ["email: Email", "vaiTrò: VaiTrò", "trạngThái: TrạngTháiTK"])
NL = C("NL", "Nguyên liệu", ["tên: Chuỗi", "đếmĐược: Boolean", "hạnDùng: Số ngày"])
MON = C("MON", "Món", ["tên: Chuỗi", "slot: Slot", "khẩuPhầnGốc: Số nguyên", "trạngThái: TrạngTháiMón"])
MAM = C("MAM", "Mâm cơm", ["bữa: Bữa", "sốNgười: Số nguyên", "kcalMụcTiêu: Số thực", "trạngThái: TrạngTháiMâm"])

cl("CL01a", "mien-tai-khoan-dong-y", "CL01a — Miền: tài khoản, hồ sơ và đồng ý", [
    TK,
    C("HS", "Hồ sơ", ["giớiTính: GiớiTính", "nămSinh: Năm", "chiềuCao: cm", "cânNặng: kg", "kcalMụcTiêu: Số thực"]),
    C("CD", "Cài đặt bếp", ["sốHọngBếp: Số nguyên", "múiGiờ: Chuỗi", "ngônNgữ: NgônNgữ"]),
    C("MD", "Mục đích đồng ý", ["mã: Chuỗi", "nhạyCảm: Boolean", "bắtBuộc: Boolean"]),
    C("PB", "Phiên bản điều khoản", ["phiênBản: Chuỗi", "hiệuLựcTừ: Thời điểm"]),
    C("SK", "Sự kiện đồng ý", ["hànhĐộng: HànhĐộngĐồngÝ", "kênh: KênhĐồngÝ", "thờiĐiểm: Thời điểm"])],
   [("comp", "TK", "HS", "", "1", "0..1"), ("comp", "TK", "CD", "", "1", "1"),
    ("assoc", "TK", "SK", "ghi", "1", "0..*"), ("assoc", "MD", "PB", "có", "1", "1..*"),
    ("assoc", "PB", "SK", "theo", "1", "0..*")],
   {"HS": (0, 0), "TK": (1, 0), "CD": (2, 0), "SK": (1, 1), "PB": (2, 1), "MD": (2, 2)})
cl("CL01b", "mien-yeu-cau-du-lieu", "CL01b — Miền: yêu cầu dữ liệu và kiểm toán", [
    TK,
    C("YC", "Yêu cầu chủ thể dữ liệu", ["loại: LoạiYêuCầu", "trạngThái: TrạngTháiYêuCầu",
                                        "nhậnLúc: Thời điểm", "xongLúc: Thời điểm", "subjectRef: Băm"]),
    C("KT", "Nhật ký kiểm toán", ["vaiTrò: Chuỗi", "hànhĐộng: Chuỗi", "đốiTượng: Chuỗi", "mụcĐích: Chuỗi",
                                  "thờiĐiểm: Thời điểm"])],
   [("assoc", "TK", "YC", "gửi", "0..1", "0..*"), ("assoc", "TK", "KT", "thực hiện", "0..1", "0..*")],
   {"TK": (0, 0), "YC": (1, 0), "KT": (1, 1)})
cl("CL01c", "mien-danh-muc-nguyen-lieu", "CL01c — Miền: nguyên liệu, dinh dưỡng và dị ứng", [
    C("NTP", "Nhóm thực phẩm", ["mã: Chuỗi", "tên: Chuỗi"]), NL,
    C("TP", "Thực phẩm tham chiếu", ["nguồn: Chuỗi", "mãNguồn: Chuỗi", "tỉLệThải: %"]),
    C("CDD", "Chất dinh dưỡng", ["mã: Chuỗi", "đơnVị: Chuỗi"]),
    C("GT", "Giá trị dinh dưỡng", ["lượngTrên100g: Số thực"]),
    C("DU", "Nhóm dị ứng", ["mã: Chuỗi", "tên: Chuỗi"])],
   [("assoc", "NTP", "NL", "thuộc", "1", "0..*"), ("assoc", "NL", "TP", "tra", "0..*", "0..1"),
    ("assoc", "TP", "GT", "", "1", "0..*"), ("assoc", "CDD", "GT", "", "1", "0..*"),
    ("assoc", "NL", "DU", "chứa", "0..*", "0..*")],
   {"NTP": (0, 0), "NL": (1, 0), "DU": (2, 0), "TP": (1, 1), "GT": (1, 2), "CDD": (2, 2)})
cl("CL01d", "mien-mon-an", "CL01d — Miền: món ăn và công thức", [
    MON, C("TPM", "Thành phần món", ["lượng: Gam", "vaiTrò: VaiTròNL", "luônCó: Boolean"]),
    C("BN", "Bước nấu", ["sốBước: Số nguyên", "loại: LoạiBước", "phút: Số nguyên", "dùngBếp: Boolean"]),
    C("NL", "Nguyên liệu", ["tên: Chuỗi"]),
    C("DDM", "Dinh dưỡng món", ["kcal: Số thực", "đạm: Gam", "béo: Gam", "bộtĐường: Gam"]),
    C("THE", "Thẻ", ["loại: LoạiThẻ", "tên: Chuỗi"])],
   [("comp", "MON", "TPM", "", "1", "1..*"), ("assoc", "NL", "TPM", "", "1", "0..*"),
    ("comp", "MON", "BN", "", "1", "1..*"), ("comp", "MON", "DDM", "", "1", "0..1"),
    ("assoc", "MON", "THE", "", "0..*", "0..*")],
   {"MON": (1, 0), "TPM": (0, 1), "NL": (0, 2), "BN": (1, 1), "DDM": (2, 1), "THE": (2, 0)})
cl("CL01e", "mien-kho", "CL01e — Miền: kho nguyên liệu và đi chợ", [
    TK, C("NL", "Nguyên liệu", ["tên: Chuỗi"]),
    C("LO", "Lô kho", ["ngàyNhập: Thời điểm", "cănCứNgày: CănCứNgày", "gMin: Gam", "gMax: Gam",
                       "trạngThái: TrạngTháiLô"]),
    C("GD", "Giao dịch kho", ["lýDo: LýDoGiaoDịch", "deltaMin: Gam", "deltaMax: Gam", "thờiĐiểm: Thời điểm"]),
    C("DC", "Mục đi chợ", ["lượng: Chuỗi", "trạngThái: TrạngTháiMục"]),
    C("CT", "Cặp thay thế", ["slot: Slot", "cáchNấu: Chuỗi", "điểm: Số thực"])],
   [("assoc", "TK", "LO", "sở hữu", "1", "0..*"), ("assoc", "NL", "LO", "là", "1", "0..*"),
    ("comp", "LO", "GD", "phát sinh", "1", "1..*"), ("assoc", "TK", "DC", "", "1", "0..*"),
    ("assoc", "NL", "DC", "", "1", "0..*"), ("assoc", "NL", "CT", "gốc / thay", "2", "0..*")],
   {"TK": (0, 0), "LO": (1, 0), "GD": (2, 0), "DC": (0, 1), "NL": (1, 1), "CT": (2, 1)})
cl("CL01f", "mien-quet-anh", "CL01f — Miền: quét ảnh và nhận diện", [
    C("LQ", "Lần quét", ["chếĐộ: ChếĐộQuét", "trạngThái: TrạngTháiQuét", "sốLầnThử: Số nguyên"]),
    C("AQ", "Ảnh quét", ["thứTự: Số nguyên", "nhómNgăn: Số nguyên", "đãGóp: Boolean"]),
    C("KH", "Khung phát hiện", ["toạĐộ: Khung", "độTinCậy: Số thực", "xácSuấtTươi: Số thực"]),
    C("CHIP", "Chip nguyên liệu", ["nguồn: NguồnChip", "sốĐếmCuối: Số nguyên", "mứcLượng: MứcLượng",
                                   "thaoTác: ThaoTácChip"]),
    C("LTG", "Lớp thị giác", ["mã: Chuỗi", "cóMôHìnhTươi: Boolean"]), C("NL", "Nguyên liệu", ["tên: Chuỗi"])],
   [("comp", "LQ", "AQ", "", "1", "1..2"), ("comp", "AQ", "KH", "", "1", "0..*"),
    ("assoc", "KH", "LTG", "", "0..*", "1"), ("assoc", "KH", "CHIP", "gộp vào", "0..*", "0..1"),
    ("comp", "LQ", "CHIP", "đề xuất", "1", "0..*"), ("assoc", "CHIP", "NL", "", "0..*", "1")],
   {"LQ": (0, 0), "AQ": (1, 0), "KH": (2, 0), "CHIP": (1, 1), "LTG": (2, 1), "NL": (0, 1)})
cl("CL01g", "mien-mam-nau", "CL01g — Miền: mâm cơm và phiên nấu", [
    MAM, C("MTM", "Món trong mâm", ["slot: Slot", "hệSốKhẩuPhần: Số thực", "trạngThái: TrạngTháiMónMâm"]),
    C("TTDC", "Thay thế đã chọn", ["nguồn: NguồnThayThế"]),
    C("PN", "Phiên nấu", ["giờDọn: Thời điểm", "sốHọngBếp: Số nguyên", "trạngThái: TrạngTháiPhiên",
                          "hoànTấtLúc: Thời điểm"]),
    C("ML", "Mục lịch nấu", ["sốBước: Số nguyên", "bắtĐầu: Giây", "kếtThúc: Giây"]),
    C("MON", "Món", ["tên: Chuỗi"])],
   [("comp", "MAM", "MTM", "", "1", "2..3"), ("assoc", "MTM", "MON", "", "0..*", "1"),
    ("comp", "MTM", "TTDC", "", "1", "0..*"), ("assoc", "MAM", "PN", "được nấu", "1", "0..*"),
    ("comp", "PN", "ML", "", "1", "1..*")],
   {"MAM": (0, 0), "MTM": (1, 0), "MON": (2, 0), "TTDC": (1, 1), "PN": (0, 1), "ML": (0, 2)})
cl("CL01h", "mien-tuong-tac-mo-hinh", "CL01h — Miền: tương tác và phiên bản mô hình", [
    TK, C("TT", "Tương tác", ["loại: LoạiTươngTác", "thờiĐiểm: Thời điểm"]), C("MON", "Món", ["tên: Chuỗi"]),
    C("MAM", "Mâm cơm", ["trạngThái: TrạngTháiMâm"]),
    C("PBMH", "Phiên bản mô hình", ["tên: TênMôHình", "phiênBản: Chuỗi", "sha256: Băm", "trạngThái: TrạngTháiPB"]),
    C("TKMH", "Triển khai mô hình", ["tên: TênMôHình", "chuyểnLúc: Thời điểm"])],
   [("assoc", "TK", "TT", "ghi nhận", "1", "0..*"), ("assoc", "TT", "MON", "về", "0..*", "1"),
    ("assoc", "TT", "MAM", "trong", "0..*", "0..1"), ("assoc", "MAM", "PBMH", "xếp hạng bởi", "0..*", "0..1"),
    ("assoc", "TKMH", "PBMH", "đang chạy / bản trước", "0..*", "1..2")],
   {"TK": (0, 0), "TT": (1, 0), "MON": (2, 0), "MAM": (1, 1), "PBMH": (1, 2), "TKMH": (2, 2)})
cl("CL01i", "mien-khao-sat", "CL01i — Miền: khảo sát gu món ăn", [
    C("PKS", "Phiếu khảo sát", ["phiênBản: Chuỗi", "sốNeo: Số nguyên", "sốNgẫuNhiên: Số nguyên", "đangMở: Boolean"]),
    C("NTG", "Người tham gia khảo sát", ["kênh: KênhKhảoSát", "hoànTấtLúc: Thời điểm"]),
    C("PC", "Phân công món", ["thứTự: Số nguyên"]), C("DKS", "Điểm khảo sát", ["điểm: 1..5"]),
    C("MON", "Món", ["tên: Chuỗi"]), C("PB", "Phiên bản điều khoản", ["phiênBản: Chuỗi"])],
   [("assoc", "PKS", "NTG", "điền", "1", "0..*"), ("comp", "NTG", "PC", "được giao", "1", "1..*"),
    ("assoc", "PC", "MON", "", "0..*", "1"), ("comp", "PC", "DKS", "", "1", "0..1"),
    ("assoc", "NTG", "PB", "chấp nhận", "0..*", "1")],
   {"PKS": (0, 0), "NTG": (1, 0), "PB": (2, 0), "PC": (1, 1), "MON": (2, 1), "DKS": (1, 2)})

# --- BCE
B_, C_, E_ = "boundary", "control", "entity"
cl("CL02a", "bce-quet", "CL02a — Lớp phân tích BCE: UC12 Quét nguyên liệu", [
    C("BQ", "Màn hình Quét", ["chếĐộ", "ảnh[1..2]"], ["gửiẢnh()"], B_),
    C("CT", "Tạo lần quét", [], ["kiểmTraẢnh()", "tạoLầnQuét()"], C_),
    C("CS", "Nhận diện ảnh", [], ["nhậnDiện()", "gộpChip()"], C_),
    C("ELQ", "Lần quét", ["chếĐộ", "trạngThái"], [], E_),
    C("EAQ", "Ảnh quét", ["thứTự", "nhómNgăn", "đãGóp"], [], E_),
    C("ECH", "Chip nguyên liệu", ["sốĐếm", "mứcLượng"], [], E_)],
   [("assoc", "BQ", "CT", "", "", ""), ("assoc", "CT", "ELQ", "", "", ""), ("assoc", "CT", "EAQ", "", "", ""),
    ("assoc", "CS", "EAQ", "", "", ""), ("assoc", "CS", "ECH", "", "", "")],
   {"BQ": (0, 0), "CT": (1, 0), "ELQ": (2, 0), "EAQ": (2, 1), "CS": (1, 1), "ECH": (2, 2)})
cl("CL02b", "bce-xac-nhan-quet", "CL02b — Lớp phân tích BCE: UC13 Xác nhận kết quả quét", [
    C("BX", "Màn hình Xác nhận", ["danhSáchChip"], ["sửaChip()", "xácNhận()"], B_),
    C("CSC", "Sửa chip", [], ["cậpNhậtChip()"], C_),
    C("CX", "Xác nhận vào kho", [], ["xácNhận()", "quyĐổiLượng()"], C_),
    C("ECH", "Chip nguyên liệu", ["sốĐếm", "mứcLượng", "thaoTác"], [], E_),
    C("ELO", "Lô kho", ["khoảngGam", "trạngThái"], [], E_),
    C("EGD", "Giao dịch kho", ["lýDo", "delta"], [], E_)],
   [("assoc", "BX", "CSC", "", "", ""), ("assoc", "BX", "CX", "", "", ""), ("assoc", "CSC", "ECH", "", "", ""),
    ("assoc", "CX", "ECH", "", "", ""), ("assoc", "CX", "ELO", "", "", ""), ("assoc", "CX", "EGD", "", "", "")],
   {"BX": (0, 0), "CSC": (1, 0), "ECH": (2, 0), "CX": (1, 1), "ELO": (2, 1), "EGD": (2, 2)})
cl("CL03a", "bce-tao-mam", "CL03a — Lớp phân tích BCE: UC15 Tạo mâm cơm", [
    C("BM", "Màn hình Mâm cơm", ["bữa", "sốNgười"], ["yêuCầuMâm()"], B_),
    C("CT", "Tạo mâm", [], ["tạoMâm()"], C_),
    C("CG", "Ghép mâm", [], ["lọcCứng()", "xếpHạng()", "ghép()"], C_),
    C("EHS", "Hồ sơ", ["dịỨng", "chếĐộĂn", "kcalMụcTiêu"], [], E_),
    C("ELO", "Lô kho", ["khoảngGam", "độGấp"], [], E_),
    C("EM", "Mâm cơm", ["trạngThái", "kcalMụcTiêu"], [], E_)],
   [("assoc", "BM", "CT", "", "", ""), ("assoc", "CT", "CG", "", "", ""), ("assoc", "CT", "EM", "", "", ""),
    ("assoc", "CG", "EHS", "", "", ""), ("assoc", "CG", "ELO", "", "", "")],
   {"BM": (0, 0), "CT": (1, 0), "EM": (2, 0), "CG": (1, 1), "EHS": (2, 1), "ELO": (2, 2)})
cl("CL03b", "bce-nhan-mam", "CL03b — Lớp phân tích BCE: UC15 Xem và nhận mâm", [
    C("BM", "Màn hình Mâm cơm", ["dòngLýDo"], ["nhậnMâm()"], B_),
    C("CN", "Nhận mâm", [], ["nhận()"], C_),
    C("CSK", "Ghi tương tác", [], ["ghi()"], C_),
    C("EM", "Mâm cơm", ["trạngThái"], [], E_),
    C("EMM", "Món trong mâm", ["slot", "hệSốKhẩuPhần"], [], E_),
    C("ETT", "Tương tác", ["loại"], [], E_)],
   [("assoc", "BM", "CN", "", "", ""), ("assoc", "CN", "EM", "", "", ""), ("assoc", "CN", "CSK", "", "", ""),
    ("assoc", "EM", "EMM", "", "1", "2..3"), ("assoc", "CSK", "ETT", "", "", "")],
   {"BM": (0, 0), "CN": (1, 0), "EM": (2, 0), "CSK": (1, 1), "EMM": (2, 1), "ETT": (1, 2)})
cl("CL04a", "bce-nau-xong-tru-kho", "CL04a — Lớp phân tích BCE: UC20 Nấu xong – trừ kho", [
    C("BN", "Màn hình Nấu xong", ["đánhGiáMón"], ["nấuXong()"], B_),
    C("CH", "Hoàn tất phiên nấu", [], ["hoànTất()"], C_),
    C("CTK", "Trừ kho theo độ gấp", [], ["tínhLượngDùng()", "trừKho()"], C_),
    C("EPN", "Phiên nấu", ["trạngThái", "hoànTấtLúc"], [], E_),
    C("ELO", "Lô kho", ["khoảngGam", "độGấp"], [], E_),
    C("EGD", "Giao dịch kho", ["lýDo", "delta"], [], E_)],
   [("assoc", "BN", "CH", "", "", ""), ("assoc", "CH", "EPN", "", "", ""), ("assoc", "CH", "CTK", "", "", ""),
    ("assoc", "CTK", "ELO", "", "", ""), ("assoc", "CTK", "EGD", "", "", "")],
   {"BN": (0, 0), "CH": (1, 0), "EPN": (2, 0), "CTK": (1, 1), "ELO": (2, 1), "EGD": (2, 2)})
cl("CL04b", "bce-nau-xong-tuong-tac", "CL04b — Lớp phân tích BCE: UC20 Nấu xong – mâm và tương tác", [
    C("CH", "Hoàn tất phiên nấu", [], ["hoànTất()"], C_),
    C("CM", "Chuyển trạng thái mâm", [], ["đánhDấuĐãNấu()"], C_),
    C("CSK", "Ghi tương tác", [], ["ghi()"], C_),
    C("EM", "Mâm cơm", ["trạngThái"], [], E_),
    C("ETT", "Tương tác", ["loại", "thờiĐiểm"], [], E_),
    C("EDY", "Đồng ý hiện hành", ["mụcĐích", "hiệuLực"], [], E_)],
   [("assoc", "CH", "CM", "", "", ""), ("assoc", "CH", "CSK", "", "", ""), ("assoc", "CM", "EM", "", "", ""),
    ("assoc", "CSK", "ETT", "", "", ""), ("assoc", "CSK", "EDY", "", "", "")],
   {"CH": (0, 0), "CM": (1, 0), "EM": (2, 0), "CSK": (1, 1), "ETT": (2, 1), "EDY": (2, 2)})

# --- thiết kế
cl("CL05a", "thiet-ke-meal-dieu-phoi", "CL05a — Thiết kế module meal: điều phối và dữ liệu", [
    C("R", "MealRouter", [], ["create_plan()", "accept()", "swap()", "list_substitutes()", "choose_substitution()"], "router"),
    C("S", "MealService", [], ["create_plan()", "accept()", "swap_item()", "choose_substitution()",
                               "get_plan_for_cooking()"], "service"),
    C("RP", "MealRepository", [], ["add_plan()", "get_plan()", "set_status()", "swap_out()"], "repository"),
    C("RQ", "MealPlanRequest", ["meal: Meal", "persons: int", "max_minutes: int", "pinned_lot_ids: list"], [], "DTO"),
    C("MP", "MealPlan", ["meal: Meal", "persons: int", "status: PlanStatus", "e_target_kcal: float"], [], "domain"),
    C("MI", "MealPlanItem", ["slot: Slot", "recipe_id: UUID", "servings_scale: float", "status: ItemStatus"], [], "domain")],
   [("dep", "R", "S", "", "", ""), ("dep", "R", "RQ", "", "", ""), ("dep", "S", "RP", "", "", ""),
    ("dep", "RP", "MP", "", "", ""), ("comp", "MP", "MI", "", "1", "2..3")],
   {"R": (0, 0), "RQ": (1, 0), "S": (0, 1), "RP": (0, 2), "MP": (1, 2), "MI": (2, 2)})
cl("CL05b", "thiet-ke-meal-ghep-mam", "CL05b — Thiết kế module meal: dịch vụ ghép mâm", [
    C("S", "MealService", [], ["create_plan()", "swap_item()"], "service"),
    C("HF", "HardFilter", [], ["filter()"], "domain service"),
    C("TR", "TasteRanker", [], ["score()"], "domain service"),
    C("TC", "TrayComposer", [], ["compose()", "resolve_swap()"], "domain service"),
    C("ME", "MakespanEstimator", [], ["estimate()"], "domain service"),
    C("RB", "ReasonBuilder", [], ["build()"], "domain service")],
   [("dep", "S", "HF", "", "", ""), ("dep", "S", "TR", "", "", ""), ("dep", "S", "TC", "", "", ""),
    ("dep", "TC", "ME", "", "", ""), ("dep", "S", "RB", "", "", "")],
   {"S": (1, 0), "HF": (0, 1), "TR": (1, 1), "TC": (2, 1), "RB": (0, 2), "ME": (2, 2)})
cl("CL06a", "thiet-ke-pantry-dieu-phoi", "CL06a — Thiết kế module pantry: điều phối và dữ liệu", [
    C("R", "PantryRouter", [], ["list_lots()", "add_lot()", "update_lot()", "discard_lot()"], "router"),
    C("S", "PantryService", [], ["list_available_lots()", "add_lots_from_scan()", "mark_not_seen()",
                                 "deduct_for_cooking()", "revert_cooking()"], "service"),
    C("RP", "PantryRepository", [], ["add_lot()", "get_lot()", "balances()", "add_transaction()", "set_status()"],
      "repository"),
    C("LO", "PantryLot", ["ingredient_id: UUID", "acquired_at: datetime", "initial_g: GramRange", "status: LotStatus"],
      [], "domain"),
    C("TX", "PantryTransaction", ["reason: TxReason", "delta_g: GramRange", "ref_id: UUID", "reverses_id: int"], [],
      "domain"),
    C("GR", "GramRange", ["g_min: float", "g_max: float"], ["clamp_zero()"], "value object")],
   [("dep", "R", "S", "", "", ""), ("dep", "S", "RP", "", "", ""), ("dep", "RP", "LO", "", "", ""),
    ("comp", "LO", "TX", "", "1", "1..*"), ("dep", "LO", "GR", "", "", "")],
   {"R": (0, 0), "S": (0, 1), "RP": (0, 2), "LO": (1, 2), "TX": (2, 2), "GR": (1, 1)})
cl("CL06b", "thiet-ke-pantry-tinh-toan", "CL06b — Thiết kế module pantry: quy đổi lượng và độ gấp", [
    C("S", "PantryService", [], ["deduct_for_cooking()", "list_available_lots()"], "service"),
    C("UC", "UrgencyCalculator", [], ["u_time()", "u_img()", "urgency()"], "domain service"),
    C("QC", "QuantityConverter", [], ["from_count()", "from_level()"], "domain service"),
    C("DP", "DeductionPlanner", [], ["plan()"], "domain service"),
    C("UR", "Urgency", ["u: float", "source: str"], [], "value object"),
    C("FP", "FreshnessProbs", ["p_tuoi: float", "p_dung_som: float", "p_dung_ngay: float", "p_kiem_tra: float"], [],
      "value object")],
   [("dep", "S", "UC", "", "", ""), ("dep", "S", "QC", "", "", ""), ("dep", "S", "DP", "", "", ""),
    ("dep", "UC", "UR", "", "", ""), ("dep", "UC", "FP", "", "", "")],
   {"S": (1, 0), "QC": (0, 1), "UC": (1, 1), "DP": (2, 1), "UR": (0, 2), "FP": (1, 2)})
cl("CL07a", "thiet-ke-scan-dieu-phoi", "CL07a — Thiết kế module scan: điều phối và dữ liệu", [
    C("R", "ScanRouter", [], ["create_scan()", "get_scan()", "update_item()", "confirm()", "discard()"], "router"),
    C("S", "ScanService", [], ["create_scan()", "get_scan()", "confirm()", "discard()", "sweep_stuck_scans()"],
      "service"),
    C("RP", "ScanRepository", [], ["add_scan()", "get_scan()", "set_status()", "upsert_item()", "stuck_scans()"],
      "repository"),
    C("SC", "Scan", ["mode: ScanMode", "status: ScanStatus", "attempts: int", "enqueued_at: datetime"], [], "domain"),
    C("SI", "ScanImage", ["ordinal: int", "shelf_group: int", "storage_key: str", "contributed: bool"], [], "domain"),
    C("IT", "ScanItem", ["ingredient_id: UUID", "final_count: int", "qty_level: QtyLevel", "user_action: Action"], [],
      "domain")],
   [("dep", "R", "S", "", "", ""), ("dep", "S", "RP", "", "", ""), ("dep", "RP", "SC", "", "", ""),
    ("comp", "SC", "SI", "", "1", "1..2"), ("comp", "SC", "IT", "", "1", "0..*")],
   {"R": (0, 0), "S": (0, 1), "RP": (0, 2), "SC": (1, 2), "SI": (2, 2), "IT": (1, 1)})
cl("CL07b", "thiet-ke-scan-nhan-dien", "CL07b — Thiết kế module scan: job nhận diện", [
    C("J", "InferenceJob", [], ["warm_up()", "run()"], "worker job"),
    C("IS", "ImageSanitizer", [], ["sanitize()"], "domain service"),
    C("DM", "DetectionMerger", [], ["merge()"], "domain service"),
    C("CB", "ChipBuilder", [], ["build()"], "domain service"),
    C("DT", "Detection", ["box: Box", "confidence: float", "p_fresh: FreshnessProbs"], [], "domain"),
    C("IT", "ScanItem", ["ingredient_id: UUID", "model_count: int"], [], "domain")],
   [("dep", "J", "DM", "", "", ""), ("dep", "J", "CB", "", "", ""), ("dep", "DM", "DT", "", "", ""),
    ("dep", "CB", "IT", "", "", ""), ("dep", "J", "IS", "", "", "")],
   {"J": (1, 0), "IS": (0, 0), "DM": (0, 1), "CB": (2, 1), "DT": (0, 2), "IT": (2, 2)})
cl("CL08a", "thiet-ke-cooking-dieu-phoi", "CL08a — Thiết kế module cooking: điều phối và dữ liệu", [
    C("R", "CookingRouter", [], ["start()", "complete()", "undo()", "abandon()"], "router"),
    C("S", "CookingService", [], ["start()", "complete()", "undo()", "abandon()"], "service"),
    C("RP", "CookingRepository", [], ["add_session()", "lock_session()", "add_entries()", "transition()"],
      "repository"),
    C("CS", "CookSession", ["meal_plan_id: UUID", "status: SessionStatus", "serve_at: datetime", "burners: int",
                            "completed_at: datetime"], [], "domain"),
    C("SE", "ScheduleEntry", ["recipe_id: UUID", "step_no: int", "start_offset_s: int", "end_offset_s: int"], [],
      "domain"),
    C("CC", "CookCompletion", ["cook_session: CookSessionOut", "deductions: list", "interactions_recorded: int"], [],
      "DTO")],
   [("dep", "R", "S", "", "", ""), ("dep", "S", "RP", "", "", ""), ("dep", "RP", "CS", "", "", ""),
    ("comp", "CS", "SE", "", "1", "1..*"), ("dep", "S", "CC", "", "", "")],
   {"R": (0, 0), "S": (0, 1), "CC": (1, 1), "RP": (0, 2), "CS": (1, 2), "SE": (2, 2)})
cl("CL08b", "thiet-ke-cooking-lap-lich", "CL08b — Thiết kế module cooking: lập lịch và hoàn tác", [
    C("S", "CookingService", [], ["start()", "complete()", "undo()"], "service"),
    C("SC", "CookScheduler", [], ["solve()"], "domain service"),
    C("NC", "NeedCalculator", [], ["needs()"], "domain service"),
    C("UP", "UndoPolicy", [], ["can_undo()"], "domain service"),
    C("SH", "Schedule", ["entries: list", "makespan_s: int"], [], "value object"),
    C("CS", "CookSession", ["status: SessionStatus", "completed_at: datetime"], [], "domain")],
   [("dep", "S", "SC", "", "", ""), ("dep", "S", "NC", "", "", ""), ("dep", "S", "UP", "", "", ""),
    ("dep", "SC", "SH", "", "", ""), ("dep", "UP", "CS", "", "", "")],
   {"S": (1, 0), "SC": (0, 1), "NC": (1, 1), "UP": (2, 1), "SH": (0, 2), "CS": (2, 2)})


# =====================================================================  THÀNH PHẦN / TRIỂN KHAI / GÓI
def box(key, name, st=None, parent=None):
    return (key, name, st, parent)


def struct(kind, did, slug, title, boxes, links, grid):
    """kind: comp | deploy | pkg. links: (a, b, nhãn). grid: khoá -> (cột, hàng); hộp con nằm trong cha."""
    return D(kind, did, slug, title, boxes=list(boxes), links=list(links), grid=grid)


struct("comp", "CP01a", "he-thong", "CP01a — Thành phần: các khối chạy của hệ thống", [
    box("App", "App Tastoria (Expo)", "client"), box("Nginx", "nginx", "reverse proxy"),
    box("Api", "API (FastAPI, modular monolith)", "process"), box("Worker", "Worker (RQ + ONNX)", "process"),
    box("Sched", "Scheduler (cron)", "process"), box("Pg", "PostgreSQL + pgvector", "database"),
    box("Vk", "Valkey", "queue"), box("Fs", "Kho tệp", "storage")],
   [("App", "Nginx", "HTTPS"), ("Nginx", "Api", "HTTP"), ("Nginx", "Fs", "đọc tệp"), ("Api", "Pg", "SQL"),
    ("Api", "Vk", "job"), ("Api", "Fs", "ghi ảnh"), ("Worker", "Vk", "nhận job"), ("Worker", "Pg", "SQL"),
    ("Worker", "Fs", "đọc ảnh, mô hình"), ("Sched", "Pg", "SQL")],
   {"App": (0, 0), "Nginx": (1, 0), "Api": (1, 1), "Fs": (2, 0), "Vk": (2, 1), "Worker": (2, 2),
    "Pg": (1, 2), "Sched": (0, 2)})
struct("comp", "CP01b", "ket-noi-ngoai", "CP01b — Thành phần: kết nối với hệ thống ngoài", [
    box("App", "App Tastoria (Expo)", "client"), box("CF", "Cloudflare Tunnel", "external"),
    box("Api", "API (FastAPI)", "process"), box("Sched", "Scheduler (cron)", "process"),
    box("Smtp", "Dịch vụ email (SMTP)", "external"), box("Ls", "Công cụ gán nhãn (Label Studio)", "external"),
    box("Drive", "Google Drive (rclone)", "external")],
   [("App", "CF", "HTTPS"), ("CF", "Api", "tunnel"), ("Api", "Smtp", "SMTP"), ("Api", "Ls", "REST"),
    ("Sched", "Drive", "sao lưu")],
   {"App": (0, 0), "CF": (1, 0), "Api": (2, 0), "Smtp": (3, 0), "Ls": (3, 1), "Sched": (2, 1), "Drive": (2, 2)})
MODS = {mm["name"]: mm for mm in META["modules"]}


def mod_struct(did, slug, title, names, grid):
    boxes = [box(n, f"{MODS[n]['id']} {n}", "module") for n in names]
    links = [(n, d, "") for n in names for d in MODS[n]["deps"] if d in names]
    return struct("comp", did, slug, title, boxes, links, grid)


mod_struct("CP01c", "module-loi", "CP01c — Thành phần: module lõi, định danh và danh mục",
           ["core", "identity", "privacy", "catalog", "profile"],
           {"profile": (1, 0), "privacy": (0, 1), "catalog": (2, 1), "identity": (0, 2), "core": (1, 3)})
mod_struct("CP01d", "module-bep", "CP01d — Thành phần: module nghiệp vụ bếp",
           ["cooking", "meal", "substitute", "events", "scan", "pantry", "mlops", "catalog"],
           {"cooking": (1, 0), "meal": (1, 1), "events": (0, 1), "substitute": (2, 1), "scan": (3, 1),
            "pantry": (1, 2), "mlops": (3, 2), "catalog": (2, 3)})
mod_struct("CP01e", "module-nhan-su-tac-vu", "CP01e — Thành phần: module nhân sự, tác vụ và báo cáo",
           ["admin", "jobs", "journal", "survey", "identity", "privacy", "scan", "mlops"],
           {"admin": (1, 0), "jobs": (3, 0), "journal": (0, 0), "survey": (0, 1), "mlops": (1, 1),
            "privacy": (2, 1), "identity": (3, 1), "scan": (4, 1)})

struct("deploy", "DP01a", "thiet-bi-ket-noi", "DP01a — Triển khai: thiết bị và kết nối", [
    box("Phone", "Điện thoại Android\n(App APK)", "device"), box("Browser", "Trình duyệt\n(web app, landing)", "device"),
    box("CF", "Cloudflare edge", "cloud"), box("Lab", "Máy chủ lab\n(Docker Compose)", "device"),
    box("Gpu", "Máy GPU lab (L40S)", "device"), box("Drive", "Google Drive", "cloud")],
   [("Phone", "CF", "HTTPS"), ("Browser", "CF", "HTTPS"), ("CF", "Lab", "Cloudflare Tunnel"),
    ("Lab", "Drive", "rclone sao lưu"), ("Gpu", "Lab", "chép ONNX")],
   {"Phone": (0, 0), "Browser": (0, 1), "CF": (1, 0), "Lab": (2, 0), "Gpu": (2, 1), "Drive": (3, 0)})
struct("deploy", "DP01b", "container-may-chu", "DP01b — Triển khai: container trên máy chủ lab", [
    box("Host", "Máy chủ lab – Docker Compose", "device"),
    box("Nginx", "nginx", "container", "Host"), box("Api", "api", "container", "Host"),
    box("Worker", "worker", "container", "Host"), box("Sched", "scheduler", "container", "Host"),
    box("Migrate", "migrate (chạy một lần)", "container", "Host"), box("Pg", "postgres", "container", "Host"),
    box("Vk", "valkey", "container", "Host")],
   [("Nginx", "Api", "HTTP"), ("Api", "Pg", "SQL"), ("Api", "Vk", "RESP"), ("Worker", "Vk", "RESP"),
    ("Worker", "Pg", "SQL"), ("Sched", "Pg", "SQL"), ("Migrate", "Pg", "alembic")],
   {"Nginx": (0, 0), "Api": (1, 0), "Vk": (2, 0), "Worker": (2, 1), "Pg": (1, 1), "Sched": (0, 1),
    "Migrate": (1, 2)})
struct("deploy", "DP01c", "huan-luyen-mo-hinh", "DP01c — Triển khai: huấn luyện và nạp mô hình", [
    box("Gpu", "Máy GPU lab (L40S)", "device"),
    box("Train", "Huấn luyện (ultralytics, PyTorch, LightGBM)", "artifact", "Gpu"),
    box("Mlflow", "MLflow", "artifact", "Gpu"),
    box("Lab", "Máy chủ lab", "device"),
    box("Cli", "CLI tastoria mlops", "artifact", "Lab"), box("Models", "volume models/", "artifact", "Lab")],
   [("Train", "Mlflow", "ghi run"), ("Train", "Cli", "ONNX + số đo"), ("Cli", "Models", "đăng ký")],
   {"Train": (0, 0), "Mlflow": (0, 1), "Cli": (1, 0), "Models": (1, 1)})

struct("pkg", "PG01a", "goi-tong-the", "PG01a — Gói: bố cục mã nguồn tổng thể", [
    box("Be", "backend/src/tastoria", None), box("Core", "core", "M01", "Be"), box("Mods", "modules", "M02–M15", "Be"),
    box("Jobs", "jobs", "M16", "Be"), box("Cli", "cli", None, "Be"), box("Mig", "backend/migrations", None),
    box("App", "app (Expo, TypeScript)", None), box("Land", "landing (HTML/CSS)", None)],
   [("Mods", "Core", ""), ("Jobs", "Mods", ""), ("Cli", "Mods", ""), ("Mig", "Core", "")],
   {"Cli": (0, 0), "Jobs": (1, 0), "Mods": (0, 1), "Core": (0, 2), "Mig": (1, 3), "App": (2, 3),
    "Land": (3, 3)})
struct("pkg", "PG01b", "cau-truc-module", "PG01b — Gói: cấu trúc một module (ví dụ meal)", [
    box("M", "tastoria.modules.meal", "M11"),
    box("Router", "router.py", None, "M"), box("Service", "service.py", "public", "M"),
    box("Repo", "repository.py", None, "M"), box("Domain", "domain.py", None, "M"),
    box("Schemas", "schemas.py", None, "M"), box("Tables", "tables.py", None, "M")],
   [("Router", "Service", ""), ("Router", "Schemas", ""), ("Service", "Repo", ""), ("Service", "Domain", ""),
    ("Repo", "Tables", "")],
   {"Router": (0, 0), "Schemas": (1, 0), "Service": (0, 1), "Domain": (1, 1), "Repo": (0, 2), "Tables": (1, 2)})
struct("pkg", "PG01c", "goi-app", "PG01c — Gói: ứng dụng Expo", [
    box("A", "app", None), box("Routes", "app/app (expo-router)", None, "A"), box("Api", "src/api", None, "A"),
    box("Off", "src/offline", None, "A"), box("Ui", "src/ui", None, "A")],
   [("Routes", "Api", ""), ("Routes", "Off", ""), ("Routes", "Ui", ""), ("Off", "Api", "outbox")],
   {"Routes": (1, 0), "Ui": (0, 1), "Off": (1, 1), "Api": (2, 1)})


# =====================================================================  ERD
# Crow's foot chi tiết sinh từ db/schema.sql (gen_erd.py đọc DDL); nhóm ≤ 8 bảng kể cả bảng cha ở nhóm khác.
ERD_GROUPS = {
    "ERD01a": ("dinh-danh", "ERD01a — Định danh và khoá lũy đẳng (core, identity)",
               ["users", "refresh_tokens", "password_resets", "idempotency_keys"]),
    "ERD01b": ("quyen-rieng-tu", "ERD01b — Đồng ý, yêu cầu dữ liệu và kiểm toán (privacy)",
               ["consent_purposes", "policy_versions", "consent_events", "dsr_requests", "audit_log"]),
    "ERD02": ("ho-so", "ERD02 — Hồ sơ người dùng (profile)",
              ["profiles", "user_allergens", "user_favorite_recipes", "user_settings"]),
    "ERD03a": ("thanh-phan-dinh-duong", "ERD03a — Danh mục: thành phần thực phẩm và dinh dưỡng",
               ["food_groups", "nutrient_sources", "food_items", "nutrients", "food_nutrients"]),
    "ERD03b": ("nguyen-lieu-di-ung", "ERD03b — Danh mục: nguyên liệu, dị ứng và chế độ ăn",
               ["ingredients", "ingredient_synonyms", "ingredient_allergens", "allergen_groups", "diets",
                "diet_exclusions"]),
    "ERD03c": ("don-vi-lop-thi-giac", "ERD03c — Danh mục: đơn vị, mức lượng và lớp thị giác",
               ["ingredient_units", "qty_levels", "vision_classes", "vision_class_ingredients"]),
    "ERD04a": ("cong-thuc", "ERD04a — Món ăn: công thức và bước nấu",
               ["recipes", "recipe_ingredients", "recipe_steps", "cooking_methods", "recipe_make_ahead"]),
    "ERD04b": ("the-nguon-dinh-duong", "ERD04b — Món ăn: thẻ, nguồn và dinh dưỡng món",
               ["tags", "recipe_tags", "recipe_sources", "recipe_nutrition"]),
    "ERD05a": ("kho", "ERD05a — Kho nguyên liệu (pantry)", ["pantry_lots", "pantry_transactions"]),
    "ERD05b": ("quet", "ERD05b — Quét ảnh (scan)", ["scans", "scan_images", "scan_items", "detections"]),
    "ERD06a": ("mam", "ERD06a — Mâm cơm và món trong mâm (meal)",
               ["meal_plans", "meal_plan_items", "meal_plan_item_substitutions"]),
    "ERD06b": ("rang-buoc-mam", "ERD06b — Ràng buộc mâm: dị ứng người ăn cùng, lô ghim (meal)",
               ["meal_plan_coeater_allergens", "meal_plan_pins"]),
    "ERD06c": ("thay-the-di-cho", "ERD06c — Thay thế và đi chợ (substitute)",
               ["substitution_pairs", "ingredient_embeddings", "shopping_items"]),
    "ERD06d": ("phien-nau", "ERD06d — Phiên nấu và lịch nấu (cooking)", ["cook_sessions", "cook_schedule_entries"]),
    "ERD06e": ("tuong-tac", "ERD06e — Tương tác (events)", ["interactions"]),
    "ERD07a": ("mo-hinh", "ERD07a — Vận hành mô hình (mlops)",
               ["model_versions", "model_version_classes", "model_deployments"]),
    "ERD07b": ("khao-sat", "ERD07b — Khảo sát gu (survey)",
               ["survey_forms", "survey_form_anchors", "survey_respondents", "survey_assignments", "survey_ratings",
                "survey_favorites"]),
}
ERD_OVERVIEW = ("ERD08", "tong-quan", "ERD08 — Tổng quan bảng theo module (chỉ tên bảng; cột ở ERD01a–ERD07b)")

# Chen khái niệm: tách theo mảng từ mô hình đầy đủ docs/erd/src/khai-niem-day-du.chen
CHEN_GROUPS = {
    "ERD00a": ("chen-nguoi-dung-ho-so", "ERD00a — Khái niệm (Chen): người dùng, hồ sơ, dị ứng, chế độ ăn",
               ["NGUOIDUNG", "HOSO", "DIUNG", "CHEDO", "NHOMTP"]),
    "ERD00b": ("chen-nguyen-lieu-mon", "ERD00b — Khái niệm (Chen): nguyên liệu và món",
               ["NGUYENLIEU", "NHOMTP", "DIUNG", "THUCPHAM", "CHATDD", "MON", "BUOCNAU"]),
    "ERD00c": ("chen-kho", "ERD00c — Khái niệm (Chen): kho nguyên liệu",
               ["NGUOIDUNG", "LOKHO", "GIAODICH", "NGUYENLIEU", "CHIP"]),
    "ERD00d": ("chen-quet", "ERD00d — Khái niệm (Chen): quét ảnh và nhận diện",
               ["NGUOIDUNG", "LANQUET", "ANHQUET", "CHIP", "KHUNG", "LOPTG", "NGUYENLIEU"]),
    "ERD00e": ("chen-mam-nau", "ERD00e — Khái niệm (Chen): mâm cơm và phiên nấu",
               ["NGUOIDUNG", "MAM", "MONMAM", "MON", "LOKHO", "PHIENNAU", "BUOCNAU"]),
    "ERD00f": ("chen-tuong-tac-mo-hinh", "ERD00f — Khái niệm (Chen): tương tác và mô hình",
               ["NGUOIDUNG", "TUONGTAC", "MON", "MAM", "MOHINH", "LOPTG"]),
    "ERD00g": ("chen-dong-y", "ERD00g — Khái niệm (Chen): đồng ý theo mục đích",
               ["NGUOIDUNG", "MUCDICH", "DIEUKHOAN", "SUKIENDY"]),
    "ERD00h": ("chen-khao-sat", "ERD00h — Khái niệm (Chen): khảo sát gu",
               ["NGUOIKS", "PHIEUKS", "DIEUKHOAN", "PHANCONG", "MON", "DIEMKS"]),
}

FOLDER = {"uc": "usecase", "ctx": "context", "seq": "sequence", "act": "activity", "state": "state",
          "class": "class", "comp": "component", "deploy": "deployment", "pkg": "package"}


def check():
    bad = []
    for d in DIAGRAMS:
        k = d["kind"]
        if k == "seq":
            msgs = [i for i in d["items"] if i[0] == "m"] + [mm for i in d["items"] if i[0] == "frag"
                                                              for _, ms in i[2] for mm in ms]
            nfr = sum(1 for i in d["items"] if i[0] == "frag")
            if len(d["lls"]) > 5 or len(msgs) > 12 or nfr > 1:
                bad.append((d["id"], len(d["lls"]), len(msgs), nfr))
        if k == "act":
            def cnt(items):
                n = 0
                for it in items:
                    if it[0] == "a":
                        n += 1
                    elif it[0] == "if":
                        n += cnt(it[4]) + cnt(it[6])
                    elif it[0] == "while":
                        n += cnt(it[4])
                return n
            if cnt(d["items"]) > 10:
                bad.append((d["id"], cnt(d["items"])))
        if k == "uc" and len(d["ucs"]) > 8:
            bad.append((d["id"], len(d["ucs"])))
        if k == "class" and (len(d["classes"]) > 6 or any(len(c[2]) + len(c[3]) > 5 for c in d["classes"])):
            bad.append((d["id"], "class"))
        if k in ("comp", "deploy", "pkg") and len(d["boxes"]) > 8:
            bad.append((d["id"], len(d["boxes"])))
    return bad


if __name__ == "__main__":
    print(len(DIAGRAMS), "sơ đồ UML;", len(ERD_GROUPS), "ERD chi tiết;", len(CHEN_GROUPS), "Chen; vi phạm:", check())
