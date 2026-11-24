import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import auth, meta, profiles
from .settings import get_settings

log = logging.getLogger("dihari")

ROUTERS = [meta.router, auth.router, profiles.router]


def _optional_routers():
    """Routers added in later milestones; imported lazily so earlier milestones run."""
    import importlib
    out = []
    for name in ("jobs", "offers", "agreements", "payments", "voice", "admin", "notify", "reports"):
        try:
            out.append(importlib.import_module(f"app.routers.{name}").router)
        except ModuleNotFoundError as e:
            if e.name != f"app.routers.{name}":
                raise
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = None
    if get_settings().scheduler_enabled:
        from .modules.payments import scheduler_loop
        task = asyncio.create_task(scheduler_loop())
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="Dihari", version="0.1.0", lifespan=lifespan)
    for r in ROUTERS + _optional_routers():
        app.include_router(r)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
