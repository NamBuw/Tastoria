#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
if [ "$#" -eq 0 ]; then
  set -- Bao-cao-Tastoria Phu-luc-A-Use-Cases Phu-luc-B-Co-so-du-lieu Ma-tran-truy-vet
fi
for name in "$@"; do
  for pass in 1 2 3; do
    pdflatex -interaction=nonstopmode -halt-on-error -file-line-error -output-directory=build "$name.tex" > "build/$name.console.log" 2>&1 || { tail -40 "build/$name.console.log"; exit 1; }
  done
  cp "build/$name.pdf" "../$name.pdf"
  printf 'Built %s.pdf\n' "$name"
done
