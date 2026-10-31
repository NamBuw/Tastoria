#!/bin/bash
# usage: run.sh SPEC.tsv OUT.vpp PNGDIR   — build .vpp from spec on Xvfb :77, then export every diagram as PNG.
SPEC="$1"; P="$2"; OUT="$3"
pgrep -f "Xvfb :77" >/dev/null || { Xvfb :77 -screen 0 1600x1000x24 >/dev/null 2>&1 & sleep 1; }
rm -f "$P" "$P".bak*; cp ~/opt/vp/blank/blank.vpp "$P"
cd ~/opt/vp/Visual_Paradigm_CE_18.1/Application/bin || exit 9
LOG=$(mktemp)
DISPLAY=:77 JAVA_TOOL_OPTIONS="-Duser.name=NamNT $PTTKHT_JOPTS" setsid ./Plugin.sh -project "$P" -pluginid pttkht.uml -pluginargs -spec "$SPEC" > "$LOG" 2>&1 &
PID=$!
for i in $(seq 1 900); do
  sleep 1
  grep -qE 'UML-BUILD-(OK|FAILED)' "$LOG" && { sleep 3; grep -q 'Saved project\|UML-BUILD' "$LOG"; break; }
  kill -0 $PID 2>/dev/null || break
  # newProject() hỏi "Do you want to save the project?" -> bấm No (ở toạ độ cố định trên Xvfb)
  if [ $i -eq 10 ] && ! grep -q NEWPROJECT "$LOG" && grep -q "^NEWPROJECT" "$SPEC"; then
    $HOME/opt/vp/venv/bin/python $HOME/opt/vp/tools/xinput.py click 150 64
  fi
done
sleep 2; kill -- -$PID 2>/dev/null; sleep 1; kill -9 -- -$PID 2>/dev/null
grep -E 'WARN|UML-BUILD|Exception|Error|DUMP|SANITIZE|NEWPROJECT|SAVEAS|FONT|REPOINT|reversed|CALL-RET' "$LOG" | head -120
[ -n "$PTTKHT_KEEPLOG" ] && cp "$LOG" "$PTTKHT_KEEPLOG"; rm -f "$LOG"
rm -rf "$OUT"; mkdir -p "$OUT"
DISPLAY=:77 timeout 900 ./ExportDiagramImage.sh -project "$P" -out "$OUT" -diagram '*' -type png_with_background 2>&1 | grep -vE 'WARNING|MaxPerm' | tail -3
ls "$OUT" | head -50
