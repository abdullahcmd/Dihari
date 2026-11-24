from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .settings import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always store UTC, always return tz-aware UTC (SQLite drops tzinfo)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


_engine = None
_Session = None


def make_engine(url: str):
    kw = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            from sqlalchemy.pool import StaticPool
            kw["poolclass"] = StaticPool
    return create_engine(url, **kw)


def init_db(url: str | None = None):
    global _engine, _Session
    _engine = make_engine(url or get_settings().database_url)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    from . import models  # noqa: F401
    Base.metadata.create_all(_engine)
    if _engine.dialect.name == "postgresql":
        from .modules.geo import ensure_postgis
        ensure_postgis(_engine)
    return _engine


def get_engine():
    if _engine is None:
        init_db()
    return _engine


def SessionLocal():
    if _Session is None:
        init_db()
    return _Session()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
