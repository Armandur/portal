"""Styrning av förregistrerade supervisor-resurser."""

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_SYSTEMD_UNIT_RE = re.compile(r"^[A-Za-z0-9:_.@-]+\.service$")


class SupervisorError(RuntimeError):
    pass


def valid_systemd_unit(unit: str | None) -> bool:
    return bool(unit and _SYSTEMD_UNIT_RE.fullmatch(unit))


def _systemd_user_dir() -> Path:
    override = os.environ.get("PORTAL_SYSTEMD_USER_DIR")
    return Path(override) if override else Path.home() / ".config" / "systemd" / "user"


def portal_managed_systemd_unit(unit: str) -> bool:
    if not valid_systemd_unit(unit):
        return False
    path = _systemd_user_dir() / unit
    try:
        return "X-Portal-Managed=true" in path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


def systemd_unit_states(units: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(unit for unit in units if valid_systemd_unit(unit)))
    if not unique:
        return {}
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--", *unique],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logger.exception("Kunde inte läsa systemd-status för %s", ", ".join(unique))
        return {unit: "unknown" for unit in unique}
    states = result.stdout.splitlines()
    if len(states) != len(unique):
        logger.error(
            "Systemd returnerade %s statusrader för %s units: %s",
            len(states), len(unique), (result.stderr or "").strip(),
        )
    return {
        unit: states[index].strip() if index < len(states) and states[index].strip()
        else "unknown"
        for index, unit in enumerate(unique)
    }


def systemd_unit_state(unit: str) -> str:
    return systemd_unit_states([unit]).get(unit, "unknown")


def control_systemd(action: str, unit: str) -> None:
    if action not in {"start", "stop"}:
        raise ValueError(f"Otillåten systemd-åtgärd: {action}")
    try:
        result = subprocess.run(
            ["systemctl", "--user", action, "--", unit],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.exception("Kunde inte köra systemctl %s för %s", action, unit)
        raise SupervisorError("systemctl kunde inte köras") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "okänt fel").strip()
        logger.error(
            "systemctl %s misslyckades för %s med kod %s: %s",
            action,
            unit,
            result.returncode,
            detail,
        )
        raise SupervisorError(detail)
