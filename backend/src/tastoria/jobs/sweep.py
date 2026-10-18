"""UC34 sweeper: `python -m tastoria.jobs.sweep` (cron, every minute — ADR 0003).

Cleans expired refresh tokens, password-reset tokens and idempotency keys (> 48 h), and handles stuck scans (ST01):
enqueues scans whose enqueue never happened, expires scans no worker is running (scan.sweep_stuck_scans).
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
from tastoria.modules.scan import service as scan
from tastoria.modules.scan.service import ScanQueue

log = logging.getLogger("tastoria.jobs.sweep")


def sweep(sm: sessionmaker[Session], queue: ScanQueue | None = None) -> dict[str, int]:
    def work(uow: UnitOfWork) -> dict[str, int]:
        counts = identity.purge_expired(uow.session)
        counts["idempotency_keys"] = idempotency.purge_expired(uow.session)
        counts.update(scan.sweep_stuck_scans(uow.session, queue))
        return counts

    return run_in_uow(sm, work)  # type: ignore[return-value]


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url, pool_size=1)
    try:
        counts = sweep(make_sessionmaker(engine), ScanQueue(settings.valkey_url))
    finally:
        engine.dispose()
    log.info("sweep done", extra={"deleted": counts})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
