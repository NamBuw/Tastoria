#!/bin/bash
# usage: run_erd.sh SPEC.tsv OUT.vpp PNGDIR — dựng Tastoria-ERD.vpp bằng plugin tastoria.erd (bảng, cột, PK/FK thật
# của VP, bố cục đặt tay theo dòng P của spec), rồi xuất PNG mọi sơ đồ. Spec sinh bằng
# docs/vp-import-kit/tools/ddl_to_spec.py db/schema_vp.sql docs/sad/tools/diagrams/model.py SPEC.tsv
SPEC="$1"; P="$2"; OUT="$3"
pgrep -f "Xvfb :77" >/dev/null || { Xvfb :77 -screen 0 1600x1000x24 >/dev/null 2>&1 & sleep 1; }
rm -f "$P" "$P".bak*; cp ~/opt/vp/blank/blank.vpp "$P"
cd ~/opt/vp/Visual_Paradigm_CE_18.1/Application/bin || exit 9
LOG=$(mktemp)
DISPLAY=:77 setsid ./Plugin.sh -project "$P" -pluginid tastoria.erd -pluginargs -spec "$SPEC" > "$LOG" 2>&1 &
PID=$!
for i in $(seq 1 900); do
  sleep 1
  grep -qE 'ERD-BUILD-OK|Exception' "$LOG" && { sleep 3; break; }
  kill -0 $PID 2>/dev/null || break
done
sleep 2; kill -- -$PID 2>/dev/null; sleep 1; kill -9 -- -$PID 2>/dev/null
grep -E 'WARN|ERD-BUILD|Exception|diagram |tables=' "$LOG" | head -40; rm -f "$LOG"
rm -rf "$OUT"; mkdir -p "$OUT"
DISPLAY=:77 timeout 900 ./ExportDiagramImage.sh -project "$P" -out "$OUT" -diagram '*' -type png_with_background 2>&1 | grep -vE 'WARNING|MaxPerm' | tail -2
