"""UC34 sweeper: `python -m tastoria.jobs.sweep` (cron, every minute — ADR 0003).

This slice cleans expired refresh tokens, password-reset tokens and idempotency keys (> 48 h). Stuck scans are
added with the scan slice.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core import idempotency
from tastoria.core.config import get_settings
from tastoria.core.db import UnitOfWork, make_engine, make_sessionmaker, run_in_uow
from tastoria.core.logging import configure_logging
from tastoria.modules.identity import service as identity

log = logging.getLogger("tastoria.jobs.sweep")


def sweep(sm: sessionmaker[Session]) -> dict[str, int]:
    def work(uow: UnitOfWork) -> dict[str, int]:
        counts = identity.purge_expired(uow.session)
        counts["idempotency_keys"] = idempotency.purge_expired(uow.session)
        return counts

    return run_in_uow(sm, work)  # type: ignore[return-value]


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url, pool_size=1)
    try:
        counts = sweep(make_sessionmaker(engine))
    finally:
        engine.dispose()
    log.info("sweep done", extra={"deleted": counts})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
