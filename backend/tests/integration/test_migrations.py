"""The Alembic chain reproduces db/schema.sql exactly, runs cleanly up/down, and enforces 0007 hardening."""

from __future__ import annotations

import re

import docker_services as ds
from alembic import command
from conftest import REPO_ROOT

from tastoria.migrations import alembic_config


def _create_db(pg: ds.Container, name: str) -> None:
    r = pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", ds.PG_DB, "-c", f"CREATE DATABASE {name}")
    assert r.returncode == 0, r.stderr


def _schema_dump(pg: ds.Container, db: str) -> str:
    r = pg.exec("pg_dump", "--schema-only", "--no-owner", "--no-privileges", "-U", ds.PG_USER, "-d", db)
    assert r.returncode == 0, r.stderr
    text = r.stdout
    # pg_dump embeds a random \restrict token per run; alembic adds its bookkeeping table.
    text = re.sub(r"^\\(un)?restrict .*$", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"CREATE TABLE public\.alembic_version \(.*?\);\n|ALTER TABLE ONLY public\.alembic_version\n.*?;\n",
        "",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"--\n-- Name: alembic_version.*?\n--\n", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", text)


def test_migration_head_equals_schema_sql(pg: ds.Container) -> None:
    _create_db(pg, "ref_schema")
    r = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", ds.PG_USER, "-d", "ref_schema",
        input_text=(REPO_ROOT / "db/schema.sql").read_text(encoding="utf-8"),
    )  # fmt: skip
    assert r.returncode == 0, r.stderr

    _create_db(pg, "mig_schema")
    command.upgrade(alembic_config(ds.pg_url(pg, "mig_schema")), "head")

    ref, mig = _schema_dump(pg, "ref_schema"), _schema_dump(pg, "mig_schema")
    assert "CREATE TABLE public.users" in ref
    assert "CREATE TABLE public.meal_logs" in ref
    assert mig == ref


def test_upgrade_downgrade_upgrade(pg: ds.Container) -> None:
    _create_db(pg, "roundtrip")
    cfg = alembic_config(ds.pg_url(pg, "roundtrip"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    sql = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    r = pg.exec("psql", "-tA", "-U", ds.PG_USER, "-d", "roundtrip", "-c", sql)
    assert r.stdout.strip() == "68"


def test_migration_0005_and_0007_roles_dsr_app_params_and_constraints(pg: ds.Container) -> None:
    _create_db(pg, "rolecheck")
    command.upgrade(alembic_config(ds.pg_url(pg, "rolecheck")), "head")

    enum_r = pg.exec(
        "psql", "-tA", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "SELECT unnest(enum_range(NULL::model_name_t))",
    )
    assert enum_r.returncode == 0, enum_r.stderr
    assert set(enum_r.stdout.strip().splitlines()) == {
        "detector",
        "freshness",
        "ranker",
        "substitution",
        "meal_calorie",
        "dish_classifier",
        "mushroom_classifier",
    }

    # Verify app_params defaults via app_param()
    params_r = pg.exec(
        "psql", "-tA", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "SELECT app_param('fresh_u_soon'), app_param('fresh_u_check'), app_param('rice_bowl_kcal'), app_param('kcal_half_width')",
    )
    assert params_r.returncode == 0, params_r.stderr
    assert [float(x) for x in params_r.stdout.strip().split("|")] == [0.5, 1.0, 200.0, 0.15]

    # Verify tastoria_app cannot DELETE from append-only tables or mutate app_params
    deny_r = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; DELETE FROM interactions; ROLLBACK;",
    )
    assert deny_r.returncode != 0
    assert "permission denied" in deny_r.stderr.lower()

    deny_params = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "BEGIN; SET LOCAL ROLE tastoria_app; UPDATE app_params SET value_num = 999 WHERE key = 'rice_bowl_kcal'; ROLLBACK;",
    )
    assert deny_params.returncode != 0
    assert "permission denied" in deny_params.stderr.lower()

    # Verify DSR-bound SECURITY DEFINER erasure: denied without DSR/withdrawal (42501), succeeds with active DSR
    seed_sql = """
    INSERT INTO users (id, email, password_hash)
    VALUES ('11111111-1111-1111-1111-111111111111', 'dsr@tastoria.vn', 'x'),
           ('22222222-2222-2222-2222-222222222222', 'withdraw@tastoria.vn', 'x');
    """
    assert pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck", "-c", seed_sql).returncode == 0

    no_dsr_inter = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "SELECT erase_user_interactions('11111111-1111-1111-1111-111111111111'); ROLLBACK;",
    )
    assert no_dsr_inter.returncode != 0
    assert "active dsr request" in no_dsr_inter.stderr.lower()

    no_dsr_acct = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "SELECT erase_user_account('11111111-1111-1111-1111-111111111111'); ROLLBACK;",
    )
    assert no_dsr_acct.returncode != 0
    assert "active delete dsr request" in no_dsr_acct.stderr.lower()

    # Verify tastoria_app cannot directly DELETE/TRUNCATE users or dsr_requests, while retaining SELECT/INSERT/UPDATE
    priv_r = pg.exec(
        "psql", "-tA", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "SELECT "
        "has_table_privilege('tastoria_app', 'public.users', 'DELETE'), "
        "has_table_privilege('tastoria_app', 'public.users', 'TRUNCATE'), "
        "has_table_privilege('tastoria_app', 'public.users', 'SELECT, INSERT, UPDATE'), "
        "has_table_privilege('tastoria_app', 'public.dsr_requests', 'DELETE'), "
        "has_table_privilege('tastoria_app', 'public.dsr_requests', 'TRUNCATE'), "
        "has_table_privilege('tastoria_app', 'public.dsr_requests', 'SELECT, INSERT, UPDATE'), "
        "has_table_privilege('tastoria_jobs', 'public.users', 'DELETE'), "
        "has_table_privilege('tastoria_jobs', 'public.dsr_requests', 'DELETE');",
    )
    assert priv_r.returncode == 0, priv_r.stderr
    assert priv_r.stdout.strip() == "f|f|t|f|f|t|t|t"

    deny_users = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "DELETE FROM users WHERE id = '11111111-1111-1111-1111-111111111111'; ROLLBACK;",
    )
    assert deny_users.returncode != 0
    assert "permission denied" in deny_users.stderr.lower()

    deny_dsr_del = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "DELETE FROM dsr_requests; ROLLBACK;",
    )
    assert deny_dsr_del.returncode != 0
    assert "permission denied" in deny_dsr_del.stderr.lower()

    # Verify pg_temp.dsr_requests shadowing cannot bypass erase_user_account or erase_user_interactions (42501)
    shadow_acct = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "CREATE TEMP TABLE dsr_requests (user_id uuid, type text, status text); "
        "INSERT INTO pg_temp.dsr_requests VALUES ('11111111-1111-1111-1111-111111111111', 'delete', 'in_progress'); "
        "SELECT erase_user_account('11111111-1111-1111-1111-111111111111'); ROLLBACK;",
    )
    assert shadow_acct.returncode != 0
    assert "active delete dsr request" in shadow_acct.stderr.lower()

    shadow_inter = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "BEGIN; SET LOCAL tastoria.erasure = 'on'; SET LOCAL ROLE tastoria_app; "
        "CREATE TEMP TABLE dsr_requests (user_id uuid, type text, status text); "
        "INSERT INTO pg_temp.dsr_requests VALUES ('11111111-1111-1111-1111-111111111111', 'delete', 'in_progress'); "
        "SELECT erase_user_interactions('11111111-1111-1111-1111-111111111111'); ROLLBACK;",
    )
    assert shadow_inter.returncode != 0
    assert "active dsr request" in shadow_inter.stderr.lower()

    victim_still = pg.exec(
        "psql", "-tA", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "SELECT count(*) FROM users WHERE id = '11111111-1111-1111-1111-111111111111';",
    )
    assert victim_still.returncode == 0, victim_still.stderr
    assert victim_still.stdout.strip() == "1"

    ok_dsr_sql = """
    INSERT INTO dsr_requests (user_id, subject_ref, type, status, received_at)
    VALUES ('11111111-1111-1111-1111-111111111111', '\\x01', 'delete', 'in_progress', now());
    INSERT INTO consent_events (user_id, policy_version_id, action, channel)
    SELECT '22222222-2222-2222-2222-222222222222', id, 'withdraw', 'settings'
      FROM policy_versions WHERE purpose_code = 'personalization' LIMIT 1;
    BEGIN;
    SET LOCAL tastoria.erasure = 'on';
    SET LOCAL ROLE tastoria_app;
    SELECT erase_user_interactions('22222222-2222-2222-2222-222222222222');
    SELECT erase_user_interactions('11111111-1111-1111-1111-111111111111');
    SELECT erase_user_account('11111111-1111-1111-1111-111111111111');
    COMMIT;
    SELECT count(*) FROM users WHERE id = '11111111-1111-1111-1111-111111111111';
    """
    ok_r = pg.exec("psql", "-tA", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck", "-c", ok_dsr_sql)
    assert ok_r.returncode == 0, ok_r.stderr
    assert ok_r.stdout.strip().splitlines()[-1] == "0"

    # Verify FAVORITES_MAX <= 5 trigger (ON CONFLICT DO NOTHING safe at 5, rejects 6th)
    fav_setup = """
    INSERT INTO cooking_methods (code, name_vi) VALUES ('xao', 'Xào');
    INSERT INTO food_groups (code, name_vi) VALUES ('rau', 'Rau');
    INSERT INTO ingredients (id, name_vi, food_group_code)
    VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Rau test', 'rau');
    INSERT INTO recipes (id, name_vi, slot, servings, method_code, status) VALUES
        ('00000000-0000-0000-0000-000000000001', 'Món 1', 'man', 2, 'xao', 'published'),
        ('00000000-0000-0000-0000-000000000002', 'Món 2', 'man', 2, 'xao', 'published'),
        ('00000000-0000-0000-0000-000000000003', 'Món 3', 'man', 2, 'xao', 'published'),
        ('00000000-0000-0000-0000-000000000004', 'Món 4', 'man', 2, 'xao', 'published'),
        ('00000000-0000-0000-0000-000000000005', 'Món 5', 'man', 2, 'xao', 'published'),
        ('00000000-0000-0000-0000-000000000006', 'Món 6', 'man', 2, 'xao', 'published');
    INSERT INTO user_favorite_recipes (user_id, recipe_id) VALUES
        ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000001'),
        ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000002'),
        ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000003'),
        ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000004'),
        ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000005')
    ON CONFLICT DO NOTHING;
    INSERT INTO user_favorite_recipes (user_id, recipe_id)
    VALUES ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000001')
    ON CONFLICT DO NOTHING;
    """
    assert pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck", "-c", fav_setup).returncode == 0
    fav_6 = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "INSERT INTO user_favorite_recipes (user_id, recipe_id) VALUES ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000006');",
    )
    assert fav_6.returncode != 0
    assert "favorites_max = 5" in fav_6.stderr.lower()

    # Verify partial unique indexes on open shopping_items
    shop_ok = """
    INSERT INTO meal_plans (id, user_id, meal, persons, max_minutes, reason_vi, params_version)
    VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'dinner', 2, 30, 'r', 'p');
    INSERT INTO meal_plan_items (id, meal_plan_id, slot, recipe_id, rank_score, servings_scale)
    VALUES ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'man', '00000000-0000-0000-0000-000000000001', 1.0, 1.0);
    INSERT INTO shopping_items (user_id, ingredient_id, status, source_meal_plan_item_id) VALUES
        ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'open', NULL),
        ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bought', NULL),
        ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bought', NULL),
        ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'open', 'cccccccc-cccc-cccc-cccc-cccccccccccc');
    """
    assert pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck", "-c", shop_ok).returncode == 0
    dup_null = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "INSERT INTO shopping_items (user_id, ingredient_id, status, source_meal_plan_item_id) VALUES ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'open', NULL);",
    )
    assert dup_null.returncode != 0
    dup_src = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c", "INSERT INTO shopping_items (user_id, ingredient_id, status, source_meal_plan_item_id) VALUES ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'open', 'cccccccc-cccc-cccc-cccc-cccccccccccc');",
    )
    assert dup_src.returncode != 0

    # Verify ck_meal_log_items_kcal rejects negative kcal and accepts kcal = 0
    meal_log_ok = """
    INSERT INTO meal_logs (id, user_id, logged_date, meal_slot, title, source_type)
    VALUES ('dddddddd-dddd-dddd-dddd-dddddddddddd', '22222222-2222-2222-2222-222222222222', '2026-11-24', 'trua', 'Cơm trưa', 'manual');
    INSERT INTO meal_log_items (meal_log_id, ordinal, label_vi, kcal)
    VALUES ('dddddddd-dddd-dddd-dddd-dddddddddddd', 1, 'Nước lọc', 0);
    """
    assert pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck", "-c", meal_log_ok).returncode == 0
    neg_kcal = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "rolecheck",
        "-c",
        "INSERT INTO meal_log_items (meal_log_id, ordinal, label_vi, kcal) "
        "VALUES ('dddddddd-dddd-dddd-dddd-dddddddddddd', 2, 'Món âm', -50);",
    )
    assert neg_kcal.returncode != 0
    assert "ck_meal_log_items_kcal" in neg_kcal.stderr


def test_pg_dump_restore_preserves_v_journal_days_urgent_lots(pg: ds.Container) -> None:
    _create_db(pg, "src_dr")
    command.upgrade(alembic_config(ds.pg_url(pg, "src_dr")), "head")

    seed = """
    INSERT INTO users (id, email, password_hash)
    VALUES ('33333333-3333-3333-3333-333333333333', 'dr@tastoria.vn', 'x');
    INSERT INTO food_groups (code, name_vi) VALUES ('rau', 'Rau');
    INSERT INTO cooking_methods (code, name_vi) VALUES ('xao', 'Xào');
    INSERT INTO ingredients (id, name_vi, food_group_code)
    VALUES ('44444444-4444-4444-4444-444444444444', 'Cải xanh', 'rau');
    INSERT INTO recipes (id, name_vi, slot, servings, method_code, status)
    VALUES ('55555555-5555-5555-5555-555555555555', 'Cải xanh xào', 'rau', 2, 'xao', 'published');
    INSERT INTO meal_plans (id, user_id, meal, persons, max_minutes, status, rice_bowls_per_person, reason_vi, params_version)
    VALUES ('66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333', 'dinner', 2, 30, 'cooked', 1.5, 'r', 'p');
    INSERT INTO meal_plan_items (id, meal_plan_id, slot, recipe_id, rank_score, servings_scale, kcal_per_person)
    VALUES ('77777777-7777-7777-7777-777777777777', '66666666-6666-6666-6666-666666666666', 'rau', '55555555-5555-5555-5555-555555555555', 1.0, 1.0, 120);
    INSERT INTO cook_sessions (id, meal_plan_id, status, serve_at, burners, started_at, completed_at)
    VALUES ('88888888-8888-8888-8888-888888888888', '66666666-6666-6666-6666-666666666666', 'completed', now(), 2, now() - interval '20 minutes', now());
    INSERT INTO pantry_lots (id, user_id, ingredient_id, initial_g_min, initial_g_max, acquired_at, acquired_basis)
    VALUES ('99999999-9999-9999-9999-999999999999', '33333333-3333-3333-3333-333333333333', '44444444-4444-4444-4444-444444444444', 200, 300, now() - interval '2 days', 'purchase_date_entered');
    INSERT INTO pantry_transactions (lot_id, delta_g_min, delta_g_max, reason, ref_type, ref_id, urgency_at_event)
    VALUES ('99999999-9999-9999-9999-999999999999', -100, -100, 'cook_deduct', 'cook_session', '88888888-8888-8888-8888-888888888888', 0.75);
    """
    assert pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", "src_dr", "-c", seed).returncode == 0

    src_q = pg.exec("psql", "-tA", "-U", ds.PG_USER, "-d", "src_dr", "-c", "SELECT urgent_lots_used, kcal_per_person FROM v_journal_days")
    assert src_q.returncode == 0, src_q.stderr
    assert src_q.stdout.strip() == "1|420.0"

    _create_db(pg, "dst_dr")
    dump_path = "/tmp/tastoria_dr_test.dump"
    try:
        dump_r = pg.exec("pg_dump", "-Fc", "-U", ds.PG_USER, "-d", "src_dr", "-f", dump_path)
        assert dump_r.returncode == 0, dump_r.stderr
        rest_r = pg.exec("pg_restore", "--no-owner", "--no-privileges", "-U", ds.PG_USER, "-d", "dst_dr", dump_path)
        assert rest_r.returncode == 0, rest_r.stderr
    finally:
        pg.exec("rm", "-f", dump_path)

    dst_q = pg.exec("psql", "-tA", "-U", ds.PG_USER, "-d", "dst_dr", "-c", "SELECT urgent_lots_used, kcal_per_person FROM v_journal_days")
    assert dst_q.returncode == 0, dst_q.stderr
    assert dst_q.stdout.strip() == "1|420.0"
