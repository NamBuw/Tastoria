"""UC32 / BR-RETAIN-01: `python -m tastoria.jobs.purge_images` (scheduler, hourly) — delete scan photos 30 days after
their scan unless the user contributed them (photo_contribution consent at upload)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.config import get_settings
from tastoria.core.db import make_engine, make_sessionmaker, run_in_uow
from tastoria.core.logging import configure_logging
from tastoria.modules.scan import service as scan

log = logging.getLogger("tastoria.jobs.purge_images")


def purge(sm: sessionmaker[Session], storage_dir: Path) -> dict[str, int]:
    return run_in_uow(sm, lambda uow: scan.purge_images(uow.session, storage_dir))  # type: ignore[return-value]


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url, pool_size=1)
    try:
        counts = purge(make_sessionmaker(engine), Path(settings.storage_dir))
    finally:
        engine.dispose()
    log.info("purge done", extra={"deleted": counts})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
