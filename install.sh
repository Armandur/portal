#!/usr/bin/env bash
# Installerar portalen som systemd user unit och länkar svc-CLI:t.
# Idempotent - kan köras om vid uppdateringar.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/bin"
UV="${UV:-$HOME/.local/bin/uv}"

echo "== Portal: installation =="

echo "-> uv sync (skapar/uppdaterar .venv)"
cd "$PROJECT_DIR"
"$UV" sync

echo "-> Installerar systemd user unit"
mkdir -p "$UNIT_DIR"
cp "$PROJECT_DIR/deploy/portal.service" "$UNIT_DIR/portal.service"
systemctl --user daemon-reload
systemctl --user enable --now portal

echo "-> Länkar svc-CLI:t till $BIN_DIR/svc"
mkdir -p "$BIN_DIR"
chmod +x "$PROJECT_DIR/cli/svc"
ln -sf "$PROJECT_DIR/cli/svc" "$BIN_DIR/svc"

echo ""
echo "Klart. Portalen kör på http://ubuntu-ai:8890"
echo ""
echo "PÅMINNELSE: för att portalen ska starta vid boot (utan aktiv session),"
echo "kör en gång som root eller med sudo:"
echo "  loginctl enable-linger rasmus"
