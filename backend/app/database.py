from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")

is_sqlite = database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine_kwargs = {
    "connect_args": connect_args,
    "future": True,
    "pool_pre_ping": not is_sqlite,
}
if not is_sqlite:
    # Supabase's session pooler on the current plan exposes a small client
    # ceiling. SQLAlchemy's default QueuePool can reach 5 + 10 overflow
    # connections *per Render instance*. During a rolling deploy the old and
    # new instances overlap, which can exhaust that ceiling before startup.
    # HippoEdge can keep one connection checked out while a programme import awaits
    # remote race data, while the UI simultaneously performs programme/history/
    # selection reads. A pool of four fixed sessions avoids starving the API.
    # With one worker and Render rolling deploy overlap, 4 + 4 stays below the
    # Supabase session-pooler ceiling of 15. This limits connections, not data depth.
    engine_kwargs.update(
        pool_size=max(1, int(settings.database_pool_size)),
        max_overflow=max(0, int(settings.database_max_overflow)),
        pool_timeout=30,
        pool_recycle=120,
        pool_use_lifo=True,
    )

engine = create_engine(database_url, **engine_kwargs)


if is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
