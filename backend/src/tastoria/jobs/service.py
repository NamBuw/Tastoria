"""Public job service helpers for scheduled maintenance (M16): email outbox drain & export cleanup."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow

log = logging.getLogger("tastoria.jobs")

DEFAULT_OUTBOX_BATCH = 20
DEFAULT_OUTBOX_MAX_ATTEMPTS = 5
DEFAULT_EXPORT_MAX_AGE_HOURS = 24
_CLAIM_LEASE_SECONDS = 300
_STALE_TMP_SECONDS = 3600


class MailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


def drain_email_outbox(
    sessionmaker: sessionmaker[Session],
    mailer: MailSender,
    *,
    batch_size: int = DEFAULT_OUTBOX_BATCH,
    max_attempts: int = DEFAULT_OUTBOX_MAX_ATTEMPTS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Claim pending/stale-sending email_outbox rows, deliver SMTP outside DB tx, and update retry/sent state."""
    ts = now or utcnow()
    lease_until = ts + timedelta(seconds=_CLAIM_LEASE_SECONDS)
    with sessionmaker() as session:
        rows = session.execute(
            text(
                "WITH picked AS ("
                "  SELECT id FROM email_outbox"
                "  WHERE status IN ('pending', 'sending') AND next_attempt_at <= :now"
                "  ORDER BY next_attempt_at, created_at"
                "  LIMIT :lim"
                "  FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE email_outbox e "
                "SET status = 'sending', next_attempt_at = :lease_until "
                "FROM picked WHERE e.id = picked.id "
                "RETURNING e.id, e.to_email, e.subject, e.body_text, e.attempts"
            ),
            {"now": ts, "lim": max(1, int(batch_size)), "lease_until": lease_until},
        ).all()
        session.commit()

    sent = 0
    retried = 0
    failed = 0
    for oid, to_email, subject, body_text, attempts in rows:
        try:
            mailer.send(str(to_email), str(subject), str(body_text))
        except Exception as exc:  # noqa: BLE001 — isolate per-email SMTP failure so remaining outbox drains
            done_at = utcnow()
            next_attempts = int(attempts) + 1
            err = f"{type(exc).__name__}: {exc}"[:300]
            if next_attempts >= max_attempts:
                status = "failed"
                next_at = done_at
                failed += 1
            else:
                backoff_s = min(3600, 60 * (2 ** min(6, max(0, next_attempts - 1))))
                status = "pending"
                next_at = done_at + timedelta(seconds=backoff_s)
                retried += 1
            log.warning("outbox delivery failed", extra={"outbox_id": str(oid), "attempt": next_attempts, "status": status})
            with sessionmaker() as session:
                session.execute(
                    text(
                        "UPDATE email_outbox "
                        "SET status = :st, attempts = :att, next_attempt_at = :nxt, last_error = :err "
                        "WHERE id = :oid"
                    ),
                    {"st": status, "att": next_attempts, "nxt": next_at, "err": err, "oid": oid},
                )
                session.commit()
        else:
            done_at = utcnow()
            sent += 1
            with sessionmaker() as session:
                session.execute(
                    text(
                        "UPDATE email_outbox "
                        "SET status = 'sent', sent_at = :done_at, last_error = NULL "
                        "WHERE id = :oid"
                    ),
                    {"done_at": done_at, "oid": oid},
                )
                session.commit()
    return {"claimed": len(rows), "sent": sent, "retried": retried, "failed": failed}


def purge_exports(
    storage_dir: Path | str,
    *,
    max_age_hours: int = DEFAULT_EXPORT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete expired privacy export ZIP archives (> max_age_hours) and stale `.zip.tmp` debris."""
    ts = now or utcnow()
    cutoff_zip = (ts - timedelta(hours=max(1, int(max_age_hours)))).timestamp()
    cutoff_tmp = (ts - timedelta(seconds=_STALE_TMP_SECONDS)).timestamp()
    exports_root = (Path(storage_dir) / "exports").resolve()
    if not exports_root.is_dir():
        return {"exports_purged": 0, "tmp_removed": 0}

    purged = 0
    tmp_removed = 0
    for entry in exports_root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        resolved = entry.resolve()
        if not resolved.is_relative_to(exports_root):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if entry.name.endswith(".zip") and mtime <= cutoff_zip:
            entry.unlink(missing_ok=True)
            purged += 1
        elif entry.name.endswith(".zip.tmp") and mtime <= cutoff_tmp:
            entry.unlink(missing_ok=True)
            tmp_removed += 1
    return {"exports_purged": purged, "tmp_removed": tmp_removed}
