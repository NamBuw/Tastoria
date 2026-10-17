#!/usr/bin/env bash
# Áp db/schema.sql vào PostgreSQL 18 + pgvector tạm và so với docs/sad/model.yaml.
#
#   test_ddl.sh [schema.sql] [model.yaml]
#
# - Container tên riêng, không publish cổng, luôn bị xoá khi thoát (trap).
# - psql -v ON_ERROR_STOP=1: lỗi SQL đầu tiên -> thoát 1.
# - So tên BASE TABLE (schema public) và tên VIEW với model.yaml; so tên cột từng bảng
#   (token đầu của mỗi chuỗi cột, bỏ mục bắt đầu bằng "CK("); so NOT NULL với NN/PK/NULL.
# Thoát 1 nếu lệch hoặc lỗi SQL.
set -euo pipefail

ROOT="${SAD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
SCHEMA="${1:-$ROOT/db/schema.sql}"
MODEL="${2:-$ROOT/docs/sad/model.yaml}"
IMAGE="${PG_IMAGE:-pgvector/pgvector:pg18}"
NAME="tastoria-ddl-test-$$-$(date +%s)"

[ -f "$SCHEMA" ] || { echo "test_ddl.sh: không thấy $SCHEMA" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "test_ddl.sh: không thấy $MODEL" >&2; exit 1; }

WORK="$(mktemp -d)"
cleanup() {
  docker rm -f -v "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Kéo image $IMAGE ..."
  docker pull "$IMAGE" >/dev/null
fi

docker run -d --name "$NAME" -e POSTGRES_PASSWORD=ddltest -e POSTGRES_DB=tastoria \
  --tmpfs /var/lib/postgresql:rw "$IMAGE" >/dev/null

# Chờ server thật (TCP nội bộ container chỉ mở sau khi initdb xong).
ready=0
for _ in $(seq 1 90); do
  if docker exec -e PGPASSWORD=ddltest "$NAME" pg_isready -h 127.0.0.1 -U postgres -d tastoria >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "test_ddl.sh: PostgreSQL không sẵn sàng sau 90 giây" >&2
  docker logs "$NAME" 2>&1 | tail -20 >&2
  exit 1
fi

PSQL=(docker exec -i -e PGPASSWORD=ddltest "$NAME" psql -h 127.0.0.1 -U postgres -d tastoria -X -q -v ON_ERROR_STOP=1)

echo "Áp $SCHEMA ..."
if ! "${PSQL[@]}" < "$SCHEMA" > "$WORK/apply.log" 2>&1; then
  echo "LỖI SQL khi áp schema:" >&2
  sed 's/^/    /' "$WORK/apply.log" >&2
  exit 1
fi
grep -i "warning" "$WORK/apply.log" | sed 's/^/    /' || true

"${PSQL[@]}" -At -F $'\t' -c "
  SELECT c.table_name, c.column_name, c.is_nullable
  FROM information_schema.columns c
  JOIN information_schema.tables t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
  WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
  ORDER BY c.table_name, c.ordinal_position" > "$WORK/columns.tsv"
"${PSQL[@]}" -At -F $'\t' -c "
  SELECT table_name, table_type FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type IN ('BASE TABLE','VIEW')
  ORDER BY table_name" > "$WORK/tables.tsv"

if command -v uv >/dev/null 2>&1; then
  PY=(uv run --quiet --no-project --with pyyaml python)
else
  PY=(python3)
fi

"${PY[@]}" - "$MODEL" "$WORK/tables.tsv" "$WORK/columns.tsv" <<'PYEOF'
import sys, yaml

model_path, tables_tsv, columns_tsv = sys.argv[1:4]
model = yaml.safe_load(open(model_path, encoding="utf-8"))

def expected_columns(t):
    cols = {}
    pk = set(t.get("pk", []))
    for spec in t.get("columns", []):
        spec = str(spec).strip()
        if spec.startswith("CK("):
            continue
        toks = spec.split()
        name = toks[0]
        flags = set(toks[1:])
        if "PK" in flags or "NN" in flags or name in pk:
            nullable = False
        elif "NULL" in flags:
            nullable = True
        else:
            nullable = None  # mô hình không nói rõ
        cols[name] = nullable
    return cols

exp_tables = {t["name"]: expected_columns(t) for t in model.get("tables", [])}
exp_views = {v["name"] for v in model.get("views", [])}

db_tables, db_views = set(), set()
for line in open(tables_tsv, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line:
        continue
    name, kind = line.split("\t")
    (db_tables if kind == "BASE TABLE" else db_views).add(name)

db_cols = {}
for line in open(columns_tsv, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line:
        continue
    tname, cname, is_nullable = line.split("\t")
    db_cols.setdefault(tname, {})[cname] = (is_nullable == "YES")

problems = 0
def report(msg):
    global problems
    problems += 1
    print("LỆCH  " + msg)

for t in sorted(set(exp_tables) - db_tables):
    report(f"bảng có trong model.yaml nhưng không có trong DB: {t}")
for t in sorted(db_tables - set(exp_tables)):
    report(f"bảng có trong DB nhưng không có trong model.yaml: {t}")
for v in sorted(exp_views - db_views):
    report(f"view có trong model.yaml nhưng không có trong DB: {v}")
for v in sorted(db_views - exp_views):
    report(f"view có trong DB nhưng không có trong model.yaml: {v}")

for t in sorted(set(exp_tables) & db_tables):
    exp, got = exp_tables[t], db_cols.get(t, {})
    for c in [c for c in exp if c not in got]:
        report(f"{t}: thiếu cột {c}")
    for c in [c for c in got if c not in exp]:
        report(f"{t}: thừa cột {c}")
    for c in [c for c in exp if c in got]:
        if exp[c] is not None and exp[c] != got[c]:
            want = "NULL" if exp[c] else "NOT NULL"
            have = "NULL" if got[c] else "NOT NULL"
            report(f"{t}.{c}: model.yaml {want}, DB {have}")

n_cols = sum(len(v) for k, v in db_cols.items() if k in exp_tables)
print(f"test_ddl: DB {len(db_tables)} bảng / {len(db_views)} view / {n_cols} cột; "
      f"model.yaml {len(exp_tables)} bảng / {len(exp_views)} view; {problems} chỗ lệch")
sys.exit(1 if problems else 0)
PYEOF
