#!/bin/bash
# usage: vp_import_one.sh PROJECT.vpp FILE_OR_DIR LOG [SHOTDIR]
# Runs the PlantUML-VP plugin CLI headless (Xvfb :77). The plugin pops modal warning dialogs and
# leaves the JVM alive after exceptions, so: screenshot + press Return every 10 s, kill on exception.
P="$1"; F="$2"; L="$3"; SH="${4:-/tmp}"
X="$HOME/opt/vp/venv/bin/python $HOME/opt/vp/tools/xinput.py"
cd ~/opt/vp/Visual_Paradigm_CE_18.1/Application/bin || exit 9
TMP=$(mktemp)
DISPLAY=:77 setsid ./Plugin.sh -project "$P" -pluginid plugins.plantUML -pluginargs -action import -path "$F" > "$TMP" 2>&1 &
PID=$!
n=0
for i in $(seq 1 600); do
  sleep 1
  if grep -q 'Saved project' "$TMP"; then RES=OK; break; fi
  if grep -qE 'Exception in thread' "$TMP"; then RES=FAIL; break; fi
  kill -0 $PID 2>/dev/null || { RES=EXITED; break; }
  if [ $((i % 10)) -eq 0 ] && grep -q 'Importing from path' "$TMP"; then
    n=$((n+1)); B=$(basename "$F" .puml)
    DISPLAY=:77 import -window root "$SH/dlg-$B-$n.png" 2>/dev/null
    if [ "$(convert "$SH/dlg-$B-$n.png" -format '%[fx:mean>0]' info: 2>/dev/null)" = "1" ]; then
      $X key Return   # a modal dialog is up: record it (screenshot kept) and dismiss
    else
      rm -f "$SH/dlg-$B-$n.png"; n=$((n-1))
    fi
  fi
done
RES=${RES:-TIMEOUT}
sleep 2
kill -- -$PID 2>/dev/null; sleep 1; kill -9 -- -$PID 2>/dev/null
wait $PID 2>/dev/null
{ echo "### $RES $F (dialogs dismissed: $n)"; grep -vE 'Duplicated|WARNING|MaxPerm|LicenseKey|startup' "$TMP"; } >> "$L"
rm -f "$TMP"
echo "$RES $(basename "$F") dialogs=$n"
