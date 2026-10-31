"""Modelljobb: förlopp, beräknad sluttid och previews för körningar mot modeller.

Klienten skickar hela sitt läge som en ögonblicksbild (`spara`), nyckad på ett
uuid den själv skapat. Senaste skrivning vinner, så klienten kan strypa fritt.
Portalen stämplar mottagningstiden själv och flyttar klientens tider med
skillnaden mellan klockorna, så en maskin med fel klocka ger ändå rätt takt.

Jobb mot en endpoint i ollama-växlaren tar och förlänger växlarens rådgivande
anspråk vid varje rapport, och släpper det när jobbet blir klart. Det sker här
och inte i klienten, så varje klient får anspråken gratis.
"""

import json
import logging
import re
import shutil
import sqlite3
import time

from app import config, modelljobb_notis, ollama
from app.database import _ensure_column, get_conn

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS modelljobb (
    uuid TEXT PRIMARY KEY,
    beskrivning TEXT NOT NULL,
    projekt TEXT,
    agare TEXT,
    endpoint TEXT,
    host TEXT,
    pid INTEGER,
    version TEXT,
    start REAL NOT NULL,
    senast REAL NOT NULL,
    klar INTEGER NOT NULL DEFAULT 0,
    spar TEXT NOT NULL,
    fel TEXT NOT NULL,
    aktuell TEXT,
    tog_ansprak INTEGER NOT NULL DEFAULT 0,
    ansprak_konflikt TEXT,
    prompt TEXT,
    notis INTEGER NOT NULL DEFAULT 1,
    notis_lage TEXT
);

CREATE TABLE IF NOT EXISTS modelljobb_preview (
    id INTEGER PRIMARY KEY,
    jobb TEXT NOT NULL,
    spar TEXT NOT NULL,
    rubrik TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'text',
    indata_text TEXT,
    indata_bild TEXT,
    svar_text TEXT,
    svar_bild TEXT,
    jamfor INTEGER NOT NULL DEFAULT 0,
    skapad REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS modelljobb_preview_jobb ON modelljobb_preview (jobb, spar);
"""

# Klientmodulen som projekten hämtar via /api/modelljobb/klient.py.
KLIENT = config.BASE_DIR / "cli" / "modelljobb.py"

# Hur länge ett anspråk räcker per rapport. Nästa rapport förlänger det, och
# ett kraschat jobb släpper det av sig själv.
ANSPRAK_MINUTER = 30

# Löpande previews per spår. Jämförelsepreviews har ett eget, större tak och
# trängs aldrig undan av de löpande: spåren körs efter varandra, så annars
# hinner första modellens svar försvinna innan nästa modell når samma rubrik.
MAX_LOPANDE = 12
MAX_JAMFOR = 30

TEXT_MAX = 4000
PROMPT_MAX = 20000

# En preview har två delar, och båda kan vara text och/eller bild. Så passar
# samma vy både bildtolkning (bild in, text ut), textjobb (text in, text ut)
# och bildgenerering (text in, bild ut).
DELAR = ("indata", "svar")
FORMAT = ("text", "json")
BILD_MAX_BYTES = 200 * 1024

# Ett jobb som inte hörts av på så här länge räknas som övergivet.
OVERGIVET_SEKUNDER = 6 * 3600

TYST_MIN = 120

_BILDTYPER = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


class JobbFel(ValueError):
    """Ogiltig indata från klienten."""


def init_schema() -> None:
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
        # Kolumner som kom till efter första versionen.
        _ensure_column(conn, "modelljobb", "notis", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "modelljobb", "notis_lage", "TEXT")
        conn.commit()
    finally:
        conn.close()


def validera_uuid(uuid: str) -> str:
    if not _UUID_RE.match(uuid or ""):
        raise JobbFel("Jobb-id får bara innehålla bokstäver, siffror och bindestreck (8-64 tecken).")
    return uuid


def _katalog(uuid: str):
    return config.MODELLJOBB_DIR / uuid


def _endpointnamn(endpoint: str | None) -> str | None:
    """Namnet i växlaren för en endpoint som anges som namn eller URL."""
    if not endpoint:
        return None
    endpoints = ollama.list_endpoints()
    for e in endpoints:
        if e["name"] == endpoint:
            return e["name"]
    try:
        url = ollama.normalize_url(endpoint)
    except ollama.OllamaError:
        return None
    return next((e["name"] for e in endpoints if e["url"] == url), None)


def _forlang_ansprak(namn: str, agare: str, notis: str) -> bool:
    """Tar eller förlänger anspråket, men kortar aldrig ett längre eget.

    Svarar True när det inte fanns något eget anspråk innan, alltså när
    jobbet självt tog det.
    """
    befintligt = ollama.las_ansprak(namn)
    eget = bool(befintligt and befintligt["agare"] == agare)
    minuter = max(ANSPRAK_MINUTER, befintligt["minuter_kvar"]) if eget else ANSPRAK_MINUTER
    ollama.gor_ansprak(namn, agare, minuter, notis)
    return not eget


def _hantera_ansprak(data: dict, tidigare: sqlite3.Row | None) -> tuple[bool, str | None]:
    """Returnerar (tog_ansprak, konflikt) för jobbraden."""
    tog = bool(tidigare["tog_ansprak"]) if tidigare else False
    namn = _endpointnamn(data["endpoint"])
    agare = data["agare"]
    if not namn or not agare:
        return tog, None
    if data["klar"]:
        # Släpp bara ett anspråk jobbet självt tog. Sessionen kan ha ett eget
        # som ska leva vidare efter det här jobbet.
        if tog:
            try:
                ollama.slapp_ansprak(namn, agare)
            except ollama.AnsprakUpptaget as exc:
                # Någon annan har tagit över, och då är det inte vårt att släppa.
                logger.info("Släppte inte anspråket på %s: %s", namn, exc)
        return False, None
    try:
        tog_nu = _forlang_ansprak(namn, agare, data["beskrivning"])
    except ollama.AnsprakUpptaget as exc:
        return tog, str(exc)
    return tog or tog_nu, None


def spara(uuid: str, data: dict) -> dict:
    """Sparar klientens ögonblicksbild. `data` är redan schemavaliderad."""
    uuid = validera_uuid(uuid)
    nu = time.time()
    # Klientens klocka kan gå fel. Med dess sändtid flyttas alla tider till
    # portalens klocka. Utan sändtid litar portalen på klienten.
    skift = nu - data["skickad"] if data.get("skickad") else 0.0

    def flytta(t):
        return t + skift if t is not None else None

    spar = []
    for s in data["spar"]:
        spar.append({**s, "start": flytta(s.get("start")), "slut": flytta(s.get("slut"))})
    fel = [{**f, "tid": flytta(f.get("tid")) or nu} for f in data["fel"][-20:]]

    with get_conn() as conn:
        tidigare = conn.execute("SELECT * FROM modelljobb WHERE uuid = ?", (uuid,)).fetchone()
        start = flytta(data.get("start")) or (tidigare["start"] if tidigare else nu)
        tog, konflikt = _hantera_ansprak(data, tidigare)
        conn.execute(
            """INSERT INTO modelljobb (uuid, beskrivning, projekt, agare, endpoint, host,
                   pid, version, start, senast, klar, spar, fel, aktuell, tog_ansprak,
                   ansprak_konflikt, prompt, notis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   beskrivning = excluded.beskrivning, projekt = excluded.projekt,
                   agare = excluded.agare, endpoint = excluded.endpoint,
                   host = excluded.host, pid = excluded.pid, version = excluded.version,
                   start = excluded.start, senast = excluded.senast, klar = excluded.klar,
                   spar = excluded.spar, fel = excluded.fel, aktuell = excluded.aktuell,
                   tog_ansprak = excluded.tog_ansprak,
                   ansprak_konflikt = excluded.ansprak_konflikt,
                   prompt = excluded.prompt, notis = excluded.notis""",
            (
                uuid, data["beskrivning"], data.get("projekt"), data.get("agare"),
                data.get("endpoint"), data.get("host"), data.get("pid"), data.get("version"),
                start, nu, int(data["klar"]), json.dumps(spar, ensure_ascii=False),
                json.dumps(fel, ensure_ascii=False),
                json.dumps(data.get("aktuell"), ensure_ascii=False) if data.get("aktuell") else None,
                int(tog), konflikt, data.get("prompt"), int(data.get("notis", True)),
            ),
        )
    jobb = hamta(uuid)
    modelljobb_notis.efter_rapport(jobb, var_klar=bool(tidigare and tidigare["klar"]))
    return jobb


def _berakna_spar(s: dict, nu: float) -> dict:
    """Förlopp, takt och tid kvar för ett spår. Samma logik som storstil_status."""
    klara, totalt, fran = s["klara"], s.get("totalt"), s.get("fran") or 0
    start, slut = s.get("start"), s.get("slut")
    gjorda = klara - fran
    tid = ((slut or nu) - start) if start else 0
    per_enhet = round(tid / gjorda, 1) if gjorda > 0 and tid > 0 else None
    kvar = None
    if per_enhet and totalt is not None and not slut:
        kvar = round(max(0, totalt - klara) * per_enhet)
    lage = "klar" if slut else "pågår" if start else "väntar"
    procent = None
    if totalt:
        procent = min(100, round(100 * klara / totalt))
    elif totalt == 0:
        procent = 100
    return {**s, "procent": procent, "per_enhet": per_enhet, "kvar_sekunder": kvar, "lage": lage}


def _previews(conn: sqlite3.Connection, uuid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM modelljobb_preview WHERE jobb = ? ORDER BY skapad DESC, id DESC",
        (uuid,),
    ).fetchall()
    def bild(r, del_):
        if not r[f"{del_}_bild"]:
            return None
        return f"/api/modelljobb/{uuid}/preview/{r['id']}/{del_}"

    return [
        {
            "id": r["id"],
            "spar": r["spar"],
            "rubrik": r["rubrik"],
            "format": r["format"],
            "jamfor": bool(r["jamfor"]),
            "skapad": r["skapad"],
            **{d: {"text": r[f"{d}_text"], "bild": bild(r, d)} for d in DELAR},
        }
        for r in rows
    ]


def _berakna(row: sqlite3.Row, conn: sqlite3.Connection, nu: float) -> dict:
    spar = [_berakna_spar(s, nu) for s in json.loads(row["spar"])]
    klar = bool(row["klar"])
    sedan = round(nu - row["senast"])

    # Sluttid för hela jobbet bara när varje återstående spår har en takt.
    # Ett spår som inte startat har ingen, och då gissar sidan inte.
    kvar = 0
    for s in spar:
        if s["lage"] == "klar":
            continue
        if s["kvar_sekunder"] is None:
            kvar = None
            break
        kvar += s["kvar_sekunder"]

    takter = [s["per_enhet"] for s in spar if s["per_enhet"]]
    grans = max(TYST_MIN, 3 * max(takter)) if takter else TYST_MIN
    overgivet = not klar and sedan > OVERGIVET_SEKUNDER
    return {
        "uuid": row["uuid"],
        "beskrivning": row["beskrivning"],
        "projekt": row["projekt"],
        "agare": row["agare"],
        "endpoint": row["endpoint"],
        "endpointnamn": _endpointnamn(row["endpoint"]),
        "host": row["host"],
        "pid": row["pid"],
        "version": row["version"],
        "start": row["start"],
        "senast": row["senast"],
        "sedan": sedan,
        "tid": round((row["senast"] if klar else nu) - row["start"]),
        "klar": klar,
        "overgivet": overgivet,
        "tyst": not klar and not overgivet and sedan > grans,
        "tyst_grans": round(grans),
        "kvar_sekunder": None if klar else kvar,
        "spar": spar,
        "fel": json.loads(row["fel"]),
        "aktuell": json.loads(row["aktuell"]) if row["aktuell"] else None,
        "tog_ansprak": bool(row["tog_ansprak"]),
        "ansprak_konflikt": row["ansprak_konflikt"],
        "prompt": row["prompt"],
        "notis": bool(row["notis"]),
        "notis_lage": row["notis_lage"],
        "previews": _previews(conn, row["uuid"]),
    }


def hamta(uuid: str) -> dict | None:
    validera_uuid(uuid)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM modelljobb WHERE uuid = ?", (uuid,)).fetchone()
        return _berakna(row, conn, time.time()) if row else None


def lista() -> dict:
    """Pågående jobb och de som avslutats eller övergetts, nyast först."""
    stada()
    nu = time.time()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM modelljobb ORDER BY start DESC").fetchall()
        jobb = [_berakna(r, conn, nu) for r in rows]
    pagaende = [j for j in jobb if not j["klar"] and not j["overgivet"]]
    avslutade = [j for j in jobb if j["klar"] or j["overgivet"]]
    avslutade.sort(key=lambda j: j["senast"], reverse=True)
    return {"pagaende": pagaende, "avslutade": avslutade}


def ta_bort(uuid: str) -> bool:
    validera_uuid(uuid)
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM modelljobb WHERE uuid = ?", (uuid,))
        conn.execute("DELETE FROM modelljobb_preview WHERE jobb = ?", (uuid,))
    shutil.rmtree(_katalog(uuid), ignore_errors=True)
    return cur.rowcount > 0


def stada() -> int:
    """Tar bort jobb som inte hörts av på TTL-tiden, med previews och bilder."""
    grans = time.time() - config.MODELLJOBB_TTL_DAGAR * 86400
    with get_conn() as conn:
        gamla = [r["uuid"] for r in conn.execute(
            "SELECT uuid FROM modelljobb WHERE senast < ?", (grans,)
        ).fetchall()]
    for uuid in gamla:
        ta_bort(uuid)
    return len(gamla)


def _bildtyp(data: bytes) -> tuple[str, str]:
    """Typen ur filens magiska bytes. Klientens påstådda typ litar vi inte på."""
    for magi, typ, andelse in _BILDTYPER:
        if data.startswith(magi):
            return typ, andelse
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise JobbFel("Bilden måste vara JPEG, PNG eller WebP.")


def lagg_till_preview(uuid: str, spar: str, rubrik: str, delar: dict,
                      format: str = "text", jamfor: bool = False) -> dict:
    """`delar` är {"indata"|"svar": {"text": str|None, "bild": bytes|None}}."""
    validera_uuid(uuid)
    if format not in FORMAT:
        raise JobbFel(f"Formatet måste vara ett av: {', '.join(FORMAT)}.")
    bilder = {}
    for del_ in DELAR:
        bild = (delar.get(del_) or {}).get("bild")
        if bild is None:
            continue
        if len(bild) > BILD_MAX_BYTES:
            raise JobbFel(f"Bilden är för stor (max {BILD_MAX_BYTES // 1024} kB). Skala ner den först.")
        bilder[del_] = (bild, _bildtyp(bild)[1])
    texter = [((delar.get(d) or {}).get("text") or "")[:TEXT_MAX] or None for d in DELAR]
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM modelljobb WHERE uuid = ?", (uuid,)).fetchone():
            raise LookupError(uuid)
        cur = conn.execute(
            "INSERT INTO modelljobb_preview (jobb, spar, rubrik, format, indata_text, svar_text,"
            " jamfor, skapad) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid, spar, rubrik, format, *texter, int(jamfor), time.time()),
        )
        pid = cur.lastrowid
        for del_, (bild, andelse) in bilder.items():
            filnamn = f"{pid}-{del_}.{andelse}"
            _katalog(uuid).mkdir(parents=True, exist_ok=True)
            (_katalog(uuid) / filnamn).write_bytes(bild)
            conn.execute(f"UPDATE modelljobb_preview SET {del_}_bild = ? WHERE id = ?", (filnamn, pid))
        _trimma(conn, uuid, spar, jamfor, MAX_JAMFOR if jamfor else MAX_LOPANDE)
    return {"id": pid}


def _trimma(conn: sqlite3.Connection, uuid: str, spar: str, jamfor: bool, tak: int) -> None:
    overflodiga = conn.execute(
        "SELECT id, indata_bild, svar_bild FROM modelljobb_preview"
        " WHERE jobb = ? AND spar = ? AND jamfor = ?"
        " ORDER BY skapad DESC, id DESC LIMIT -1 OFFSET ?",
        (uuid, spar, int(jamfor), tak),
    ).fetchall()
    for r in overflodiga:
        conn.execute("DELETE FROM modelljobb_preview WHERE id = ?", (r["id"],))
        for filnamn in (r["indata_bild"], r["svar_bild"]):
            if filnamn:
                (_katalog(uuid) / filnamn).unlink(missing_ok=True)


def preview_bild(uuid: str, preview_id: int, del_: str) -> tuple[bytes, str] | None:
    validera_uuid(uuid)
    if del_ not in DELAR:
        return None
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {del_}_bild AS bild FROM modelljobb_preview WHERE id = ? AND jobb = ?",
            (preview_id, uuid),
        ).fetchone()
    if not row or not row["bild"]:
        return None
    try:
        data = (_katalog(uuid) / row["bild"]).read_bytes()
    except OSError:
        return None
    return data, _bildtyp(data)[0]
