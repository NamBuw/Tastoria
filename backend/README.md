# Tastoria backend

FastAPI modular monolith (ADR 0001). This first slice has `core`, `identity`, `privacy`, `profile` and the part
of `catalog` that `profile` needs. Contract: `docs/api/openapi-v1.yaml`; schema: `db/schema.sql`; modules and
their allowed dependencies: `docs/sad/model.yaml`.

## Layout

```
backend/
  src/tastoria/
    app.py               assembly root: routers, readiness checks, cross-module handlers
    cli/                 `tastoria` command (db upgrade, jobs)
    core/                config, db + Unit of Work, RFC 9457 errors, request_id + JSON logs,
                         Idempotency-Key, auth dependency, health
    modules/<name>/      router.py · service.py (public) · models.py · schemas.py (+ private helpers)
    jobs/                cron entry points (python -m tastoria.jobs.sweep)
    migrations/          Alembic; 0001 runs sql/0001_schema.sql = byte copy of db/schema.sql
  scripts/gen_importlinter.py   writes .importlinter from model.yaml
  tests/unit, tests/integration
```

Other modules call only `service.py` (and `schemas.py`) of a module they are allowed to depend on.
`.importlinter` is generated from `model.yaml` and checked in the test suite.

Sync SQLAlchemy 2.0 + psycopg 3: FastAPI runs sync endpoints in its threadpool, so blocking DB calls do not
block the event loop. One request is one transaction; the `Uow` dependency commits before the response is sent
(`Depends(..., scope="function")`), so a failing COMMIT returns 5xx, never 200. Side effects outside the DB
(mail, jobs, files) run in `uow.after_commit`.

## Run locally

Needs Python 3.12, `uv`, PostgreSQL 18 with pgvector (`pgvector/pgvector:pg18`) and Valkey 9.

```bash
# from the repo root (uv workspace)
export TASTORIA_DATABASE_URL=postgresql+psycopg://tastoria:tastoria@127.0.0.1:5432/tastoria
export TASTORIA_VALKEY_URL=redis://127.0.0.1:6379/0
uv run --package tastoria-backend tastoria db upgrade
uv run --package tastoria-backend uvicorn tastoria.app:create_app --factory --host 127.0.0.1 --port 8000
# behind nginx: add --proxy-headers --forwarded-allow-ips=127.0.0.1 so the login lock sees the client IP
```

Do not run `uv sync --package tastoria-backend` in the shared `.venv`: it removes the `ml` member's packages.
`uv run --package ...` (inexact) or `uv sync --all-packages --inexact` is safe.

Allergen groups and diets are catalog reference data loaded by the catalog import (next slice) from
`data/kb/ref/`. Until then `PUT /me/allergens` and `PUT /me/diet` answer `unknown_code` for every code.

Jobs:

```bash
uv run --package tastoria-backend tastoria jobs process-dsr   # finish open export/delete/withdraw requests
uv run --package tastoria-backend python -m tastoria.jobs.sweep  # UC34: expired tokens, idempotency keys > 48 h
```

## Tests

```bash
uv run --package tastoria-backend pytest backend/tests -q
uv run --package tastoria-backend lint-imports --config backend/.importlinter   # also run by the suite
uv run --package tastoria-backend python backend/scripts/gen_importlinter.py     # after editing model.yaml
```

Integration tests start throwaway containers (`pgvector/pgvector:pg18`, `valkey/valkey:9`) with
`docker run -p 127.0.0.1::<port>`, so Docker picks a free host port and nothing collides with running
services. They are labelled `tastoria-test=1` and removed at the end of the session
(`docker rm -f $(docker ps -aq --filter label=tastoria-test=1)` cleans up after a crash). Without Docker the
integration tests are skipped; set `TASTORIA_REQUIRE_DOCKER=1` to make that a failure (CI).

What the suite checks besides endpoint behaviour:
- migration 0001 gives the same `pg_dump --schema-only` as applying `db/schema.sql` directly; the copy in
  `migrations/sql/` is byte-identical to `db/schema.sql`;
- every ORM-mapped table matches the migrated catalog (alembic `compare_metadata`, comments ignored);
- every implemented operation exists in `openapi-v1.yaml` with the same method, path and operationId;
- `ProblemCode` equals the contract enum (plus backend-only `internal_error`);
- published policy texts still hash to the SHA-256 frozen in migration 0002.

## Environment variables

All prefixed `TASTORIA_`. JSON values for the key maps.

| Variable | Default | Meaning |
|---|---|---|
| `ENV` | `development` | `production` refuses the development secrets below |
| `DATABASE_URL` | `postgresql+psycopg://tastoria:tastoria@127.0.0.1:5432/tastoria` | SQLAlchemy URL |
| `DB_POOL_SIZE` | `5` | connection pool (overflow = same) |
| `VALKEY_URL` | `redis://127.0.0.1:6379/0` | Valkey (login lock counters; RQ later) |
| `LOGIN_THROTTLE_BACKEND` | `valkey` | `memory` = one process only, for local dev without Valkey |
| `JWT_KEYS` | dev key | `{"kid": "secret", ...}` HS256 keys by `kid` |
| `JWT_ACTIVE_KID` | `dev-1` | key used to sign new access tokens |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `tastoria` / `tastoria-app` | checked on every token |
| `ACCESS_TOKEN_TTL_S` | `900` | NFR-SEC-01 |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | NFR-SEC-01 |
| `PASSWORD_MIN_LENGTH` / `PASSWORD_MAX_LENGTH` | `10` / `128` | FR-01-03 |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_S` | `5` / `900` | NFR-SEC-02, per (email, IP) |
| `RESET_TOKEN_TTL_S` / `RESET_RESEND_COOLDOWN_S` | `1800` / `60` | UC04 |
| `RESET_URL_BASE` | `https://tastoria.ctslab.net/dat-lai-mat-khau` | link in the reset mail (`?token=`) |
| `MAILER` | `smtp` | `log` = do not send, log the subject only |
| `SMTP_HOST` / `SMTP_PORT` | `127.0.0.1` / `1025` | Mailpit in dev |
| `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_STARTTLS` | – / – / `false` | |
| `MAIL_FROM` | `Tastoria <no-reply@tastoria.ctslab.net>` | |
| `HEALTH_ENC_KEYS` | dev key (zeros) | `{"key_id": "<base64 of 32 bytes>"}` AES-256-GCM keys for `profiles.*_enc` |
| `HEALTH_ENC_ACTIVE_KEY_ID` | `dev-1` | key for new writes; old key ids stay readable while listed |
| `DSR_HMAC_KEY` | dev key | HMAC-SHA256 key for `dsr_requests.subject_ref` |
| `STORAGE_DIR` | `./var/storage` | volume root; exports go to `exports/<id>.zip` |
| `ACCEL_REDIRECT_PREFIX` | `/_protected/` | nginx internal location for `X-Accel-Redirect` |
| `JOBS_BACKEND` | `sync` | only `sync` in this slice (job runs after the request commits) |
| `MIN_APP_VERSION` | `0.0.0` | lower `X-App-Version` → 412 `app_too_old` |
| `LOG_LEVEL` | `INFO` | |
| `TIMEZONE` | `Asia/Ho_Chi_Minh` | "current year" for the age gate |

Generate keys: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
The health-column key must be backed up apart from the database backup (ADR 0005): losing it loses the
metrics (`GET /me/profile` → 500 `decryption_failed`).

## Decisions taken in this slice

- Login lock counts per (email, IP) in Valkey only; if Valkey is down, login answers 503 (UC02 3b, fail
  closed). `users.failed_logins` / `locked_until` mirror the last lock for display (UC02 step 3).
- Refresh-token reuse detection is strict (no grace window; TBD-15 still open).
- Idempotency-Key: `pg_try_advisory_xact_lock`; a concurrent duplicate gets 409 `idempotency_in_progress`
  with `Retry-After: 1` (openapi), not a wait.
- `PUT /me/profile` refuses changing `goal` to or from `expert` (422): that goes through `PUT /me/energy-target`,
  which keeps `ck_profiles_expert` true.
- `get_meal_constraints()` reads `kcal_target` (plain column) and does not decrypt metrics, so meal planning
  writes no audit row.
- Policy texts in `modules/privacy/policies/` are team drafts, marked in the text as not legally reviewed.
