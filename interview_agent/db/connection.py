import os
import logging
from contextlib import contextmanager
from typing import Optional, Generator, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, NullPool

from interview_agent.config import settings
from interview_agent.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None
_current_url = None


def normalize_database_url(url: str) -> str:
    """Normalize database connection URL for SQLAlchemy 2.0 with modern psycopg driver."""
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine(db_url: Optional[str] = None, pool_override: Optional[Any] = None):
    """Create or return cached SQLAlchemy engine."""
    global _engine, _session_factory, _current_url
    url = normalize_database_url(db_url or settings.database_url or os.getenv("DATABASE_URL", ""))
    
    if not url:
        raise ValueError(
            "Database connection URL is missing. Set DATABASE_URL in your environment or .env file."
        )

    # If already created with matching URL, reuse
    if _engine is not None and _current_url == url:
        return _engine

    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass

    engine_kwargs = {"echo": False}
    if url.startswith("sqlite"):
        if ":memory:" in url:
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            engine_kwargs["poolclass"] = StaticPool
        else:
            engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL production configuration
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10
        engine_kwargs["pool_timeout"] = 30.0

    engine = create_engine(url, **engine_kwargs)
    _engine = engine
    _current_url = url
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def get_session_factory(db_url: Optional[str] = None):
    global _session_factory, _current_url
    url = normalize_database_url(db_url or settings.database_url or os.getenv("DATABASE_URL", ""))
    if _session_factory is None or _current_url != url:
        get_engine(url)
    return _session_factory


@contextmanager
def get_db_session(session_override: Optional[Session] = None) -> Generator[Session, None, None]:
    """
    Context manager providing a transactional database session.
    Commits on successful completion, rollbacks on error, and ensures the session is closed.
    """
    if session_override is not None:
        yield session_override
        return

    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database transaction rolled back due to error: {e}")
        raise
    finally:
        session.close()


def init_db(engine_override=None):
    """Create database tables if they do not exist."""
    engine = engine_override or get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")


def check_db_health(engine_override=None) -> bool:
    """Check database connectivity with a simple SELECT 1 query."""
    engine = engine_override or get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        return result.scalar() == 1
