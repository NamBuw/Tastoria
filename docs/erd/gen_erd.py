"""Sinh ERD chân quạ ERD01–08 từ db/schema.sql.

Dùng: python3 docs/erd/gen_erd.py [thư mục đích] [tệp schema.json]
Mặc định ghi vào docs/erd; ERD00 (Chen) viết tay, không sinh."""
import re, sys, pathlib, json

ROOT = pathlib.Path("/home/namnx/NamBuw/Tastoria")
SQL = (ROOT / "db/schema.sql").read_text()

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
assert len(T) == 62, len(T)

GROUPS = {
    "ERD01-dinh-danh-quyen-rieng-tu": ("ERD01 — Lõi, định danh và quyền riêng tư (core, identity, privacy)",
        ["idempotency_keys", "users", "refresh_tokens", "password_resets", "consent_purposes", "policy_versions",
         "consent_events", "dsr_requests", "audit_log"]),
    "ERD02-ho-so": ("ERD02 — Hồ sơ người dùng (profile) và danh mục được tham chiếu",
        ["profiles", "user_allergens", "user_favorite_recipes", "user_settings"]),
    "ERD03-danh-muc-thanh-phan": ("ERD03 — Danh mục: thành phần thực phẩm, nguyên liệu, dị ứng, chế độ ăn, đơn vị, mức lượng, lớp thị giác",
        ["food_groups", "nutrient_sources", "food_items", "nutrients", "food_nutrients", "allergen_groups", "diets",
         "diet_exclusions", "ingredients", "ingredient_synonyms", "ingredient_allergens", "ingredient_units",
         "qty_levels", "vision_classes", "vision_class_ingredients"]),
    "ERD04-mon-an": ("ERD04 — Món ăn: công thức, bước, thẻ, nguồn, dinh dưỡng món",
        ["cooking_methods", "tags", "recipes", "recipe_ingredients", "recipe_steps", "recipe_tags", "recipe_sources",
         "recipe_nutrition"]),
    "ERD05-kho-quet": ("ERD05 — Kho (pantry) và quét ảnh (scan)",
        ["pantry_lots", "pantry_transactions", "scans", "scan_images", "scan_items", "detections"]),
    "ERD06-mam-nau": ("ERD06 — Mâm cơm, thay thế, phiên nấu và tương tác (meal, substitute, cooking, events)",
        ["substitution_pairs", "ingredient_embeddings", "shopping_items", "meal_plans", "meal_plan_coeater_allergens",
         "meal_plan_pins", "meal_plan_items", "meal_plan_item_substitutions", "cook_sessions",
         "cook_schedule_entries", "interactions"]),
    "ERD07-khao-sat-mo-hinh": ("ERD07 — Khảo sát gu (survey) và vận hành mô hình (mlops)",
        ["model_versions", "model_version_classes", "model_deployments", "survey_forms", "survey_form_anchors",
         "survey_respondents", "survey_assignments", "survey_ratings", "survey_favorites"]),
}
HOME = {t: g for g, (_, ts) in GROUPS.items() for t in ts}
allg = [t for _, ts in GROUPS.values() for t in ts]
assert sorted(allg) == sorted(T) and len(allg) == 62, set(T) ^ set(allg)

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

HEADER = """@startuml
title {title}
hide circle
"""

LEGEND = """legend right
  * = NOT NULL; PK khoá chính; FK khoá ngoại; UQ duy nhất
  UNIQUE(...) WHERE ...: chỉ mục duy nhất một phần (không phải khoá của cả bảng)
  ||  đúng một; |o  không hoặc một
  o{  không hoặc nhiều; o|  không hoặc một
  (cascade), (set_null): hành vi ON DELETE; không ghi = NO ACTION
  Thực thể nền xám: bảng thuộc sơ đồ khác (chỉ ghi khoá chính)
endlegend
"""

out_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/erd"
out_dir.mkdir(parents=True, exist_ok=True)
for g, (title, ts) in GROUPS.items():
    rels, stubs = [], []
    for t in ts:
        for fk in T[t]["fks"]:
            rels.append(rel(t, fk))
            if fk["ref"] not in ts and fk["ref"] not in stubs:
                stubs.append(fk["ref"])
    body = [HEADER.format(title=title)]
    for t in ts:
        body.append(entity_full(t))
    for t in stubs:
        body.append(entity_stub(t))
    body.append("")
    body.extend(rels)
    body.append("")
    body.append(LEGEND)
    body.append("@enduml\n")
    (out_dir / f"{g}.puml").write_text("\n".join(body))

# ERD08 tổng quan
MODS = [
    ("core", ["idempotency_keys"]),
    ("identity", ["users", "refresh_tokens", "password_resets"]),
    ("privacy", ["consent_purposes", "policy_versions", "consent_events", "dsr_requests", "audit_log"]),
    ("catalog", GROUPS["ERD03-danh-muc-thanh-phan"][1] + GROUPS["ERD04-mon-an"][1]),
    ("profile", GROUPS["ERD02-ho-so"][1]),
    ("pantry", ["pantry_lots", "pantry_transactions"]),
    ("scan", ["scans", "scan_images", "scan_items", "detections"]),
    ("mlops", ["model_versions", "model_version_classes", "model_deployments"]),
    ("substitute", ["substitution_pairs", "ingredient_embeddings", "shopping_items"]),
    ("meal", ["meal_plans", "meal_plan_coeater_allergens", "meal_plan_pins", "meal_plan_items", "meal_plan_item_substitutions"]),
    ("cooking", ["cook_sessions", "cook_schedule_entries"]),
    ("events", ["interactions"]),
    ("survey", GROUPS["ERD07-khao-sat-mo-hinh"][1][3:]),
]
assert sorted(x for _, l in MODS for x in l) == sorted(T)
b = ["@startuml", "title ERD08 — Tổng quan 62 bảng và mọi khoá ngoại (chi tiết cột ở ERD01–ERD07)",
     "hide circle", "hide empty members", "left to right direction", ""]
for mname, ts in MODS:
    b.append(f'package "{mname}" {{')
    for t in ts:
        b.append(f'  entity "{t}" as {t}')
    b.append("}")
b.append("")
for t in T:
    for fk in T[t]["fks"]:
        b.append(rel(t, fk))
b.append("")
b.append("@enduml\n")
(out_dir / "ERD08-tong-quan.puml").write_text("\n".join(b))
if len(sys.argv) > 2:
    json.dump(T, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print("ok", sum(len(t["fks"]) for t in T.values()), "FK")
