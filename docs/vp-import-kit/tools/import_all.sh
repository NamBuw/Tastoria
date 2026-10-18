#!/bin/bash
# Build Tastoria-UML.vpp from staged .puml copies, one file per VP CLI run.
S=${S:-/tmp/vpimport}; mkdir -p $S/dlg
P=/home/namnx/NamBuw/Tastoria/dist/vpp/Tastoria-UML.vpp
rm -f $P $P.bak* ; cp ~/opt/vp/blank/blank.vpp $P
: > $S/full.log; : > $S/full.sum
for d in class component package deployment context usecase state activity sequence; do
  for f in ~/opt/vp/stage-puml/$d/*.puml; do
    ~/opt/vp/tools/vp_import_one.sh $P $f $S/full.log $S/dlg >> $S/full.sum
  done
done
echo DONE >> $S/full.sum
