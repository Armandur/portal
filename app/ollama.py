"""Ollama-endpoints: vilken LLM-server projekten ska prata med.

Portalen äger valet. Klienter frågar `GET /api/ollama/active` och får en
bas-URL tillbaka, så en flytt mellan TERVO2 och en annan maskin inte kräver
att varje projekt redigeras.

Läsvägen är en ren databasuppslagning utan nätverksanrop. Varje LLM-anrop i
varje projekt passerar den, så den får inte betala för en hälsokoll.
Livskontrollen ligger i `probe()`, som bara kortet anropar.
"""

import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from app.database import get_conn

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

# Portalen seedar den här vid start, så den aldrig svarar utan aktiv
# endpoint. TERVO2 gällde innan växlaren fanns.
_SEED = ("tervo2", "http://192.168.1.2:11434", "Unraid-servern, RTX 2080 Ti")

PROBE_TIMEOUT = 2.0


class OllamaError(ValueError):
    """Ogiltig indata från användare eller API-klient."""


class OkandEndpoint(OllamaError):
    """Namnet finns inte i registret."""


class AnsprakUpptaget(OllamaError):
    """Någon annan har ett levande anspråk."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


MAX_ANSPRAK_MINUTER = 24 * 60


def _ansprak(row: sqlite3.Row) -> dict | None:
    """Aktivt anspråk, eller None om det saknas eller gått ut.

    Anspråket är rådgivande, precis som filanspråken i `arbetar`. Det hindrar
    ingen från att skicka jobb - det talar om att någon annan är igång, och
    upphör av sig självt så ett glömt anspråk inte låser maskinen för alltid.
    """
    if not row["claimed_by"] or not row["claimed_until"]:
        return None
    try:
        slut = datetime.fromisoformat(row["claimed_until"])
    except ValueError:
        return None
    kvar = (slut - datetime.now(timezone.utc)).total_seconds()
    if kvar <= 0:
        return None
    return {
        "agare": row["claimed_by"],
        "till": row["claimed_until"],
        "minuter_kvar": round(kvar / 60),
        "notis": row["claim_note"],
    }


def _row(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "url": row["url"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "stopgap": bool(row["stopgap"]),
        "ansprak": _ansprak(row),
    }


def normalize_url(url: str) -> str:
    """Validerar och trimmar en endpoint-URL.

    Funktionen klipper bort avslutande snedstreck. Klienterna sätter ihop
    `{url}/api/chat` och ska slippa gissa om basen redan har ett.
    """
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise OllamaError("Adressen måste börja med http:// eller https://")
    if len(url) > 300:
        raise OllamaError("Adressen är för lång.")
    return url


def validate_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise OllamaError(
            "Namnet får bara innehålla små bokstäver, siffror och bindestreck "
            "(max 32 tecken)."
        )
    return name


def ensure_seed() -> None:
    """Skapar default-endpointen om tabellen är tom. Idempotent."""
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM ollama_endpoints LIMIT 1").fetchone():
            return
        name, url, desc = _SEED
        now = _now()
        conn.execute(
            "INSERT INTO ollama_endpoints"
            " (name, url, description, is_active, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (name, url, desc, now, now),
        )


def list_endpoints() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ollama_endpoints ORDER BY is_active DESC, name"
        ).fetchall()
    return [_row(r) for r in rows]


def get_active() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ollama_endpoints WHERE is_active = 1 LIMIT 1"
        ).fetchone()
    return _row(row) if row else None


def set_active(name: str) -> dict | None:
    """Gör en endpoint aktiv. Returnerar None om namnet inte finns.

    Samma transaktion nollställer den gamla och sätter den nya. Ett avbrott
    kan därför aldrig lämna registret utan aktiv endpoint.
    """
    name = validate_name(name)
    with get_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM ollama_endpoints WHERE name = ?", (name,)
        ).fetchone():
            return None
        conn.execute("UPDATE ollama_endpoints SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "UPDATE ollama_endpoints SET is_active = 1, updated_at = ? WHERE name = ?",
            (_now(), name),
        )
    return get_active()


def add_endpoint(
    name: str, url: str, description: str | None = None, stopgap: bool = False
) -> dict:
    name = validate_name(name)
    url = normalize_url(url)
    now = _now()
    desc = (description or "").strip() or None
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO ollama_endpoints"
                " (name, url, description, is_active, stopgap, created_at, updated_at)"
                " VALUES (?, ?, ?, 0, ?, ?, ?)",
                (name, url, desc, int(stopgap), now, now),
            )
        except sqlite3.IntegrityError:
            conn.execute(
                "UPDATE ollama_endpoints SET url = ?, description = ?, stopgap = ?,"
                " updated_at = ? WHERE name = ?",
                (url, desc, int(stopgap), now, name),
            )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ollama_endpoints WHERE name = ?", (name,)
        ).fetchone()
    return _row(row)


def delete_endpoint(name: str) -> bool:
    """Tar bort en endpoint. Den aktiva går inte att ta bort."""
    name = validate_name(name)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_active FROM ollama_endpoints WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return False
        if row["is_active"]:
            raise OllamaError(
                "Den aktiva endpointen går inte att ta bort - växla till en "
                "annan först."
            )
        conn.execute("DELETE FROM ollama_endpoints WHERE name = ?", (name,))
    return True


def las_ansprak(name: str) -> dict | None:
    """Anspråket på en endpoint. Ren databasläsning, ingen nätverkstrafik.

    En session som frågar "är någon igång?" före varje batch ska inte betala
    en rundtur till ollama-värden för svaret.
    """
    name = validate_name(name)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ollama_endpoints WHERE name = ?", (name,)
        ).fetchone()
    if row is None:
        raise OkandEndpoint(f"Ingen endpoint med namnet '{name}' finns.")
    return _ansprak(row)


def gor_ansprak(name: str, agare: str, minuter: int, notis: str | None = None) -> dict:
    """Tar anspråk på en endpoint. Skriver över ett utgånget anspråk.

    Ett levande anspråk från någon annan avvisas - inte för att spärra
    maskinen, utan för att två sessioner som båda tror sig äga den är värre
    än en som får veta att den ska vänta.
    """
    name = validate_name(name)
    agare = (agare or "").strip()
    if not agare:
        raise OllamaError("Anspråket behöver en ägare - vem är det som kör?")
    if len(agare) > 80:
        raise OllamaError("Ägarnamnet är för långt (max 80 tecken).")
    if not 1 <= minuter <= MAX_ANSPRAK_MINUTER:
        raise OllamaError(
            f"Anspråket måste gälla mellan 1 och {MAX_ANSPRAK_MINUTER} minuter."
        )

    befintligt = las_ansprak(name)
    if befintligt and befintligt["agare"] != agare:
        raise AnsprakUpptaget(
            f"{befintligt['agare']} har anspråk på {name} i "
            f"{befintligt['minuter_kvar']} minuter till."
        )

    till = (datetime.now(timezone.utc) + timedelta(minutes=minuter)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE ollama_endpoints SET claimed_by = ?, claimed_until = ?,"
            " claim_note = ?, updated_at = ? WHERE name = ?",
            (agare, till, (notis or "").strip() or None, _now(), name),
        )
    return las_ansprak(name)


def slapp_ansprak(name: str, agare: str | None = None) -> bool:
    """Släpper anspråket. Med ägare angiven släpps bara det egna."""
    name = validate_name(name)
    befintligt = las_ansprak(name)
    if befintligt is None:
        return False
    if agare and befintligt["agare"] != agare:
        raise AnsprakUpptaget(
            f"Anspråket tillhör {befintligt['agare']}, inte {agare}."
        )
    with get_conn() as conn:
        conn.execute(
            "UPDATE ollama_endpoints SET claimed_by = NULL, claimed_until = NULL,"
            " claim_note = NULL, updated_at = ? WHERE name = ?",
            (_now(), name),
        )
    return True


def _hamta(url: str, timeout: float) -> dict | None:
    """GET som returnerar None i stället för att kasta när servern tiger."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _minuter_kvar(expires_at: str | None) -> int | None:
    """Minuter tills keep-alive lastar ur modellen.

    Ollama svarar med sin egen lokala tid plus offset, så jämförelsen sker i
    UTC. Ett oläsbart värde ger None i stället för att fälla hela probet.
    """
    if not expires_at:
        return None
    try:
        slut = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if slut.tzinfo is None:
        return None
    kvar = (slut - datetime.now(timezone.utc)).total_seconds()
    return max(0, round(kvar / 60))


def _laddade(ps: dict | None) -> list[dict]:
    rader = []
    for m in (ps or {}).get("models", []):
        storlek, i_vram = m.get("size") or 0, m.get("size_vram") or 0
        rader.append({
            "namn": m.get("name"),
            "storlek_gb": round(storlek / 1e9, 1) if storlek else None,
            "gpu_procent": round(i_vram / storlek * 100) if storlek else None,
            "context": m.get("context_length"),
            "minuter_kvar": _minuter_kvar(m.get("expires_at")),
        })
    return rader


def probe(url: str, timeout: float = PROBE_TIMEOUT) -> dict:
    """Frågar en endpoint om den lever, vad den har och vad som är laddat.

    Funktionen returnerar alltid en dict. En nedsläckt Windows-burk är ett
    väntat utfall här, inte ett fel att kasta uppåt.

    Modellistan avgör om servern lever. Svarar den inte hoppas de två andra
    anropen över, så en död endpoint kostar en timeout och inte tre.
    """
    tags = _hamta(f"{url}/api/tags", timeout)
    if tags is None:
        return {"up": False, "models": [], "laddade": [], "version": None}
    ps = _hamta(f"{url}/api/ps", timeout)
    version = (_hamta(f"{url}/api/version", timeout) or {}).get("version")
    return {
        "up": True,
        "models": [m["name"] for m in tags.get("models", []) if "name" in m],
        "laddade": _laddade(ps),
        "version": version,
    }
