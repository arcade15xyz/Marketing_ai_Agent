from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(RuntimeError):
    """Raised when database storage is selected without valid configuration."""


def storage_backend() -> str:
    backend = os.getenv("STORAGE_BACKEND", "json").strip().lower()
    if backend not in {"json", "database"}:
        raise DatabaseConfigurationError(
            "STORAGE_BACKEND must be either 'json' or 'database'."
        )
    return backend


def database_url(*, required: bool = False) -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value.removeprefix("postgres://")
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value.removeprefix("postgresql://")

    if required and not value:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required when STORAGE_BACKEND=database."
        )
    return value


def database_echo() -> bool:
    return os.getenv("DATABASE_ECHO", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def create_database_engine(url: str | None = None, *, echo: bool | None = None) -> Engine:
    resolved_url = url or database_url(required=True)
    return create_engine(
        resolved_url,
        echo=database_echo() if echo is None else echo,
        pool_pre_ping=not resolved_url.startswith("sqlite"),
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache(maxsize=1)
def configured_session_factory() -> sessionmaker[Session]:
    return create_session_factory(create_database_engine())


@contextmanager
def session_scope(
    factory: sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    session_factory = factory or configured_session_factory()
    with session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
