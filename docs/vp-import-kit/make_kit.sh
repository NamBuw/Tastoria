#!/usr/bin/env bash
# Đóng gói bộ nhập Visual Paradigm cho Tastoria.
#
#   docs/vp-import-kit/make_kit.sh [--no-render]
#
# Kết quả: dist/tastoria-vp-kit.zip, gốc zip là thư mục tastoria-vp-kit/ gồm:
#   HUONG-DAN.md
#   docs/uml/<loai>/*.puml      (mọi sơ đồ UML, bỏ docs/uml/out/)
#   docs/erd/*.puml             (ERD Chen + chân quạ)
#   db/schema_vp.sql            (DDL cho Tools > DB > Reverse DDL)
#   docs/uml/out/<loai>/*.svg, *.png (ảnh render sẵn)
#
# Mặc định chạy docs/sad/tools/render.sh trước để ảnh khớp nguồn; --no-render bỏ bước này.
# Thoát mã khác 0 nếu render lỗi, thiếu tệp nguồn, thiếu ảnh SVG của một .puml, hoặc SVG chứa "Syntax Error".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KIT_NAME="tastoria-vp-kit"
DIST="$ROOT/dist"
ZIP="$DIST/$KIT_NAME.zip"
RENDER=1
[ "${1:-}" = "--no-render" ] && RENDER=0

command -v zip >/dev/null 2>&1 || { echo "make_kit.sh: thiếu lệnh zip" >&2; exit 2; }

if [ "$RENDER" = 1 ]; then
  echo "== Render sơ đồ"
  bash "$ROOT/docs/sad/tools/render.sh" >/dev/null || { echo "make_kit.sh: render.sh báo lỗi" >&2; exit 1; }
fi

cd "$ROOT"

for f in docs/vp-import-kit/HUONG-DAN.md db/schema_vp.sql; do
  [ -s "$f" ] || { echo "make_kit.sh: thiếu $f" >&2; exit 1; }
done

mapfile -t PUML < <( { find docs/uml -path docs/uml/out -prune -o -type f -name '*.puml' -print; find docs/erd -maxdepth 1 -type f -name '*.puml'; } | sort )
[ "${#PUML[@]}" -gt 0 ] || { echo "make_kit.sh: không có tệp .puml" >&2; exit 1; }

# Mỗi .puml phải có SVG tương ứng, không lỗi cú pháp.
IMAGES=()
missing=0
for p in "${PUML[@]}"; do
  base="$(basename "$p" .puml)"
  case "$p" in
    docs/erd/*) out="docs/uml/out/erd" ;;
    *) loai="$(basename "$(dirname "$p")")"; out="docs/uml/out/$loai" ;;
  esac
  svg="$out/$base.svg"
  if [ ! -s "$svg" ]; then
    echo "make_kit.sh: thiếu ảnh $svg cho $p" >&2; missing=1; continue
  fi
  if grep -q "Syntax Error" "$svg"; then
    echo "make_kit.sh: $svg chứa Syntax Error" >&2; missing=1; continue
  fi
  IMAGES+=("$svg")
  [ -s "$out/$base.png" ] && IMAGES+=("$out/$base.png")
done
[ "$missing" = 0 ] || exit 1

# Dựng cây tạm rồi nén để gốc zip là tastoria-vp-kit/.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
K="$STAGE/$KIT_NAME"
mkdir -p "$K"
cp docs/vp-import-kit/HUONG-DAN.md "$K/HUONG-DAN.md"
for f in "${PUML[@]}" db/schema_vp.sql "${IMAGES[@]}"; do
  mkdir -p "$K/$(dirname "$f")"
  cp "$f" "$K/$f"
done

mkdir -p "$DIST"
rm -f "$ZIP"
( cd "$STAGE" && zip -q -r -X "$ZIP" "$KIT_NAME" )

n_svg=$(printf '%s\n' "${IMAGES[@]}" | grep -c '\.svg$' || true)
n_png=$(printf '%s\n' "${IMAGES[@]}" | grep -c '\.png$' || true)
echo "== Đã tạo $ZIP"
echo "   .puml: ${#PUML[@]}  SVG: $n_svg  PNG: $n_png  + db/schema_vp.sql + HUONG-DAN.md"
echo "   Dung lượng: $(du -h "$ZIP" | cut -f1)"
