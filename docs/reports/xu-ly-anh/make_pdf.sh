#!/bin/sh
# Dựng BaoCao_XuLyAnh_ThiGiacMayTinh.pdf từ bao-cao-xu-ly-anh.md: pandoc -> LaTeX, pdflatex + vntex (T5) + lmodern.
# Cần pandoc (hoặc PANDOC=<đường dẫn>, ví dụ bản trong gói pypandoc-binary) và TeX Live có vntex.
set -eu
cd "$(dirname "$0")"
PANDOC="${PANDOC:-pandoc}"
OUT=BaoCao_XuLyAnh_ThiGiacMayTinh
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/header.tex" <<'TEX'
\usepackage[T5]{fontenc}
\usepackage{lmodern}
\usepackage{booktabs,longtable,array}
\renewcommand{\arraystretch}{1.15}
\usepackage{etoolbox}
\AtBeginEnvironment{longtable}{\small}
\usepackage{textcomp}
\DeclareUnicodeCharacter{2264}{\ensuremath{\le}}
\DeclareUnicodeCharacter{2265}{\ensuremath{\ge}}
\DeclareUnicodeCharacter{00B1}{\ensuremath{\pm}}
\DeclareUnicodeCharacter{00D7}{\ensuremath{\times}}
\DeclareUnicodeCharacter{00B2}{\ensuremath{^2}}
\DeclareUnicodeCharacter{207B}{\ensuremath{^-}}
\DeclareUnicodeCharacter{2077}{\ensuremath{^7}}
\DeclareUnicodeCharacter{03BA}{\ensuremath{\kappa}}
\DeclareUnicodeCharacter{03C4}{\ensuremath{\tau}}
\DeclareUnicodeCharacter{00B0}{\ensuremath{^\circ}}
\DeclareUnicodeCharacter{00B7}{\ensuremath{\cdot}}
TEX
# ảnh minh hoạ lớn (PNG vài MB) được thu về JPEG 1.600 px chỉ trong bản PDF, để PDF không phình
mkdir -p "$TMP/fig"
SRC="$TMP/src.md"
cp bao-cao-xu-ly-anh.md "$SRC"
for f in fig/*.png; do
  if [ "$(stat -c %s "$f")" -gt 1000000 ]; then
    j="$TMP/fig/$(basename "$f" .png).jpg"
    convert "$f" -resize '1600x1600>' -quality 85 "$j"
    sed -i "s|$f|$j|" "$SRC"
  fi
done
"$PANDOC" "$SRC" -s -o "$TMP/$OUT.tex" --pdf-engine=pdflatex \
  -V fontenc=T5 -V geometry:margin=2.2cm -V fontsize=11pt -V colorlinks=true -V papersize=a4 \
  --columns=200 --number-sections=false -H "$TMP/header.tex" --resource-path=.
for _ in 1 2; do pdflatex -interaction=nonstopmode -halt-on-error -output-directory "$TMP" "$TMP/$OUT.tex" > "$TMP/log.txt" || { tail -40 "$TMP/log.txt"; exit 1; }; done
cp "$TMP/$OUT.pdf" "$OUT.pdf"
echo "$OUT.pdf"
