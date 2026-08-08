"""Testsessioner: beta av en lista testpunkter i ett UI i stället för i chatten.

PROTOTYP (TASK-803 i infra). Portalen äger sessionen medan testningen pågår -
backlog är fel gränssnitt för att utföra testning, men rätt ställe för
spårbarhet efteråt. Punkterna skickas in explicit av den som skapar sessionen;
portalen parsar aldrig taskbeskrivningar på egen hand, eftersom en numrerad
lista i en beskrivning lika gärna kan vara utredningspunkter eller ett
verifieringsprotokoll.
"""

import html
import re
import subprocess
from datetime import datetime, timezone

from app.config import BACKLOG_BIN, BACKLOG_PROFILE, SERVICE_HOST, PORTAL_PORT
from app.database import get_conn

STATUSES = ("otestad", "ok", "fel", "hoppad")

# Kommentaren på tasken skrivs av portalen, inte av en agent eller en människa.
# Egen aktör så det syns i backlogs historik vem som faktiskt skrev raden.
BACKLOG_ACTOR = "ai:portal"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_sessions (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    task_ref TEXT,
    project TEXT,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS test_items (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES test_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    heading TEXT,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'otestad',
    note TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_test_items_session ON test_items(session_id, position);
"""


def init_schema() -> None:
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_items(text: str) -> list[dict]:
    """Plockar ut numrerade punkter ur markdown, grupperade under ##-rubriker.

    Punkter som löper över flera rader hålls ihop: allt fram till nästa
    numrerade punkt eller nästa rubrik hör till samma punkt. Raderna slås ihop
    till en, för en testpunkt är en mening - UTOM inuti ett kodblock med tre
    backticks, där radbrytningarna är själva poängen och behålls som de är.
    Inuti blocket tolkas ingen struktur: en rad som börjar med "1. " eller
    "## " är kod där, inte en ny punkt.
    """
    items: list[dict] = []
    heading = None
    current: dict | None = None
    # indraget på öppnande ```-rad, så blockets rader kan dras ut lika mycket
    # (i markdown är blocket indraget under punktnumret)
    fence_indent: int | None = None
    # texten efter ett block måste börja på ny rad - annars hamnar den efter
    # den avslutande ```-raden och blocket går inte längre att känna igen
    efter_block = False

    for line in text.splitlines():
        if fence_indent is not None:
            current["body"] += "\n" + _dedent(line, fence_indent)
            if line.strip().startswith("```"):
                fence_indent = None
                efter_block = True
            continue

        if current is not None and line.strip().startswith("```"):
            fence_indent = len(line) - len(line.lstrip())
            current["body"] += "\n" + line.strip()
            efter_block = False
            continue

        h = re.match(r"^##\s+(.*)$", line)
        if h:
            current = None
            heading = h.group(1).strip()
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            current = {"heading": heading, "body": m.group(2).strip()}
            items.append(current)
            efter_block = False
            continue
        if current is not None and line.strip():
            current["body"] += ("\n" if efter_block else " ") + line.strip()
            efter_block = False

    return items


def _dedent(line: str, indent: int) -> str:
    """Tar bort upp till `indent` inledande blanksteg - aldrig mer, så djupare
    indrag inuti blocket (en fortsättningsrad, en nästlad struktur) står kvar."""
    i = 0
    while i < indent and i < len(line) and line[i] == " ":
        i += 1
    return line[i:]


def create_session(
    slug: str, title: str, items: list[dict], task_ref=None, project=None
) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO test_sessions (slug, title, task_ref, project, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (slug, title, task_ref, project, _now()),
        )
        session_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO test_items (session_id, position, heading, body) "
            "VALUES (?, ?, ?, ?)",
            [
                (session_id, i, it.get("heading"), it["body"])
                for i, it in enumerate(items, start=1)
            ],
        )
        conn.commit()
        return session_id
    finally:
        conn.close()


def get_session(slug: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM test_sessions WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        session = dict(row)
        items = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM test_items WHERE session_id = ? ORDER BY position",
                (session["id"],),
            )
        ]
        session["items"] = items
        session["summary"] = summarize(items)
        return session
    finally:
        conn.close()


def summarize(items: list[dict]) -> dict:
    counts = {s: 0 for s in STATUSES}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    total = len(items)
    avklarat = total - counts["otestad"]
    return {
        **counts,
        "total": total,
        "avklarat": avklarat,
        "procent": round(avklarat * 100 / total) if total else 0,
    }


def set_status(slug: str, position: int, status: str, note: str | None) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"Okänd status: {status}")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM test_sessions WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE test_items SET status = ?, note = ?, updated_at = ? "
            "WHERE session_id = ? AND position = ?",
            (status, note or None, _now(), row["id"], position),
        )
        conn.commit()
    finally:
        conn.close()
    return get_session(slug)


def list_sessions() -> list[dict]:
    conn = get_conn()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM test_sessions ORDER BY created_at DESC"
            )
        ]
        for s in rows:
            items = [
                dict(r)
                for r in conn.execute(
                    "SELECT status FROM test_items WHERE session_id = ?", (s["id"],)
                )
            ]
            s["summary"] = summarize(items)
        return rows
    finally:
        conn.close()


def session_url(slug: str) -> str:
    return f"http://{SERVICE_HOST}:{PORTAL_PORT}/test/{slug}"


def _sammanfattning(session: dict) -> str:
    """Textrapport att lägga som kommentar på tasken när sessionen stängs."""
    s = session["summary"]
    rader = [
        f"Testomgång avklarad via portalen: {s['avklarat']}/{s['total']} punkter "
        f"({s['ok']} ok, {s['fel']} fel, {s['hoppad']} hoppade).",
        session_url(session["slug"]),
    ]

    for status, rubrik in (("fel", "FUNKAR INTE"), ("hoppad", "HOPPADE")):
        rader_status = [i for i in session["items"] if i["status"] == status]
        if not rader_status:
            continue
        rader.append("")
        rader.append(f"{rubrik}:")
        for i in rader_status:
            rad = f"{i['position']}. {i['body']}"
            if i["note"]:
                rad += f"\n   Kommentar: {i['note']}"
            rader.append(rad)

    kvar = [i for i in session["items"] if i["status"] == "otestad"]
    if kvar:
        nummer = ", ".join(str(i["position"]) for i in kvar[:20])
        if len(kvar) > 20:
            nummer += f" (och {len(kvar) - 20} till)"
        rader.append("")
        rader.append(f"Ej testade: {nummer}")

    # Kommentarer på godkända punkter är lätta att missa men ofta det som
    # blir nästa task - ta med dem separat.
    noterade = [i for i in session["items"] if i["status"] == "ok" and i["note"]]
    if noterade:
        rader.append("")
        rader.append("Kommentarer på godkända punkter:")
        for i in noterade:
            rader.append(f"{i['position']}. {i['note']}")

    return "\n".join(rader)


def close_session(slug: str, skriv_till_backlog: bool = True) -> dict | None:
    """Markerar sessionen som stängd och lägger sammanfattningen på tasken.

    Portalen äger inga todos - kommentaren skrivs via backlog-CLI:t, aldrig
    mot dess tabeller. Misslyckas skrivningen stängs sessionen ändå; texten
    returneras så anroparen kan lägga in den för hand.
    """
    session = get_session(slug)
    if session is None:
        return None

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE test_sessions SET closed_at = ? WHERE slug = ?", (_now(), slug)
        )
        conn.commit()
    finally:
        conn.close()

    text = _sammanfattning(session)
    resultat = {"slug": slug, "summary": session["summary"], "kommentar": text,
                "task_ref": session["task_ref"], "skriven_till_backlog": False}

    if not (skriv_till_backlog and session["task_ref"]):
        return resultat

    try:
        proc = subprocess.run(
            [BACKLOG_BIN, "--as", BACKLOG_ACTOR, "comment", "add", text,
             "--task", session["task_ref"], "--profile", BACKLOG_PROFILE],
            capture_output=True, text=True, timeout=20,
        )
        resultat["skriven_till_backlog"] = proc.returncode == 0
        if proc.returncode != 0:
            resultat["fel"] = (proc.stderr or proc.stdout).strip()[:500]
    except (OSError, subprocess.SubprocessError) as e:
        resultat["fel"] = str(e)
    return resultat


def delete_session(slug: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM test_sessions WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM test_items WHERE session_id = ?", (row["id"],))
        conn.execute("DELETE FROM test_sessions WHERE id = ?", (row["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


# Testpunkter innehåller ofta en adress man ska öppna eller ett kommando man
# ska köra. Texten escapas alltid, och bara de mönster som matchas här blir
# taggar - ingen HTML från den som skapar sessionen släpps igenom.
_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_CODE_RE = re.compile(r"`([^`\n]+)`")
# Block med tre backticks. Kräver avslutande rad - ett oavslutat block matchar
# inte och visas som tecken, i stället för att äta resten av punkten.
# Språktaggen (```sh) fångas och kastas: ingen syntaxfärgning här, punkterna
# ska kopieras och köras, inte läsas som kod.
_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)\n?^[ \t]*```[ \t]*$", re.M | re.S)


def _anchor(url: str, text: str) -> str:
    return (
        f'<a href="{html.escape(url, quote=True)}" target="_blank" '
        f'rel="noopener">{html.escape(text)}</a>'
    )


def linkify(text: str) -> str:
    """Escapar texten, gör http(s)-adresser klickbara och backticks till kod.

    Stöder både markdown-form, [öppna anmälan](http://...), och rena adresser.
    Segmenten mellan träffarna escapas, så < och & i brödtexten blir text och
    inte markup.

    Kodspann plockas ut FÖRST, så en adress inuti backticks blir kod och inte
    en länk - det är kommandot man ska kopiera, inte något att klicka på.
    Ordningen är block -> kodspann -> länkar, hela vägen ner.
    """
    ut: list[str] = []

    def skriv_med_bara_urler(segment: str) -> None:
        p = 0
        for m in _BARE_URL_RE.finditer(segment):
            ut.append(html.escape(segment[p:m.start()]))
            url = m.group(0).rstrip(".,;:!?")
            ut.append(_anchor(url, url))
            # skiljetecken som råkade följa med adressen hör till meningen
            ut.append(html.escape(m.group(0)[len(url):]))
            p = m.end()
        ut.append(html.escape(segment[p:]))

    def skriv_med_lankar(segment: str) -> None:
        pos = 0
        for m in _MD_LINK_RE.finditer(segment):
            skriv_med_bara_urler(segment[pos:m.start()])
            ut.append(_anchor(m.group(2), m.group(1)))
            pos = m.end()
        skriv_med_bara_urler(segment[pos:])

    def skriv_med_kodspann(segment: str) -> None:
        pos = 0
        for m in _CODE_RE.finditer(segment):
            skriv_med_lankar(segment[pos:m.start()])
            ut.append(f"<code>{html.escape(m.group(1))}</code>")
            pos = m.end()
        skriv_med_lankar(segment[pos:])

    pos = 0
    for m in _FENCE_RE.finditer(text):
        skriv_med_kodspann(text[pos:m.start()])
        ut.append(f"<pre><code>{html.escape(m.group(1))}</code></pre>")
        pos = m.end()
    skriv_med_kodspann(text[pos:])
    return "".join(ut)
