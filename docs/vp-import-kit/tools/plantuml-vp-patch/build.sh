#!/bin/bash
# Compile the Tastoria patches of PlantUML-VP v1.0.0 and install the patched plugin for VP.
set -e
VP=$HOME/opt/vp/Visual_Paradigm_CE_18.1/Application/lib
PL=$HOME/opt/vp/plugin-dl/plugin-plantuml-vp-v1.0.0          # unzipped release
DST=$HOME/.config/VisualParadigm/plugins/plugin-plantuml-vp-v1.0.0
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$HERE/out"; mkdir -p "$HERE/out"
javac --release 11 -nowarn -cp "$PL/lib/plantuml.jar:$PL/classes:$VP/openapi.jar:$(ls $VP/lib0*.jar | tr "\n" ":")" -d "$HERE/out" $(find "$HERE/src" -name '*.java')
rm -rf "$DST"; mkdir -p "$(dirname "$DST")"; cp -r "$PL" "$DST"
cp -r "$HERE/out/." "$DST/classes/"
echo "installed patched plugin to $DST"
