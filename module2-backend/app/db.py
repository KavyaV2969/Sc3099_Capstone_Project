"""Synchronous SQLAlchemy database connection management."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.schema_contract import inspect_readiness

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=5,
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


def database_is_healthy() -> bool:
    """Require connectivity and the exact supported PostgreSQL schema."""
    return database_readiness().healthy


def database_readiness():
    return inspect_readiness(engine)
