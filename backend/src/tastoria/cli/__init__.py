"""`tastoria` command line (assembly level, like tastoria.app: it may wire every module).

tastoria db upgrade [REVISION]     apply migrations (default: head)
tastoria db current                show the applied revision
tastoria jobs process-dsr          finish open export / delete / withdraw requests (crash recovery; cron-able)
tastoria jobs sweep                same as `python -m tastoria.jobs.sweep`
tastoria catalog import BUNDLE_DIR [--processed DIR]
                                   validate data/kb and upsert the catalog (UC25); JSON report, exit 1 on errors
tastoria catalog substitutes import FILE
                                   validate data/kb/substitution_pairs.yaml against the imported catalog and make the
                                   curated rows of substitution_pairs equal to it; JSON report, exit 1 on errors
tastoria survey create-form --anchors N --random M [--seed S] [--yes]
                                   open a new taste-survey form (UC24): N anchors drawn by slot with seed S (random
                                   and printed when omitted), M random dishes per respondent; closes the open form
tastoria survey close [VERSION]    stop accepting answers (default: the open form)
tastoria survey open VERSION       accept answers again on VERSION (closes any other open form)
tastoria survey list               forms with respondent counts
tastoria survey export VERSION [--out DIR]
                                   CSV files + manifest.json of the completed respondents, into a new directory
                                   under DIR (default: STORAGE_DIR/survey-exports)
"""

from __future__ import annotations

import argparse
import json
import sys

from tastoria.core.config import get_settings
from tastoria.core.logging import configure_logging


def _db(args: argparse.Namespace) -> int:
    from alembic import command

    from tastoria.migrations import alembic_config

    cfg = alembic_config(get_settings().database_url)
    if args.action == "upgrade":
        command.upgrade(cfg, args.revision)
    else:
        command.current(cfg, verbose=True)
    return 0


def _jobs(args: argparse.Namespace) -> int:
    from tastoria.app import build_subject_handlers
    from tastoria.core.db import make_engine, make_sessionmaker
    from tastoria.jobs.sweep import sweep
    from tastoria.modules.privacy.service import PrivacyDeps, process_pending
    from tastoria.modules.profile.service import ProfileDeps, make_cipher

    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=1)
    sm = make_sessionmaker(engine)
    try:
        if args.job == "sweep":
            print(json.dumps(sweep(sm)))
        else:
            deps = PrivacyDeps(
                settings, sm, handlers=build_subject_handlers(ProfileDeps(settings, make_cipher(settings)))
            )
            failed: list[str] = []
            done = process_pending(deps, on_error=lambda rid, exc: failed.append(str(rid)))
            print(json.dumps({"processed": done, "failed": failed}))
            return 1 if failed else 0
    finally:
        engine.dispose()
    return 0


def _catalog(args: argparse.Namespace) -> int:
    from pathlib import Path

    from tastoria.core.db import make_engine, make_sessionmaker
    from tastoria.modules.admin.service import import_catalog

    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=1)
    try:
        res = import_catalog(
            make_sessionmaker(engine), Path(args.bundle_dir), Path(args.processed) if args.processed else None
        )
    finally:
        engine.dispose()
    out = {"ok": res.ok, **res.report}
    if res.errors:
        out["errors"] = res.errors
        for e in res.errors:
            print(e, file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


def _substitutes(args: argparse.Namespace) -> int:
    from pathlib import Path

    from tastoria.core.db import make_engine, make_sessionmaker
    from tastoria.modules.admin.service import import_substitutes

    engine = make_engine(get_settings().database_url, pool_size=1)
    try:
        res = import_substitutes(make_sessionmaker(engine), Path(args.file))
    finally:
        engine.dispose()
    out = {"ok": res.ok, **res.report}
    if res.errors:
        out["errors"] = res.errors
        for e in res.errors:
            print(e, file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


def _positive(raw: str) -> int:
    try:
        v = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("phải là số nguyên dương") from None
    if v < 1:
        raise argparse.ArgumentTypeError("phải là số nguyên dương")
    return v


def _survey(args: argparse.Namespace) -> int:
    from datetime import date
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from tastoria.core.clock import utcnow
    from tastoria.core.db import make_engine, make_sessionmaker, run_in_uow
    from tastoria.modules.admin import service as admin
    from tastoria.modules.survey import service as survey

    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=1)
    sm = make_sessionmaker(engine)
    try:
        if args.survey_cmd == "list":
            page = run_in_uow(sm, lambda uow: survey.list_forms(uow.session, cursor=None, limit=100))
            print(json.dumps(page.model_dump(mode="json")["items"], ensure_ascii=False, indent=2))  # type: ignore[union-attr]
            return 0
        if args.survey_cmd == "create-form":
            current = admin.survey_open_form(sm)
            if current is not None and current.respondents_total > 0 and not args.yes:
                msg = (
                    f"Phiếu {current.version} đang mở với {current.respondents_total} người tham gia "
                    f"({current.respondents_completed} hoàn tất); tạo phiếu mới sẽ đóng nó."
                )
                if not sys.stdin.isatty():
                    print(msg + " Chạy lại với --yes để xác nhận.", file=sys.stderr)
                    return 1
                if input(msg + " Tiếp tục? [y/N] ").strip().lower() not in {"y", "yes", "c", "co"}:
                    return 1
            today: date = utcnow().astimezone(ZoneInfo(settings.timezone)).date()
            res = admin.create_survey_form(sm, n_anchor=args.anchors, n_random=args.random, seed=args.seed, today=today)
        elif args.survey_cmd in {"open", "close"}:
            res = admin.set_survey_open(sm, args.version, args.survey_cmd == "open")
        else:
            out = Path(args.out) if args.out else Path(settings.storage_dir) / "survey-exports"
            res = admin.export_survey(sm, args.version, out)
            if res.ok and res.report["is_open"]:
                print(
                    f"Cảnh báo: phiếu {args.version} vẫn đang mở; tệp xuất là ảnh chụp tại lúc chạy.", file=sys.stderr
                )
    finally:
        engine.dispose()
    out_json = {"ok": res.ok, **res.report}
    if res.errors:
        out_json["errors"] = res.errors
        for e in res.errors:
            print(e, file=sys.stderr)
    print(json.dumps(out_json, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="tastoria")
    sub = p.add_subparsers(dest="cmd", required=True)
    db = sub.add_parser("db", help="migrations")
    db.add_argument("action", choices=["upgrade", "current"])
    db.add_argument("revision", nargs="?", default="head")
    db.set_defaults(func=_db)
    jobs = sub.add_parser("jobs", help="background jobs")
    jobs.add_argument("job", choices=["process-dsr", "sweep"])
    jobs.set_defaults(func=_jobs)
    cat = sub.add_parser("catalog", help="catalog bundle (UC25)")
    cat_sub = cat.add_subparsers(dest="catalog_cmd", required=True)
    imp = cat_sub.add_parser("import", help="validate and import a bundle directory (data/kb)")
    imp.add_argument("bundle_dir")
    imp.add_argument(
        "--processed", default=None, help="processed composition tables (default: BUNDLE_DIR/../processed)"
    )
    imp.set_defaults(func=_catalog)
    subs = cat_sub.add_parser("substitutes", help="curated substitution table (design v2 §6.3)")
    subs_sub = subs.add_subparsers(dest="substitutes_cmd", required=True)
    simp = subs_sub.add_parser("import", help="validate and import data/kb/substitution_pairs.yaml")
    simp.add_argument("file")
    simp.set_defaults(func=_substitutes)
    sv = sub.add_parser("survey", help="taste survey forms (UC24)")
    sv_sub = sv.add_subparsers(dest="survey_cmd", required=True)
    cf = sv_sub.add_parser("create-form", help="open a new form (closes the open one)")
    cf.add_argument("--anchors", type=_positive, required=True, help="anchor dishes everyone rates (e.g. 10)")
    cf.add_argument("--random", type=_positive, required=True, help="random dishes per respondent (e.g. 35)")
    cf.add_argument("--seed", type=int, default=None, help="seed of the anchor draw (default: random, printed)")
    cf.add_argument("--yes", action="store_true", help="do not ask when the open form already has respondents")
    cl = sv_sub.add_parser("close", help="stop accepting answers")
    cl.add_argument("version", nargs="?", default=None)
    op = sv_sub.add_parser("open", help="accept answers again")
    op.add_argument("version")
    sv_sub.add_parser("list", help="forms with respondent counts")
    ex = sv_sub.add_parser("export", help="CSV + manifest.json of completed respondents")
    ex.add_argument("version")
    ex.add_argument("--out", default=None, help="base directory (default: STORAGE_DIR/survey-exports)")
    sv.set_defaults(func=_survey)
    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
