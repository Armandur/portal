"""Liggar-generering: portalen är sanningskällan och skriver om
~/.claude/running-services.md efter varje ändring av tjänsteregistret.
Vid appstart importeras rader från den gamla manuella liggaren."""

import re

from app.config import LEDGER_PATH, PORTAL_PORT, SERVICE_HOST
from app.database import create_service, get_service, get_service_by_port, list_services

_HEADER = f"""# Körande tjänster (delad VM ubuntu-ai)

> **OBS: Denna fil genereras automatiskt av portalen**
> (http://{SERVICE_HOST}:{PORTAL_PORT}). Redigera den inte för hand -
> registrera och avregistrera tjänster via `svc`-CLI:t eller portalens API.

Delad liggare över lyssnande processer som Claude-instanser startat. Syfte:
ingen instans ska döda en annan instans server för att den inte vet vems PID är vems.

**Regler:**

- Startar du en dev-server/lyssnande process: registrera den i portalen
  (`svc register ...`) när du startat den och sett PID:en.
- Stoppar du din egen process: avregistrera den igen (`svc unregister ...`).
- **Döda ALDRIG en PID som inte står här som din egen** (ditt projekt, startad i
  din session). Står porten upptagen men saknas här - lämna den ifred och välj en
  annan port. En tom/inaktuell rad betyder "okänt ägarskap", inte "fritt fram".
- Liggaren kan bli inaktuell (krasch, glömd städning). Verifiera mot `ss -tlnp`
  innan du litar på en rad - matchar PID:en inte längre porten är raden död, men
  det ger dig fortfarande inte rätt att döda någon annans process.

| Port | PID | Projekt | Process/Tjänst | Startad |
|------|-----|---------|----------------|---------|
"""

_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*$"
)

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    slug = _SLUG_STRIP_RE.sub("-", text.lower()).strip("-")
    return slug or "tjanst"


def write_ledger() -> None:
    """Skriver om liggarfilen från databasen, sorterad på port."""
    lines = [_HEADER]
    for svc in list_services():
        pid = svc["pid"] if svc["pid"] is not None else "-"
        started = svc.get("started_by") or (svc.get("created_at") or "")[:10] or "-"
        desc = svc.get("description") or svc["name"]
        lines.append(
            f"| {svc['port']} | {pid} | {svc['project']} | {desc} | {started} |\n"
        )
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text("".join(lines), encoding="utf-8")


def import_ledger() -> int:
    """Läser befintlig liggarfil och importerar tabellrader vars port inte
    redan finns i databasen (DB vinner vid konflikt). Returnerar antal
    importerade rader."""
    if not LEDGER_PATH.exists():
        return 0
    try:
        text = LEDGER_PATH.read_text(encoding="utf-8")
    except OSError:
        return 0

    imported = 0
    for line in text.splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        port_str, pid_str, project, process, started = (g.strip() for g in m.groups())
        if project.lower() in ("projekt", "---", "") or not port_str.isdigit():
            continue
        port = int(port_str)
        if get_service_by_port(port) is not None:
            continue
        pid = int(pid_str) if pid_str.isdigit() else None
        name = f"{_slugify(project)}-{port}"
        if get_service(name) is not None:
            name = f"{name}-import"
        create_service({
            "name": name,
            "project": project,
            "port": port,
            "pid": pid,
            "description": process or None,
            "url_path": "/",
            "started_by": f"importerad från liggaren ({started})" if started
                          else "importerad från liggaren",
        })
        imported += 1
    return imported
