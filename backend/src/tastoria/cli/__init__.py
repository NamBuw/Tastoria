"""`tastoria` command line (assembly level, like tastoria.app: it may wire every module).

tastoria db upgrade [REVISION]     apply migrations (default: head)
tastoria db current                show the applied revision
tastoria jobs process-dsr          finish open export / delete / withdraw requests (crash recovery; cron-able)
tastoria jobs sweep                same as `python -m tastoria.jobs.sweep`
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
    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
