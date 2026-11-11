"""Ghi bộ sơ đồ PlantUML từ model.py: docs/uml/<loại>/*.puml và docs/erd/*.puml.

python3 docs/sad/tools/diagrams/gen_puml.py   (xoá .puml cũ không còn trong bộ, rồi ghi lại toàn bộ)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402

ROOT = M.ROOT
UML = ROOT / "docs/uml"
ERD = ROOT / "docs/erd"
HEAD = """@startuml
title {title}
' Sinh từ docs/sad/tools/diagrams/model.py — sửa ở đó rồi chạy gen_puml.py, không sửa tay.
skinparam shadowing false
skinparam defaultFontName DejaVu Sans
skinparam defaultFontSize 13
skinparam dpi 110
"""


def q(s):
    return s.replace('"', "'").replace("\n", "\\n")


def akey(a):
    return a if a != "DRIVE" else "DRIVE"


# ---------------------------------------------------------------- use case
def w_uc(d):
    o = [HEAD.format(title=d["title"]), "left to right direction", "skinparam packageStyle rectangle",
         "skinparam actorStyle stick", "skinparam usecase {\n  BackgroundColor White\n  BorderColor Black\n}", ""]
    prim = [a for a in d["actors"] if any(l[0] == a and M.UCS[l[1]]["primary"] == a for l in d["links"])]
    sec = [a for a in d["actors"] if a not in prim]
    for a in prim:
        o.append(f'actor "{M.ACTOR[a]}\\n({a})" as {a}')
    o.append('rectangle "Tastoria" {')
    for u in d["ucs"]:
        o.append(f'  usecase "{u}\\n{q(M.ucname(u))}" as {u}')
    o.append("}")
    for a in sec:
        st = " <<system>>" if a in ("A09", "A10") else ""
        o.append(f'actor "{M.ACTOR[a]}\\n({a})" as {a}{st}')
    o.append("")
    for c, p in d["gens"]:
        o.append(f"{c} -|> {p}")
    for a, u in d["links"]:
        o.append(f"{a} -- {u}" if a in prim else f"{u} -- {a}")
    for kind, x, y, cond in d["rels"]:
        if kind == "include":
            o.append(f"{x} ..> {y} : <<include>>")
        else:
            o.append(f"{x} ..> {y} : <<extend>>" + (f"\\n[{q(cond)}]" if cond else ""))
    o.append("@enduml")
    return "\n".join(o)


def w_ctx(d):
    o = [HEAD.format(title=d["title"]), "left to right direction", "skinparam actorStyle stick", ""]
    name = lambda k: d.get("extra", {}).get(k) or M.ACTOR[k]
    for k, _ in d["left"]:
        o.append(f'actor "{name(k)}" as {k}' if k != "DRIVE" else f'rectangle "{name(k)}" as {k}')
    o.append(f'rectangle "{d["center"]}" as SYS #EEF6FB')
    for k, _ in d["right"]:
        st = " <<system>>" if k in ("A09", "A10") else ""
        o.append(f'actor "{name(k)}" as {k}{st}' if k != "DRIVE" else f'rectangle "{name(k)}" as {k}')
    for k, lab in d["left"]:
        o.append(f"{k} -- SYS : {lab}")
    for k, lab in d["right"]:
        o.append(f"SYS -- {k} : {lab}")
    o.append("@enduml")
    return "\n".join(o)


# ---------------------------------------------------------------- tuần tự
def w_seq(d):
    o = [HEAD.format(title=d["title"]), "autonumber", "hide footbox", "skinparam sequenceMessageAlign center",
         "skinparam ParticipantPadding 30", ""]
    for k, kind, name in d["lls"]:
        o.append(f'{kind} "{name}" as {k}')
    o.append("")

    def msg(it, ind=""):
        _, a, b, lab, kind = it
        o.append(f"{ind}{a} {'-->' if kind == 'ret' else '->'} {b} : {lab}")

    for it in d["items"]:
        if it[0] == "m":
            msg(it)
        else:
            _, op, operands = it
            for i, (g, ms) in enumerate(operands):
                o.append(("" if i == 0 else "else") + (op if i == 0 else "") + f" {g}")
                for mm in ms:
                    msg(mm, "  ")
            o.append("end")
    o.append("@enduml")
    return "\n".join(o)


# ---------------------------------------------------------------- hoạt động
def w_act(d):
    o = [HEAD.format(title=d["title"]), "skinparam ActivityBackgroundColor White", ""]
    for ln in d["lanes"]:
        o.append(f"|{ln}|")
    first = d["items"][0]
    o.append(f"|{first[1]}|")
    o.append("start")
    cur = [first[1]]

    def lane(ln, ind):
        if ln != cur[0]:
            o.append(f"{ind}|{ln}|")
            cur[0] = ln

    def emit(items, ind=""):
        for it in items:
            if it[0] == "a":
                lane(it[1], ind)
                o.append(f"{ind}:{it[2]};")
            elif it[0] == "stop":
                o.append(f"{ind}stop")
            elif it[0] == "if":
                _, ln, qq, yes, yi, no, ni = it
                lane(ln, ind)
                o.append(f"{ind}if ({qq}) then ({no})")
                emit(ni, ind + "  ")
                o.append(f"{ind}else ({yes})")
                emit(yi, ind + "  ")
                o.append(f"{ind}endif")
            elif it[0] == "fork":
                for i, br in enumerate(it[1]):
                    o.append(f"{ind}fork" if i == 0 else f"{ind}fork again")
                    emit(br, ind + "  ")
                o.append(f"{ind}end fork")
            elif it[0] == "while":
                _, ln, qq, yes, body, no = it
                lane(ln, ind)
                o.append(f"{ind}while ({qq}) is ({yes})")
                emit(body, ind + "  ")
                lane(ln, ind)
                o.append(f"{ind}endwhile ({no})")
    emit(d["items"])
    if d["items"][-1][0] != "stop":
        o.append("stop")
    o.append("@enduml")
    return "\n".join(o)


# ---------------------------------------------------------------- trạng thái
def w_state(d):
    o = [HEAD.format(title=d["title"]), "hide empty description", "skinparam StateBackgroundColor White", ""]
    for k, name, entry in d["states"]:
        if name == "<<choice>>":
            o.append(f"state {k} <<choice>>")
        else:
            o.append(f'state "{name}" as {k}' + (f" : entry / {entry}" if entry else ""))
    o.append("")
    for a, b, lab in d["trans"]:
        a2 = "[*]" if a == "*" else a
        b2 = "[*]" if b == "#" else b
        o.append(f"{a2} --> {b2}" + (f" : {lab}" if lab else ""))
    o.append("@enduml")
    return "\n".join(o)


# ---------------------------------------------------------------- lớp
ARROW = {"assoc": "--", "comp": "*--", "dep": "..>", "gen": "--|>"}


def w_class(d):
    o = [HEAD.format(title=d["title"]), "hide circle", "hide empty members", "skinparam classAttributeIconSize 0",
         "skinparam ClassBackgroundColor White", ""]
    for k, name, attrs, ops, st in d["classes"]:
        o.append(f'class "{name}" as {k}' + (f" <<{st}>>" if st else "") + " {")
        for at in attrs:
            o.append(f"  -{at}")
        for op in ops:
            o.append(f"  +{op}")
        o.append("}")
    o.append("")
    for kind, x, y, lab, ma, mb in d["rels"]:
        l = f'"{ma}" ' if ma and kind != "comp" else ""
        r = f' "{mb}"' if mb else ""
        o.append(f"{x} {l}{ARROW[kind]}{r} {y}" + (f" : {lab}" if lab else ""))
    o.append("@enduml")
    return "\n".join(o)


# ---------------------------------------------------------------- thành phần / triển khai / gói
SHAPE = {"comp": "component", "deploy": "node", "pkg": "package"}


def w_struct(d):
    o = [HEAD.format(title=d["title"]), "skinparam componentStyle rectangle", ""]
    kids = {}
    for b in d["boxes"]:
        kids.setdefault(b[3], []).append(b)

    def shape(b):
        k, name, st, parent = b
        if d["kind"] == "comp":
            return "database" if st == "database" else "queue" if st == "queue" else "component"
        if d["kind"] == "deploy":
            return "artifact" if st == "artifact" else "cloud" if st == "cloud" else "node"
        return "package" if k in kids or parent is None else "file"

    def emit(b, ind):
        k, name, st, _ = b
        sts = f" <<{st}>>" if st and st not in ("artifact",) else ""
        if k in kids:
            o.append(f'{ind}{shape(b)} "{q(name)}" as {k}{sts} {{')
            for c in kids[k]:
                emit(c, ind + "  ")
            o.append(f"{ind}}}")
        else:
            o.append(f'{ind}{shape(b)} "{q(name)}" as {k}{sts}')
    for b in kids.get(None, []):
        emit(b, "")
    o.append("")
    for a, b, lab in d["links"]:
        o.append(f"{a} ..> {b}" + (f" : {lab}" if lab else ""))
    o.append("@enduml")
    return "\n".join(o)


W = {"uc": w_uc, "ctx": w_ctx, "seq": w_seq, "act": w_act, "state": w_state, "class": w_class,
     "comp": w_struct, "deploy": w_struct, "pkg": w_struct}


# ---------------------------------------------------------------- ERD
def erd_api():
    """Bộ đọc DDL dùng chung với gen_erd.py (một cách hiểu schema cho cả PlantUML và VP)."""
    sys.path.insert(0, str(ERD))
    import gen_erd as ns
    ns.HOME.update({t: g for g, (_, _, ts) in M.ERD_GROUPS.items() for t in ts})
    return vars(ns)


def stubs_of(ns, ts):
    out = []
    for t in ts:
        for fk in ns["T"][t]["fks"]:
            if fk["ref"] not in ts and fk["ref"] not in out:
                out.append(fk["ref"])
    return out


def w_erd_groups(ns):
    T = ns["T"]
    allg = sorted(t for _, _, ts in M.ERD_GROUPS.values() for t in ts)
    assert allg == sorted(T), set(allg) ^ set(T)
    files = {}
    for gid, (slug, title, ts) in M.ERD_GROUPS.items():
        stubs = stubs_of(ns, ts)
        assert len(ts) + len(stubs) <= 8, (gid, len(ts), stubs)
        b = ["@startuml", f"title {title}",
             "' Sinh từ db/schema.sql qua docs/sad/tools/diagrams/gen_puml.py — không sửa tay.",
             "hide circle", "skinparam linetype ortho", "skinparam defaultFontName DejaVu Sans", ""]
        for t in ts:
            b.append(ns["entity_full"](t))
        for t in stubs:
            b.append(ns["entity_stub"](t).replace(" #EEEEEE", " #EEEEEE"))
        b.append("")
        for t in ts:
            for fk in T[t]["fks"]:
                b.append(ns["rel"](t, fk))
        b += ["", "legend right", "  * = NOT NULL; PK khoá chính; FK khoá ngoại; UQ duy nhất",
              "  Bảng nền xám thuộc sơ đồ khác (chỉ ghi khoá chính)", "endlegend", "@enduml", ""]
        files[ERD / f"{gid}-{slug}.puml"] = "\n".join(b)
    # tổng quan: chỉ tên bảng, nhóm theo module, không nhãn quan hệ
    gid, slug, title = M.ERD_OVERVIEW
    b = ["@startuml", f"title {title}", "' Sinh từ db/schema.sql — không sửa tay.", "hide circle",
         "hide empty members", "skinparam defaultFontName DejaVu Sans", "skinparam linetype ortho",
         "skinparam packageStyle rectangle", ""]
    for g, (_, t2, ts) in M.ERD_GROUPS.items():
        b.append(f'package "{g} {t2.split(" — ")[1]}" {{')
        for t in ts:
            b.append(f'  entity "{t}" as {t}')
        b.append("}")
    b += ["@enduml", ""]
    files[ERD / f"{gid}-{slug}.puml"] = "\n".join(b)
    return files


def chen_parse():
    src = (ERD / "src/khai-niem-day-du.chen").read_text()
    blocks = {}
    for mm in re.finditer(r'^(entity|relationship) "([^"]+)" as (\w+)( <<\w+>>)? \{', src, re.M):
        i, depth = mm.end(), 1
        while depth:
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        blocks[mm.group(3)] = (mm.group(1), mm.group(2), src[mm.start():i], bool(mm.group(4)))
    links = re.findall(r"^(\w+) ([-=])(\w+)\2 (\w+)$", src, re.M)
    return blocks, links


def chen_attrs(raw):
    """Thuộc tính cấp một; giữ khoá và tối đa 2 thuộc tính khác để sơ đồ gọn."""
    top, depth = [], 0
    for ln in raw.split("\n")[1:-1]:
        t = ln.strip()
        if depth == 0 and t and t != "}":
            top.append(t.rstrip(" {"))
        depth += ln.count("{") - ln.count("}")
    keys = [t for t in top if "<<key>>" in t]
    return keys + [t for t in top if "<<key>>" not in t][:2]


def chen_entity(b):
    kind, name, raw, weak = b
    first = raw.split("\n")[0]
    return "\n".join([first] + ["  " + t for t in chen_attrs(raw)] + ["}"])


def w_chen():
    blocks, links = chen_parse()
    files = {}
    for gid, (slug, title, ents) in M.CHEN_GROUPS.items():
        rels = {}
        for a, line, card, b in links:
            e, r = (a, b) if a in ents or b in ents else (None, None)
            if a in blocks and blocks[a][0] == "relationship":
                e, r = b, a
            elif b in blocks and blocks[b][0] == "relationship":
                e, r = a, b
            rels.setdefault(r, []).append((e, line, card, a == e))
        keep = [r for r, ends in rels.items() if r and len(ends) == 2 and all(x[0] in ents for x in ends)]
        o = ["@startchen", f"title {title}", "' Tách từ docs/erd/src/khai-niem-day-du.chen bằng gen_puml.py.", ""]
        for e in ents:
            o.append(chen_entity(blocks[e]))
        for r in keep:
            o.append(blocks[r][2])
        o.append("")
        for r in keep:
            for e, line, card, e_first in rels[r]:
                o.append(f"{e} {line}{card}{line} {r}" if e_first else f"{r} {line}{card}{line} {e}")
        o += ["", "@endchen", ""]
        files[ERD / f"{gid}-{slug}.puml"] = "\n".join(o)
    return files


def chen_model():
    """Dùng cho VP: thực thể (tên, yếu?, thuộc tính khoá) và quan hệ (tên, hai đầu, bản số) theo nhóm."""
    blocks, links = chen_parse()
    rels = {}
    for a, line, card, b in links:
        e, r = (b, a) if blocks.get(a, ("",))[0] == "relationship" else (a, b)
        rels.setdefault(r, []).append((e, card, line == "="))
    out = {}
    for gid, (slug, title, ents) in M.CHEN_GROUPS.items():
        es = []
        for e in ents:
            kind, name, raw, weak = blocks[e]
            attrs = chen_attrs(raw)
            es.append((e, name, weak, attrs))
        rs = [(r, blocks[r][1], ends) for r, ends in rels.items()
              if len(ends) == 2 and all(x[0] in ents for x in ends)]
        out[gid] = (slug, title, es, rs)
    return out


def main():
    files = {}
    for d in M.DIAGRAMS:
        files[UML / M.FOLDER[d["kind"]] / f"{d['id']}-{d['slug']}.puml"] = W[d["kind"]](d) + "\n"
    ns = erd_api()
    files.update(w_erd_groups(ns))
    files.update(w_chen())
    keep = set(files)
    for p in list(UML.glob("*/*.puml")) + list(ERD.glob("*.puml")):
        if "/out/" not in str(p) and p not in keep:
            p.unlink()
    for p, txt in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    print("ghi", len(files), "tệp .puml")


if __name__ == "__main__":
    main()
