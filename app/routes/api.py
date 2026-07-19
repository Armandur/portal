"""JSON-API för tjänsteregistret, portverktyget, delningar och teman."""

import base64
import binascii
import json
import mimetypes
import os
import secrets
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import backlog
from app import database as db
from app.config import (
    PORT_RANGE_END, PORT_RANGE_START, PORTAL_BASE_URL, PORTAL_PORT,
    SERVICE_HOST, SHARE_MAX_BYTES, SHARE_TTL_MINUTES, THEME_MAX_BYTES,
)
from app.ledger import write_ledger
from app.ports import find_free_port, scan_listening_ports, service_status

router = APIRouter(prefix="/api")


class ServiceIn(BaseModel):
    name: str
    project: str
    port: int | None = None
    pid: int | None = None
    description: str | None = None
    url_path: str = "/"
    docs_path: str | None = None
    docs_md: str | None = None
    started_by: str | None = None


class ServicePatch(BaseModel):
    project: str | None = None
    port: int | None = None
    pid: int | None = None
    description: str | None = None
    url_path: str | None = None
    docs_path: str | None = None
    docs_md: str | None = None
    started_by: str | None = None


class ReserveIn(BaseModel):
    range_start: int = Field(default=PORT_RANGE_START, ge=1, le=65535)
    range_end: int = Field(default=PORT_RANGE_END, ge=1, le=65535)
    note: str | None = None


class ShareIn(BaseModel):
    filename: str
    content_b64: str
    content_type: str | None = None
    description: str | None = None
    ttl_minutes: int = SHARE_TTL_MINUTES


class ThemeIn(BaseModel):
    name: str
    spec: dict
    tokens_css: str


def _with_status(svc: dict, listening: dict) -> dict:
    out = dict(svc)
    out["status"] = service_status(svc, listening)
    if svc.get("port") is None:
        # Portlös dokumentationspost: länka till dokumentationssidan
        out["url"] = f"http://{SERVICE_HOST}:{PORTAL_PORT}/docs/{svc['name']}"
    else:
        out["url"] = f"http://{SERVICE_HOST}:{svc['port']}{svc.get('url_path') or '/'}"
    out["has_docs"] = bool(svc.get("docs_path") or svc.get("docs_md"))
    return out


def _validate_port(port: int) -> None:
    if not (1 <= port <= 65535):
        raise HTTPException(400, "Ogiltig port: måste vara ett heltal mellan 1 och 65535.")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/todos")
def list_todos():
    """Öppna todos per projekt, lästa read-only från backlog-CLI:t."""
    return backlog.open_todos()


@router.get("/services")
def list_services():
    listening = scan_listening_ports()
    return [_with_status(s, listening) for s in db.list_services()]


@router.get("/services/{name}")
def get_service(name: str):
    svc = db.get_service(name)
    if svc is None:
        raise HTTPException(404, f"Ingen tjänst med namnet '{name}' är registrerad.")
    return _with_status(svc, scan_listening_ports())


@router.post("/services", status_code=201)
def create_service(body: ServiceIn):
    if not db.valid_slug(body.name):
        raise HTTPException(
            400, "Ogiltigt namn: använd bara små bokstäver a-z, siffror och bindestreck."
        )
    if body.port is None:
        if not (body.docs_path or body.docs_md):
            raise HTTPException(
                400,
                "Registrering utan port kräver dokumentation: "
                "ange docs_path eller docs_md.",
            )
    else:
        _validate_port(body.port)
    if db.get_service(body.name) is not None:
        raise HTTPException(409, f"Namnet '{body.name}' är redan registrerat.")
    if body.port is not None:
        existing = db.get_service_by_port(body.port)
        if existing is not None:
            raise HTTPException(
                409,
                f"Port {body.port} är redan registrerad av tjänsten '{existing['name']}'.",
            )
    try:
        svc = db.create_service(body.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Namn eller port är redan registrerat.")
    write_ledger()
    return _with_status(svc, scan_listening_ports())


@router.patch("/services/{name}")
def update_service(name: str, body: ServicePatch):
    if db.get_service(name) is None:
        raise HTTPException(404, f"Ingen tjänst med namnet '{name}' är registrerad.")
    fields = body.model_dump(exclude_unset=True)
    if "port" in fields and fields["port"] is not None:
        _validate_port(fields["port"])
        other = db.get_service_by_port(fields["port"])
        if other is not None and other["name"] != name:
            raise HTTPException(
                409, f"Port {fields['port']} är redan registrerad av '{other['name']}'."
            )
    try:
        svc = db.update_service(name, fields)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Uppdateringen krockar med en befintlig tjänst.")
    write_ledger()
    return _with_status(svc, scan_listening_ports())


@router.delete("/services/{name}")
def delete_service(name: str):
    if not db.delete_service(name):
        raise HTTPException(404, f"Ingen tjänst med namnet '{name}' är registrerad.")
    write_ledger()
    return {"status": "borttagen", "name": name}


@router.get("/ports")
def list_ports():
    listening = scan_listening_ports()
    services = db.list_services()
    by_port = {s["port"]: s for s in services}
    ports = []
    for port in sorted(listening):
        entry = listening[port]
        svc = by_port.get(port)
        ports.append({
            "port": port,
            "pids": entry["pids"],
            "processes": entry["processes"],
            "registered": svc is not None,
            "service": svc["name"] if svc else None,
            "project": svc["project"] if svc else None,
        })
    return {
        "listening": ports,
        "services": [_with_status(s, listening) for s in services],
    }


@router.post("/ports/reserve")
def reserve_port(body: ReserveIn | None = None):
    body = body or ReserveIn()
    if body.range_start > body.range_end:
        raise HTTPException(400, "Ogiltigt intervall: range_start är större än range_end.")
    port = find_free_port(body.range_start, body.range_end, body.note)
    if port is None:
        raise HTTPException(
            409, f"Ingen ledig port i intervallet {body.range_start}-{body.range_end}."
        )
    return {"port": port}


def _safe_filename(name: str) -> str:
    """Plockar ut ett rent basnamn (ingen sökväg, inga separatorer)."""
    name = os.path.basename((name or "").replace("\\", "/").strip())
    if not name or name in (".", ".."):
        return ""
    return name


def _share_out(share: dict) -> dict:
    out = dict(share)
    out["url"] = f"{PORTAL_BASE_URL}/share/{share['uid']}/{quote(share['filename'])}"
    return out


@router.get("/shares")
def list_shares():
    return [_share_out(s) for s in db.list_shares()]


@router.post("/shares", status_code=201)
def create_share(body: ShareIn):
    filename = _safe_filename(body.filename)
    if not filename:
        raise HTTPException(400, "Ogiltigt filnamn.")
    try:
        content = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "content_b64 är inte giltig base64.")
    if not content:
        raise HTTPException(400, "Filen är tom.")
    if len(content) > SHARE_MAX_BYTES:
        raise HTTPException(
            413, f"Filen är för stor (max {SHARE_MAX_BYTES // (1024 * 1024)} MB)."
        )
    content_type = body.content_type or mimetypes.guess_type(filename)[0]
    for _ in range(5):
        uid = secrets.token_hex(6)
        try:
            share = db.create_share(
                uid, filename, content, content_type,
                body.description, body.ttl_minutes,
            )
            return _share_out(share)
        except sqlite3.IntegrityError:
            continue
    raise HTTPException(500, "Kunde inte skapa ett unikt delnings-id, försök igen.")


@router.delete("/shares/{uid}")
def delete_share(uid: str):
    if not db.delete_share(uid):
        raise HTTPException(404, f"Ingen delning med id '{uid}' finns.")
    return {"status": "borttagen", "uid": uid}


def _theme_out(theme: dict) -> dict:
    out = dict(theme)
    out["spec"] = json.loads(theme["spec"])
    out["tokens_url"] = f"{PORTAL_BASE_URL}/api/themes/{quote(theme['name'])}/tokens.css"
    return out


@router.get("/themes")
def list_themes():
    return [_theme_out(t) for t in db.list_themes()]


@router.post("/themes")
def create_theme(body: ThemeIn):
    if not db.valid_slug(body.name):
        raise HTTPException(
            400, "Ogiltigt namn: använd bara små bokstäver a-z, siffror och bindestreck."
        )
    if not body.tokens_css:
        raise HTTPException(400, "tokens_css saknas.")
    if len(body.tokens_css.encode("utf-8")) > THEME_MAX_BYTES:
        raise HTTPException(
            413, f"tokens_css är för stor (max {THEME_MAX_BYTES // 1024} KB)."
        )
    theme = db.upsert_theme(body.name, json.dumps(body.spec), body.tokens_css)
    return _theme_out(theme)


@router.get("/themes/{name}")
def get_theme(name: str):
    theme = db.get_theme(name)
    if theme is None:
        raise HTTPException(404, f"Inget tema med namnet '{name}' finns.")
    return _theme_out(theme)


@router.get("/themes/{name}/tokens.css")
def get_theme_tokens_css(name: str):
    theme = db.get_theme(name)
    if theme is None:
        raise HTTPException(404, f"Inget tema med namnet '{name}' finns.")
    return Response(content=theme["tokens_css"], media_type="text/css")


@router.delete("/themes/{name}")
def delete_theme(name: str):
    if not db.delete_theme(name):
        raise HTTPException(404, f"Inget tema med namnet '{name}' finns.")
    return {"status": "borttagen", "name": name}
