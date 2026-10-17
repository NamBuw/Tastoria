#!/usr/bin/env bash
# Render mọi sơ đồ PlantUML của bộ phân tích thiết kế ra SVG và PNG.
#
#   render.sh [glob]
#
# Nguồn: docs/uml/**/*.puml và docs/erd/*.puml (bỏ qua docs/uml/out/).
# Đích:  docs/uml/<loai>/X.puml -> docs/uml/out/<loai>/X.{svg,png}
#        docs/erd/X.puml        -> docs/uml/out/erd/X.{svg,png}
# glob (tuỳ chọn) so với đường dẫn tương đối từ gốc repo, ví dụ 'docs/uml/state/*'
# hoặc '*ST0*'. Thoát mã 1 nếu plantuml lỗi, thiếu SVG hoặc SVG chứa "Syntax Error".
set -uo pipefail

ROOT="${SAD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
PLANTUML="${PLANTUML:-plantuml}"
GLOB="${1:-}"
OUT_BASE="$ROOT/docs/uml/out"

command -v "$PLANTUML" >/dev/null 2>&1 || { echo "render.sh: không tìm thấy plantuml" >&2; exit 2; }

mapfile -t FILES < <(
  {
    [ -d "$ROOT/docs/uml" ] && find "$ROOT/docs/uml" -path "$OUT_BASE" -prune -o -type f -name '*.puml' -print
    [ -d "$ROOT/docs/erd" ] && find "$ROOT/docs/erd" -maxdepth 1 -type f -name '*.puml' -print
  } | sort
)

declare -A BATCHES=()   # out_dir -> danh sách tệp (phân cách bằng \n)
selected=0
for f in "${FILES[@]}"; do
  rel="${f#"$ROOT"/}"
  if [ -n "$GLOB" ]; then
    # shellcheck disable=SC2053
    [[ "$rel" == $GLOB || "$(basename "$rel")" == $GLOB ]] || continue
  fi
  case "$rel" in
    docs/erd/*) out="$OUT_BASE/erd" ;;
    docs/uml/*/*) sub="${rel#docs/uml/}"; out="$OUT_BASE/$(dirname "$sub")" ;;
    docs/uml/*) out="$OUT_BASE/misc" ;;
    *) continue ;;
  esac
  BATCHES["$out"]+="$f"$'\n'
  selected=$((selected + 1))
done

if [ "$selected" -eq 0 ]; then
  echo "render.sh: không có tệp .puml nào${GLOB:+ khớp '$GLOB'}"
  exit 0
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
ok=0; bad=0
for out in "${!BATCHES[@]}"; do
  mkdir -p "$out"
  mapfile -t batch < <(printf '%s' "${BATCHES[$out]}")
  for f in "${batch[@]}"; do   # xoá ảnh cũ để không đọc nhầm kết quả lần trước
    name="$(basename "${f%.puml}")"; rm -f "$out/$name.svg" "$out/$name.png"
  done
  for fmt in svg png; do
    if ! "$PLANTUML" -t"$fmt" -charset UTF-8 -o "$out" "${batch[@]}" >"$LOG" 2>&1; then
      echo "LỖI plantuml (-t$fmt) cho nhóm ${out#"$ROOT"/}:" >&2
      sed 's/^/    /' "$LOG" >&2
      plantuml_failed=1
    fi
  done
  for f in "${batch[@]}"; do
    name="$(basename "${f%.puml}")"
    svg="$out/$name.svg"
    rel="${f#"$ROOT"/}"
    if [ ! -s "$svg" ]; then
      echo "LỖI $rel: không thấy $svg (tên sau @startuml phải bỏ trống hoặc trùng tên tệp)" >&2
      bad=$((bad + 1))
    elif grep -q "Syntax Error" "$svg"; then
      echo "LỖI $rel: SVG chứa 'Syntax Error'" >&2
      bad=$((bad + 1))
    elif [ ! -s "$out/$name.png" ]; then
      echo "LỖI $rel: không thấy PNG" >&2
      bad=$((bad + 1))
    else
      ok=$((ok + 1))
    fi
  done
done

echo "render.sh: $selected tệp, $ok đạt, $bad lỗi"
if [ "$bad" -gt 0 ] || [ "${plantuml_failed:-0}" -eq 1 ]; then
  exit 1
fi
exit 0
