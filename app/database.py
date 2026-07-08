"""SQLite-lager: anslutning, schema och CRUD för tjänster och reservationer."""

import re
import sqlite3
from datetime import datetime, timezone

from app.config import DB_PATH

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    project TEXT NOT NULL,
    port INTEGER UNIQUE,
    pid INTEGER,
    description TEXT,
    url_path TEXT DEFAULT '/',
    docs_path TEXT,
    docs_md TEXT,
    started_by TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS reservations (
    port INTEGER PRIMARY KEY,
    note TEXT,
    reserved_at TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """ALTER TABLE-guard: lägg till kolumn om den saknas (migreringsmönster)."""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_port_nullable(conn: sqlite3.Connection) -> None:
    """Bygger om services-tabellen om port fortfarande har NOT NULL.

    SQLite kan inte droppa NOT NULL med ALTER TABLE, så tabellen byggs om:
    rename -> ny tabell från _SCHEMA -> kopiera rader -> droppa gamla.
    Idempotent: gör ingenting om port redan tillåter NULL.
    UNIQUE på port behålls (SQLite tillåter flera NULL i UNIQUE-kolumn).
    """
    info = conn.execute("PRAGMA table_info(services)").fetchall()
    port_col = next((r for r in info if r["name"] == "port"), None)
    if port_col is None or not port_col["notnull"]:
        return
    old_cols = {r["name"] for r in info}
    conn.execute("ALTER TABLE services RENAME TO services_old")
    conn.executescript(_SCHEMA)
    new_cols = {r["name"] for r in conn.execute("PRAGMA table_info(services)")}
    col_list = ", ".join(sorted(old_cols & new_cols))
    conn.execute(
        f"INSERT INTO services ({col_list}) SELECT {col_list} FROM services_old"
    )
    conn.execute("DROP TABLE services_old")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
        _migrate_port_nullable(conn)
        # Framtida migreringar läggs till här med _ensure_column(...), t.ex.:
        # _ensure_column(conn, "services", "tags", "TEXT")
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def valid_slug(name: str) -> bool:
    return bool(_SLUG_RE.match(name or ""))


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def list_services() -> list[dict]:
    conn = get_conn()
    try:
        # Portlösa dokumentationsposter sorteras sist
        rows = conn.execute(
            "SELECT * FROM services ORDER BY port IS NULL, port"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_service(name: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM services WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_service_by_port(port: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM services WHERE port = ?", (port,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_service(data: dict) -> dict:
    """Skapar en tjänst. Port kan vara None (dokumentationspost).
    Kastar sqlite3.IntegrityError vid namn-/portkrock."""
    ts = now_iso()
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO services
               (name, project, port, pid, description, url_path, docs_path,
                docs_md, started_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"], data["project"], data.get("port"), data.get("pid"),
                data.get("description"), data.get("url_path") or "/",
                data.get("docs_path"), data.get("docs_md"),
                data.get("started_by"), data.get("created_at") or ts, ts,
            ),
        )
        # En reservation på porten förbrukas när tjänsten registreras
        if data.get("port") is not None:
            conn.execute("DELETE FROM reservations WHERE port = ?", (data["port"],))
        conn.commit()
    finally:
        conn.close()
    return get_service(data["name"])


def update_service(name: str, fields: dict) -> dict | None:
    """Uppdaterar angivna fält. Returnerar tjänsten eller None om den saknas."""
    allowed = {"project", "port", "pid", "description", "url_path",
               "docs_path", "docs_md", "started_by"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_service(name)
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    try:
        cur = conn.execute(
            f"UPDATE services SET {set_clause} WHERE name = ?",
            (*updates.values(), name),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    finally:
        conn.close()
    return get_service(name)


def delete_service(name: str) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM services WHERE name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def upsert_service(data: dict) -> dict:
    """Skapa eller uppdatera tjänst med givet namn (används vid självregistrering)."""
    existing = get_service(data["name"])
    if existing:
        return update_service(data["name"], data)
    return create_service(data)
