# Tastoria backend

FastAPI modular monolith (ADR 0001). Slice 1: `core`, `identity`, `privacy`, `profile`. Slice 2: `catalog` (import of
`data/kb`), `pantry`, `meal`, `substitute` (shopping list), `events`, `cooking`, `journal`, and `admin` (CLI side of
the import). Contract: `docs/api/openapi-v1.yaml`; schema: `db/schema.sql` + later migrations; modules and their
allowed dependencies: `docs/sad/model.yaml`.

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
    migrations/          Alembic; 0001 runs sql/0001_schema.sql = byte copy of db/schema.sql; 0002 consent
                         purposes; 0003 recipe_make_ahead
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

Load the catalog (reference data, composition rows, ingredients, recipes, nutrition) once after `db upgrade`, and
again whenever `data/kb` changes:

```bash
uv run --package tastoria-backend tastoria catalog import data/kb          # composition tables: data/processed
uv run --package tastoria-backend tastoria catalog import data/kb --processed /path/to/processed
```

It prints a JSON report (changes per table, new recipe versions, drafts, `data_version`, E_bát) and exits 1 with every
problem as `file:line: code: message` when the bundle does not validate; nothing is written then. Re-running an
unchanged bundle reports `"changes": 0`. Until the first import `PUT /me/allergens` and `PUT /me/diet` answer
`unknown_code` for every code and `POST /meal-plans` finds no recipe.

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

Tests that need the real catalog run against a second database, `kb`, migrated and loaded with
`tastoria catalog import data/kb` once per session (`kb_client`, `kb_db` fixtures in `tests/conftest.py`); only
personal data is wiped between those tests. Import tests that change the bundle get a fresh database each
(`fresh_database`). Users made by `tests/kb_helpers.user()` get a fixed-offset time zone where it is morning, so
plans do not expire mid-test whatever the hour.

What the suite checks besides endpoint behaviour:
- migration 0001 gives the same `pg_dump --schema-only` as applying `db/schema.sql` directly; the copy in
  `migrations/sql/` is byte-identical to `db/schema.sql`;
- every ORM-mapped table matches the migrated catalog (alembic `compare_metadata`, comments ignored);
- every implemented operation exists in `openapi-v1.yaml` with the same method, path and operationId, and every field
  the backend puts in a 2xx JSON body is declared in the contract's schema for that response;
- `openapi-v1.yaml` is valid OpenAPI 3.1 (openapi-spec-validator);
- `ProblemCode` equals the contract enum, in order;
- BR-ALG-01: every published recipe × every allergen group, and random user + co-eater allergen sets and diets,
  against raw SQL (staples, optional lines and made-ahead items included);
- composer: every tray returned for random pantries, pins, persons and time limits fits the pooled stock, the pins,
  the makespan bound and the structure; cooking: every CP-SAT schedule of random trays of the catalog passes the
  BR-COOK-01 checker; completing a session again (same or new Idempotency-Key) deducts once;
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

## Decisions taken in slice 1

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

## Decisions taken in slice 2

Catalog import (UC25, `modules/catalog/{bundle,importer,nutrition}.py`, CLI in `modules/admin`):
- The bundle is a full sync of the catalog: recipes and ingredients missing from it are retired / deactivated, never
  deleted. Identity across imports is `name_vi` (ingredients: active name; recipes: non-retired name).
- A recipe is published when it has ≥ 2 sources and every non-seasoning, non-optional ingredient has a composition
  row; otherwise it is imported as draft with a warning (FR-25-08). On `data/kb` today: 171 published, 9 drafts
  (5 with one source, 4 with an unmapped main ingredient). Seasonings without composition carry an explicit reason in
  `ingredients.yaml` and are accepted.
- Any content change of a published recipe (lines, grams, steps, tags, sources, notes, servings, method, make-ahead)
  retires it and inserts a new published version (BR-CATALOG-01). Drafts are edited in place.
- Only composition rows the ingredients use (+ FCT 1004 gạo tẻ for E_bát) go into `food_items` / `food_nutrients`.
  USDA glucid = carb − fibre (carb is "by difference"), as in the ML nutrition module.
- `recipe_nutrition` comes from `tastoria_ml.kb.nutrition` when that package is importable (it carries the documented
  refuse / moisture / sodium overrides); otherwise from the fallback EuroFIR formula in `catalog/nutrition.py`. The
  two write different `data_version` prefixes (`nut-r1+…` / `catalog-nut-r1+…`); 164 of 171 published recipes agree within
  0.2 kcal, the rest differ by the ML overrides. Run the import where `tastoria-ml` is installed to store the
  reference numbers.
- E_bát (150 g cooked rice, BR-TRAY-03) = FCT 1004 energy × 150 / 2.98 / 100 (cooked yield 2.98, Bognár 2002): 173.2
  kcal. The import also sets the database parameter `tastoria.rice_bowl_kcal` for `v_journal_days`; meal and journal
  compute E_bát from the table, because a parameter set by `ALTER DATABASE` reaches a session only when it connects.
  Both parameters need the database owner; without it the import reports a warning.
- After writing, the import re-checks the hard filter against raw SQL for every published recipe × allergen group /
  diet and the `vegetarian` flags of `dish_list.yaml`; any violation rolls everything back. Every run, failed or not,
  writes one `audit_log` row (`catalog.import`, actor_role `curator`, outcome in `purpose`; the CLI has no logged-in
  actor, `actor_user_id` is NULL — UC25 open question 1).

Make-ahead recipes (passive step > 120 min: Dưa cải muối, Cà pháo muối, Dưa giá, Canh măng nấu chân giò):
- Tagged `lam_san` (system tag, kind `occasion`, added by the import) and mapped in `data/kb/make_ahead.yaml` to the
  made-ahead item the user must hold. The mapping is stored in `recipe_make_ahead` (migration 0003, immutable like
  `recipe_steps`); `make_ahead.yaml` also defines the two products missing from `ingredients.yaml` (cà pháo muối,
  dưa giá; no composition, shelf life not tracked yet). The import fails when a long passive step has no entry, when
  the item of a whole-dish make-ahead lacks an allergen group or diet-excluded food group of the recipe, or when a
  partial item is not an ingredient of the recipe.
- Steps 1..through_step_no (the last long passive step) are left out of the cook schedule and the makespan.
- Whole dish made ahead (the three pickles): proposed only when the item has usable stock (presence, no amount check:
  no yield data); its raw lines are neither stock-checked nor deducted; cooking deducts from the item Σ raw grams ×
  n / servings (1:1 yield, uncalibrated). Partial (ngâm măng khô): the item is an ordinary line of the recipe, only the
  soaking steps leave the schedule.

Pantry (UC14):
- `POST /pantry/lots` stores the amount as the lot's initial interval and writes no transaction (the openapi text said
  manual_edit; initial + Σ delta is the balance, a transaction would count it twice).
- Counting works with any `ingredient_units` row (2 bó rau muống) even when the ingredient is not `countable`;
  ít/vừa/nhiều only for non-countable ingredients.
- Lots without a shelf life and without freshness probabilities have `urgency = null`, label `chua_ro`, are available
  and never rewarded (FR-14-05); their deductions record `urgency_at_event = NULL` rather than a made-up number.
- Deducting from intervals uses interval arithmetic over the lots in order (pinned lots of the plan, then most
  urgent): the remaining [lo, hi] of lot i is [lo − max(0, need − Σ previous lo), hi − max(0, need − Σ previous hi)]
  floored at 0 (UC20 open question 1). Shortfalls are reported for non-staple, non-optional ingredients only.

Meal (UC15–UC17):
- Objective weights are provisional (`tray-p0-provisional`: α = 1, β = 1, γ = 0.5, K = 20); spec §6.2 fixes them
  later by the pre-registered scenario rule.
- Calorie range (BR-NUT-06, FR-15-22): `kcal_low/high` = Σ dish kcal per person × (1 ∓ h). h is the
  `p80_abs_rel_error` of `data/kb/validation/nin_dishes.yaml` (the ML team's comparison with Viện Dinh dưỡng; today
  45 dishes, h = 0.2135). The import stores it as the database parameter `tastoria.kcal_half_width` only when ≥ 30
  dishes were compared with the same nutrition `data_version` that computed `recipe_nutrition`; otherwise it resets
  it and the API shows "đang hiệu chỉnh" (NULL range, journal `calibrating`). Database parameters are read from
  `pg_db_role_setting` on each request, so an import takes effect without restarting the API.
- Ranker: `meal/ranker.py` `Ranker` protocol; the served `BaselineRanker` = shrunk popularity of consenting users'
  interactions + content-based cosine to the 5 favourites (+ the user's own signal with consent). No ranker model is
  deployed (mlops has no code yet), so `ranker_version_id` is NULL and propensity is 1.
- Options that cannot fit the stock alone are dropped before the top-K cut (they can never be in a feasible tray), so
  the K = 20 cut is taken among dishes the pantry can make.
- Makespan (BR-TRAY-05) uses the same CP-SAT solver as cooking (`meal/schedule.py`, exposed through meal.service; the
  solver lives in meal because cooking depends on meal, not the reverse — UC15 TBD-02). The composer prunes with a
  lower bound; the best trays are then solved exactly in objective order.
- When the 5-minute serving window is impossible (one burner, long braise + stir-fry), the schedule is solved again
  without the window (`relaxed`; stir-fry still last) before the sequential fallback.
- Plan lifecycle is applied when plans are read or written: a plan is for the first lunch end (15:00) / dinner end
  (24:00) after its creation (a lunch plan made at 16:00 is tomorrow's lunch); past it, proposed → expired, accepted
  without a live cook session → abandoned; a new plan for the same meal occurrence supersedes the open one.
- Whether a plan has a live cook session, and whether a plan item belongs to a user (for `POST /shopping-items`), are
  installed by `tastoria.app` as callables (`MealDeps`, `SubstituteDeps`) — the allowed module dependencies forbid
  the direct imports.
- Swapping is refused (409 `conflict_state`) while the plan is being cooked (UC16 open question 1).
- Substitute candidates come from `substitution_pairs` only (exact context, slot-only, method-only, generic; then
  score), filtered by food group, activity and the allergens / diet of the user and the co-eaters. Embedding and
  nutrition-vector neighbours are not served: there is no deployed substitution model, and the DB enum
  `substitution_origin_t` has no value for a nutrition neighbour. `data/kb` has no curated pairs yet, so "Thiếu gì?"
  lists the missing ingredients with empty candidate lists until `tastoria catalog substitutes import` (UC26) exists.

Cooking (UC19–UC21):
- `POST /cook-sessions` with a schedule longer than the plan's `max_minutes` answers 409 `conflict_state` with
  `over_time_minutes`, `makespan_s`, `solver_status` and creates nothing; `confirm_over_time: true` creates it
  (FR-19-10; UC19 9a said 200 without a session, which no response schema can carry).
- `serve_at` earlier than now + makespan is moved to that earliest time (UC19 1a); the response shows the moved value.
- `completed_at` is server time (the undo window and the journal use it); the client's `completed_at` only becomes
  `occurred_at` of the interactions.

Journal (UC22): kcal per person = Σ dish snapshots + Σ rice bowls × E_bát; days without a cooked tray have
`kcal_per_person = null`; `kcal_range_status` follows the calibration above.

Privacy: pantry, meal, cooking, events and substitute export their tables in data-subject exports; withdrawing
`personalization` deletes the user's interactions (BR-CONSENT-04).

## Taste survey (UC23, UC24)

Respondents (A03) need no account. `POST /survey/respondents` checks the `consent` flag (422 `consent_required`),
the current `survey` policy version (409 `policy_outdated`) and the open form (409 `survey_closed`), then assigns
every anchor of the form plus `n_random` published non-anchor dishes:
- split over man / rau / canh in proportion to the published dishes per slot, largest remainder with random
  tie-break (FR-23-06: every share within 1 of the exact proportion);
- within a slot, the dishes shown least often in this form first, random among equals, so every dish collects about
  the same number of ratings (within 1 per slot). The form row is locked while assigning, so concurrent starts keep
  that balance;
- `display_order` is a random permutation of all assigned dishes (anchors included).

`respondent_token` (header `X-Respondent-Token`) is an HS256 JWT signed with the active JWT key, audience
`tastoria-survey`, `sub` = respondent id, valid 30 days, not stored. A missing, forged or expired token, a user access
token, or a token of another respondent answers 401 `respondent_token_invalid` (the contract and UC23 8b; TC-SEC-07
says 404). Answering is allowed on anchors too, "Chưa ăn bao giờ" included (UC23 open question 4). Writes on a closed
form answer 409 `survey_closed`, after completion 409 `survey_already_completed`; `complete` lists what is missing in
`missing_recipe_ids` (422 `survey_incomplete`).

Staff commands (inside the `api` container; container access is the `ml_operator` check, as for `catalog import`;
every run, refused ones included, writes one `audit_log` row with `actor_role = ml_operator`):

```bash
tastoria survey create-form --anchors 10 --random 35 [--seed S] [--yes]  # version YYYYMMDD-n, closes the open form
tastoria survey close [VERSION]       # stop answers (default: the open form)
tastoria survey open VERSION          # accept answers again (closes any other open form)
tastoria survey list                  # forms with respondent / completed counts
tastoria survey export VERSION [--out DIR]   # default DIR: $TASTORIA_STORAGE_DIR/survey-exports
```

Anchors are drawn by slot with `random.Random(seed)` over the published dishes ordered by id; the seed is printed
and stored in `audit_log.purpose` (`seed=…`), so the same seed on the same published catalog gives the same anchors.
`--yes` is required (or an interactive confirmation) when the open form already has respondents. `export` writes
`respondents.csv`, `assignments.csv`, `ratings.csv`, `favorites.csv`, `anchors.csv`, `recipes.csv` and
`manifest.json` (sha256 and row count per file) for completed respondents only, with `respondent_id` as the only
identifier, into a new directory `<VERSION>-<UTC stamp>` (written through a temporary directory, never overwriting).
`GET /admin/surveys` (JWT role `ml_operator`, else 403) lists the forms with counts and is audited.

## Contract changes made in slice 2 (`docs/api/openapi-v1.yaml`)

- Declared fields slice 1 already sent: `Profile.target_stale`, `Profile.suggested_kcal`; `EnergySuggestion.goal`,
  `age_years`, `equation`, `source`, `bmr_mifflin_kcal`; `DataRequestCreate.password`; `EnergyTargetResult` (response of
  `PUT /me/energy-target`); `ConsentWithdrawResult.data_request_id`. `ProblemCode` gained `internal_error`.
- `Recipe.make_ahead` (schema `MakeAhead`); `IngredientUnit.unit_code` + `cay`, `tep`, `con`.
- `PantryLot.urgency` nullable, `freshness_label` + `chua_ro`; `PantryLotPatch.status` + `used_up`; `POST /pantry/lots`
  description (no transaction).
- `GET /meal-plans/{id}/items/{itemId}/substitutes?ingredient_id=` (FR-17-02); `SubstituteCandidate.available_g_min`,
  `available_g_max` (FR-17-08).
- `POST /shopping-items` answers 200 when it merges into an open row (FR-18-05).
- `CookSessionCreate.confirm_over_time`; 409 `conflict_state` for an over-long schedule; `CookCompletion.shortfalls`.
- Descriptions: `GET /meal-plans` newest first; `GET /recipes/{id}` 404 for drafts.

## Next steps

- `tastoria catalog substitutes import` (UC26) and a curated `data/kb/substitutions.yaml`; then UC17 has candidates.
- mlops module (model_versions / model_deployments mapping) to serve a trained ranker through the `Ranker` protocol
  and to record `ranker_version_id`; scan module (UC12/UC13) writing lots and freshness probabilities.
- Calibrate: objective weights (§6.2 rule), qty_levels, made-ahead yields, shelf lives of the made-ahead products.
- Refresh the derived documents for migration 0003 (`docs/sad/05-tu-dien-du-lieu.md`, `db/schema_vp.sql`, ERD).
- A role for the CLI actor in `audit_log` (UC25 open question 1); `Idempotency-Key` on `POST /pantry/lots` (UC14 open
  question 2).

