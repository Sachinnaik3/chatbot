from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session_factory(database_url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("postgresql"):
        kwargs.update(pool_size=5, max_overflow=10, connect_args={"options": "-c statement_timeout=5000"})
    engine = create_engine(database_url, **kwargs)
    return sessionmaker(engine, expire_on_commit=False)
