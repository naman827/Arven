"""Async engine/session and idempotent schema init (never drops data)."""

from collections.abc import AsyncIterator

from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base, ResearchJob

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

ACTIVE_JOB_STATES = ("queued", "planning", "searching", "reading", "cross_checking", "synthesizing")


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(settings.async_database_url, connect_args={"timeout": 30})

        @event.listens_for(_engine.sync_engine, "connect")
        def _pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # creates missing tables only


async def mark_interrupted_jobs() -> int:
    async with session_factory()() as session:
        result = await session.execute(
            update(ResearchJob)
            .where(ResearchJob.status.in_(ACTIVE_JOB_STATES))
            .values(status="failed", error="interrupted: the server restarted while this job was running")
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
