# Tastoria 4-Tier Opaque-Box E2E Test Suite (`tests/e2e/`)

> **Infrastructure Rule (R5):** Never run Playwright, Docker, `pytest`, or heavy builds on machine `121`. Edit files on `121` and execute the suite remotely via SSH on `171.226.10.153` using `./tests/e2e/run_remote.sh`.

## Directory Layout
- `requirements-e2e.txt`: Isolated E2E dependencies (`pytest`, `playwright`, `httpx`, `pillow`, `pyyaml`, `python-docx`), keeping root `pyproject.toml` untouched.
- `pytest.ini`: Strict markers (`tier1`, `tier2`, `tier3`, `tier4`, `pending_m3_m4`).
- `docker-compose.e2e.yml`: Isolated Compose override (`COMPOSE_PROJECT_NAME=tastoria_e2e`) exposing nginx on `127.0.0.1:16880:80` with isolated `tastoria_e2e_*` volumes so live `:6880` is untouched.
- `run_remote.sh`: R5-compliant SSH execution wrapper (`rsync` -> bring up `tastoria_e2e` -> seed DB/catalog/models/survey -> `uv run --with-requirements` + Playwright Chromium -> `rsync` artifacts/screenshots back to `121` -> cleanup unless `--keep`).
- `conftest.py`: API client, dynamic KB UUID resolvers, user/consent/pantry/role seeders, `tastoria survey` CLI helpers, Playwright browser/context factory (`1440x900`, `390x844`, `320x568`, `light`/`dark`, `vi-VN`, `Asia/Ho_Chi_Minh`, `reduced_motion`), strict `assert_clean_page` telemetry, and dual screenshot saver.
- `rubric.py`: Automated in-browser UI/UX rubric evaluator (`0px` overflow, touch targets `>=44px`/`>=48px`, loaded `BeVietnamPro`/`Vietnam` fonts, live computed WCAG 2.2 AA contrast, Light/Dark background delta, non-broken `<img>`/`<svg>`, responsive Desktop rail vs Mobile tabs, and `MASTER.md`/`tokens.ts` alignment) writing `tests/e2e/artifacts/ui_rubric_report.json`.
- `fixtures.py`: Programmatic produce JPEG, EXIF-GPS+Orientation=6 JPEG, `>3MB` JPEG, `4097x4096` JPEG, and `%PDF-1.7` spoofed `.jpg` generators, plus real test image discovery from `data/processed/cv/yolo/images/test/`.
- `test_tier1_features.py`: Isolated functional tests across all 15 features `F1`–`F15` (>= 75 tests).
- `test_tier2_boundaries.py`: Boundary value & negative/rejection tests across `F1`–`F15` (>= 75 tests).
- `test_tier3_pairwise.py`: All-Pairs cross-feature combinations (>= 16 scenarios).
- `test_tier4_journeys.py`: 8 real-world Playwright end-to-end journeys (`J1`–`J8`) across Desktop & Mobile, Light & Dark, running `rubric.py` and saving Mobile App report screenshots.

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `TASTORIA_E2E_BASE_URL` | `http://127.0.0.1:16880` | Base URL of the isolated E2E nginx ingress |
| `TASTORIA_E2E_COMPOSE_PROJECT` | `tastoria_e2e` | Docker Compose project name used for `psql`/`tastoria` CLI seeding |
| `TASTORIA_E2E_SCREENSHOT_DIR` | `app/docs/screenshots` | Regression screenshot output folder |
| `TASTORIA_E2E_REPORT_FIG_DIR` | `docs/reports/mobile-app/fig` | Mobile App course report figure output folder |
| `TASTORIA_E2E_REMOTE_HOST` | `namnx@171.226.10.153` | Remote GPU/compute host for `run_remote.sh` |
| `TASTORIA_E2E_REMOTE_DIR` | `~/Tastoria-e2e` | Isolated remote directory synced on `171.226.10.153` |
| `TASTORIA_E2E_PORT` | `16880` | Loopback port on `171.226.10.153` |

## Running via SSH (`171.226.10.153`)
```bash
# Run full 4-tier E2E suite on 171.226.10.153
./tests/e2e/run_remote.sh

# Run baseline-HEAD compatible tests only (exclude M3/M4/M5 pending deliverables)
./tests/e2e/run_remote.sh -m "not pending_m3_m4"

# Run a single tier and keep the isolated stack running for inspection
./tests/e2e/run_remote.sh --keep -m "tier4"
```
