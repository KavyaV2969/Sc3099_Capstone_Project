"""Synchronous SQLAlchemy database connection management."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.schema_contract import inspect_readiness

settings = get_settings()
# Recommended pool (size 10, overflow 20). Request threads are capped at this capacity
# (see main.lifespan), so a burst queues for a thread instead of timing out on the pool.
POOL_SIZE, MAX_OVERFLOW = 10, 20
POOL_CAPACITY = POOL_SIZE + MAX_OVERFLOW
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=30,
    connect_args={"connect_timeout": 10} if settings.database_url.startswith("postgresql") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session and roll back unsuccessful work."""
    database = SessionLocal()
    try:
        yield database
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def database_is_reachable() -> bool:
    """Cheap liveness probe: one pooled round trip, no catalog inspection."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def database_is_healthy() -> bool:
    """Require connectivity and the exact supported PostgreSQL schema."""
    return database_readiness().healthy


def database_readiness():
    return inspect_readiness(engine)
