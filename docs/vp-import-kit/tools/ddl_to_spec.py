"""db/schema_vp.sql -> tab-separated spec read by the TastoriaERD VP plug-in.
Lines:  T table module comment | C table col type len scale notnull default pk unique comment
        F fkname child cols parent refcols ondelete | G diagram title table1,table2,...
Usage: python3 ddl_to_spec.py schema_vp.sql gen_erd.py out.tsv"""
import re, sys, ast
sql = open(sys.argv[1], encoding='utf-8').read()
gen = open(sys.argv[2], encoding='utf-8').read()
groups = ast.literal_eval(re.search(r'^GROUPS = (\{.*?^\})', gen, re.S | re.M).group(1))
out = []
def clean(s): return (s or '').replace('\t', ' ').replace('\n', ' ')
def split_top(body):
    parts, buf, depth, q = [], '', 0, False
    for ch in body:
        if ch == "'": q = not q
        if not q:
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            elif ch == ',' and depth == 0:
                parts.append(buf.strip()); buf = ''; continue
        buf += ch
    if buf.strip(): parts.append(buf.strip())
    return parts
# strip line comments outside of strings (comments only start lines here)
body_sql = '\n'.join(l for l in sql.split('\n') if not l.lstrip().startswith('--'))
module = None; tables = {}; order = []
for m in re.finditer(r"(-- =+ Module (\w+) =+)|CREATE TABLE (\w+) \((.*?)\n\);", sql, re.S):
    if m.group(2): module = m.group(2); continue
    name, body = m.group(3), '\n'.join(l for l in m.group(4).split('\n') if not l.lstrip().startswith('--'))
    t = {'module': module, 'cols': [], 'pk': [], 'uq': [], 'fks': [], 'comment': '', 'ccomment': {}}
    for item in split_top(body):
        item = ' '.join(item.split())
        if item.startswith('CONSTRAINT'):
            c = re.match(r"CONSTRAINT (\w+) (PRIMARY KEY|UNIQUE|FOREIGN KEY|CHECK) ?\((.*)", item)
            cname, kind, rest = c.groups()
            if kind == 'PRIMARY KEY': t['pk'] = [x.strip() for x in rest.rstrip(')').split(',')]
            elif kind == 'UNIQUE': t['uq'].append([x.strip() for x in rest.rstrip(')').split(',')])
            elif kind == 'FOREIGN KEY':
                r = re.match(r"(.*?)\) REFERENCES (\w+) \((.*?)\)(.*)", rest)
                act = re.search(r'ON DELETE (CASCADE|SET NULL|SET DEFAULT|RESTRICT|NO ACTION)', r.group(4))
                t['fks'].append((cname, [x.strip() for x in r.group(1).split(',')], r.group(2),
                                 [x.strip() for x in r.group(3).split(',')], act.group(1) if act else ''))
            continue
        parts = item.split(' ', 1); cname = parts[0]; rest = parts[1] if len(parts) > 1 else ''
        ctype = re.split(r" NOT NULL| NULL| DEFAULT| PRIMARY KEY| UNIQUE| CHECK| REFERENCES", rest)[0].strip()
        dm = re.search(r" DEFAULT (.+?)(?= NOT NULL| CHECK| UNIQUE|$)", ' ' + rest)
        tm = re.match(r"([\w ]+?)\s*\((\d+)(?:,\s*(\d+))?\)", ctype)
        base, ln, sc = (tm.group(1), tm.group(2), tm.group(3) or '0') if tm else (ctype, '0', '0')
        t['cols'].append([cname, base, ln, sc, 'NOT NULL' in rest, dm.group(1).strip() if dm else ''])
    tables[name] = t; order.append(name)
for m in re.finditer(r"ALTER TABLE (\w+) ADD CONSTRAINT (\w+) FOREIGN KEY \((.*?)\) REFERENCES (\w+) \((.*?)\)(.*?);", sql):
    act = re.search(r'ON DELETE (CASCADE|SET NULL|SET DEFAULT|RESTRICT|NO ACTION)', m.group(6))
    tables[m.group(1)]['fks'].append((m.group(2), [x.strip() for x in m.group(3).split(',')], m.group(4),
                                      [x.strip() for x in m.group(5).split(',')], act.group(1) if act else ''))
for m in re.finditer(r"COMMENT ON TABLE (\w+) IS '((?:[^']|'')*)';", sql):
    tables[m.group(1)]['comment'] = m.group(2).replace("''", "'")
for m in re.finditer(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '((?:[^']|'')*)';", sql):
    tables[m.group(1)]['ccomment'][m.group(2)] = m.group(3).replace("''", "'")
assert len(tables) == 62, len(tables)
nfk = 0
for name in order:
    t = tables[name]
    out.append('\t'.join(['T', name, t['module'] or '', clean(t['comment'])]))
    singles = {u[0] for u in t['uq'] if len(u) == 1}
    for c in t['cols']:
        pk = c[0] in t['pk']
        out.append('\t'.join(['C', name, c[0], c[1], c[2], c[3], '1' if (c[4] or pk) else '0', clean(c[5]),
                              '1' if pk else '0', '1' if c[0] in singles else '0', clean(t['ccomment'].get(c[0], ''))]))
for name in order:
    for fk in tables[name]['fks']:
        nfk += 1
        out.append('\t'.join(['F', fk[0], name, ','.join(fk[1]), fk[2], ','.join(fk[3]), fk[4]]))
allg = []
for g, (title, ts) in groups.items():
    out.append('\t'.join(['G', g, title, ','.join(ts)])); allg += ts
assert sorted(allg) == sorted(tables), set(allg) ^ set(tables)
out.append('\t'.join(['G', 'ERD08-tong-quan', 'ERD08 — Tổng quan 62 bảng và mọi khoá ngoại', ','.join(order)]))
open(sys.argv[3], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(len(tables), 'tables', sum(len(t['cols']) for t in tables.values()), 'columns', nfk, 'FKs')
