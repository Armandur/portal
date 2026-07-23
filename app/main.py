"""Portal: tjänsteportal för delad dev-VM (ubuntu-ai).

App-instans, lifespan och router-registrering.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, PORTAL_PORT
from app.database import clean_expired_shares, init_db, upsert_service
from app.ledger import import_ledger, write_ledger
from app.ports import clean_dead_ephemeral_services
from app.routes import api, pages


def _register_self() -> None:
    """Registrerar/uppdaterar portalen själv i registret vid start."""
    upsert_service({
        "name": "portal",
        "project": "portal",
        "port": PORTAL_PORT,
        "pid": os.getpid(),
        "description": "Tjänsteportal: register, portverktyg och dokumentation",
        "url_path": "/",
        "docs_path": str(BASE_DIR / "README.md"),
        "started_by": "portal (självregistrering)",
    })


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    import_ledger()
    clean_dead_ephemeral_services()
    _register_self()
    write_ledger()
    clean_expired_shares()
    yield


app = FastAPI(
    title="Portal",
    description="Tjänsteportal för delad dev-VM",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.include_router(api.router)
app.include_router(pages.router)
