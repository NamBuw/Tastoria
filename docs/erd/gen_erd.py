"""Đọc DDL (db/schema.sql + migration tạo bảng sau 0001) và dựng khối entity/quan hệ chân quạ.

Thư viện cho docs/sad/tools/diagrams/gen_puml.py, nơi chia nhóm ERD01a–ERD07b, ERD08 và tách Chen ERD00a–h.
Chạy tệp này = chạy gen_puml.py (ghi lại toàn bộ sơ đồ)."""
import re, sys, pathlib, json

ROOT = pathlib.Path("/home/namnx/NamBuw/Tastoria")
SQL = (ROOT / "db/schema.sql").read_text()
_MIG = ROOT / "backend/src/tastoria/migrations/versions"
for _f in sorted(_MIG.glob("0*.py")):
    _m = re.search(r'UPGRADE = """(.*?)"""', _f.read_text(), re.S)
    if _m and "CREATE TABLE" in _m.group(1):
        SQL += "\n" + re.sub(r"\n\s+REFERENCES", " REFERENCES", _m.group(1))

def parse(sql):
    tables = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", sql, re.S):
        name, body = m.group(1), m.group(2)
        t = {"cols": [], "pk": [], "uq": [], "fks": [], "partial": []}
        merged, buf = [], ""
        for raw in body.split("\n"):
            buf = (buf + " " + raw.strip()) if buf else raw.strip()
            if buf.count("(") == buf.count(")"):
                merged.append(buf)
                buf = ""
        for line in merged:
            line = line.strip().rstrip(",")
            if not line:
                continue
            if line.startswith("CONSTRAINT"):
                c = re.match(r"CONSTRAINT (\w+) (PRIMARY KEY|UNIQUE(?: NULLS NOT DISTINCT)?|FOREIGN KEY|CHECK) ?\((.*?)\)(.*)", line)
                kind, cols, rest = c.group(2), c.group(3), c.group(4)
                if kind == "PRIMARY KEY":
                    t["pk"] = [x.strip() for x in cols.split(",")]
                elif kind.startswith("UNIQUE"):
                    t["uq"].append([x.strip() for x in cols.split(",")])
                elif kind == "FOREIGN KEY":
                    r = re.match(r" REFERENCES (\w+) \((.*?)\)(.*)", rest)
                    t["fks"].append({"cols": [x.strip() for x in cols.split(",")], "ref": r.group(1),
                                     "refcols": [x.strip() for x in r.group(2).split(",")],
                                     "action": r.group(3).strip()})
                continue
            parts = line.split()
            cname = parts[0]
            rest = " ".join(parts[1:])
            ctype = re.split(r" NOT NULL| DEFAULT| GENERATED", rest)[0].strip()
            nn = "NOT NULL" in rest or "GENERATED ALWAYS" in rest
            t["cols"].append({"name": cname, "type": ctype, "nn": nn})
        tables[name] = t
    for m in re.finditer(r"CREATE UNIQUE INDEX (\w+) ON (\w+) \((.*?)\) WHERE (.*?);", sql):
        tables[m.group(2)]["partial"].append(f"UNIQUE({m.group(3)}) WHERE {m.group(4)}")
    for m in re.finditer(r"ALTER TABLE (\w+) ADD CONSTRAINT \w+ FOREIGN KEY \((.*?)\) REFERENCES (\w+) \((.*?)\)(.*?);", sql):
        tables[m.group(1)]["fks"].append({"cols": [x.strip() for x in m.group(2).split(",")], "ref": m.group(3),
                                          "refcols": [x.strip() for x in m.group(4).split(",")],
                                          "action": m.group(5).strip()})
    # PK cột NOT NULL ngầm định
    for t in tables.values():
        for c in t["cols"]:
            if c["name"] in t["pk"]:
                c["nn"] = True
    return tables

T = parse(SQL)
assert len(T) == 63, len(T)

HOME = {}   # bảng -> mã ERD chứa chi tiết; gen_puml.py điền trước khi dùng entity_stub

def is_unique(t, cols):
    """Khoá ngoại là duy nhất khi tập cột của nó chứa một khoá (PK hoặc UNIQUE)."""
    s = set(cols)
    return set(T[t]["pk"]) <= s or any(set(u) <= s for u in T[t]["uq"])

def nn(t, col):
    return next(c for c in T[t]["cols"] if c["name"] == col)["nn"]

def rel(child, fk):
    parent = fk["ref"]
    all_nn = all(nn(child, c) for c in fk["cols"])
    pend = "||" if all_nn else "|o"
    cend = "o|" if is_unique(child, fk["cols"]) else "o{"
    label = ", ".join(fk["cols"])
    act = re.sub(r"\s*\(.*\)", "", fk["action"]).replace("ON DELETE ", "")
    if act:
        label += " (" + act.lower().replace(" ", "_") + ")"
    return f"{parent} {pend}--{cend} {child} : {label}"

def fk_cols(t):
    s = set()
    for fk in T[t]["fks"]:
        s.update(fk["cols"])
    return s

def entity_full(t):
    tb = T[t]
    fkc = fk_cols(t)
    single_uq = {u[0] for u in tb["uq"] if len(u) == 1}
    lines = [f'entity "{t}" as {t} {{']
    def fmt(c):
        marks = []
        if c["name"] in tb["pk"]:
            marks.append("PK")
        if c["name"] in fkc:
            marks.append("FK")
        if c["name"] in single_uq:
            marks.append("UQ")
        star = "* " if c["nn"] else "  "
        m = f" <<{', '.join(marks)}>>" if marks else ""
        return f"  {star}{c['name']} : {c['type']}{m}"
    for c in tb["cols"]:
        if c["name"] in tb["pk"]:
            lines.append(fmt(c))
    lines.append("  --")
    for c in tb["cols"]:
        if c["name"] not in tb["pk"]:
            lines.append(fmt(c))
    multi = [u for u in tb["uq"] if len(u) > 1]
    for u in multi:
        lines.append(f"  .. UNIQUE({', '.join(u)}) ..")
    for u in tb.get("partial", []):
        lines.append(f"  .. {u} ..")
    lines.append("}")
    return "\n".join(lines)

def entity_stub(t):
    tb = T[t]
    erd = HOME[t].split("-")[0]
    lines = [f'entity "{t}" as {t} #EEEEEE {{']
    for c in tb["cols"]:
        if c["name"] in tb["pk"]:
            lines.append(f"  * {c['name']} : {c['type']} <<PK>>")
    lines.append(f"  .. chi tiết ở {erd} ..")
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    import runpy
    runpy.run_path(str(ROOT / "docs/sad/tools/diagrams/gen_puml.py"), run_name="__main__")
