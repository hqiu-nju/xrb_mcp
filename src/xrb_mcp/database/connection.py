from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from xrb_mcp.server.config import get_settings


@lru_cache
def get_engine(read_only: bool = False) -> Engine:
    settings = get_settings()
    url = settings.read_database_url if read_only else settings.database_url
    return create_engine(url.get_secret_value(), pool_pre_ping=True, hide_parameters=True)


@contextmanager
def session_scope(read_only: bool = False) -> Iterator[Session]:
    with Session(get_engine(read_only), expire_on_commit=False) as session, session.begin():
        if read_only:
            session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
