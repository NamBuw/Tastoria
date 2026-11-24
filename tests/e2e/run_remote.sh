#!/usr/bin/env bash
# R5-compliant E2E runner: syncs repo from machine 121 -> 171.226.10.153, starts isolated
# COMPOSE_PROJECT_NAME=tastoria_e2e on 127.0.0.1:16880:80, seeds catalog/models/open survey,
# runs pytest + Playwright Chromium on 153, pulls back JUnit/JSON/screenshots, and tears down.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REMOTE_HOST="${TASTORIA_E2E_REMOTE_HOST:-namnx@171.226.10.153}"
REMOTE_DIR="${TASTORIA_E2E_REMOTE_DIR:-~/Tastoria-e2e}"
E2E_PORT="${TASTORIA_E2E_PORT:-16880}"
COMPOSE_PROJECT="${TASTORIA_E2E_COMPOSE_PROJECT:-tastoria_e2e}"
PG_PASS="${POSTGRES_PASSWORD:-tastoria_e2e_pg_pass}"
KEEP_STACK=0
PYTEST_ARGS=()

for arg in "$@"; do
  if [[ "$arg" == "--keep" ]]; then
    KEEP_STACK=1
  else
    PYTEST_ARGS+=("$arg")
  fi
done

if [[ ${#PYTEST_ARGS[@]} -gt 0 ]]; then
  PYTEST_ARGS_B64="$(printf '%s\0' "${PYTEST_ARGS[@]}" | base64 -w0)"
else
  PYTEST_ARGS_B64=""
fi

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10)

echo "[e2e] Syncing repository to ${REMOTE_HOST}:${REMOTE_DIR}..."
rsync -az --delete \
  --exclude '.venv' \
  --exclude 'app/node_modules' \
  --exclude 'app/android' \
  --exclude 'data/raw' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude 'deploy/.env' \
  --exclude 'tests/e2e/artifacts' \
  "${REPO_ROOT}/" "${REMOTE_HOST}:${REMOTE_DIR}/"

cleanup_remote() {
  if [[ "${KEEP_STACK}" -eq 0 ]]; then
    echo "[e2e] Tearing down isolated stack (${COMPOSE_PROJECT}) on ${REMOTE_HOST}..."
    ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" bash -s -- "${REMOTE_DIR}" "${COMPOSE_PROJECT}" "${PG_PASS}" <<'REMOTE_CLEANUP' || true
set -euo pipefail
REMOTE_DIR="${1/#\~/$HOME}"
COMPOSE_PROJECT="$2"
export POSTGRES_PASSWORD="$3"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}"
if [[ -d "${REMOTE_DIR}" ]]; then
  cd "${REMOTE_DIR}"
  docker compose -f deploy/docker-compose.yml -f tests/e2e/docker-compose.e2e.yml down -v --remove-orphans || true
fi
REMOTE_CLEANUP
  else
    echo "[e2e] --keep passed: leaving ${COMPOSE_PROJECT} running on ${REMOTE_HOST} (port ${E2E_PORT})."
  fi
}
trap cleanup_remote EXIT

echo "[e2e] Staging models, building & starting isolated stack (${COMPOSE_PROJECT}) on ${REMOTE_HOST}..."
ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" bash -s -- "${REMOTE_DIR}" "${COMPOSE_PROJECT}" "${E2E_PORT}" "${PG_PASS}" <<'REMOTE_BOOT'
set -euo pipefail
REMOTE_DIR="${1/#\~/$HOME}"
COMPOSE_PROJECT="$2"
E2E_PORT="$3"
export POSTGRES_PASSWORD="$4"
cd "${REMOTE_DIR}"

export PATH="$HOME/.local/bin:$PATH"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}"
export TASTORIA_E2E_PORT="${E2E_PORT}"

# Stage detector artifact + matching metrics.json and serving.json for models-bootstrap.sh
det_version="${TASTORIA_DETECTOR_VERSION:-yolo26n_640_none}"
mkdir -p deploy/models/detector
if [[ ! -f deploy/models/detector/model.onnx ]]; then
  CANDIDATE_DET="ml/runs/detect/${det_version}/weights/best.onnx"
  if [[ ! -f "${CANDIDATE_DET}" ]]; then
    CANDIDATE_DET="$(find ml/runs/detect -name 'best.onnx' 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -n "${CANDIDATE_DET}" && -f "${CANDIDATE_DET}" ]]; then
    run_name="$(basename "$(dirname "$(dirname "${CANDIDATE_DET}")")")"
    cp "${CANDIDATE_DET}" deploy/models/detector/model.onnx
    printf '%s' "${run_name}" > deploy/models/detector/version
    printf '%s' "none" > deploy/models/detector/preprocess_version
    det_version="${run_name}"
  fi
elif [[ -f deploy/models/detector/version ]]; then
  det_version="$(cat deploy/models/detector/version)"
fi

if [[ -f deploy/models/detector/model.onnx ]]; then
  metrics_src="data/processed/cv/detector/${det_version}.json"
  serving_src="data/processed/cv/detector/${det_version}_serving.json"
  [[ -f "${metrics_src}" ]] || metrics_src="data/processed/cv/detector/yolo26n_640_none.json"
  [[ -f "${serving_src}" ]] || serving_src="data/processed/cv/detector/yolo26n_640_none_serving.json"
  if [[ ! -f deploy/models/detector/metrics.json && -f "${metrics_src}" ]]; then
    cp "${metrics_src}" deploy/models/detector/metrics.json
  fi
  if [[ ! -f deploy/models/detector/serving.json && -f "${serving_src}" ]]; then
    cp "${serving_src}" deploy/models/detector/serving.json
  fi
fi

docker compose -f deploy/docker-compose.yml -f tests/e2e/docker-compose.e2e.yml up -d --build --wait

# Wait for /readyz
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${E2E_PORT}/readyz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${E2E_PORT}/readyz"

# Open a deterministic 45-dish taste survey form for Khao Sat E2E tests
docker compose -f deploy/docker-compose.yml -f tests/e2e/docker-compose.e2e.yml exec -T api \
  tastoria survey create-form --anchors 10 --random 35 --seed 42 --yes
REMOTE_BOOT

echo "[e2e] Running 4-tier pytest + Playwright Chromium on ${REMOTE_HOST}..."
set +e
ssh "${SSH_OPTS[@]}" "${REMOTE_HOST}" bash -s -- "${REMOTE_DIR}" "${COMPOSE_PROJECT}" "${E2E_PORT}" "${PG_PASS}" "${PYTEST_ARGS_B64}" <<'REMOTE_RUN'
set -euo pipefail
REMOTE_DIR="${1/#\~/$HOME}"
COMPOSE_PROJECT="$2"
E2E_PORT="$3"
export POSTGRES_PASSWORD="$4"
PYTEST_ARGS_B64="${5:-}"
cd "${REMOTE_DIR}"

PYTEST_ARGS=()
if [[ -n "${PYTEST_ARGS_B64}" ]]; then
  while IFS= read -r -d '' arg; do
    PYTEST_ARGS+=("${arg}")
  done < <(printf '%s' "${PYTEST_ARGS_B64}" | base64 -d)
fi

export PATH="$HOME/.local/bin:$PATH"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}"
export TASTORIA_E2E_BASE_URL="http://127.0.0.1:${E2E_PORT}"
export TASTORIA_E2E_COMPOSE_PROJECT="${COMPOSE_PROJECT}"
export TASTORIA_E2E_SCREENSHOT_DIR="${REMOTE_DIR}/app/docs/screenshots"
export TASTORIA_E2E_REPORT_FIG_DIR="${REMOTE_DIR}/docs/reports/mobile-app/fig"

mkdir -p tests/e2e/artifacts "${TASTORIA_E2E_SCREENSHOT_DIR}" "${TASTORIA_E2E_REPORT_FIG_DIR}"

uv run --with-requirements tests/e2e/requirements-e2e.txt playwright install chromium >/dev/null 2>&1 || true

uv run --with-requirements tests/e2e/requirements-e2e.txt \
  pytest -c tests/e2e/pytest.ini tests/e2e \
  --junitxml=tests/e2e/artifacts/junit.xml \
  ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}
REMOTE_RUN
PYTEST_RC=$?
set -e

echo "[e2e] Pulling test artifacts and screenshots back to ${REPO_ROOT}..."
mkdir -p "${REPO_ROOT}/tests/e2e/artifacts" "${REPO_ROOT}/app/docs/screenshots" "${REPO_ROOT}/docs/reports/mobile-app/fig"
rsync -az "${REMOTE_HOST}:${REMOTE_DIR}/tests/e2e/artifacts/" "${REPO_ROOT}/tests/e2e/artifacts/" || true
rsync -az "${REMOTE_HOST}:${REMOTE_DIR}/app/docs/screenshots/" "${REPO_ROOT}/app/docs/screenshots/" || true
rsync -az "${REMOTE_HOST}:${REMOTE_DIR}/docs/reports/mobile-app/fig/" "${REPO_ROOT}/docs/reports/mobile-app/fig/" || true

exit "${PYTEST_RC}"
