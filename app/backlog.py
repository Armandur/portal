"""Läsvy mot backlog-verktyget (mazen160/backlog).

Portalen äger inga todos - den läser dem read-only från backlog-CLI:t via
det stabila `--json`-gränssnittet (aldrig råa SQLite-tabeller, vars schema
migrerar). backlog självt äger all skrivning. Portalen visar bara en
kompakt överblick (antal öppna/pågående per projekt) länkad till backlogs
egen webb-UI, som är detaljvyn. En kort cache räcker: klienten pollar var
30:e sekund och flera samtidiga besök ska inte spawna en process var.
"""

import json
import subprocess
import threading
import time
import urllib.parse

from app.config import BACKLOG_BIN, BACKLOG_PROFILE, BACKLOG_WEB_BASE

_OPEN_STATUSES = ("todo", "doing")
_LIMIT = 500

_cache: dict = {"at": 0.0, "data": None}
_CACHE_TTL = 15.0
# list_todos är sync -> FastAPI-threadpool. Låset serialiserar cache-miss så
# bara en tråd startar backlog-CLI:t; övriga väntar och får det färska svaret.
_cache_lock = threading.Lock()


def _run_list() -> tuple[list[dict], bool]:
    """Hämtar öppna tasks (todo + doing) och returnerar (tasks, truncated).

    Filtrerar på status i CLI-anropet så klarmarkerade (done) aldrig hämtas -
    annars kunde de tränga ut öppna todos ur en olfiltrerad lista vid --limit.
    truncated=True om någon status-batch nådde gränsen (öppna todos kan då
    saknas och det ska signaleras, inte döljas bakom available=true).

    Kastar vid processfel eller trasig JSON - anroparen fångar och visar
    ett tydligt fel i stället för att krascha vyn.
    """
    tasks: list[dict] = []
    truncated = False
    # backlog task list tar ett --status-värde per anrop, så en batch per status.
    for status in _OPEN_STATUSES:
        proc = subprocess.run(
            [
                BACKLOG_BIN, "task", "list",
                "--json", "--profile", BACKLOG_PROFILE,
                "--status", status,
                "--sort", "priority", "--limit", str(_LIMIT),
            ],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"backlog avslutade med kod {proc.returncode}")
        payload = json.loads(proc.stdout)
        if not isinstance(payload, dict):
            raise RuntimeError("oväntat svar från backlog: JSON är inte ett objekt")
        batch = payload.get("tasks", [])
        tasks.extend(batch)
        if len(batch) >= _LIMIT:
            truncated = True
    return tasks, truncated


def _aggregate(tasks: list[dict]) -> list[dict]:
    """Räknar öppna/pågående todos per projekt, sorterat fallande på öppna."""
    counts: dict[str, dict[str, int]] = {}
    for task in tasks:
        if task.get("status") not in _OPEN_STATUSES:
            continue
        project = task.get("project") or {}
        alias = project.get("alias", "okänt")
        entry = counts.setdefault(alias, {"open": 0, "doing": 0})
        entry["open"] += 1
        if task.get("status") == "doing":
            entry["doing"] += 1
    projects = [
        {
            "project": alias,
            "open": c["open"],
            "doing": c["doing"],
            "url": f"{BACKLOG_WEB_BASE}/?project={urllib.parse.quote(alias)}",
        }
        for alias, c in counts.items()
    ]
    projects.sort(key=lambda p: (-p["open"], p["project"]))
    return projects


def open_todos() -> dict:
    """Returnerar en kompakt överblick av öppna todos per projekt.

    Formen: {"available": bool, "error": str | None, "truncated": bool,
    "total": int, "web_base": str, "projects": [...]}.
    Alltid ett giltigt svar - fel fångas och rapporteras, aldrig en 500.
    """
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    with _cache_lock:
        # Dubbelkoll: en annan tråd kan ha fyllt cachen medan vi väntade på låset.
        now = time.monotonic()
        if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL:
            return _cache["data"]

        base = {"web_base": BACKLOG_WEB_BASE}
        try:
            tasks, truncated = _run_list()
            projects = _aggregate(tasks)
            data = {
                **base, "available": True, "error": None, "truncated": truncated,
                "total": sum(p["open"] for p in projects), "projects": projects,
            }
        except FileNotFoundError:
            data = {**base, "available": False, "error": "backlog-binären hittas inte",
                    "truncated": False, "total": 0, "projects": []}
        except (
            subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError,
            KeyError, AttributeError, TypeError, ValueError,
        ) as exc:
            # AttributeError/TypeError: t.ex. om backlog ändrar JSON-formen så att
            # ett fält har oväntad typ i _aggregate. ValueError: oväntad uppackning.
            # Vyn ska aldrig ge 500 - alltid ett giltigt {available: false}-svar.
            data = {**base, "available": False, "error": str(exc), "truncated": False,
                    "total": 0, "projects": []}

        _cache["at"] = now
        _cache["data"] = data
        return data
