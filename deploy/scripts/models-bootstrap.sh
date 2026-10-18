#!/bin/sh
# Runs inside the `migrate` container after the catalog import (vision_classes must exist).
# deploy.sh stages each model under deploy/models/<name>/ on the host (mounted read-only at /import):
#   model.onnx  version  preprocess_version  metrics.json  serving.json
# For every staged model: register (no-op when the same bytes are already registered), gate, and deploy only when
# the name has no deployment yet (--if-none): an operator's `tastoria mlops deploy|rollback` is never overridden.
# The registered copy lives in the file volume (models/<name>/<version>/), so the worker does not need /import.
set -eu
for dir in /import/*/; do
  [ -f "$dir/model.onnx" ] || continue
  name="$(basename "$dir")"
  version="$(cat "$dir/version")"
  prep="$(cat "$dir/preprocess_version" 2>/dev/null || echo none)"
  set -- --version "$version" --preprocess-version "$prep"
  [ -f "$dir/metrics.json" ] && set -- "$@" --metrics "$dir/metrics.json"
  [ -f "$dir/serving.json" ] && set -- "$@" --serving "$dir/serving.json"
  echo "models: $name $version"
  tastoria mlops register "$name" "$dir/model.onnx" "$@" > /dev/null
  tastoria mlops gate "$name" "$version"
  tastoria mlops deploy "$name" "$version" --if-none
done
