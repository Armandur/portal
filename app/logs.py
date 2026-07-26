"""Loggkälleresolution och strömning för GET /api/services/{name}/logs.

En tjänst kan ha två sorters loggkälla: en explicit fil (log_path) eller,
för systemd-tjänster, journalen för dess unit. log_source() avgör vilken
källa en given tjänst ska läsas ur - anropande kod skickar aldrig in en
sökväg/unit själv, den kommer alltid ur DB-raden.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.supervisor import valid_systemd_unit


def log_source(svc: dict) -> tuple[str, str] | None:
    """Avgör var tjänstens loggar ska läsas ifrån.

    Returnerar ("file", sökväg) eller ("journal", unit), eller None om
    tjänsten saknar en känd loggkälla.
    """
    log_path = svc.get("log_path")
    if log_path:
        if Path(log_path).is_absolute():
            return ("file", log_path)
        return None
    if svc.get("kind") == "systemd" and valid_systemd_unit(svc.get("unit")):
        return ("journal", svc["unit"])
    return None


def has_logs(svc: dict) -> bool:
    return log_source(svc) is not None


async def stream_lines(svc: dict, tail: int) -> AsyncIterator[str]:
    """Strömmar loggrader (utan radbrytning) för tjänsten tills klienten
    kopplar ner eller processen dör.

    Körs via asyncio.create_subprocess_exec (inte blockande subprocess.Popen):
    Starlette avbryter den här generatorn med en cancellation när klienten
    stänger anslutningen, och bara en asyncio-subprocess ger en finally-sats
    som faktiskt hinner köra då. Blockande readline() i en threadpool hänger
    kvar tills nästa loggrad kommer - på en tyst logg kan det vara aldrig,
    vilket läcker processen.
    """
    source = log_source(svc)
    if source is None:
        return
    kind, target = source
    if kind == "journal":
        args = [
            "journalctl", "--user", "-u", target,
            "-n", str(tail), "-f", "--output=short-iso", "--no-pager",
        ]
    else:
        args = ["tail", "-n", str(tail), "-F", target]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n")
    finally:
        # Processen kan redan ha dött av sig själv (t.ex. journalctl vid fel),
        # och då är den borta när vi städar.
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
