#!/bin/bash
# Compile and install the Tastoria ERD builder plugin (CE-compatible, uses VP Open API only).
set -e
VP=$HOME/opt/vp/Visual_Paradigm_CE_18.1/Application/lib
HERE=$(cd "$(dirname "$0")" && pwd)
DST=$HOME/.config/VisualParadigm/plugins/tastoria-erd
rm -rf "$HERE/classes"; mkdir -p "$HERE/classes"
javac --release 11 -nowarn -cp "$VP/openapi.jar" -d "$HERE/classes" "$HERE/src/tastoria/erd/ErdPlugin.java"
rm -rf "$DST"; mkdir -p "$DST"; cp -r "$HERE/plugin.xml" "$HERE/classes" "$DST/"
echo "installed to $DST"
