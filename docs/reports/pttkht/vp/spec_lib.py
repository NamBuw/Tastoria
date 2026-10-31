# Thư viện nhỏ sinh spec TSV cho plugin VP pttkht.uml (xem ~/opt/vp/tools/pttkht-uml-plugin).
# Mỗi lệnh là một dòng, các trường cách nhau bởi TAB, '-' là rỗng.
#
# Đơn vị: toạ độ viết trong các tệp gen_*.py là "toạ độ thiết kế"; khi xuất ra spec được nhân POS.
# Kích thước lớp, use case tính theo font thật (DejaVu Sans, cỡ FONT px) nên đã ở đơn vị cuối.
# Waypoint có thể dùng điểm tính theo cạnh hình: s.T/B/L/R(key, f) và s.cx/cy/top/bottom/left/right(key).
from PIL import ImageFont

FONT = 15                 # cỡ chữ VP cho mọi hình và nhãn (gốc 11)
POS = 1.05                # hệ số giãn toạ độ thiết kế
_REG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", FONT)
_BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT)
ROW = round(18 * FONT / 15)       # chiều cao một dòng trong ngăn (đo ở cỡ 15)
BASE = round(30 * FONT / 15)


def tw(s, bold=False):
    return (_BOLD if bold else _REG).getlength(s)


class FN(float):
    """Số đã ở đơn vị cuối (không nhân POS)."""


class FP(tuple):
    """Điểm đã ở đơn vị cuối."""


def _f(x):
    if x is None or x == "":
        return "-"
    return str(x).replace("\n", "\\n")


def _fmt_op(o):
    name, rest = o.split("(", 1)
    params, ret = rest.split(")", 1)
    ps = ", ".join(p.strip().replace(":", " : ") for p in params.split(",") if p.strip())
    ret = ret.lstrip(":").strip()
    return f"+{name.strip()}({ps})" + (f" : {ret}" if ret else "")


class Spec:
    def __init__(self):
        self.lines = []
        self.classes = {}      # key -> (name, attrs, ops, stereo)
        self.names = {}        # key -> tên hiển thị (use case, actor...)
        self.cur_diag = None
        self.geo = {}          # key -> (x, y, w, h) trên sơ đồ hiện tại (đơn vị cuối)
        self.parent = {}       # key -> khoá hình cha (System) trên sơ đồ hiện tại
        self.sys = None        # (key, x, y, w, h) khung System của sơ đồ hiện tại
        self.rels = {}         # khoá quan hệ -> (from, to, tên)
        self.drawn = []        # (sơ đồ, quan hệ, có waypoint?)
        self.allgeo = {}       # sơ đồ -> hình học (để kiểm bố cục)
        self.ops = []          # thao tác của sơ đồ hiện tại, xuất ra sau khi nới bố cục
        self.notes_pending = []

    def emit(self, *fields):
        self.lines.append("\t".join(_f(x) for x in fields))

    # ---- mô hình ----
    def pkg(self, key, name):
        self.emit("PKG", key, name)

    def usepkg(self, key):
        self.emit("USEPKG", key)

    def actor(self, key, name, stereo=None, abstract=False):
        self.names[key] = name
        self.emit("ACTOR", key, name, stereo, "abstract" if abstract else None)

    def uc(self, key, name, eps=None, desc=None, abstract=False):
        self.names[key] = (name, list(eps or []))
        self.emit("UC", key, name, ";".join(eps) if eps else None, desc, "abstract" if abstract else None)

    def cls(self, key, name, attrs=(), ops=(), abstract=False, stereo=None, vis="-"):
        """attrs: 'name:Type' (private, '/name' = dẫn xuất); ops: 'name(p:T, q:U):R' (public)."""
        self.emit("CLASS", key, name, "abstract" if abstract else None, stereo)
        for a in attrs:
            n, t = a.split(":", 1)
            mult = None
            import re as _re
            m_ = _re.match(r"^(.*)\[([0-9*.]+)\]$", t.strip())
            if m_:                      # multiplicity kiểu "[1..*]"; "list[X]" là tên kiểu, giữ nguyên
                t, mult = m_.group(1), m_.group(2)
            n = n.strip()
            derived = n.startswith("/")
            self.emit("ATTR", key, vis, n.lstrip("/"), t.strip(), mult, "derived" if derived else None)
        for o in ops:
            name_, rest = o.split("(", 1)
            params, ret = rest.split(")", 1)
            ret = ret.lstrip(":").strip() or None
            self.emit("OPER", key, "+", name_.strip(), params.replace(" ", "") or None, ret)
        self.classes[key] = (name, list(attrs), list(ops), stereo)

    def enum(self, key, name, lits):
        self.emit("CLASS", key, name, None, "enumeration")
        for l in lits:
            self.emit("LIT", key, l)
        self.classes[key] = (name, list(lits), [], "enumeration")

    def assoc(self, key, a, b, name=None, ma=None, mb=None, agg_a=None, agg_b=None, role_a=None, role_b=None, nav=None):
        self.rels[key] = (a, b, name or "")
        self.emit("ASSOC", key, a, b, name, ma, mb, agg_a, agg_b, role_a, role_b, None, nav)

    def link(self, key, a, b):
        self.rels[key] = (a, b, "")
        self.emit("LINK", key, a, b)

    def acls(self, key, cls_key, assoc_key):
        self.emit("ACLS", key, cls_key, assoc_key)

    def gen(self, key, child, parent):
        self.rels[key] = (child, parent, "")
        self.emit("GEN", key, child, parent)

    def inc(self, key, base, included):
        self.rels[key] = (base, included, "<<Include>>")
        self.emit("INC", key, base, included)

    def extd(self, key, extending, base, ep=None, cond=None):
        self.rels[key] = (extending, base, "<<Extend>>")
        self.emit("EXTD", key, extending, base, ep, cond)

    def dep(self, key, client, supplier, stereo=None, name=None):
        self.rels[key] = (client, supplier, f"<<{stereo}>> {name or ''}")
        self.emit("DEP", key, client, supplier, stereo, name)

    def note(self, key, text):
        self.names[key] = text
        self.emit("NOTE", key, text)

    def proc(self, key, dfid, name):
        self.emit("PROC", key, dfid, name)

    def extent(self, key, name):
        self.emit("EXTENT", key, name)

    def flow(self, key, a, b, name):
        self.emit("FLOW", key, a, b, name)

    # ---- kích thước ----
    def csize(self, key, keep=None):
        """Kích thước lớp/kiểu liệt kê đặt cho VP ở cỡ FONT. Đo trên SVG VP xuất: rộng = chữ dài nhất + 8
        (±4px), enum rộng tối thiểu 157; cộng 8px rộng dự phòng vì hụt 1px là VP xuống dòng chữ."""
        name, attrs, ops, stereo = self.classes[key]
        if stereo == "enumeration":
            w = max([tw(name, True), tw("<<enumeration>>")] + [tw(l) for l in attrs]) + 8
            return int(max(w, 157) + 8), BASE + ROW * (len(attrs) + 1) - 2
        rows = []
        for a in attrs:
            n, t = a.split(":", 1)
            n = n.strip()
            t = __import__("re").sub(r"\[([0-9*.]+)\]$", r" [\1]", t.strip())   # VP hiện multiplicity sau kiểu
            rows.append(("-/ " + n[1:] if n.startswith("/") else "-" + n) + " : " + t)
        if keep is not None:
            ops = [o for o in ops if o.split("(")[0].strip() in keep]
        rows += [_fmt_op(o) for o in ops]
        w = max([tw(name, True)] + [tw(r) + (12 if "[" in r else 0) for r in rows] + ([tw("<<%s>>" % stereo)] if stereo else [])) + 8
        h = BASE + ROW * (max(len(attrs), 1) + len(ops) + (1 if stereo else 0)) - (4 if not ops else 0)
        return int(w + 8), int(h + 2)

    def ucsize(self, key, w_design=None):
        name, eps = self.names[key]
        need = tw(name) + 70
        if eps:
            need = max(need, tw("extension points", True) + 70, max(tw(e) for e in eps) + 70)
        w = max(need, (w_design or 0) * POS)
        h = (52 if not eps else 66 + 22 * len(eps)) * FONT / 11
        return int(w), int(h)

    # ---- sơ đồ ----
    def _gap_need(self, a, b, name):
        """Khoảng trống tối thiểu giữa hai hình cho một quan hệ thẳng (ngang, dọc).
        Quan hệ giữa hai lớp có multiplicity ở hai đầu: chừa thêm chỗ để nhãn tên không chạm số."""
        mult = a in self.classes and b in self.classes
        need = (tw(name) + (100 if mult else 70)) if name else (80 if mult else 60)
        return need, (100 if mult and name else 76)

    def _relax(self, fixed=()):
        """Chèn khoảng trống cho tới khi không còn hình chạm nhau và mỗi quan hệ thẳng đủ chỗ cho nhãn."""
        geo = self.geo
        conts = {self.sys[0]} if self.sys else set()
        free = [k for k in geo if k not in conts and k not in fixed]
        rels = [(r, ) + self.rels[r] for d, r, hp in self.drawn if d == self.cur_diag and not hp and r in self.rels]
        def shift(axis, at, amt):
            for k in free:
                x, y, w, h = geo[k]
                if axis == 0 and x >= at - 0.5: geo[k] = (x + amt, y, w, h)
                if axis == 1 and y >= at - 0.5: geo[k] = (x, y + amt, w, h)
        for _ in range(200):
            moved = False
            for i, a in enumerate(free):
                for b in free[i + 1:]:
                    A, B = geo[a], geo[b]
                    ox = min(A[0] + A[2], B[0] + B[2]) + 24 - max(A[0], B[0])
                    oy = min(A[1] + A[3], B[1] + B[3]) + 24 - max(A[1], B[1])
                    if ox > 0 and oy > 0:
                        # đẩy theo trục tách dễ hơn (lượng chồng nhỏ hơn)
                        if ox <= oy:
                            first, second = (a, b) if A[0] <= B[0] else (b, a)
                            shift(0, geo[second][0], ox)
                        else:
                            first, second = (a, b) if A[1] <= B[1] else (b, a)
                            shift(1, geo[second][1], oy)
                        moved = True
                        break
                if moved:
                    break
            if moved:
                continue
            for r, a, b, name in rels:
                if a not in geo or b not in geo or a == b or a in conts or b in conts:
                    continue
                A, B = geo[a], geo[b]
                gx = max(B[0] - (A[0] + A[2]), A[0] - (B[0] + B[2]))
                gy = max(B[1] - (A[1] + A[3]), A[1] - (B[1] + B[3]))
                need, vneed = self._gap_need(a, b, name)
                if gx >= gy and gx < need:
                    right = b if B[0] > A[0] else a
                    if right in free:
                        shift(0, geo[right][0], need - gx); moved = True; break
                if gy > gx and gy < vneed:
                    low = b if B[1] > A[1] else a
                    if low in free:
                        shift(1, geo[low][1], vneed - gy); moved = True; break
            if not moved:
                break

    def _finish_diag(self):
        if not getattr(self, "no_relax", False):
            self._relax()
        for key, x, text, at in self.notes_pending:
            bottom = max(g[1] + g[3] for k, g in self.geo.items())
            right = max(g[0] + g[2] for k, g in self.geo.items())
            w = max(360, min(700, right - 420, tw(text) + 30))
            y = bottom + 40
            if at:                  # đặt vào chỗ trống cho trước: (x, y, rộng) theo toạ độ thiết kế
                x, y, w = at[0] * POS, at[1] * POS, at[2] * POS
            lines = -(-int(tw(text)) // int(w - 40))
            self.geo[key] = (x, y, w, 26 + 21 * lines)
            self.ops.append(("show", key, None, True))
        self.notes_pending = []
        # xuất thao tác theo thứ tự đã ghi, dùng hình học sau khi nới; lớp được fit kích thước trước đường nối đầu tiên
        fitted = False
        for op in self.ops:
            if op[0] == "conn" and not fitted:
                self.emit("FIT", self.cur_diag)
                fitted = True
            if op[0] == "sys":
                key, name = op[1], op[2]
                X, Y, W, H = self.geo[key]
                self.emit("SYS", self.cur_diag, key, name, int(X), int(Y), int(W), int(H))
            elif op[0] == "show":
                key, parent, wh = op[1], op[2], op[3]
                X, Y, W, H = self.geo[key]
                self.emit("SHOW", self.cur_diag, key, int(X), int(Y), int(W) if wh else None, int(H) if wh else None, parent)
                if key in self.classes and any(__import__("re").search(r"\[[0-9*.]+\]$", a) for a in self.classes[key][1] if isinstance(a, str) and ":" in a):
                    self.emit("SCALL", self.cur_diag, key, "setShowClassMemberMultiplicity", "b:true")
                if key in getattr(self, "hide", {}):
                    self.emit("HIDEOPS", self.cur_diag, key, key, ",".join(self.hide[key]))
            elif op[0] == "conn":
                rel, pts, frm, to = op[1:]
                if callable(pts):
                    pts = pts(self)
                p = ";".join(f"{int(round(x))},{int(round(y))}" for x, y in (self._pt(q) for q in pts)) if pts else None
                self.emit("CONN", self.cur_diag, rel, frm, to, p)
            else:
                self.emit(*op[1])
        self.ops = []
        self.hide = {}
        if self.sys:
            key, x, y, w, h = self.sys
            kids = [g for k, g in self.geo.items() if self.parent.get(k) == key]
            if kids:
                r = max(g[0] + g[2] for g in kids) + 40
                b = max(g[1] + g[3] for g in kids) + 40
                w, h = max(w, r - x), max(h, b - y)
            self.geo[key] = (x, y, w, h)
            self.emit("BOUNDS", self.cur_diag, key, int(x), int(y), int(w), int(h))
        self.allgeo[self.cur_diag] = (dict(self.geo), dict(self.parent))
        self.geo, self.parent, self.sys = {}, {}, None

    def diag(self, key, typ, name):
        if self.cur_diag:
            self._finish_diag()
        self.cur_diag = key
        self.emit("DIAG", key, typ, name)

    def system(self, key, name, x, y, w, h):
        X, Y, W, H = x * POS, y * POS, w * POS, h * POS
        self.sys = (key, X, Y, W, H)
        self.geo[key] = (X, Y, W, H)
        self.ops.append(("sys", key, name))

    def show(self, key, x, y, w=None, h=None, parent=None, final=False, ops=None):
        """x, y: toạ độ thiết kế (nhân POS) trừ khi final=True; w, h: đơn vị cuối.
        ops: tên các thao tác hiện trên hình này (None = hiện hết); thao tác khác được ẩn trên hình."""
        X, Y = (x, y) if final else (x * POS, y * POS)
        if ops is not None and key in self.classes:
            hidden = [o.split("(")[0].strip() for o in self.classes[key][2] if o.split("(")[0].strip() not in ops]
            if hidden:
                self.hide = getattr(self, "hide", {})
                self.hide[key] = hidden
        if w is None and key in self.classes:
            W, H = self.csize(key, ops)  # đặt sẵn kích thước thật: VP kẹp đầu đường nối theo kích thước lúc tạo
            self.ops.append(("show", key, parent, True))
        else:
            W, H = (w or 100), (h or 50)
            self.ops.append(("show", key, parent, True))
        self.geo[key] = (X, Y, W, H)
        if parent:
            self.parent[key] = parent

    def show_actor(self, key, x, y):
        self.show(key, x, y, 30, 60)

    def show_uc(self, key, x, y, w=190, h=None, parent=None, eps=0):
        W, H = self.ucsize(key, w)
        self.show(key, x, y, W, H, parent)

    # điểm và số theo cạnh hình (đơn vị cuối)
    def box(self, k):
        return self.geo[k]

    def left(self, k): return FN(self.geo[k][0])
    def right(self, k): return FN(self.geo[k][0] + self.geo[k][2])
    def top(self, k): return FN(self.geo[k][1])
    def bottom(self, k): return FN(self.geo[k][1] + self.geo[k][3])
    def cx(self, k): return FN(self.geo[k][0] + self.geo[k][2] / 2)
    def cy(self, k): return FN(self.geo[k][1] + self.geo[k][3] / 2)

    def T(self, k, f=0.5): x, y, w, h = self.geo[k]; return FP((x + w * f, y))
    def B(self, k, f=0.5): x, y, w, h = self.geo[k]; return FP((x + w * f, y + h))
    def L(self, k, f=0.5): x, y, w, h = self.geo[k]; return FP((x, y + h * f))
    def R(self, k, f=0.5): x, y, w, h = self.geo[k]; return FP((x + w, y + h * f))

    def _pt(self, p):
        if isinstance(p, FP):
            return p
        return tuple(c if isinstance(c, FN) else c * POS for c in p)

    def conn(self, rel, pts=None, frm=None, to=None):
        self.drawn.append((self.cur_diag, rel, bool(pts)))
        self.ops.append(("conn", rel, pts, frm, to))

    def bus(self, parent, child, gap=34):
        """Nhánh cây generalization: đáy cha -> trục ngang -> đỉnh con (điểm chung ở cha)."""
        yb = FN(self.bottom(parent) + gap * POS)
        return [self.B(parent), (self.cx(parent), yb), (self.cx(child), yb), self.T(child)]

    def cstyle(self, rel, style):   # 0 vuông góc, 1 xiên
        self.ops.append(("raw", ("CSTYLE", self.cur_diag, rel, style)))

    def dstyle(self, style):
        self.ops.append(("raw", ("DSTYLE", self.cur_diag, style)))

    def route(self):                # VP định tuyến lại mọi đường nối theo kiểu vuông góc, không dời hình
        self.ops.append(("raw", ("ROUTE", self.cur_diag)))

    def lorient(self, rel, v=3):   # 3: nhãn chạy theo góc đường nối, chữ luôn đứng
        self.ops.append(("raw", ("LORIENT", self.cur_diag, rel, v)))

    def fit(self):
        self.ops.append(("raw", ("FIT", self.cur_diag)))

    def lint(self, only=None):
        """Kiểm bố cục trước khi dựng: hình chồng hình; quan hệ thẳng có khoảng trống quá ngắn cho nhãn."""
        probs = []
        for d, (geo, parent) in self.allgeo.items():
            if only and d not in only:
                continue
            ks = [k for k in geo if not any(parent.get(x) == k for x in geo)]   # bỏ khung System
            for i, a in enumerate(ks):
                for b in ks[i + 1:]:
                    A, B = geo[a], geo[b]
                    if A[0] < B[0] + B[2] + 8 and B[0] < A[0] + A[2] + 8 and A[1] < B[1] + B[3] + 8 and B[1] < A[1] + A[3] + 8:
                        probs.append(f"{d}: HÌNH CHẠM {a} × {b}")
            for dd, rel, has_pts in self.drawn:
                if dd != d or has_pts or rel not in self.rels:
                    continue
                a, b, name = self.rels[rel]
                if a not in geo or b not in geo or a == b:
                    continue
                A, B = geo[a], geo[b]
                gx = max(B[0] - (A[0] + A[2]), A[0] - (B[0] + B[2]))
                gy = max(B[1] - (A[1] + A[3]), A[1] - (B[1] + B[3]))
                need, vneed = self._gap_need(a, b, name)
                if gx >= gy and gx < need and gx > -1e9:
                    probs.append(f"{d}: NGẮN NGANG {rel} {a}->{b} gap={gx:.0f} cần {need:.0f}")
                if gy > gx and gy < vneed - 6:
                    probs.append(f"{d}: NGẮN DỌC {rel} {a}->{b} gap={gy:.0f} cần {vneed}")
        return probs

    def flush(self):
        """Xuất nốt sơ đồ đang dựng (trước các lệnh áp cho toàn dự án)."""
        if self.cur_diag:
            self._finish_diag()
            self.cur_diag = None

    def write(self, path):
        self.flush()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(self.lines) + "\n")
