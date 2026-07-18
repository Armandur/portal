"""Konfiguration för portalen. Värdena kan överridas via miljövariabler."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Databasfil (data/ är gitignorerad)
DB_PATH = Path(os.environ.get("PORTAL_DB_PATH", BASE_DIR / "data" / "portal.db"))

# Katalog för delade filer (svc share). data/ är gitignorerad.
SHARE_DIR = Path(os.environ.get("PORTAL_SHARE_DIR", BASE_DIR / "data" / "shares"))

# Default-livslängd för en delning innan den auto-städas. 0 = aldrig.
SHARE_TTL_MINUTES = int(os.environ.get("PORTAL_SHARE_TTL", "120"))

# Maxstorlek på en delad fil (base64 skickas i JSON, så håll den rimlig)
SHARE_MAX_BYTES = int(os.environ.get("PORTAL_SHARE_MAX_BYTES", str(25 * 1024 * 1024)))

# Liggarfilen som portalen auto-genererar (bakåtkompatibilitet med gamla flöden)
LEDGER_PATH = Path(
    os.environ.get("PORTAL_LEDGER_PATH", Path.home() / ".claude" / "running-services.md")
)

# Portalens egen adress
PORTAL_HOST = os.environ.get("PORTAL_HOST", "0.0.0.0")
PORTAL_PORT = int(os.environ.get("PORTAL_PORT", "8890"))

# Hostnamn som används i länkar till tjänster (aldrig localhost/127.0.0.1 -
# användaren når VM:en via hostnamn/Tailscale)
SERVICE_HOST = os.environ.get("PORTAL_SERVICE_HOST", "ubuntu-ai")

# Portalens bas-URL för länkar den serverar själv (docs, delningar).
# Port 80 utelämnas så http://ubuntu-ai räcker.
PORTAL_BASE_URL = f"http://{SERVICE_HOST}" + ("" if PORTAL_PORT == 80 else f":{PORTAL_PORT}")

# backlog-verktyget (mazen160/backlog): portalen läser todos read-only via
# CLI:t. Absolut sökväg krävs - systemd user-unitens PATH inkluderar inte
# nödvändigtvis ~/.local/bin.
BACKLOG_BIN = os.environ.get("PORTAL_BACKLOG_BIN", str(Path.home() / ".local" / "bin" / "backlog"))
BACKLOG_PROFILE = os.environ.get("PORTAL_BACKLOG_PROFILE", "default")

# Bas-URL till backlog web-UI:t; todo-korten deep-länkar dit (/tasks/<ref>).
BACKLOG_WEB_BASE = os.environ.get("PORTAL_BACKLOG_WEB_BASE", f"http://{SERVICE_HOST}:8004")

# Portreservationer gäller så här många minuter innan de städas bort
RESERVATION_TTL_MINUTES = int(os.environ.get("PORTAL_RESERVATION_TTL", "15"))

# Default-range för lediga portar
PORT_RANGE_START = 8000
PORT_RANGE_END = 8999
