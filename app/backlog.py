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

import bleach
import markdown as _md

from app.config import BACKLOG_BIN, BACKLOG_PROFILE, BACKLOG_WEB_BASE

# Prioritet lagras som heltal 1-5 i backlog; visa som P1-P5.
_OPEN_STATUSES = ("todo", "doing")
_LIMIT = 500

# Task-descriptions är markdown. De renderas server-side och SANERAS med en
# allowlist innan de skickas till klienten (som injicerar dem via innerHTML) -
# så inget injektionsutrymme öppnas oavsett vad en task-beskrivning innehåller.
_ALLOWED_TAGS = [
    "h2", "h3", "h4", "p", "ul", "ol", "li", "code", "pre",
    "strong", "em", "a", "br", "hr", "blockquote", "input",
]
_ALLOWED_ATTRS = {"a": ["href", "title"], "input": ["type", "checked", "disabled"]}


def _render_description(text: str) -> str:
    """Renderar markdown -> sanerad HTML (allowlist). Aldrig råa taggar/skript."""
    if not text:
        return ""
    html = _md.markdown(
        text,
        extensions=["fenced_code", "tables", "pymdownx.tasklist"],
        extension_configs={"pymdownx.tasklist": {"custom_checkbox": False}},
    )
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


# Beskrivningar kortare än så här (ren text) renderas inline utan <details> -
# en utfällning som visar samma text igen tillför inget.
_COLLAPSE_THRESHOLD = 160


def _summary(text: str) -> str:
    """Prosa-preview till <summary>: hoppa över rubrik-/HR-rader (t.ex. '## Context'),
    strippa list-/checkbox-markörer, ta första meningen (~100 tecken)."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or set(s) <= {"-", "*", "_"}:
            continue  # tom rad, rubrik, eller horisontell linje
        s = s.lstrip("-*0123456789. ").strip()               # listmarkör
        s = s.replace("[ ]", "").replace("[x]", "").strip()  # checkbox
        if not s:
            continue
        sentence = s.split(". ")[0].rstrip(".")
        return f"{sentence[:100]}…" if len(sentence) > 100 else sentence
    return ""


def _plaintext(html: str) -> str:
    """Ren text ur renderad HTML - för att bedöma om en beskrivning är lång."""
    return bleach.clean(html, tags=[], strip=True).strip()


_cache: dict = {"at": 0.0, "data": None}
_CACHE_TTL = 15.0


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
        batch = json.loads(proc.stdout).get("tasks", [])
        tasks.extend(batch)
        if len(batch) >= _LIMIT:
            truncated = True
    return tasks, truncated


def _shape(task: dict) -> dict:
    """Plockar ut de fält portalen visar och normaliserar formatet."""
    project = task.get("project") or {}
    actor = task.get("actor") or {}
    ref = f"TASK-{task['seq']}" if task.get("seq") is not None else task.get("id", "")
    description = task.get("description") or ""
    description_html = _render_description(description)
    # Fäll bara ihop långa beskrivningar; korta renderas inline (klienten följer collapse).
    collapse = len(_plaintext(description_html)) > _COLLAPSE_THRESHOLD
    return {
        "ref": ref,
        "title": task.get("title", ""),
        "description": description,
        "description_html": description_html,
        "description_summary": _summary(description),
        "collapse": collapse,
        "priority": task.get("priority", 3),
        "status": task.get("status", "todo"),
        "type": task.get("type", "task"),
        "project": project.get("alias", "okänt"),
        "project_path": task.get("project_path") or "",
        "source": task.get("source") or "",
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
        tasks, truncated = _run_list()
        projects = _group(tasks)
        data = {"available": True, "error": None, "truncated": truncated, "projects": projects}
    except FileNotFoundError:
        data = {"available": False, "error": "backlog-binären hittas inte", "truncated": False, "projects": []}
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        data = {"available": False, "error": str(exc), "truncated": False, "projects": []}

    _cache["at"] = now
    _cache["data"] = data
    return data
