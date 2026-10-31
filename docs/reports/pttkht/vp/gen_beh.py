# Biểu đồ hành vi: activity (có swimlane), sequence, communication, state machine, object.
# Toạ độ ở đơn vị cuối của VP; hình đặt tay, đường nối vuông góc qua waypoint.
from spec_lib import Spec, tw

ACT_H = 46          # chiều cao hình action
NODE = 30           # nút đầu/cuối
DIAM = 36           # nút quyết định / gộp


class B:
    """Ghi lệnh cho các phần tử hành vi (không qua bộ nới bố cục của sơ đồ lớp)."""

    def __init__(self, s: Spec):
        self.s = s
        self.geo = {}

    def new(self, k, t, name=None, owner=None):
        self.s.emit("NEW", k, t, name, owner)

    def rel(self, k, t, a, b, name=None):
        self.s.emit("NEWREL", k, t, a, b, name)

    def call(self, k, m, *a):
        self.s.emit("CALL", k, m, *a)

    def stereo(self, k, st):
        self.call(k, "addStereotype", st)

    def diag(self, d, typ, title):
        self.d = d
        self.geo = {}
        self.s.diag(d, typ, title)

    def show(self, k, x, y, w=None, h=None, parent=None):
        self.geo[k] = (x, y, w or 0, h or 0)
        self.s.emit("SHOW", self.d, k, int(x), int(y), int(w) if w else None, int(h) if h else None, parent)

    def conn(self, k, pts=None, frm=None, to=None):
        p = ";".join(f"{int(round(x))},{int(round(y))}" for x, y in pts) if pts else None
        self.s.emit("CONN", self.d, k, frm, to, p)
        if pts and len(pts) > 2:
            self.s.emit("CSTYLE", self.d, k, 0)

    def scall(self, k, m, *a):
        self.s.emit("SCALL", self.d, k, m, *a)

    def caption(self, k, x, y, w, h):
        self.s.emit("CAPTION", self.d, k, int(x), int(y), int(w), int(h))

    # điểm trên cạnh hình (theo hình học đã đặt)
    def T(self, k, dx=0): x, y, w, h = self.geo[k]; return (x + w / 2 + dx, y)
    def Bm(self, k, dx=0): x, y, w, h = self.geo[k]; return (x + w / 2 + dx, y + h)
    def L(self, k, dy=0): x, y, w, h = self.geo[k]; return (x, y + h / 2 + dy)
    def R(self, k, dy=0): x, y, w, h = self.geo[k]; return (x + w, y + h / 2 + dy)


# ------------------------------------------------------------------ activity
class Act(B):
    def lanes(self, key, lanes, y0, height, x0=20):
        """lanes: [(khoá, tên, rộng)] -> swimlane dọc; trả về tâm từng làn."""
        self.new(key, "ActivitySwimlane2", " ")
        for k, n, w in lanes:
            self.new(k, "ActivityPartition", n)
            self.call(key, "addVerticalPartition", f"@{k}")
        self.new(key + "_h", "ActivityPartition", " ")
        self.call(key, "addHorizontalPartition", f"@{key}_h")
        total = sum(w for _, _, w in lanes)
        self.show(key, x0, y0, total, height)
        x = x0
        self.cx = {}
        for k, n, w in lanes:
            self.show(k, x, y0 + 30, w, height - 30, key)
            self.cx[k] = x + w / 2
            x += w
        self.lane_of = {}
        return self.cx

    def node(self, k, typ, cx, cy, name=None, w=None, h=None, lane=None):
        if typ == "ActivityAction":
            w = w or tw(name) + 34
            h = h or ACT_H
        elif typ in ("InitialNode", "ActivityFinalNode"):
            w = h = NODE
        elif typ in ("DecisionNode", "MergeNode"):
            w = h = DIAM
            name = name or " "
        elif typ in ("ForkNode", "JoinNode"):
            h = 8
        self.new(k, typ, name)
        self.show(k, cx - w / 2, cy - h / 2, w, h, lane)

    def route(self, a, b, mode):
        """Điểm cho đường vuông góc: v (thẳng đứng), h (ngang), vh (xuống rồi ngang), hv (ngang rồi xuống/lên)."""
        ax, ay, aw, ah = self.geo[a]; bx, by, bw, bh = self.geo[b]
        acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
        if mode == "v":
            return [self.Bm(a), self.T(b)] if bcy > acy else [self.T(a), self.Bm(b)]
        if mode == "h":
            return [self.R(a), self.L(b)] if bcx > acx else [self.L(a), self.R(b)]
        if mode == "vh":
            p0 = self.Bm(a) if bcy > acy else self.T(a)
            return [p0, (acx, bcy), self.L(b) if bcx > acx else self.R(b)]
        if mode == "hv":
            p0 = self.R(a) if bcx > acx else self.L(a)
            return [p0, (bcx, acy), self.T(b) if bcy > acy else self.Bm(b)]
        raise ValueError(mode)

    def f(self, k, a, b, mode="v", guard=None, at=None, pts=None):
        self.flow(k, a, b, pts or self.route(a, b, mode), guard, at)

    def flow(self, k, a, b, pts, guard=None, at=None):
        self.rel(k, "ControlFlow", a, b, guard)
        self.conn(k, pts)
        if guard and at:
            self.caption(k, at[0], at[1], tw(guard) + 12, 22)

    def note(self, k, text, x, y, w):
        from spec_lib import tw as _tw
        self.s.note(k, text)
        lines = -(-int(_tw(text)) // int(w - 40))
        self.show(k, x, y, w, 26 + 21 * lines)


def act01(s):
    """ACT01: đặt hàng và thanh toán (UC07, UC08)."""
    a = Act(s)
    a.diag("D_ACT02", "ACT", "ACT02 Đặt hàng và thanh toán")
    c = a.lanes("A1_SW", [("A1_KH", "Khách hàng doanh nghiệp", 320), ("A1_HT", "Hệ thống TMĐT SafeWork", 540),
                          ("A1_CT", "Cổng thanh toán", 230)], 20, 1130)
    K, H, G = c["A1_KH"], c["A1_HT"], c["A1_CT"]
    HL, HR = H - 130, H + 135                       # hai cột trong làn hệ thống
    n = a.node
    n("A1_i", "InitialNode", K, 85)
    n("A1_a1", "ActivityAction", K, 150, "Chọn địa chỉ giao")
    n("A1_m1", "MergeNode", K, 225)
    n("A1_a2", "ActivityAction", HL, 225, "Tính phí giao, tổng tiền")
    n("A1_a3", "ActivityAction", K, 300, "Xác nhận đặt hàng")
    n("A1_a4", "ActivityAction", HL, 375, "Kiểm tra, giữ hàng mọi dòng")
    n("A1_d1", "DecisionNode", HL, 455)
    n("A1_a5", "ActivityAction", K, 455, "Sửa giỏ theo dòng lỗi")
    n("A1_a6", "ActivityAction", HL, 540, "Tạo đơn, xoá giỏ")
    n("A1_a7", "ActivityAction", K, 620, "Chọn cách thanh toán")
    n("A1_d2", "DecisionNode", K, 700)
    n("A1_a8", "ActivityAction", HL, 700, "Ghi lần thanh toán")
    n("A1_a9", "ActivityAction", G, 700, "Xử lý giao dịch")
    n("A1_d3", "DecisionNode", HL, 790)
    n("A1_a10", "ActivityAction", HL, 875, "Ghi nhận đã thanh toán")
    n("A1_a11", "ActivityAction", HR, 875, "Ghi lần thanh toán lỗi")
    n("A1_f1", "ActivityFinalNode", HL, 955)
    n("A1_f3", "ActivityFinalNode", HR, 955)
    n("A1_a12", "ActivityAction", HR, 1030, "Hiện số tài khoản, mã đơn")
    n("A1_f2", "ActivityFinalNode", HR, 1105)
    f, T, Bm, L, R = a.flow, a.T, a.Bm, a.L, a.R
    f("A1_c1", "A1_i", "A1_a1", [Bm("A1_i"), T("A1_a1")])
    f("A1_c2", "A1_a1", "A1_m1", [Bm("A1_a1"), T("A1_m1")])
    f("A1_c3", "A1_m1", "A1_a2", [R("A1_m1"), L("A1_a2")])
    f("A1_c4", "A1_a2", "A1_a3", [Bm("A1_a2"), (HL, 300), R("A1_a3")])
    f("A1_c5", "A1_a3", "A1_a4", [Bm("A1_a3"), (K, 375), L("A1_a4")])
    f("A1_c6", "A1_a4", "A1_d1", [Bm("A1_a4"), T("A1_d1")])
    f("A1_c7", "A1_d1", "A1_a5", [L("A1_d1"), R("A1_a5")], "[có dòng không đạt]")
    f("A1_c8", "A1_a5", "A1_m1", [L("A1_a5"), (38, 455), (38, 225), L("A1_m1")])
    f("A1_c9", "A1_d1", "A1_a6", [Bm("A1_d1"), T("A1_a6")], "[mọi dòng đạt]", at=(HL + 10, 478))
    f("A1_c10", "A1_a6", "A1_a7", [L("A1_a6"), (K, 540), T("A1_a7")])
    f("A1_c12", "A1_a7", "A1_d2", [Bm("A1_a7"), T("A1_d2")])
    f("A1_c13", "A1_d2", "A1_a8", [R("A1_d2"), L("A1_a8")], "[cổng thanh toán]")
    f("A1_c14", "A1_a8", "A1_a9", [R("A1_a8"), L("A1_a9")])
    f("A1_c15", "A1_a9", "A1_d3", [Bm("A1_a9"), (G, 748), (HL, 748), T("A1_d3")])
    f("A1_c16", "A1_d3", "A1_a10", [Bm("A1_d3"), T("A1_a10")], "[thành công]", at=(HL + 10, 812))
    f("A1_c17", "A1_d3", "A1_a11", [R("A1_d3"), (HR, 790), T("A1_a11")], "[không thành công]")
    f("A1_c18", "A1_a11", "A1_f3", [Bm("A1_a11"), T("A1_f3")])
    f("A1_c19", "A1_a10", "A1_f1", [Bm("A1_a10"), T("A1_f1")])
    f("A1_c20", "A1_d2", "A1_a12", [Bm("A1_d2"), (K, 1030), L("A1_a12")], "[chuyển khoản]")
    f("A1_c21", "A1_a12", "A1_f2", [Bm("A1_a12"), T("A1_f2")])
    a.note("N_ACT02", "UC25 chạy trong một giao dịch: một dòng không đạt thì không giữ hàng, không tạo đơn, giỏ giữ nguyên (BR-04). "
           "Đơn PLACED quá 72 giờ chưa thanh toán thì tự hủy (BR-07); chuyển khoản do kế toán xác nhận ở UC15.", 20, 1170, 760)


def act02(s):
    """ACT02: hoàn tất đơn hàng (UC19) — hai nhánh song song: giao hàng vật lý và kích hoạt gói."""
    a = Act(s)
    a.diag("D_ACT07", "ACT", "ACT07 Hoàn tất đơn hàng")
    c = a.lanes("A2_SW", [("A2_NT", "Nền tảng giám sát", 200), ("A2_HT", "Hệ thống TMĐT SafeWork", 480),
                          ("A2_KO", "Nhân viên kho", 210), ("A2_VC", "Đơn vị vận chuyển", 200)], 20, 980)
    N, H, K, V = c["A2_NT"], c["A2_HT"], c["A2_KO"], c["A2_VC"]
    HL, HR = H - 122, H + 122
    n = a.node
    n("A2_i", "InitialNode", K, 85)
    n("A2_a1", "ActivityAction", K, 150, "Nhận đơn đã thanh toán")
    n("A2_a2", "ActivityAction", HR, 150, "Chuyển đơn sang xử lý")
    n("A2_F", "ForkNode", H, 225, w=400)
    n("A2_dA", "DecisionNode", HR, 295)
    n("A2_a3", "ActivityAction", K, 295, "Lấy hàng, quét serial")
    n("A2_a4", "ActivityAction", HR, 375, "Gán serial, trừ hàng giữ")
    n("A2_a5", "ActivityAction", HR, 455, "Tạo yêu cầu vận chuyển")
    n("A2_a6", "ActivityAction", V, 455, "Trả mã vận đơn")
    n("A2_a7", "ActivityAction", HR, 535, "Ghi vận đơn, đơn đã gửi")
    n("A2_a8", "ActivityAction", V, 615, "Giao hàng, báo đã giao")
    n("A2_mA", "MergeNode", HR, 700)
    n("A2_dB", "DecisionNode", HL, 295)
    n("A2_b1", "ActivityAction", HL, 375, "Tạo gói chờ kích hoạt")
    n("A2_b2", "ActivityAction", N, 375, "Kích hoạt gói")
    n("A2_b3", "ActivityAction", HL, 455, "Ghi gói đã kích hoạt")
    n("A2_mB", "MergeNode", HL, 700)
    n("A2_J", "JoinNode", H, 780, w=400)
    n("A2_a9", "ActivityAction", H, 855, "Hoàn tất đơn")
    n("A2_f", "ActivityFinalNode", H, 935)
    f, T, Bm, L, R = a.flow, a.T, a.Bm, a.L, a.R
    f("A2_c1", "A2_i", "A2_a1", [Bm("A2_i"), T("A2_a1")])
    f("A2_c2", "A2_a1", "A2_a2", [L("A2_a1"), R("A2_a2")])
    f("A2_c3", "A2_a2", "A2_F", [Bm("A2_a2"), (HR, 221)])
    f("A2_c4", "A2_F", "A2_dA", [(HR, 229), T("A2_dA")])
    f("A2_c5", "A2_F", "A2_dB", [(HL, 229), T("A2_dB")])
    f("A2_c6", "A2_dA", "A2_a3", [R("A2_dA"), L("A2_a3")], "[có hàng]", at=(HR + 24, 263))
    f("A2_c7", "A2_a3", "A2_a4", [Bm("A2_a3"), (K, 375), R("A2_a4")])
    f("A2_c8", "A2_a4", "A2_a5", [Bm("A2_a4"), T("A2_a5")])
    f("A2_c9", "A2_a5", "A2_a6", [R("A2_a5"), L("A2_a6")])
    f("A2_c10", "A2_a6", "A2_a7", [Bm("A2_a6"), (V, 535), R("A2_a7")])
    f("A2_c11", "A2_a7", "A2_a8", [Bm("A2_a7"), (HR, 615), L("A2_a8")])
    f("A2_c12", "A2_a8", "A2_mA", [Bm("A2_a8"), (V, 700), R("A2_mA")])
    xA = HR - 125
    f("A2_c13", "A2_dA", "A2_mA", [L("A2_dA"), (xA, 295), (xA, 700), L("A2_mA")], "[không]", at=(xA + 8, 263))
    f("A2_c14", "A2_dB", "A2_b1", [Bm("A2_dB"), T("A2_b1")], "[có gói]", at=(HL + 10, 318))
    f("A2_c15", "A2_b1", "A2_b2", [L("A2_b1"), R("A2_b2")])
    f("A2_c16", "A2_b2", "A2_b3", [Bm("A2_b2"), (N, 455), L("A2_b3")])
    f("A2_c17", "A2_b3", "A2_mB", [Bm("A2_b3"), T("A2_mB")])
    f("A2_c18", "A2_dB", "A2_mB", [L("A2_dB"), (42, 295), (42, 700), L("A2_mB")], "[không]", at=(HL - 80, 263))
    f("A2_c19", "A2_mA", "A2_J", [Bm("A2_mA"), (HR, 776)])
    f("A2_c20", "A2_mB", "A2_J", [Bm("A2_mB"), (HL, 776)])
    f("A2_c21", "A2_J", "A2_a9", [Bm("A2_J"), T("A2_a9")])
    f("A2_c22", "A2_a9", "A2_f", [Bm("A2_a9"), T("A2_f")])
    a.note("N_ACT07", "Hai nhánh chạy song song: nền tảng giám sát chậm phản hồi không chặn việc giao hàng (UC19, A3). "
           "complete() chỉ chạy khi cả hai nhánh đã xong.", 20, 1020, 760)


def act03(s):
    """ACT03: hỏi trợ lý tư vấn (UC32, UC35) — tìm tài liệu và đọc dữ liệu danh mục song song."""
    a = Act(s)
    a.diag("D_ACT09", "ACT", "ACT09 Hỏi trợ lý tư vấn")
    c = a.lanes("A3_SW", [("A3_KH", "Người truy cập", 250), ("A3_HT", "Hệ thống TMĐT SafeWork", 540),
                          ("A3_NV", "Nhân viên kinh doanh", 230)], 20, 960)
    K, H, V = c["A3_KH"], c["A3_HT"], c["A3_NV"]
    HL, HR = H - 135, H + 135
    n = a.node
    n("A3_i", "InitialNode", K, 85)
    n("A3_m0", "MergeNode", K, 150)
    n("A3_a1", "ActivityAction", K, 220, "Nhập câu hỏi")
    n("A3_a2", "ActivityAction", H, 220, "Ghi câu hỏi vào phiên")
    n("A3_F", "ForkNode", H, 290, w=440)
    n("A3_a3", "ActivityAction", HL, 360, "Tìm đoạn tài liệu liên quan")
    n("A3_a4", "ActivityAction", HR, 360, "Đọc giá, tồn, chứng nhận")
    n("A3_J", "JoinNode", H, 430, w=440)
    n("A3_d1", "DecisionNode", H, 500)
    n("A3_a5", "ActivityAction", HL, 585, "Viết câu trả lời có trích dẫn")
    n("A3_a6", "ActivityAction", HR, 585, "Đề nghị chuyển nhân viên")
    n("A3_m1", "MergeNode", K, 640)
    n("A3_a7", "ActivityAction", K, 715, "Đọc câu trả lời")
    n("A3_d2", "DecisionNode", K, 795)
    n("A3_f1", "ActivityFinalNode", K, 905)
    n("A3_a8", "ActivityAction", H, 795, "Chuyển phiên cho nhân viên")
    n("A3_a9", "ActivityAction", V, 795, "Trả lời khách")
    n("A3_f2", "ActivityFinalNode", V, 875)
    f, T, Bm, L, R = a.flow, a.T, a.Bm, a.L, a.R
    f("A3_c1", "A3_i", "A3_m0", [Bm("A3_i"), T("A3_m0")])
    f("A3_c2", "A3_m0", "A3_a1", [Bm("A3_m0"), T("A3_a1")])
    f("A3_c3", "A3_a1", "A3_a2", [R("A3_a1"), L("A3_a2")])
    f("A3_c4", "A3_a2", "A3_F", [Bm("A3_a2"), (H, 286)])
    f("A3_c5", "A3_F", "A3_a3", [(HL, 294), T("A3_a3")])
    f("A3_c6", "A3_F", "A3_a4", [(HR, 294), T("A3_a4")])
    f("A3_c7", "A3_a3", "A3_J", [Bm("A3_a3"), (HL, 426)])
    f("A3_c8", "A3_a4", "A3_J", [Bm("A3_a4"), (HR, 426)])
    f("A3_c9", "A3_J", "A3_d1", [(H, 434), T("A3_d1")])
    f("A3_c10", "A3_d1", "A3_a5", [L("A3_d1"), (HL, 500), T("A3_a5")], "[có đoạn đủ liên quan]")
    f("A3_c11", "A3_d1", "A3_a6", [R("A3_d1"), (HR, 500), T("A3_a6")], "[không có đoạn phù hợp]")
    f("A3_c12", "A3_a5", "A3_m1", [L("A3_a5"), (K, 585), T("A3_m1")])
    f("A3_c13", "A3_a6", "A3_m1", [Bm("A3_a6"), (HR, 640), R("A3_m1")])
    f("A3_c14", "A3_m1", "A3_a7", [Bm("A3_m1"), T("A3_a7")])
    f("A3_c15", "A3_a7", "A3_d2", [Bm("A3_a7"), T("A3_d2")])
    f("A3_c16", "A3_d2", "A3_m0", [L("A3_d2"), (36, 795), (36, 150), L("A3_m0")], "[hỏi tiếp]")
    f("A3_c17", "A3_d2", "A3_a8", [R("A3_d2"), L("A3_a8")], "[gặp nhân viên]")
    f("A3_c18", "A3_a8", "A3_a9", [R("A3_a8"), L("A3_a9")])
    f("A3_c19", "A3_a9", "A3_f2", [Bm("A3_a9"), T("A3_f2")])
    a.note("N_ACT09", "Giá, số còn bán được, chứng nhận đọc từ danh mục và chèn vào câu trả lời sau bước sinh, "
           "không lấy từ văn bản mô hình sinh ra (FR-AI-03).", 20, 1000, 760)
    f("A3_c20", "A3_d2", "A3_f1", [Bm("A3_d2"), T("A3_f1")], "[đã đủ]", at=(K + 10, 828))


# ------------------------------------------------------------------ sequence
class Seq(B):
    """Sequence diagram: lifeline đứng, message ngang ở toạ độ y cho trước, activation tự gom theo khoảng."""
    HEAD = 62

    def setup(self, p, lifelines, top, bottom):
        """lifelines: [(khoá, kiểu 'actor'|'boundary'|'control'|'entity', tên, cx, rộng, y_tạo hoặc None)]"""
        self.p, self.top, self.bottom = p, top, bottom
        self.cxs, self.acts, self.msgs = {}, {}, []
        self.lls = lifelines
        for k, kind, name, cx, w, created in lifelines:
            if kind == "actor":
                self.new(k, "InteractionActor", name)
            else:
                self.new(k, "InteractionLifeLine", name)
                if kind != "obj":
                    self.stereo(k, kind)
            self.cxs[k] = cx

    def act(self, ll, y1, y2):
        k = f"{ll}_act{len(self.acts.get(ll, []))}"
        self.new(k, "Activation", None, ll)
        self.acts.setdefault(ll, []).append((k, y1, y2))

    def _act_at(self, ll, y):
        for k, y1, y2 in self.acts.get(ll, []):
            if y1 - 1 <= y <= y2 + 1:
                return k
        return None

    def msg(self, k, a, b, label, y, kind="call"):
        self.rel(k, "Message", a, b, label)
        if kind == "return":
            self.new(k + "_rt", "ActionTypeReturn")
            self.call(k, "setActionType", f"@{k}_rt")
        if kind == "create":
            self.call(k, "setType", "i:2")
        self.msgs.append((k, a, b, y, kind))

    def frag(self, k, op, x1, y1, x2, y2, covered, operands, parent=None):
        """operands: [(guard, y_bắt_đầu)]"""
        self.new(k, "CombinedFragment", op)
        self.call(k, "setInteractionOperator", op)
        for ll in covered:
            self.call(k, "addCoveredLifeLine", f"@{ll}")
        if parent:
            self.call(parent, "addCombinedFragment", f"@{k}")
        ops = []
        for i, (g, oy) in enumerate(operands):
            ok = f"{k}_op{i}"
            self.new(ok, "InteractionOperand", None)
            self.call(k, "addOperand", f"@{ok}")
            if g:
                self.new(ok + "_g", "InteractionConstraint", None)
                self.call(ok + "_g", "setConstraint", g)
                self.call(ok, "setGuard", f"@{ok}_g")
            ops.append((ok, oy))
        self.frags = getattr(self, "frags", []) + [(k, x1, y1, x2, y2, ops, parent)]

    def draw(self):
        # activation gắn message
        for k, a, b, y, kind in self.msgs:
            fa, ta = self._act_at(a, y), self._act_at(b, y)
            if fa:
                self.call(k, "setFromActivation", f"@{fa}")
            if ta and kind != "create":
                self.call(k, "setToActivation", f"@{ta}")
        for k, kind, name, cx, w, created in self.lls:
            if kind == "actor":
                self.show(k, cx - 15, self.top, None, None)
            else:
                # đầu lifeline của đối tượng được tạo nằm ngang message «create»
                y = (created - (20 if kind == "obj" else 16)) if created else self.top
                h = self.bottom - y
                self.show(k, cx - w / 2, y, w, h)
        for ll, lst in self.acts.items():
            for k, y1, y2 in lst:
                self.show(k, self.cxs[ll] - 7, y1, 14, y2 - y1, ll)
        for k, x1, y1, x2, y2, ops, parent in getattr(self, "frags", []):
            self.show(k, x1, y1, x2 - x1, y2 - y1, parent)
            for i, (ok, oy) in enumerate(ops):
                ny = ops[i + 1][1] if i + 1 < len(ops) else y2
                self.show(ok, x1, oy, x2 - x1, ny - oy, k)
        for k, a, b, y, kind in self.msgs:
            xa, xb = self.cxs[a], self.cxs[b]
            right = xb > xa
            fa, ta = self._act_at(a, y), self._act_at(b, y)
            sx = xa + (7 if right else -7) if fa else xa
            if kind == "create":
                kind_b, w_b = [(kd, w) for kk, kd, _, _, w, _ in self.lls if kk == b][0]
                ex = xb - (w_b / 2 if kind_b == "obj" else 17)
            else:
                ex = xb + (-7 if right else 7) if ta else xb
            self.conn(k, [(sx, y), (ex, y)], frm=fa or a, to=(ta if kind != "create" else None) or b)


def seq01(s):
    """SEQ01: đặt hàng (UC07, kèm UC25) — kiểm tra mọi dòng trước, chỉ giữ hàng khi mọi dòng đạt (BR-04).
    Mức phân tích: actor gửi thông điệp tới đối tượng thực thể; mọi thông điệp là thao tác có trong lớp."""
    q = Seq(s)
    LL = [("S1_kh", "actor", "Khách hàng doanh nghiệp", 90, 0, None),
          ("S1_ca", "obj", ":Cart", 480, 110, None),
          ("S1_pp", "obj", ":PhysicalProduct", 690, 190, None),
          ("S1_or", "obj", ":Order", 900, 120, 550),
          ("S1_oi", "obj", ":OrderItem", 1230, 150, 690)]
    q.setup("S1", LL, 30, 1010)
    q.diag("D_SEQ01", "SEQ", "SEQ01 Đặt hàng")
    m = q.msg
    m("S1_m1", "S1_kh", "S1_ca", "1: checkout(address)", 130)
    m("S1_m2", "S1_ca", "S1_pp", "2: isSellable()", 225)
    m("S1_m3", "S1_ca", "S1_pp", "3: canReserve(qty)", 265)
    m("S1_m4", "S1_ca", "S1_pp", "4: reserve(qty)", 455)
    m("S1_m5", "S1_ca", "S1_or", "5: «create»(address, phí giao)", 550, "create")
    m("S1_m6", "S1_or", "S1_oi", "6: «create»(tên, qty, đơn giá)", 690, "create")
    m("S1_m7", "S1_ca", "S1_or", "7: calculateTotal()", 795)
    m("S1_m8", "S1_ca", "S1_kh", "8: order", 830, "return")
    m("S1_m9", "S1_ca", "S1_kh", "9: các dòng không đạt", 930, "return")
    q.act("S1_ca", 130, 935)
    for y in (225, 265, 455):
        q.act("S1_pp", y, y + 22)
    q.act("S1_or", 572, 805)
    q.act("S1_oi", 712, 730)
    q.frag("S1_L1", "loop", 320, 160, 790, 295, ["S1_ca", "S1_pp"], [("mỗi CartItem", 160)])
    q.frag("S1_A", "alt", 300, 325, 1330, 960, ["S1_ca", "S1_pp", "S1_or", "S1_oi"],
           [("mọi dòng đạt", 325), ("có dòng không đạt", 860)])
    q.frag("S1_L2", "loop", 320, 390, 790, 480, ["S1_ca", "S1_pp"], [("mỗi CartItem", 390)], parent="S1_A_op0")
    q.frag("S1_L3", "loop", 720, 610, 1320, 745, ["S1_or", "S1_oi"], [("mỗi CartItem", 610)], parent="S1_A_op0")
    q.draw()


def seq02(s):
    """SEQ02: thanh toán qua cổng thanh toán (UC08.1): kiểm tra đơn còn hạn, Payment tạo trước khi sang cổng,
    kết quả chỉ được nhận khi chữ ký hợp lệ và đúng số tiền."""
    q = Seq(s)
    LL = [("S2_kh", "actor", "Khách hàng doanh nghiệp", 90, 0, None),
          ("S2_or", "obj", ":Order", 520, 110, None),
          ("S2_pa", "obj", ":Payment", 930, 120, 240),
          ("S2_gw", "actor", "Cổng thanh toán", 1180, 0, None)]
    q.setup("S2", LL, 30, 840)
    q.diag("D_SEQ02", "SEQ", "SEQ02 Thanh toán qua cổng")
    m = q.msg
    m("S2_m1", "S2_kh", "S2_or", "1: pay(ONLINE_GATEWAY)", 130)
    m("S2_m2", "S2_or", "S2_pa", "2: «create»(ONLINE_GATEWAY)", 240, "create")
    m("S2_m3", "S2_or", "S2_kh", "3: payment", 290, "return")
    m("S2_m4", "S2_kh", "S2_gw", "4: thanh toán(orderNumber, amount)", 330)
    m("S2_m5", "S2_gw", "S2_pa", "5: confirm(transactionRef)", 440)
    m("S2_m6", "S2_pa", "S2_or", "6: markPaid()", 480)
    m("S2_m7", "S2_gw", "S2_pa", "7: markFailed()", 600)
    m("S2_m8", "S2_gw", "S2_kh", "8: kết quả giao dịch", 705, "return")
    m("S2_m9", "S2_or", "S2_kh", "9: từ chối (quá hạn hoặc đã hủy)", 790, "return")
    q.act("S2_or", 130, 300)
    q.act("S2_or", 480, 502)
    q.act("S2_or", 790, 810)
    q.act("S2_pa", 262, 280)
    q.act("S2_pa", 440, 490)
    q.act("S2_pa", 600, 622)
    q.frag("S2_A", "alt", 280, 165, 1235, 820, ["S2_or", "S2_pa", "S2_gw"],
           [("đơn PLACED, còn hạn", 165), ("quá hạn hoặc đã hủy", 715)])
    q.frag("S2_B", "alt", 300, 370, 1225, 645, ["S2_or", "S2_pa", "S2_gw"],
           [("thành công, hợp lệ", 370), ("thất bại hoặc sai lệch", 530)], parent="S2_A_op0")
    q.draw()


def seq03(s):
    """SEQ03: hỏi trợ lý (UC32) — par: tìm tài liệu và đọc danh mục; opt: gắn trích dẫn khi có nguồn."""
    q = Seq(s)
    LL = [("S3_kh", "actor", "Người truy cập", 70, 0, None),
          ("S3_se", "obj", ":ChatSession", 380, 150, None),
          ("S3_q", "obj", "q:ChatMessage", 745, 170, 175),
          ("S3_dc", "obj", ":DocumentChunk", 960, 180, None),
          ("S3_pr", "obj", ":Product", 1150, 110, None),
          ("S3_a", "obj", "a:ChatMessage", 1340, 170, 500),
          ("S3_ci", "obj", ":Citation", 1650, 120, 715)]
    q.setup("S3", LL, 30, 880)
    q.diag("D_SEQ03", "SEQ", "SEQ03 Hỏi trợ lý tư vấn")
    m = q.msg
    m("S3_m1", "S3_kh", "S3_se", "1: ask(question)", 130)
    m("S3_m2", "S3_se", "S3_q", "2: «create»(question)", 175, "create")
    m("S3_m3", "S3_se", "S3_dc", "3: search(question, k)", 270)
    m("S3_m4", "S3_dc", "S3_se", "4: các đoạn, điểm", 305, "return")
    m("S3_m5", "S3_se", "S3_pr", "5: salesInfo()", 385)
    m("S3_m6", "S3_pr", "S3_se", "6: giá, tồn, chứng nhận", 420, "return")
    m("S3_m7", "S3_se", "S3_a", "7: «create»(ASSISTANT, nội dung)", 500, "create")
    m("S3_m8", "S3_se", "S3_a", "8: cite(chunk, rank, score)", 680)
    m("S3_m9", "S3_a", "S3_ci", "9: «create»(rank, score)", 715, "create")
    m("S3_m10", "S3_se", "S3_kh", "10: câu trả lời, trích dẫn", 845, "return")
    q.act("S3_se", 130, 850)
    q.act("S3_q", 197, 215)
    q.act("S3_dc", 270, 310)
    q.act("S3_pr", 385, 425)
    q.act("S3_a", 522, 540)
    q.act("S3_a", 680, 725)
    q.act("S3_ci", 737, 755)
    q.frag("S3_P", "par", 140, 215, 1220, 450, ["S3_se", "S3_dc", "S3_pr"], [(None, 215), (None, 340)])
    q.frag("S3_O", "opt", 140, 565, 1730, 795, ["S3_se", "S3_a", "S3_ci"], [("có đoạn đủ liên quan", 565)])
    q.frag("S3_L", "loop", 160, 620, 1720, 770, ["S3_se", "S3_a", "S3_ci"], [("mỗi đoạn đã dùng", 620)], parent="S3_O_op0")
    q.draw()


# ------------------------------------------------------------------ communication
def com01(s):
    """COM01: cùng kịch bản đặt hàng như SEQ01, đánh số phân cấp thay cho trục thời gian."""
    b = B(s)
    objs = {"C1_kh": ("InteractionActor", "Khách hàng doanh nghiệp", (40, 70, 0, 0)),
            "C1_ca": ("InteractionLifeLine", ":Cart", (440, 70, 110, 44)),
            "C1_pp": ("InteractionLifeLine", ":PhysicalProduct", (400, 420, 190, 44)),
            "C1_or": ("InteractionLifeLine", ":Order", (880, 70, 120, 44)),
            "C1_oi": ("InteractionLifeLine", ":OrderItem", (865, 420, 150, 44))}
    for k, (t, n, _) in objs.items():
        b.new(k, t, n)
    links = [("C1_l1", "C1_kh", "C1_ca"), ("C1_l2", "C1_ca", "C1_pp"), ("C1_l3", "C1_ca", "C1_or"),
             ("C1_l4", "C1_or", "C1_oi")]
    for k, a, c in links:
        b.rel(k, "InteractionLifeLineLink", a, c)
    b.diag("D_COM01", "COM", "COM01 Đặt hàng")
    for k, (t, n, (x, y, w, h)) in objs.items():
        b.show(k, x, y, w or None, h or None)
    for k, a, c in links:
        b.conn(k)
    # (khoá, từ, tới, nhãn, link, x mũi tên, y mũi tên, vị trí nhãn: "trên" | "phải")
    msgs = [("C1_m1", "C1_kh", "C1_ca", "1: checkout(address)", "C1_l1", 290, 70, "trên"),
            ("C1_m2", "C1_ca", "C1_pp", "1.1 *[mỗi dòng]: isSellable()", "C1_l2", 520, 200, "phải"),
            ("C1_m3", "C1_ca", "C1_pp", "1.2 *[mỗi dòng]: canReserve(qty)", "C1_l2", 520, 260, "phải"),
            ("C1_m4", "C1_ca", "C1_pp", "1.3 *[mọi dòng đạt]: reserve(qty)", "C1_l2", 520, 320, "phải"),
            ("C1_m5", "C1_ca", "C1_or", "1.4: «create»(address, phí giao)", "C1_l3", 715, 70, "trên"),
            ("C1_m6", "C1_ca", "C1_or", "1.5: calculateTotal()", "C1_l3", 715, 125, "dưới"),
            ("C1_m7", "C1_or", "C1_oi", "1.4.1 *[mỗi dòng]: «create»(tên, qty, đơn giá)", "C1_l4", 965, 250, "phải")]
    for k, a, c, lab, ln, ax, ay, where in msgs:
        b.rel(k, "Message", a, c, lab)
        b.show(k, ax, ay, None, None, ln)
        b.scall(k, "fitSize")
        w = tw(lab) + 12
        # caption VP hiển thị lệch (+35, -25) so với toạ độ đặt; mũi tên hiện ở (ax + 20..40, ay - 37)
        lx, ly = {"trên": (ax - 5 - w / 2, ay - 32), "dưới": (ax - 5 - w / 2, ay + 5),
                  "phải": (ax + 30, ay - 10)}[where]
        b.caption(k, lx, ly, w, 22)
    s.note("N_COM01", "Cùng kịch bản với SEQ01. Số thứ tự phân cấp thay cho trục thời gian; * là lặp, [ ] là điều kiện.")
    b.show("N_COM01", 40, 540, 700, 50)


# ------------------------------------------------------------------ state machine
class Stm(B):
    def state(self, k, name, x, y, w=None, h=56):
        self.new(k, "State2", name)
        self.show(k, x, y, w or tw(name, True) + 60, h)

    def pseudo(self, k, typ, cx, cy):
        self.new(k, typ, None)
        self.show(k, cx - 15, cy - 15, 30, 30)

    def tr(self, k, a, b, label, pts, at=None):
        self.rel(k, "Transition2", a, b, label)
        self.conn(k, pts)
        if label and at:
            self.caption(k, at[0], at[1], tw(label) + 12, 22)


def stm01(s):
    """STM01: vòng đời Order (BR-05, BR-07, BR-08, BR-09, BR-13)."""
    m = Stm(s)
    m.diag("D_STM01", "STM", "STM01 Vòng đời đơn hàng (Order)")
    X, W = 90, 190
    cx = X + W / 2
    m.pseudo("T1_i", "InitialPseudoState", cx, 50)
    for k, n, y in (("T1_pl", "PLACED", 140), ("T1_pa", "PAID", 340), ("T1_pr", "PROCESSING", 540),
                    ("T1_sh", "SHIPPED", 740), ("T1_co", "COMPLETED", 940)):
        m.state(k, n, X, y, W)
    m.state("T1_ca", "CANCELLED", 760, 240, W)
    m.pseudo("T1_f1", "FinalState2", cx, 1070)
    m.pseudo("T1_f2", "FinalState2", 1030, 268)
    T, Bm, L, R = m.T, m.Bm, m.L, m.R
    m.tr("T1_t0", "T1_i", "T1_pl", None, [Bm("T1_i"), T("T1_pl")])
    m.tr("T1_t1", "T1_pl", "T1_pa", "markPaid() [amount ≥ totalAmount]", [Bm("T1_pl"), T("T1_pa")])
    m.tr("T1_t2", "T1_pa", "T1_pr", "startProcessing()", [Bm("T1_pa"), T("T1_pr")])
    m.tr("T1_t3", "T1_pr", "T1_sh", "markShipped() [đã có vận đơn]", [Bm("T1_pr"), T("T1_sh")])
    m.tr("T1_t4", "T1_sh", "T1_co", "complete() [đã giao, gói đã kích hoạt]", [Bm("T1_sh"), T("T1_co")])
    m.tr("T1_t5", "T1_pr", "T1_co", "complete() [không có hàng vật lý, gói đã kích hoạt]",
         [R("T1_pr"), (cx + 470, 568), (cx + 470, 968), R("T1_co")])
    m.tr("T1_t6", "T1_pl", "T1_ca", "cancel(reason) / release(qty)",
         [R("T1_pl", -12), (855, 156), T("T1_ca")], at=(400, 128))
    m.tr("T1_t7", "T1_pl", "T1_ca", "when(now > paymentDueAt) / release(qty)",
         [R("T1_pl", 14), (700, 182), (700, 268), L("T1_ca")], at=(300, 190))
    m.tr("T1_t8", "T1_pa", "T1_ca", "cancel(reason) / release(qty), tạo Refund",
         [R("T1_pa"), (855, 368), Bm("T1_ca")])
    m.tr("T1_t9", "T1_co", "T1_f1", None, [Bm("T1_co"), T("T1_f1")])
    m.tr("T1_t10", "T1_ca", "T1_f2", None, [R("T1_ca"), L("T1_f2")])


def stm02(s):
    """STM02: vòng đời Quotation (BR-11)."""
    m = Stm(s)
    m.diag("D_STM02", "STM", "STM02 Vòng đời báo giá (Quotation)")
    m.pseudo("T2_i", "InitialPseudoState", 55, 230)
    m.state("T2_dr", "DRAFT", 130, 202, 150)
    m.state("T2_se", "SENT", 760, 202, 150)
    m.state("T2_ac", "ACCEPTED", 1260, 60, 170)
    m.state("T2_rj", "REJECTED", 1260, 202, 170)
    m.state("T2_ex", "EXPIRED", 1260, 344, 170)
    for k, y in (("T2_f1", 88), ("T2_f2", 230), ("T2_f3", 372)):
        m.pseudo(k, "FinalState2", 1510, y)
    T, Bm, L, R = m.T, m.Bm, m.L, m.R
    m.tr("T2_t0", "T2_i", "T2_dr", None, [R("T2_i"), L("T2_dr")])
    m.tr("T2_t1", "T2_dr", "T2_se", "send() [có dòng] / validUntil = issuedAt + 30 ngày",
         [R("T2_dr"), L("T2_se")])
    m.tr("T2_t2", "T2_se", "T2_ac", "accept(address) [validUntil chưa qua]",
         [T("T2_se"), (835, 88), L("T2_ac")])
    m.tr("T2_t3", "T2_se", "T2_rj", "reject(reason)", [R("T2_se"), L("T2_rj")])
    m.tr("T2_t4", "T2_se", "T2_ex", "expire() [now > validUntil]", [Bm("T2_se"), (835, 372), L("T2_ex")])
    for i, (a, f) in enumerate((("T2_ac", "T2_f1"), ("T2_rj", "T2_f2"), ("T2_ex", "T2_f3"))):
        m.tr(f"T2_e{i}", a, f, None, [R(a), L(f)])
    s.note("N_STM02", "Báo giá có hạn 30 ngày kể từ issuedAt (BR-11). Đơn tạo khi chấp nhận dùng đơn giá báo và vẫn qua kiểm tra BR-04.")
    m.show("N_STM02", 40, 440, 760, 50)


# ------------------------------------------------------------------ object
def obj01(s):
    """OBJ01: bản chụp giá — đơn tạo từ báo giá dùng quotedUnitPrice, không dùng listPrice (BR-06, BR-11)."""
    b = B(s)
    inst = [  # khoá, tên, lớp, [(thuộc tính, giá trị)], (x, y)
        ("O1_q", "bg01", "dQuotation", [("quotationNumber", "\"BG-0001\""), ("status", "ACCEPTED"),
                                        ("validUntil", "30/11/2026")], (40, 40)),
        ("O1_ql", "dong1", "dQuotationLine", [("quantity", "40"), ("quotedUnitPrice", "950.000")], (40, 230)),
        ("O1_p", "anchor", "dDevice", [("sku", "\"ANC-01\""), ("listPrice", "1.000.000")], (380, 230)),
        ("O1_o", "dh01", "dOrder", [("orderNumber", "\"DH-0001\""), ("status", "PLACED")], (700, 40)),
        ("O1_oi", "dongDon1", "dOrderItem", [("productName", "\"Anchor UWB\""), ("quantity", "40"),
                                             ("unitPrice", "950.000")], (700, 230)),
    ]
    owner = {"dDevice": {"sku": "dProduct", "listPrice": "dProduct"}}
    for k, n, c, slots, _ in inst:
        b.new(k, "InstanceSpecification", n)
        b.call(k, "addClassifier", f"@{c}")
        for i, (a, v) in enumerate(slots):
            sk, vk = f"{k}_s{i}", f"{k}_v{i}"
            b.new(sk, "Slot", None, k)
            b.call(sk, "setFeature", f"@{owner.get(c, {}).get(a, c)}.{a}")
            b.new(vk, "CompositeValueSpecification", None)
            b.call(vk, "setValue", v)
            b.call(sk, "addValue", f"@{vk}")
    links = [("O1_l1", "O1_q", "O1_ql", "contains"), ("O1_l2", "O1_ql", "O1_p", "refers to"),
             ("O1_l3", "O1_q", "O1_o", "results in"), ("O1_l4", "O1_o", "O1_oi", "contains"),
             ("O1_l5", "O1_oi", "O1_p", "refers to")]
    for k, a, c, nm in links:
        b.rel(k, "Link", a, c, nm)
    b.diag("D_OBJ01", "OBJ", "OBJ01 Bản chụp giá khi chấp nhận báo giá")
    for k, n, c, slots, (x, y) in inst:
        b.show(k, x, y, None, None)
        b.scall(k, "setShowSlotsMode", "i:1")
        b.scall(k, "fitSize")
    for k, a, c, nm in links:
        b.conn(k)
    note = "Giá trị minh họa. dongDon1.unitPrice lấy từ dong1.quotedUnitPrice (950.000), không lấy anchor.listPrice (1.000.000)."
    s.note("N_OBJ01", note)
    b.show("N_OBJ01", 40, 380, 600, 72)


def _more():
    import beh_act_more as m
    return [m.act_uc06, act01, m.act_uc10, m.act_uc12, m.act_uc14, m.act_uc15, act02, m.act_uc20]



def build(s: Spec):
    s.pkg("P_BEH", "7. Mô hình hành vi")
    for f in _more() + [seq01, seq02, com01, stm01, stm02, obj01, act03, seq03]:
        f(s)
