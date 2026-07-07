"""Konfiguration för portalen. Värdena kan överridas via miljövariabler."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Databasfil (data/ är gitignorerad)
DB_PATH = Path(os.environ.get("PORTAL_DB_PATH", BASE_DIR / "data" / "portal.db"))

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

# Portreservationer gäller så här många minuter innan de städas bort
RESERVATION_TTL_MINUTES = int(os.environ.get("PORTAL_RESERVATION_TTL", "15"))

# Default-range för lediga portar
PORT_RANGE_START = 8000
PORT_RANGE_END = 8999
