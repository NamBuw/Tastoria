#!/bin/sh
# Runs inside the `migrate` container after the catalog import (vision_classes must exist).
# deploy.sh / host staging places each model under deploy/models/<name>/ (mounted read-only at /import):
#   detector|freshness|meal_calorie|dish_classifier|mushroom_classifier: model.onnx
#   ranker: model.npz
#   embeddings -> substitution: ingredient_embeddings.npz
# For every staged model: register (no-op when the same bytes are already registered), gate, and deploy only when
# the name has no deployment yet (--if-none): an operator's `tastoria mlops deploy|rollback` is never overridden.
set -eu

for dir in /import/*/; do
  [ -d "$dir" ] || continue
  base="$(basename "$dir")"
  case "$base" in
    detector|freshness|meal_calorie|dish_classifier|mushroom_classifier)
      name="$base"
      artifact="$dir/model.onnx"
      ;;
    ranker)
      name="ranker"
      artifact="$dir/model.npz"
      ;;
    embeddings)
      name="substitution"
      artifact="$dir/ingredient_embeddings.npz"
      ;;
    *)
      continue
      ;;
  esac
  [ -f "$artifact" ] || continue

  meta="$(python3 - "$dir" "$artifact" "$name" <<'PY'
import hashlib, json, pathlib, sys

d = pathlib.Path(sys.argv[1])
art = pathlib.Path(sys.argv[2])
name = sys.argv[3]

version = ""
vfile = d / "version"
if vfile.is_file():
    version = vfile.read_text(encoding="utf-8").strip()

serving = {}
for fname in ("serving.json", "manifest.json"):
    p = d / fname
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and not serving:
                serving = data
            if not version and isinstance(data, dict) and isinstance(data.get("version"), str):
                version = data["version"].strip()
        except Exception:
            pass

if not version:
    h = hashlib.sha256()
    with art.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    prefix = serving.get("schema_version") if isinstance(serving.get("schema_version"), str) else name
    version = f"{prefix}-{h.hexdigest()[:12]}"

prep = ""
pfile = d / "preprocess_version"
if pfile.is_file():
    prep = pfile.read_text(encoding="utf-8").strip()
elif isinstance(serving.get("input"), dict) and isinstance(serving["input"].get("preprocess"), str):
    prep = serving["input"]["preprocess"].strip()
if not prep:
    prep = "none"

print(version)
print(prep)
PY
)"
  version="$(printf '%s\n' "$meta" | sed -n '1p')"
  prep="$(printf '%s\n' "$meta" | sed -n '2p')"

  set -- --version "$version" --preprocess-version "$prep"
  if [ -f "$dir/metrics.json" ]; then
    set -- "$@" --metrics "$dir/metrics.json"
  elif [ "$name" = "substitution" ] && [ -f "$dir/manifest.json" ]; then
    set -- "$@" --metrics "$dir/manifest.json"
  fi
  [ -f "$dir/serving.json" ] && set -- "$@" --serving "$dir/serving.json"

  echo "models: $name $version"
  reg_out="$(tastoria mlops register "$name" "$artifact" "$@")"
  reg_status="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("status",""))' "$reg_out" 2>/dev/null || true)"
  if [ "$reg_status" = "retired" ]; then
    echo "models: $name $version đã retired trong CSDL, bỏ qua gate/deploy"
    continue
  fi
  tastoria mlops gate "$name" "$version"
  tastoria mlops deploy "$name" "$version" --if-none
done
