"""Engine / session lifecycle.

A single lazily-created :class:`~sqlalchemy.engine.Engine` per process. Use
:func:`session_scope` for a transactional unit of work, or :func:`get_sessionmaker`
to obtain sessions for FastAPI dependency injection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from security.config import Settings, get_settings


def _make_engine(settings: Settings) -> Engine:
    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {
        "echo": False,
        "future": True,
        "pool_pre_ping": True,
    }
    if settings.is_sqlite:
        connect_args["check_same_thread"] = False
        # In-memory sqlite needs a shared static pool to survive across sessions.
        if ":memory:" in settings.database_url or "mode=memory" in settings.database_url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(pool_size=10, max_overflow=20, pool_recycle=1800)

    engine = create_engine(settings.database_url, connect_args=connect_args, **kwargs)

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # noqa: ANN001, ANN202
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    return _make_engine(get_settings())


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closed, never auto-commits."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Dispose the engine and clear caches (used by the test harness)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
