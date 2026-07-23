"""Portlogik: skanna lyssnande portar via ss, hitta ledig port, statusbedömning."""

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

from app.config import PORT_RANGE_END, PORT_RANGE_START, RESERVATION_TTL_MINUTES
from app.database import (
    delete_dead_ephemeral_candidate, get_conn, list_services, now_iso,
)

_PROC_RE = re.compile(r'\("([^"]+)",pid=(\d+)')


class _ListeningPorts(dict):
    """Portresultat med signal om ss-scanningen var tillförlitlig."""

    def __init__(self, *args, reliable: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.reliable = reliable


def scan_listening_ports() -> dict[int, dict]:
    """Returnerar {port: {"port", "pids": [..], "processes": [..]}} från ss -tlnp.

    PID/processnamn kan saknas för processer som ägs av andra användare -
    då blir listorna tomma. IPv4/IPv6-dubbletter slås ihop.
    """
    try:
        completed = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return _ListeningPorts(reliable=False)
    if completed.returncode != 0:
        return _ListeningPorts(reliable=False)

    result: dict[int, dict] = _ListeningPorts()
    out = completed.stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != "LISTEN":
            continue
        local = parts[3]
        port_str = local.rsplit(":", 1)[-1]
        if not port_str.isdigit():
            continue
        port = int(port_str)
        entry = result.setdefault(port, {"port": port, "pids": [], "processes": []})
        for proc, pid in _PROC_RE.findall(line):
            pid = int(pid)
            if pid not in entry["pids"]:
                entry["pids"].append(pid)
            if proc not in entry["processes"]:
                entry["processes"].append(proc)
    return result


def _clean_reservations(conn) -> None:
    """Tar bort reservationer äldre än TTL."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RESERVATION_TTL_MINUTES)
    rows = conn.execute("SELECT port, reserved_at FROM reservations").fetchall()
    for row in rows:
        try:
            reserved = datetime.fromisoformat(row["reserved_at"])
            if reserved.tzinfo is None:
                reserved = reserved.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            reserved = None
        if reserved is None or reserved < cutoff:
            conn.execute("DELETE FROM reservations WHERE port = ?", (row["port"],))


def active_reservations() -> list[dict]:
    conn = get_conn()
    try:
        _clean_reservations(conn)
        conn.commit()
        rows = conn.execute("SELECT * FROM reservations ORDER BY port").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_free_port(
    range_start: int = PORT_RANGE_START,
    range_end: int = PORT_RANGE_END,
    note: str | None = None,
) -> int | None:
    """Lägsta port i intervallet som varken lyssnar live, är registrerad
    eller har aktiv reservation. Skapar en reservation för porten.
    Returnerar None om ingen port är ledig."""
    listening = set(scan_listening_ports())
    conn = get_conn()
    try:
        _clean_reservations(conn)
        registered = {
            row["port"] for row in conn.execute("SELECT port FROM services")
        }
        reserved = {
            row["port"] for row in conn.execute("SELECT port FROM reservations")
        }
        for port in range(range_start, range_end + 1):
            if port in listening or port in registered or port in reserved:
                continue
            conn.execute(
                "INSERT INTO reservations (port, note, reserved_at) VALUES (?, ?, ?)",
                (port, note, now_iso()),
            )
            conn.commit()
            return port
        conn.commit()
        return None
    finally:
        conn.close()


def _pid_is_alive(pid: int | None) -> bool:
    """Returnerar True när PID lever eller inte kan kontrolleras säkert."""
    if pid is None or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clean_dead_ephemeral_services(
    listening: dict[int, dict] | None = None,
) -> list[str]:
    """Tar bort döda efemära poster och skriver om liggaren vid ändring."""
    listening = scan_listening_ports() if listening is None else listening
    if not getattr(listening, "reliable", True):
        return []
    removed = []
    for service in list_services():
        port = service.get("port")
        if (
            service.get("kind") == "ephemeral"
            and port is not None
            and port not in listening
            and not _pid_is_alive(service.get("pid"))
            and delete_dead_ephemeral_candidate(
                service["name"], port, service["pid"]
            )
        ):
            removed.append(service["name"])
    if removed:
        from app.ledger import write_ledger
        write_ledger()
    return removed


def service_status(
    service: dict,
    listening: dict[int, dict],
    supervisor_status: str | None = None,
) -> str:
    """Kombinerar supervisor-, port- och PID-status.

    'docs' om en efemär post saknar port,
    'up' om porten lyssnar och PID okänd eller matchar,
    'conflict' om porten lyssnar med annan känd PID än den registrerade,
    'down' om inget lyssnar på porten."""
    port = service.get("port")
    entry = listening.get(port) if port is not None else None
    if service.get("kind") == "systemd":
        state = supervisor_status or "unknown"
        if state == "active":
            return "up" if port is None or entry is not None else "drift"
        if state == "activating":
            return "starting"
        if state == "deactivating":
            return "stopping"
        if state in {"inactive", "failed"}:
            return "drift" if entry is not None else "down"
        return "unknown"

    if port is None:
        return "docs"
    if entry is None:
        return "down"
    pids = entry.get("pids") or []
    if service.get("pid") is None or not pids or service["pid"] in pids:
        return "up"
    return "conflict"
