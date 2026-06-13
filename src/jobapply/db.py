"""Database engine + session helpers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import ensure_dirs, settings
from . import models  # noqa: F401  (ensure tables are registered)

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        ensure_dirs()
        _engine = create_engine(settings.database_url, echo=False)
    return _engine


def init_db() -> None:
    """Create tables if they don't exist."""
    SQLModel.metadata.create_all(get_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
