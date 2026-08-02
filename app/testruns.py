"""Testsessioner: beta av en lista testpunkter i ett UI i stället för i chatten.

PROTOTYP (TASK-803 i infra). Portalen äger sessionen medan testningen pågår -
backlog är fel gränssnitt för att utföra testning, men rätt ställe för
spårbarhet efteråt. Punkterna skickas in explicit av den som skapar sessionen;
portalen parsar aldrig taskbeskrivningar på egen hand, eftersom en numrerad
lista i en beskrivning lika gärna kan vara utredningspunkter eller ett
verifieringsprotokoll.
"""

import re
import sqlite3
from datetime import datetime, timezone

from app.database import get_conn

STATUSES = ("otestad", "ok", "fel", "hoppad")

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
    numrerade punkt eller nästa rubrik hör till samma punkt.
    """
    items: list[dict] = []
    heading = None
    current: dict | None = None

    for line in text.splitlines():
        h = re.match(r"^##\s+(.*)$", line)
        if h:
            current = None
            heading = h.group(1).strip()
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            current = {"heading": heading, "body": m.group(2).strip()}
            items.append(current)
            continue
        if current is not None and line.strip():
            current["body"] += " " + line.strip()

    return items


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
