"""JSON-API för tjänsteregistret och portverktyget."""

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import database as db
from app.config import PORT_RANGE_END, PORT_RANGE_START, PORTAL_PORT, SERVICE_HOST
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
