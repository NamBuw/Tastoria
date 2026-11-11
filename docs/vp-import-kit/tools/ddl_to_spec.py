"""db/schema_vp.sql -> tab-separated spec read by the TastoriaERD VP plug-in.
Lines:  T table module comment | C table col type len scale notnull default pk unique comment
        F fkname child cols parent refcols ondelete | G diagram title table1,table2,...
        P diagram table x y   (vị trí đặt tay, không dùng bố cục tự động của VP)
Nhóm ERD lấy từ docs/sad/tools/diagrams/model.py (ERD_GROUPS), cùng mã với bộ PlantUML.
Usage: python3 ddl_to_spec.py schema_vp.sql model.py out.tsv"""
import re, sys, ast, pathlib, importlib.util
from PIL import ImageFont
sql = open(sys.argv[1], encoding='utf-8').read()
_spec = importlib.util.spec_from_file_location('model', sys.argv[2]); _m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
groups = {g: (t.replace(' — ', ' '), ts) for g, (slug, t, ts) in _m.ERD_GROUPS.items()}
# bảng tạo ở migration sau 0001 (như gen_erd.py)
_mig = pathlib.Path(sys.argv[1]).resolve().parents[1] / 'backend/src/tastoria/migrations/versions'
for _f in sorted(_mig.glob('0*.py')):
    _mm = re.search(r'UPGRADE = """(.*?)"""', _f.read_text(), re.S)
    if _mm and 'CREATE TABLE' in _mm.group(1):
        _body = re.sub(r"\n\s+REFERENCES", " REFERENCES", _mm.group(1))
        _body = re.sub(r"COMMENT ON .*?;\n", "", re.sub(r"'\s*\n\s*'", "", _body), flags=re.S)

        sql += "\n-- ===== Module catalog =====\n" + _body
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
assert len(tables) == sum(len(v[2]) for v in _m.ERD_GROUPS.values()), len(tables)
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
FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
def size(t):
    w = max(FONT.getlength(t) + 40, max(FONT.getlength(c[0]) for c in tables[t]['cols']) +
            max(FONT.getlength(c[1]) for c in tables[t]['cols']) + 110)
    return int(w), int(30 + 18 * len(tables[t]['cols']))
def place(g, shown, edges):
    """Đặt bảng vào lưới bằng tìm kiếm ngẫu nhiên có hạt giống cố định: ít đường nối xuyên bảng nhất,
    đường nối ngắn, ô dưới cùng bên phải để trống cho dòng watermark của VP CE."""
    import random, itertools
    rnd = random.Random(7)
    n = len(shown)
    cols = 3 if n > 4 else 2
    rows = -(-(n + 1) // cols)
    cells = [(c, r) for r in range(rows) for c in range(cols) if (c, r) != (cols - 1, rows - 1)]
    sz = {t: size(t) for t in shown}
    def geo(assign):
        cw = [max([sz[t][0] for t in shown if assign[t][0] == c] or [150]) for c in range(cols)]
        rh = [max([sz[t][1] for t in shown if assign[t][1] == r] or [60]) for r in range(rows)]
        return {t: (40 + sum(cw[:assign[t][0]]) + 160 * assign[t][0], 40 + sum(rh[:assign[t][1]]) + 110 * assign[t][1],
                    sz[t][0], sz[t][1]) for t in shown}
    def hits(p, q, b):
        # đoạn thẳng p-q cắt hình chữ nhật b (lấy mẫu)
        for k in range(1, 40):
            x = p[0] + (q[0] - p[0]) * k / 40; y = p[1] + (q[1] - p[1]) * k / 40
            if b[0] - 16 < x < b[0] + b[2] + 16 and b[1] - 16 < y < b[1] + b[3] + 16: return True
        return False
    def cost(assign):
        G = geo(assign); c = 0
        for a, b in edges:
            pa = (G[a][0] + G[a][2] / 2, G[a][1] + G[a][3] / 2); pb = (G[b][0] + G[b][2] / 2, G[b][1] + G[b][3] / 2)
            c += sum(1000 for t in shown if t not in (a, b) and hits(pa, pb, G[t]))
            c += abs(assign[a][0] - assign[b][0]) + abs(assign[a][1] - assign[b][1])
        R = max(v[0] + v[2] for v in G.values()); B = max(v[1] + v[3] for v in G.values())
        c += sum(5000 for v in G.values() if v[0] + v[2] > R - 420 and v[1] + v[3] > B - 80)
        return c
    best, bc = None, None
    for _ in range(4000):
        perm = rnd.sample(cells, n)
        assign = dict(zip(shown, perm))
        cc = cost(assign)
        if bc is None or cc < bc: best, bc = assign, cc
    G = geo(best)
    return ['\t'.join(['P', g, t, str(int(G[t][0])), str(int(G[t][1]))]) for t in shown]


for g, (title, ts) in groups.items():
    out.append('\t'.join(['G', g, title, ','.join(ts)])); allg += ts
    shown = list(ts)
    for name in ts:
        for fk in tables[name]['fks']:
            if fk[2] not in shown: shown.append(fk[2])
    edges = [(name, fk[2]) for name in ts for fk in tables[name]['fks'] if fk[2] != name]
    out.extend(place(g, shown, edges))
assert sorted(allg) == sorted(tables), set(allg) ^ set(tables)
open(sys.argv[3], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(len(tables), 'tables', sum(len(t['cols']) for t in tables.values()), 'columns', nfk, 'FKs')
