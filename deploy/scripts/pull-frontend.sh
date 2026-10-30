#!/usr/bin/env bash
# GitHub CI advances deploy/frontend only after verification. Poll through existing SSH auth.
set -euo pipefail
state_dir="${TASTORIA_CD_STATE:-$HOME/.local/state/tastoria-cd}"
mkdir -p "$state_dir"
exec 9>"$state_dir/deploy.lock"
flock -n 9 || exit 0
checkout="$state_dir/checkout"
if [ ! -d "$checkout/.git" ]; then
  git clone --no-checkout git@github-nambuw:NamBuw/Tastoria.git "$checkout"
fi
# The first CI run has not promoted anything yet; absence is not a deployment failure.
remote_status=0
git -C "$checkout" ls-remote --exit-code origin refs/heads/deploy/frontend > /dev/null || remote_status=$?
[ "$remote_status" != 2 ] || exit 0
[ "$remote_status" = 0 ] || exit "$remote_status"
git -C "$checkout" fetch origin main deploy/frontend
sha="$(git -C "$checkout" rev-parse origin/deploy/frontend)"
git -C "$checkout" merge-base --is-ancestor "$sha" origin/main
[ "$(cat "$state_dir/deployed" 2>/dev/null || true)" != "$sha" ] || exit 0
# Dedicated CD checkout; user working files are never reset or cleaned.
git -C "$checkout" checkout --detach "$sha"
bash "$checkout/deploy/scripts/deploy-frontend.sh"
printf '%s\n' "$sha" > "$state_dir/deployed"
