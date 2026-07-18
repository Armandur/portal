"""Läsvy mot backlog-verktyget (mazen160/backlog).

Portalen äger inga todos - den läser dem read-only från backlog-CLI:t via
det stabila `--json`-gränssnittet (aldrig råa SQLite-tabeller, vars schema
migrerar). backlog självt äger all skrivning. En kort cache räcker: klienten
pollar var 30:e sekund och flera samtidiga besök ska inte spawna en process
var.
"""

import json
import subprocess
import time

from app.config import BACKLOG_BIN, BACKLOG_PROFILE, BACKLOG_WEB_BASE

# Prioritet lagras som heltal 1-5 i backlog; visa som P1-P5.
_OPEN_STATUSES = ("todo", "doing")

_cache: dict = {"at": 0.0, "data": None}
_CACHE_TTL = 15.0


def _run_list() -> list[dict]:
    """Kör `backlog task list --json` och returnerar rå task-lista.

    Kastar vid processfel eller trasig JSON - anroparen fångar och visar
    ett tydligt fel i stället för att krascha vyn.
    """
    proc = subprocess.run(
        [
            BACKLOG_BIN, "task", "list",
            "--json", "--profile", BACKLOG_PROFILE,
            "--sort", "priority", "--limit", "500",
        ],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"backlog avslutade med kod {proc.returncode}")
    return json.loads(proc.stdout).get("tasks", [])


def _shape(task: dict) -> dict:
    """Plockar ut de fält portalen visar och normaliserar formatet."""
    project = task.get("project") or {}
    actor = task.get("actor") or {}
    ref = f"TASK-{task['seq']}" if task.get("seq") is not None else task.get("id", "")
    return {
        "ref": ref,
        "title": task.get("title", ""),
        "description": task.get("description") or "",
        "priority": task.get("priority", 3),
        "status": task.get("status", "todo"),
        "type": task.get("type", "task"),
        "project": project.get("alias", "okänt"),
        "project_path": task.get("project_path") or "",
        "actor": f"{actor.get('kind', '')}:{actor.get('name', '')}".strip(":"),
        "web_url": f"{BACKLOG_WEB_BASE}/tasks/{ref}" if ref else BACKLOG_WEB_BASE,
    }


def _group(tasks: list[dict]) -> list[dict]:
    """Grupperar öppna tasks per projekt (bevarar prio-ordningen inom gruppen)."""
    groups: dict[str, list[dict]] = {}
    for task in tasks:
        if task.get("status") not in _OPEN_STATUSES:
            continue
        shaped = _shape(task)
        groups.setdefault(shaped["project"], []).append(shaped)
    return [
        {"project": alias, "todos": items}
        for alias, items in sorted(groups.items())
    ]


def open_todos() -> dict:
    """Returnerar öppna todos grupperade per projekt.

    Formen: {"available": bool, "error": str | None, "projects": [...]}.
    Alltid ett giltigt svar - fel fångas och rapporteras, aldrig en 500.
    """
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    try:
        projects = _group(_run_list())
        data = {"available": True, "error": None, "projects": projects}
    except FileNotFoundError:
        data = {"available": False, "error": "backlog-binären hittas inte", "projects": []}
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        data = {"available": False, "error": str(exc), "projects": []}

    _cache["at"] = now
    _cache["data"] = data
    return data
