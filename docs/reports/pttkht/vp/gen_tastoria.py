"""Dựng spec Visual Paradigm (plugin pttkht.uml) từ đúng bộ sơ đồ PlantUML: docs/sad/tools/diagrams/model.py.

Tên, mã và nội dung mỗi sơ đồ trùng 1:1 với tệp .puml cùng mã. Bố cục tính tự động theo loại sơ đồ.
ERD chi tiết (ERD01a–ERD07b) dựng riêng ở Tastoria-ERD.vpp bằng plugin tastoria.erd (xem build.sh).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "docs/sad/tools/diagrams"))
sys.path.insert(0, str(HERE))
import model as M  # noqa: E402
import gen_puml as G  # noqa: E402
from spec_lib import Spec, FONT, tw, FP  # noqa: E402
from gen_beh import Act, Seq, Stm, B  # noqa: E402

s = Spec()
s.no_relax = True
s.emit("NEWPROJECT")
s.emit("FONTSIZE", FONT)
s.emit("CPTCENTER", 1)
s.emit("EXTDIR", 3, 2)


def name_of(title):
    return title.replace(" — ", " ")


def start(d, typ, pkg=True):
    if pkg:
        s.pkg("P" + d["id"], d["id"])
        s.usepkg("P" + d["id"])
    s.diag(d["id"], typ, name_of(d["title"]))


def K(d, k):
    return f"{d['id']}_{k}"


def footer(did, bottom, right=400):
    """Ghi chú nhỏ dưới cùng chừa chỗ cho dòng watermark của VP CE."""
    k = f"{did}_foot"
    s.emit("NOTE", k, f"Tastoria | {did}")
    s.emit("SHOW", did, k, 20, int(bottom + 50), 260, 34, None)


def mult(c):
    return {"N": "*", "M": "*"}.get(c, c)


# ------------------------------------------------------------------ kích thước ước lượng
def box_size(name, rows=(), stereo=None, minw=150):
    w = max([tw(name, True)] + [tw(r.replace(":", " : ")) for r in rows] +
            ([tw(f"<<{stereo}>>")] if stereo else [])) + 36
    h = 30 + (19 if stereo else 0) + 19 * max(len(rows), 1) + 14
    return max(w, minw), h


def grid_xy(grid, sizes, gx=130, gy=110, x0=40, y0=40, gxs=None):
    cols = max(c for c, r in grid.values()) + 1
    rows = max(r for c, r in grid.values()) + 1
    cw = [max([sizes[k][0] for k, (c, r) in grid.items() if c == i and k in sizes] or [150]) for i in range(cols)]
    rh = [max([sizes[k][1] for k, (c, r) in grid.items() if r == j and k in sizes] or [60]) for j in range(rows)]
    gl = gxs or [gx] * cols
    xs = [x0 + sum(cw[:i]) + sum(gl[:i]) for i in range(cols)]
    ys = [y0 + sum(rh[:j]) + gy * j for j in range(rows)]
    return {k: (xs[c] + (cw[c] - sizes[k][0]) / 2, ys[r] + (rh[r] - sizes[k][1]) / 2) for k, (c, r) in grid.items()
            if k in sizes}


# ------------------------------------------------------------------ use case
def vp_uc(d):
    start(d, "UC")
    prim = [a for a in d["actors"] if any(l[0] == a and M.UCS[l[1]]["primary"] == a for l in d["links"])]
    sec = [a for a in d["actors"] if a not in prim]
    for a in d["actors"]:
        s.actor(K(d, a), M.ACTOR[a], stereo="system" if a in ("A09", "A10") else None)
    eps = {}
    for kind, x, y, cond in d["rels"]:
        if kind == "extend":
            eps.setdefault(y, []).append(x)
    for u in d["ucs"]:
        s.uc(K(d, u), f"{u} {M.ucname(u)}", eps=eps.get(u))
    linked = {u for _, u in d["links"]}
    order = {a: i for i, a in enumerate(d["actors"])}
    first_actor = lambda u: min(order[a] for a, x in d["links"] if x == u)
    col0 = sorted([u for u in d["ucs"] if u in linked], key=lambda u: (first_actor(u), d["ucs"].index(u)))
    multi = [u for u in d["ucs"] if u not in linked and sum(1 for k, x, y, _ in d["rels"] if x == u) > 1]
    col0 += multi
    col1 = [u for u in d["ucs"] if u not in linked and u not in multi]
    size = {u: s.ucsize(K(d, u)) for u in d["ucs"]}
    W0 = max([size[u][0] for u in col0] or [300])
    W1 = max([size[u][0] for u in col1] or [0])
    sx, sy, gap = 260, 30, 40
    pos, y = {}, sy + 60
    for u in col0:
        if u in multi:
            y += 60
        pos[u] = (sx + 50, y)
        y += size[u][1] + gap
    y1 = sy + 60
    for u in col1:
        base = next((yy for k, x, yy, _ in d["rels"] if x == u and yy in pos), None) or \
            next((x for k, x, yy, _ in d["rels"] if yy == u and x in pos), None)
        yb = pos[base][1] if base else y1
        yy = max(yb, y1)
        pos[u] = (sx + 50 + W0 + 200, yy)
        y1 = yy + size[u][1] + gap
    bottom = max(p[1] + size[u][1] for u, p in pos.items()) + 40
    width = 50 + W0 + (200 + W1 if col1 else 0) + 50
    s.system(K(d, "sys"), "Tastoria", sx / 1.05, sy / 1.05, width / 1.05, (bottom - sy) / 1.05)
    for u, (x, y) in pos.items():
        s.show(K(d, u), x, y, size[u][0], size[u][1], parent=K(d, "sys"), final=True)
    def ay(a):
        ys = [pos[u][1] + size[u][1] / 2 for x, u in d["links"] if x == a]
        return sum(ys) / len(ys)
    ys = sorted(((ay(a), a) for a in prim))
    placed = []
    for y, a in ys:
        if placed and y - placed[-1][0] < 115:
            y = placed[-1][0] + 115
        placed.append((y, a))
    over = max(0, placed[-1][0] + 60 - bottom) if placed else 0
    for y, a in placed:
        s.show(K(d, a), 70, y - 30 - over / 2, 30, 60, final=True)
    bottom = max(bottom, (placed[-1][0] + 60) if placed else 0)
    right = sx + width + 120
    for i, a in enumerate(sec):
        s.show(K(d, a), right, ay(a) - 30 + 70 * i, 30, 60, final=True)
    for c, p in d["gens"]:
        s.gen(K(d, f"g{c}"), K(d, c), K(d, p))
        s.conn(K(d, f"g{c}"))
    for i, (a, u) in enumerate(d["links"]):
        s.link(K(d, f"l{i}"), K(d, a), K(d, u))
        ax_, ay_ = s.geo[K(d, a)][:2]
        ux, uy, uw, uh = s.geo[K(d, u)]
        if a in sec:
            s.conn(K(d, f"l{i}"), [FP((ax_, ay_ + 22)), FP((ux + uw, uy + uh / 2))])
        else:
            s.conn(K(d, f"l{i}"), [FP((ax_ + 30, ay_ + 22)), FP((ux, uy + uh / 2))])
    for i, (kind, x, y, cond) in enumerate(d["rels"]):
        if kind == "include":
            s.inc(K(d, f"r{i}"), K(d, x), K(d, y))
        else:
            s.extd(K(d, f"r{i}"), K(d, x), K(d, y), x, cond)
        s.conn(K(d, f"r{i}"))
    footer(d["id"], bottom)
    s.flush()


def vp_ctx(d):
    start(d, "CLASS")
    name = lambda k: d.get("extra", {}).get(k) or M.ACTOR[k]
    sysk = K(d, "SYS")
    s.cls(sysk, d["center"], stereo="system")
    n = max(len(d["left"]), len(d["right"]))
    H = max(n * 150, 200)
    s.show(sysk, 520, 40 + H / 2 - 40, 300, 90, final=True)
    for side, items, x in (("L", d["left"], 60), ("R", d["right"], 1300)):
        for i, (k, lab) in enumerate(items):
            kk = K(d, k)
            if k == "DRIVE":
                s.cls(kk, name(k), stereo="system")
                s.show(kk, x - 60, 40 + i * 150 + (H - len(items) * 150) / 2 + 40, 260, 70, final=True)
            else:
                s.actor(kk, name(k), stereo="system" if k in ("A09", "A10") else None)
                s.show(kk, x, 40 + i * 150 + (H - len(items) * 150) / 2 + 30, 30, 60, final=True)
            r = K(d, "r" + k)
            s.assoc(r, kk, sysk, name=lab) if side == "L" else s.assoc(r, sysk, kk, name=lab)
            s.conn(r)
    footer(d["id"], 40 + H + 60)
    s.flush()


# ------------------------------------------------------------------ tuần tự
def vp_seq(d):
    q = Seq(s)
    s.pkg("P" + d["id"], d["id"])
    s.usepkg("P" + d["id"])
    lls = d["lls"]
    idx = {k: i for i, (k, _, _) in enumerate(lls)}
    widths = [max(tw(n, True) + 40, 110) if kind != "actor" else 60 for k, kind, n in lls]
    msgs = []
    for it in d["items"]:
        if it[0] == "m":
            msgs.append(it)
        else:
            for _, ms in it[2]:
                msgs.extend(ms)
    n = 0
    labels = []
    for mm in msgs:
        n += 1
        labels.append(f"{n}: {mm[3]}")
    cx = [0.0] * len(lls)
    cx[0] = 90
    for i in range(1, len(lls)):
        cx[i] = cx[i - 1] + max((widths[i - 1] + widths[i]) / 2 + 60, 170)
    for _ in range(10):
        for mm, lab in zip(msgs, labels):
            a, b = sorted((idx[mm[1]], idx[mm[2]]))
            if a == b:
                if a + 1 < len(lls):
                    b, need = a + 1, tw(lab) + 140
                else:
                    continue
            else:
                need = tw(lab) + 50
            if cx[b] - cx[a] < need:
                sh = need - (cx[b] - cx[a])
                for j in range(b, len(lls)):
                    cx[j] += sh
    LL = [(K(d, k), kind if kind != "entity" or True else kind, nm, cx[i], widths[i], None)
          for i, (k, kind, nm) in enumerate(lls)]
    top = 30
    y = top + 110
    plan = []   # (msg, y)
    frag = None
    k = 0
    for it in d["items"]:
        if it[0] == "m":
            plan.append((it, y, labels[k]))
            k += 1
            y += 50 + (26 if it[1] == it[2] else 0)
        else:
            _, op, operands = it
            fy1 = y - 20
            ops = []
            for g, ms in operands:
                ops.append((g, y - 20 if not ops else y - 14))
                y += 58
                for mm in ms:
                    plan.append((mm, y, labels[k]))
                    k += 1
                    y += 50
                y -= 14
            inv = {mm[1] for mm, _, _ in plan[-sum(len(ms) for _, ms in operands):]} | \
                  {mm[2] for mm, _, _ in plan[-sum(len(ms) for _, ms in operands):]}
            xs = [cx[idx[v]] for v in inv]
            frag = (op, min(xs) - 70, fy1, max(xs) + 70, y + 10, sorted(inv, key=lambda v: idx[v]), ops)
            y += 60
    bottom = y + 30
    q.setup(K(d, "ll"), LL, top, bottom)
    q.diag(d["id"], "SEQ", name_of(d["title"]))
    for i, (mm, my, lab) in enumerate(plan):
        q.msg(K(d, f"m{i}"), K(d, mm[1]), K(d, mm[2]), lab, my, "return" if mm[4] == "ret" else "call")
    for kk, kind, nm in lls:
        if kind == "actor":
            continue
        ys = [my for mm, my, _ in plan if kk in (mm[1], mm[2])]
        if ys:
            q.act(K(d, kk), min(ys) - 10, max(ys) + 10)
    if frag:
        op, x1, y1, x2, y2, inv, ops = frag
        q.frag(K(d, "f"), op, x1, y1, x2, y2, [K(d, v) for v in inv], ops)
    q.draw()
    footer(d["id"], bottom, cx[-1])
    s.flush()


# ------------------------------------------------------------------ hoạt động
def act_layout(d):
    nodes, edges = [], []   # nodes: [key, type, lane, col, row, text]; edges: (a, b, guard, mode)
    cnt = [0]
    row = [1]

    def new(typ, lane, col, text=None):
        cnt[0] += 1
        k = f"n{cnt[0]}"
        nodes.append([k, typ, lane, col, row[0], text])
        row[0] += 1
        return k

    first_lane = d["items"][0][1]
    nodes.append(["start", "InitialNode", first_lane, 0, 0, None])

    def run(items, prev, col, pguard=None):
        """trả về (nút cuối, đã dừng?)"""
        g = pguard
        for it in items:
            if it[0] == "a":
                k = new("ActivityAction", it[1], col, it[2])
                edges.append((prev, k, g, "auto"))
                prev, g = k, None
            elif it[0] == "stop":
                k = new("ActivityFinalNode", lane_of(prev), col)
                edges.append((prev, k, g, "auto"))
                return k, True
            elif it[0] == "if":
                _, ln, qq, yes, yi, no, ni = it
                dk = new("DecisionNode", ln, col, qq)
                edges.append((prev, dk, g, "auto"))
                r0 = row[0]
                ny_last, ny_stop = run(ni, dk, col + 1, no) if ni else (dk, False)
                r_no = row[0]
                row[0] = r0
                yl, ys = run(yi, dk, col, yes) if yi else (dk, False)
                row[0] = max(row[0], r_no)
                if ny_stop:
                    prev, g = yl, (yes if not yi else None)
                    if ys:
                        return yl, True
                    continue
                mk = new("MergeNode", ln, col)
                edges.append((yl, mk, yes if not yi else None, "auto"))
                edges.append((ny_last, mk, no if not ni else None, "side_merge"))
                prev, g = mk, None
            elif it[0] == "fork":
                fk = new("ForkNode", lane_of(prev), col)
                edges.append((prev, fk, g, "auto"))
                r0, ends, rmax = row[0], [], row[0]
                for br in it[1]:
                    row[0] = r0
                    n0 = len(edges)
                    last, _ = run(br, fk, col)
                    edges[n0] = edges[n0][:3] + ("fromfork",)
                    ends.append(last)
                    rmax = max(rmax, row[0])
                row[0] = rmax
                jk = new("JoinNode", lane_of(prev), col)
                for e in ends:
                    edges.append((e, jk, None, "tojoin"))
                prev, g = jk, None
            elif it[0] == "while":
                _, ln, qq, yes, body, no = it
                dk = new("DecisionNode", ln, col, qq)
                edges.append((prev, dk, g, "auto"))
                n0 = len(edges)
                last, _ = run(body, dk, col, yes)
                if n0 < len(edges):
                    e0 = edges[n0]
                    edges[n0] = (e0[0], e0[1], e0[2], "body")
                edges.append((last, dk, None, "loop"))
                prev, g = dk, ("exit", no)
        return prev, False

    def lane_of(k):
        return next(n[2] for n in nodes if n[0] == k)

    last, stopped = run(d["items"], "start", 0)
    if not stopped:
        k = new("ActivityFinalNode", lane_of(last), 0)
        edges.append((last, k, None, "auto"))
    return nodes, edges


def vp_act(d):
    a = Act(s)
    s.pkg("P" + d["id"], d["id"])
    s.usepkg("P" + d["id"])
    nodes, edges = act_layout(d)
    ROWH = 92
    colw = {}
    for k, typ, ln, col, r, text in nodes:
        w = tw(text) + 60 if typ == "ActivityAction" else (2 * (tw(text) + 50) if typ == "DecisionNode" else 80)
        colw[(ln, col)] = max(colw.get((ln, col), 0), w, 200)
    lanes = []
    x = 20
    cxs = {}
    for ln in d["lanes"]:
        cols = sorted(c for (l2, c) in colw if l2 == ln) or [0]
        w = sum(colw.get((ln, c), 200) for c in range(max(cols) + 1)) + 40
        cx = x + 20
        for c in range(max(cols) + 1):
            cxs[(ln, c)] = cx + colw.get((ln, c), 200) / 2
            cx += colw.get((ln, c), 200)
        lanes.append((K(d, "L" + str(len(lanes))), ln, w))
        x += w
    laneKey = {ln: lanes[i][0] for i, ln in enumerate(d["lanes"])}
    maxrow = max(n[4] for n in nodes)
    a.diag(d["id"], "ACT", name_of(d["title"]))
    a.lanes(K(d, "SW"), lanes, 20, 90 + (maxrow + 1) * ROWH + 30)
    for k, typ, ln, col, r, text in nodes:
        cy = 20 + 30 + 50 + r * ROWH
        if typ == "DecisionNode":
            a.new(K(d, k), typ, text)
            w = 36
            a.show(K(d, k), cxs[(ln, col)] - w / 2, cy - w / 2, w, w, laneKey[ln])
            # câu hỏi là tên nút quyết định, đặt phía trên bên trái, trong làn
            a.caption(K(d, k), cxs[(ln, col)] - 20 - tw(text) - 12, cy - 44, tw(text) + 12, 22)
        elif typ in ("ForkNode", "JoinNode"):
            continue
        else:
            a.node(K(d, k), typ, cxs[(ln, col)], cy, text, lane=laneKey[ln])
    for k, typ, ln, col, r, text in nodes:      # thanh fork/join trải qua các nhánh nối với nó
        if typ not in ("ForkNode", "JoinNode"):
            continue
        cy = 20 + 30 + 50 + r * ROWH
        xs = [cxs[(ln, col)]] + [a.geo[K(d, e[1] if typ == "ForkNode" else e[0])][0] +
                                 a.geo[K(d, e[1] if typ == "ForkNode" else e[0])][2] / 2
                                 for e in edges if (e[0] if typ == "ForkNode" else e[1]) == k and
                                 K(d, e[1] if typ == "ForkNode" else e[0]) in a.geo]
        a.new(K(d, k), typ, None)
        a.show(K(d, k), min(xs) - 40, cy - 4, max(xs) - min(xs) + 80, 8)
    geo = a.geo

    def P(k):
        return K(d, k)
    routed = []
    for i, (x1, x2, g, mode) in enumerate(edges):
        A, Bk = P(x1), P(x2)
        ax, ay, aw, ah = geo[A]
        bx, by, bw, bh = geo[Bk]
        acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
        guard = g[1] if isinstance(g, tuple) else g
        dec = nodes[[n[0] for n in nodes].index(x1)][1] == "DecisionNode"
        if mode == "fromfork":
            pts = [(bcx, ay + ah), (bcx, by)]
        elif mode == "tojoin":
            pts = [(acx, ay + ah), (acx, by)]
        elif nodes[[n[0] for n in nodes].index(x2)][1] in ("ForkNode", "JoinNode") or \
                nodes[[n[0] for n in nodes].index(x1)][1] in ("ForkNode", "JoinNode"):
            src_bar = nodes[[n[0] for n in nodes].index(x1)][1] in ("ForkNode", "JoinNode")
            xx = bcx if src_bar else acx
            pts = [(xx, ay + ah), (xx, by)]
        elif mode == "loop":
            xr = max([g_[0] + g_[2] for g_ in geo.values() if g_[2] > 40 and abs(g_[0] + g_[2] / 2 - bcx) < 5
                      and by - 5 < g_[1] < ay + ah + 5] + [ax + aw, bx + bw]) + 30
            pts = [(ax + aw, acy), (xr, acy), (xr, bcy), (bx + bw, bcy)]
        elif isinstance(g, tuple):    # thoát vòng lặp: vòng phải thân vòng
            body = [geo[P(n[0])] for n in nodes if n[0] != x1 and acx - 5 < geo[P(n[0])][0] + geo[P(n[0])][2] / 2 < acx + 5
                    and ay < geo[P(n[0])][1] < by]
            xl = min([bb[0] for bb in body] + [ax]) - 30
            yy = by - (50 if nodes[[n[0] for n in nodes].index(x2)][1] == "DecisionNode" else 22)
            pts = [(ax, acy), (xl, acy), (xl, yy), (bcx, yy), (bcx, by)] if abs(bcx - acx) < 5 else \
                [(ax, acy), (xl, acy), (xl, bcy), (bx if bcx > xl else bx + bw, bcy)]
        elif mode == "side_merge":
            if abs(acx - bcx) < 5:
                pts = [(acx, ay + ah), (bcx, by)]
            elif x1 == x2:
                pts = None
            else:
                pts = [(acx, ay + ah) if x1 not in [e[0] for e in edges if e[3] == "x"] else (ax + aw, acy),
                       (acx, bcy), (bx + bw if acx > bcx else bx, bcy)]
                if nodes[[n[0] for n in nodes].index(x1)][1] == "DecisionNode":
                    xr = acx + 0
                    pts = [(ax + aw, acy), (ax + aw + 60, acy), (ax + aw + 60, bcy), (bx + bw, bcy)]
        elif abs(acx - bcx) < 5:
            pts = [(acx, ay + ah), (bcx, by)] if bcy > acy else [(acx, ay), (bcx, by + bh)]
        elif mode == "body":
            pts = [(acx, ay + ah), (acx, bcy), (bx if bcx > acx else bx + bw, bcy)]
        elif dec and guard and sum(1 for e in edges if e[0] == x1) > 1 and \
                [e for e in edges if e[0] == x1][0][1] != x2:     # nhánh chính của nút quyết định: xuống rồi ngang
            pts = [(acx, ay + ah), (acx, bcy), (bx + bw if acx > bcx else bx, bcy)]
        else:
            pts = [(ax + aw if bcx > acx else ax, acy), (bcx, acy), (bcx, by)]
        routed.append((i, x1, A, Bk, pts, guard))
    # nhãn rẽ nhánh: nhánh đi ngang ghi ngay cạnh đoạn ngang; nhánh đi xuống ghi ở phía đối diện nhánh ngang
    hdir = {}
    for i, x1, A, Bk, pts, guard in routed:
        if pts and pts[1][1] == pts[0][1] and pts[1][0] != pts[0][0]:
            hdir.setdefault(x1, set()).add(1 if pts[1][0] > pts[0][0] else -1)
    for i, x1, A, Bk, pts, guard in routed:
        if not guard:
            at = None
        elif pts[1][0] == pts[0][0]:
            right = -1 in hdir.get(x1, set()) or not hdir.get(x1)
            if 1 in hdir.get(x1, set()):
                right = False
            at = (pts[0][0] + 6, pts[0][1] + 2) if right else (pts[0][0] - tw(guard) - 18, pts[0][1] + 2)
        elif pts[1][0] > pts[0][0]:
            at = (pts[0][0] + 8, pts[0][1] - 26)
        else:
            at = (pts[0][0] - tw(guard) - 20, pts[0][1] + 4)
        a.flow(K(d, f"e{i}"), A, Bk, pts, guard, at)
    footer(d["id"], 20 + 90 + (maxrow + 1) * ROWH + 30)
    s.flush()


# ------------------------------------------------------------------ trạng thái
def vp_state(d):
    m = Stm(s)
    s.pkg("P" + d["id"], d["id"])
    s.usepkg("P" + d["id"])
    m.diag(d["id"], "STM", name_of(d["title"]))
    sizes = {}
    for k, name, entry in d["states"]:
        sizes[k] = (36, 36) if name == "<<choice>>" else (max(tw(name, True) + 60, 150), 56)
    sizes["*"] = (30, 30)
    sizes["#"] = (30, 30)
    ncol = max(c for c, r in d["grid"].values()) + 1
    gxs = [190] * ncol
    for a_, b_, lab in d["trans"]:
        if a_ in d["grid"] and b_ in d["grid"]:
            (c1, r1), (c2, r2) = d["grid"][a_], d["grid"][b_]
            if r1 == r2 and abs(c1 - c2) == 1:
                gxs[min(c1, c2)] = max(gxs[min(c1, c2)], tw(lab) + 60)
    xy = grid_xy(d["grid"], sizes, gy=120, gxs=gxs)
    for k, name, entry in d["states"]:
        x, y = xy[k]
        if name == "<<choice>>":
            m.new(K(d, k), "Choice", None)
            m.show(K(d, k), x, y, 36, 36)
        else:
            m.state(K(d, k), name, x, y, sizes[k][0], 56)
    x, y = xy["*"]
    m.pseudo(K(d, "init"), "InitialPseudoState", x + 15, y + 15)
    if "#" in xy and any(t[1] == "#" for t in d["trans"]):
        x, y = xy["#"]
        m.pseudo(K(d, "fin"), "FinalState2", x + 15, y + 15)
    key = lambda v: K(d, "init") if v == "*" else K(d, "fin") if v == "#" else K(d, v)
    pairs = {(a, b) for a, b, _ in d["trans"]}
    labels = []
    for i, (a, b, lab) in enumerate(d["trans"]):
        A, Bk = key(a), key(b)
        others = [g for kk, g in m.geo.items() if kk not in (A, Bk)]
        pts = state_route(m.geo[A], m.geo[Bk], others, (b, a) in pairs and a < b, (b, a) in pairs)
        at = None
        if lab:
            at = label_at(pts, lab, labels + others)
            labels.append((at[0], at[1], tw(lab) + 12, 22))
        m.tr(K(d, f"t{i}"), A, Bk, lab or None, pts, at)
    footer(d["id"], max(g[1] + g[3] for g in m.geo.values()))
    s.flush()


def _hits(p, q, boxes, pad=6):
    (x1, y1), (x2, y2) = p, q
    for bx, by, bw, bh in boxes:
        if min(x1, x2) < bx + bw + pad and max(x1, x2) > bx - pad and min(y1, y2) < by + bh + pad and \
                max(y1, y2) > by - pad:
            return True
    return False


def path_ok(pts, boxes):
    return not any(_hits(pts[i], pts[i + 1], boxes) for i in range(len(pts) - 1))


def state_route(Ag, Bg, others, first, paired):
    ax, ay, aw, ah = Ag
    bx, by, bw, bh = Bg
    acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
    o = (-12 if first else 12) if paired else 0
    cands = []
    if abs(acy - bcy) < 30:
        cands.append([(ax + aw if bcx > acx else ax, acy + o), (bx if bcx > acx else bx + bw, acy + o)])
        yt = min(ay, by) - 40 - (12 if first else 0)
        cands.append([(acx + 15, ay), (acx + 15, yt), (bcx - 15, yt), (bcx - 15, by)])
        yb = max(ay + ah, by + bh) + 40
        cands.append([(acx - 15, ay + ah), (acx - 15, yb), (bcx + 15, yb), (bcx + 15, by + bh)])
    elif abs(acx - bcx) < 30:
        cands.append([(acx + o, ay + ah if bcy > acy else ay), (acx + o, by if bcy > acy else by + bh)])
        xr = max(ax + aw, bx + bw) + 40
        cands.append([(ax + aw, acy), (xr, acy), (xr, bcy), (bx + bw, bcy)])
        xl = min(ax, bx) - 40
        cands.append([(ax, acy), (xl, acy), (xl, bcy), (bx, bcy)])
    else:
        ex = bx + bw * (0.75 if acx > bcx else 0.25)
        cands.append([(ax + aw if bcx > acx else ax, acy), (ex, acy), (ex, by if bcy > acy else by + bh)])
        sx = ax + aw * (0.75 if bcx > acx else 0.25)
        cands.append([(sx, ay + ah if bcy > acy else ay), (sx, bcy), (bx if bcx > acx else bx + bw, bcy)])
    for c in cands:
        if path_ok(c, others):
            return c
    return cands[0]


def label_at(pts, lab, avoid):
    w = tw(lab) + 12
    segs = sorted(range(len(pts) - 1), key=lambda i: -(abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])))
    for i in segs:
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        opts = [(mx - w / 2, my - 26), (mx - w / 2, my + 4)] if abs(y1 - y2) < 2 else \
            [(mx + 8, my - 11), (mx - w - 8, my - 11), (mx + 8, my + 14), (mx - w - 8, my - 36)]
        for x, y in opts:
            if not any(x < bx + bw and x + w > bx and y < by + bh and y + 22 > by for bx, by, bw, bh in avoid):
                return (x, y)
    (x1, y1), (x2, y2) = pts[segs[0]], pts[segs[0] + 1]
    return ((x1 + x2) / 2 + 8, (y1 + y2) / 2 - 26)


# ------------------------------------------------------------------ lớp
def vp_class(d):
    start(d, "CLASS")
    sizes = {}
    for k, name, attrs, ops, st in d["classes"]:
        kk = K(d, k)
        s.emit("CLASS", kk, name, None, st)
        rows = []
        for at in attrs:
            n_, t_ = (at.split(":", 1) + [""])[:2]
            s.emit("ATTR", kk, "-", n_.strip(), t_.strip() or None, None, None)
            rows.append("-" + at)
        for op in ops:
            nm, rest = op.split("(", 1)
            params, ret = rest.rsplit(")", 1)
            ret = ret.lstrip(":").strip() or None
            s.emit("OPER", kk, "+", nm, params.replace(" ", "") or None, ret)
            rows.append("+" + op.replace(":", " : "))
        sizes[k] = box_size(name, rows, st)
    cols = max(c for c, r in d["grid"].values()) + 1
    gxs = [230] * cols
    for kind, x, y, lab, ma, mb in d["rels"]:
        (c1, r1), (c2, r2) = d["grid"][x], d["grid"][y]
        if r1 == r2 and abs(c1 - c2) == 1:
            gxs[min(c1, c2)] = max(gxs[min(c1, c2)], tw(lab) + tw(ma) + tw(mb) + 110)
    xy = grid_xy(d["grid"], sizes, gy=140, gxs=gxs)
    for k, *_ in d["classes"]:
        s.show(K(d, k), xy[k][0], xy[k][1], int(sizes[k][0]), int(sizes[k][1]), final=True)
    for i, (kind, x, y, lab, ma, mb) in enumerate(d["rels"]):
        r = K(d, f"r{i}")
        if kind in ("assoc", "comp"):
            s.assoc(r, K(d, x), K(d, y), name=lab or None, ma=(ma or None) if kind != "comp" else None, mb=mb or None,
                    agg_a="composite" if kind == "comp" else None)
        elif kind == "dep":
            s.dep(r, K(d, x), K(d, y))
        else:
            s.gen(r, K(d, x), K(d, y))
        s.conn(r)
    footer(d["id"], max(xy[k][1] + sizes[k][1] for k in sizes))
    s.flush()
    if any(c[4] in ("boundary", "control", "entity") for c in d["classes"]):
        for k, *_ in d["classes"]:
            s.emit("SCALL", d["id"], K(d, k), "setDisplayAsRobustnessAnalysisIcon", "b:false")


# ------------------------------------------------------------------ thành phần / triển khai / gói
def _cross(p1, p2, p3, p4):
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(p1, p2, p3) * o(p1, p2, p4) < 0 and o(p3, p4, p1) * o(p3, p4, p2) < 0


def best_grid(keys, links, sizes, cols=4, seed=11, tries=6000):
    """Chọn ô lưới cho các hộp: không đường nối xuyên hộp, ít giao cắt giữa các đường, đường ngắn."""
    import random
    rnd = random.Random(seed)
    rows = -(-len(keys) // cols) + 1
    cells = [(c, r) for r in range(rows) for c in range(cols)]
    def cost(grid):
        xy = grid_xy(grid, sizes, gx=190, gy=130, x0=80, y0=100)
        cen = {k: (xy[k][0] + sizes[k][0] / 2, xy[k][1] + sizes[k][1] / 2) for k in keys}
        boxes = {k: (xy[k][0], xy[k][1], *sizes[k]) for k in keys}
        c = 0
        segs = [(cen[a], cen[b], a, b) for a, b in links]
        for p, q, a, b in segs:
            c += 1000 * sum(1 for k in keys if k not in (a, b) and _hits(p, q, [boxes[k]], pad=14))
            c += (abs(grid[a][0] - grid[b][0]) + abs(grid[a][1] - grid[b][1]))
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                if not {segs[i][2], segs[i][3]} & {segs[j][2], segs[j][3]} and _cross(*segs[i][:2], *segs[j][:2]):
                    c += 40
        return c
    best, bc = None, None
    for _ in range(60):                       # leo đồi từ nhiều điểm xuất phát
        grid = dict(zip(keys, rnd.sample(cells, len(keys))))
        cc = cost(grid)
        for _ in range(tries // 20):
            k = rnd.choice(keys)
            cell = rnd.choice(cells)
            other = next((o for o in keys if grid[o] == cell), None)
            g2 = dict(grid)
            g2[k] = cell
            if other:
                g2[other] = grid[k]
            c2 = cost(g2)
            if c2 <= cc:
                grid, cc = g2, c2
        if bc is None or cc < bc:
            best, bc = grid, cc
    return best


def vp_struct(d):
    typ = {"comp": "CMP", "deploy": "DPL", "pkg": "PKGD"}[d["kind"]]
    start(d, typ)
    s.emit("DSTYLE", d["id"], 1)   # đường nối thẳng, khớp với bước chọn ô lưới
    kids = {}
    for b in d["boxes"]:
        kids.setdefault(b[3], []).append(b)
    sizes = {}
    for k, name, st, parent in d["boxes"]:
        if k in kids:
            continue
        lines = name.split("\n")
        w = max(tw(l, True) for l in lines) + 70
        if st:
            w = max(w, tw(f"<<{st}>>") + 70)
        sizes[k] = (max(w, 170), 60 + 20 * len(lines) + (14 if st else 0))
    leaf_grid = {k: v for k, v in d["grid"].items() if k in sizes}
    if d["kind"] == "comp" and not any(lab for _, _, lab in d["links"]) and len(sizes) > 4:
        leaf_grid = best_grid(list(sizes), [(x, y) for x, y, _ in d["links"]], sizes)
    xy = grid_xy(leaf_grid, sizes, gx=300 if kids.keys() - {None} else 190, gy=130, x0=80, y0=100)
    geo = {k: (xy[k][0], xy[k][1], *sizes[k]) for k in sizes}
    for k in [b[0] for b in d["boxes"] if b[0] in kids]:
        ch = [geo[c[0]] for c in kids[k]]
        x1 = min(g[0] for g in ch) - 40
        y1 = min(g[1] for g in ch) - 60
        x2 = max(g[0] + g[2] for g in ch) + 40
        y2 = max(g[1] + g[3] for g in ch) + 40
        geo[k] = (x1, y1, x2 - x1, y2 - y1)
    # hộp ngoài cùng không con nằm cạnh cha (lưới riêng đã tránh chồng)
    for k, name, st, parent in d["boxes"]:
        kk = K(d, k)
        if d["kind"] == "comp":
            t = "Component"
        elif d["kind"] == "deploy":
            t = "Artifact" if st == "artifact" else "Node"
        else:
            t = "Package" if (k in kids or parent is None) else "Class"
        s.emit("NEW", kk, t, name.replace("\n", " "), K(d, parent) if parent else None)
        if st and st != "artifact":
            s.emit("CALL", kk, "addStereotype", st)
    order = [b for b in d["boxes"] if b[3] is None] + [b for b in d["boxes"] if b[3] is not None]
    for k, name, st, parent in order:
        x, y, w, h = geo[k]
        s.emit("SHOW", d["id"], K(d, k), int(x), int(y), int(w), int(h), K(d, parent) if parent else None)
    for i, (x1, x2, lab) in enumerate(d["links"]):
        r = K(d, f"r{i}")
        s.dep(r, K(d, x1), K(d, x2), name=lab or None)
        s.emit("CONN", d["id"], r, None, None, None)
    footer(d["id"], max(g[1] + g[3] for g in geo.values()))
    s.flush()


# ------------------------------------------------------------------ Chen (ký pháp lớp) và tổng quan bảng
CHEN_GRID = {
    "ERD00a": {"DIUNG": (0, 0), "NGUOIDUNG": (1, 0), "HOSO": (2, 0), "CHEDO": (2, 1), "NHOMTP": (1, 1)},
    "ERD00b": {"NHOMTP": (0, 0), "NGUYENLIEU": (1, 0), "DIUNG": (2, 0), "THUCPHAM": (1, 1), "CHATDD": (2, 1),
               "MON": (0, 1), "BUOCNAU": (0, 2)},
    "ERD00c": {"NGUOIDUNG": (0, 0), "LOKHO": (1, 0), "GIAODICH": (2, 0), "NGUYENLIEU": (1, 1), "CHIP": (0, 1)},
    "ERD00d": {"NGUOIDUNG": (0, 0), "LANQUET": (1, 0), "ANHQUET": (2, 0), "CHIP": (1, 1), "KHUNG": (2, 1),
               "NGUYENLIEU": (1, 2), "LOPTG": (2, 2)},
    "ERD00e": {"LOKHO": (0, 0), "NGUOIDUNG": (1, 0), "MAM": (1, 1), "MONMAM": (2, 1), "PHIENNAU": (1, 2),
               "MON": (2, 2), "BUOCNAU": (1, 3)},
    "ERD00f": {"NGUOIDUNG": (0, 0), "TUONGTAC": (1, 0), "MON": (2, 0), "MAM": (1, 1), "MOHINH": (2, 1),
               "LOPTG": (2, 2)},
    "ERD00g": {"NGUOIDUNG": (0, 0), "SUKIENDY": (1, 0), "DIEUKHOAN": (2, 0), "MUCDICH": (2, 1)},
    "ERD00h": {"PHIEUKS": (0, 0), "NGUOIKS": (1, 0), "DIEUKHOAN": (2, 0), "PHANCONG": (1, 1), "MON": (2, 1),
               "DIEMKS": (1, 2)},
}


def vp_chen():
    for gid, (slug, title, es, rs) in G.chen_model().items():
        s.pkg("P" + gid, gid)
        s.usepkg("P" + gid)
        s.diag(gid, "CLASS", name_of(title))
        for e, name, weak, attrs in es:
            kk = f"{gid}_{e}"
            s.emit("CLASS", kk, name, None, "weak entity" if weak else "entity")
            for at in attrs:
                s.emit("ATTR", kk, "0", re.sub(r"\s*<<(?!key)[^>]*>>", "", at).replace(" <<key>>", " {key}"),
                       None, None, None)
        sizes = {e: box_size(name, attrs, "entity") for e, name, weak, attrs in es}
        grid = CHEN_GRID[gid]
        xy = grid_xy(grid, sizes, gx=240, gy=150)
        for e, *_ in es:
            s.show(f"{gid}_{e}", xy[e][0], xy[e][1], int(sizes[e][0]), int(sizes[e][1]), final=True)
        for r, rname, ends in rs:
            (e1, c1, t1), (e2, c2, t2) = ends
            rk = f"{gid}_{r}"
            s.assoc(rk, f"{gid}_{e1}", f"{gid}_{e2}", name=rname, ma=mult(c1), mb=mult(c2))
            s.conn(rk)
        footer(gid, max(xy[e][1] + sizes[e][1] for e in sizes))
        s.flush()
        for e, *_ in es:
            s.emit("SCALL", gid, f"{gid}_{e}", "setDisplayAsRobustnessAnalysisIcon", "b:false")


def vp_overview(ns):
    gid, slug, title = M.ERD_OVERVIEW
    s.pkg("P" + gid, gid)
    s.usepkg("P" + gid)
    s.diag(gid, "CLASS", name_of(title))
    y = 40
    for g, (_, t2, ts) in M.ERD_GROUPS.items():
        nk = f"{gid}_n{g}"
        s.note(nk, g + " " + t2.split(" — ")[1])
        s.show(nk, 40, y + 4, 520, 40, final=True)
        x = 600
        for t in ts:
            s.emit("CLASS", f"{gid}_{t}", t, None, "table")
            w = box_size(t, [], "table", 120)[0]
            s.show(f"{gid}_{t}", x, y, int(w), 56, final=True)
            x += w + 40
        y += 86
    footer(gid, y)
    s.flush()


V = {"uc": vp_uc, "ctx": vp_ctx, "seq": vp_seq, "act": vp_act, "state": vp_state, "class": vp_class,
     "comp": vp_struct, "deploy": vp_struct, "pkg": vp_struct}

if __name__ == "__main__":
    only = set(sys.argv[1:])
    for d in M.DIAGRAMS:
        if not only or d["id"] in only:
            V[d["kind"]](d)
    if not only or only & set(M.CHEN_GROUPS):
        vp_chen()
    if not only or M.ERD_OVERVIEW[0] in only:
        vp_overview(G.erd_api())
    s.flush()
    s.emit("ELEMFONT", FONT)
    s.emit("REPOINT")
    s.emit("SANITIZE", "Tastoria – Phân tích và thiết kế", "Nhóm Tastoria")
    out = HERE / ("Tastoria.vpp" if not only else "Tastoria-test.vpp")
    s.emit("SAVEAS", str(out))
    spec = HERE / ("spec_tastoria.tsv" if not only else "spec_test.tsv")
    s.write(str(spec))
    print("Wrote", len(s.lines), "commands ->", spec)
