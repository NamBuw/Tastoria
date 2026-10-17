"""Database engine, declarative Base and the Unit of Work (ADR 0007).

Sync SQLAlchemy 2.0 + psycopg 3. FastAPI runs sync endpoints and sync dependencies in its threadpool, so a
blocking DB call never blocks the event loop; with a few dozen concurrent users this is simpler than async and
keeps services plain functions that take a `Session`.

One request = one transaction: `get_uow` opens a session, the endpoint calls services (which never commit),
and the dependency commits once after the endpoint returns. Work outside the database (sending mail, running a
job, deleting files) is registered with `uow.after_commit(fn)` and runs only after a successful commit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from tastoria.core.errors import ApiError

log = logging.getLogger("tastoria.db")

# Same names as db/schema.sql (pk_<table>, fk_<table>_<cols>, uq_..., ck_..., ix_...).
NAMING = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def make_engine(url: str, *, pool_size: int = 5) -> Engine:
    return create_engine(url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=True)


@dataclass
class UnitOfWork:
    session: Session
    _after_commit: list[Callable[[], None]] = field(default_factory=list)

    def after_commit(self, fn: Callable[[], None]) -> None:
        self._after_commit.append(fn)

    def run_after_commit(self) -> None:
        hooks, self._after_commit = self._after_commit, []
        for fn in hooks:
            try:
                fn()
            except Exception:  # the transaction is already durable; a failed side effect must not turn into a 5xx
                log.exception("after-commit hook failed", extra={"hook": getattr(fn, "__name__", repr(fn))})


def run_in_uow(sm: sessionmaker[Session], fn: Callable[[UnitOfWork], object]) -> object:
    """Run `fn` in its own transaction outside a request (jobs, CLI)."""
    with sm() as session:
        uow = UnitOfWork(session)
        try:
            result = fn(uow)
            session.commit()
        except BaseException:
            session.rollback()
            raise
    uow.run_after_commit()
    return result


def get_uow(request: Request) -> Iterator[UnitOfWork]:
    sm: sessionmaker[Session] = request.app.state.sessionmaker
    with sm() as session:
        uow = UnitOfWork(session)
        try:
            yield uow
        except ApiError as exc:
            if exc.commit:
                session.commit()
            else:
                session.rollback()
            raise
        except BaseException:
            session.rollback()
            raise
        session.commit()
    uow.run_after_commit()
