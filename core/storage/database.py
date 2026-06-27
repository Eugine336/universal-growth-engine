"""
Database Engine & Session Factory

Provides SQLAlchemy engine initialization and session management.
Defaults to SQLite; accepts any SQLAlchemy-compatible URL.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def init_db(db_url: str = "sqlite:///ugie.db") -> Engine:
    global _engine, _SessionFactory
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(db_url, connect_args=connect_args, echo=False)

    from .models import Base
    Base.metadata.create_all(bind=_engine)

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.info(f"Database initialized: {db_url}")
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session() -> Session:
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionFactory()
