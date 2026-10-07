"""JSON-API för ollama-växlaren.

Kontraktet klienterna lutar sig mot är `GET /api/ollama/active`, som svarar
`{"name": ..., "url": ...}`. Den vägen rör aldrig nätverket. Hälsokollen
ligger på `/api/ollama/endpoints?probe=1`, som bara portalens eget kort anropar.
"""

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import ollama

router = APIRouter(prefix="/api/ollama")


class EndpointIn(BaseModel):
    name: str
    url: str
    description: str | None = None
    stopgap: bool = False


class AnsprakIn(BaseModel):
    agare: str
    minuter: int = 60
    notis: str | None = None


class ActiveIn(BaseModel):
    name: str


@router.get("/active")
def active_endpoint():
    """Den endpoint projekten ska prata med just nu."""
    current = ollama.get_active()
    if current is None:
        raise HTTPException(503, "Ingen ollama-endpoint är aktiv i portalen.")
    return {"name": current["name"], "url": current["url"]}


@router.get("/endpoints")
def list_endpoints(probe: int = 0):
    """Alla registrerade endpoints. `probe=1` frågar var och en om den lever."""
    endpoints = ollama.list_endpoints()
    if not probe:
        return endpoints
    # Parallellt med flit: en nedsläckt maskin ska inte lägga sin timeout
    # ovanpå de andras väntan.
    with ThreadPoolExecutor(max_workers=max(1, len(endpoints))) as pool:
        results = list(pool.map(lambda e: ollama.probe(e["url"]), endpoints))
    return [{**e, **r} for e, r in zip(endpoints, results)]


@router.post("/active")
def set_active_endpoint(payload: ActiveIn):
    try:
        current = ollama.set_active(payload.name)
    except ollama.OllamaError as exc:
        raise HTTPException(400, str(exc)) from exc
    if current is None:
        raise HTTPException(404, f"Ingen endpoint med namnet '{payload.name}' finns.")
    return current


@router.post("/endpoints")
def add_endpoint(payload: EndpointIn):
    try:
        return ollama.add_endpoint(
            payload.name, payload.url, payload.description, payload.stopgap
        )
    except ollama.OllamaError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/endpoints/{name}/claim")
def las_ansprak(name: str):
    """Är någon igång på maskinen just nu? Ren DB-läsning, inget nätverk.

    Svarar `{"ansprak": null}` när ingen kör, så en pollande session kan
    fråga före varje batch utan att betala för det.
    """
    try:
        return {"name": name, "ansprak": ollama.las_ansprak(name)}
    except ollama.OkandEndpoint as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/endpoints/{name}/claim")
def gor_ansprak(name: str, payload: AnsprakIn):
    """Tar rådgivande anspråk på en endpoint. 409 om någon annan hunnit före."""
    try:
        ansprak = ollama.gor_ansprak(
            name, payload.agare, payload.minuter, payload.notis
        )
    except ollama.OkandEndpoint as exc:
        raise HTTPException(404, str(exc)) from exc
    except ollama.AnsprakUpptaget as exc:
        raise HTTPException(409, str(exc)) from exc
    except ollama.OllamaError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"name": name, "ansprak": ansprak}


@router.delete("/endpoints/{name}/claim")
def slapp_ansprak(name: str, agare: str | None = None):
    """Släpper anspråket. `?agare=` släpper bara om det är ens eget."""
    try:
        slapptes = ollama.slapp_ansprak(name, agare)
    except ollama.OkandEndpoint as exc:
        raise HTTPException(404, str(exc)) from exc
    except ollama.AnsprakUpptaget as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"name": name, "slapptes": slapptes, "ansprak": None}


@router.delete("/endpoints/{name}")
def delete_endpoint(name: str):
    try:
        removed = ollama.delete_endpoint(name)
    except ollama.OllamaError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not removed:
        raise HTTPException(404, f"Ingen endpoint med namnet '{name}' finns.")
    return {"status": "borttagen", "name": name}
