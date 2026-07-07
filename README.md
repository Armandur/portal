# Portal

Tjänsteportal för den delade dev-VM:en ubuntu-ai. Flera Claude Code-instanser
bygger och kör dev-servrar parallellt på samma maskin - portalen är
sanningskällan för vilka portar och tjänster som körs.

Portalen:

- visar en webbsida med kort för varje registrerad tjänst (namn, projekt,
  port, beskrivning, länk, live-status) plus en dokumentationsvy per tjänst
  (markdown renderad till HTML)
- auto-genererar den gamla manuella liggaren
  `~/.claude/running-services.md` från databasen efter varje ändring
  (bakåtkompatibilitet: gamla instruktioner läser den filen)
- delar ut garanterat lediga portar (kollar registret, live-lyssnande portar
  via `ss -tlnp` och aktiva reservationer)
- listar alla lyssnande portar, inklusive oregistrerade

Portalen kör själv på port 8890: http://ubuntu-ai:8890

## Installation

Kräver Python 3.12 och uv.

```bash
cd ~/workspace/portal
./install.sh
```

Skriptet kör `uv sync`, installerar systemd user unit-filen
(`deploy/portal.service`), startar tjänsten och länkar CLI:t till
`~/.local/bin/svc`. För start vid boot utan aktiv session krävs dessutom:

```bash
sudo loginctl enable-linger rasmus
```

Manuell start utan systemd:

```bash
cd ~/workspace/portal
uv sync
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8890
```

## CLI: svc

CLI:t använder bara stdlib och fungerar utan venv. Bas-URL styrs av
miljövariabeln `PORTAL_URL` (default `http://127.0.0.1:8890`).

```bash
# Lista tjänster med live-status
svc list

# Hämta och reservera en ledig port (skriver bara portnumret - skriptvänligt)
PORT=$(svc port --note "mitt-projekt dev")
PORT=$(svc port --range 8100-8199)

# Registrera en tjänst när den startats
svc register mitt-projekt --port 8123 --project mitt-projekt \
    --pid 12345 --desc "uvicorn app.main (dev)" --by "claude, mitt-projekt" \
    --docs-file /home/rasmus/workspace/mitt-projekt/README.md

# Uppdatera fält
svc update mitt-projekt --pid 23456 --desc "ny beskrivning"

# Visa detaljer / avregistrera
svc show mitt-projekt
svc unregister mitt-projekt

# Alla lyssnande portar, inklusive oregistrerade
svc ports
```

## API-översikt

Interaktiv API-dokumentation: http://ubuntu-ai:8890/api/docs

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | /api/health | Hälsokoll |
| GET | /api/services | Alla tjänster med live-status |
| GET | /api/services/{name} | En tjänst |
| POST | /api/services | Registrera tjänst |
| PATCH | /api/services/{name} | Uppdatera fält |
| DELETE | /api/services/{name} | Avregistrera |
| GET | /api/ports | Lyssnande portar + registrerade tjänster |
| POST | /api/ports/reserve | Reservera ledig port, svarar {"port": N} |

Statusvärden per tjänst: `up` (porten lyssnar, PID okänd eller matchar),
`conflict` (porten lyssnar men med annan PID än den registrerade),
`down` (inget lyssnar).

Portreservationer gäller 15 minuter och städas därefter bort automatiskt.
När en tjänst registreras på en reserverad port förbrukas reservationen.

## Liggaren

`~/.claude/running-services.md` skrivs om av portalen efter varje
create/update/delete. Redigera den inte för hand - använd `svc` eller API:t.
Vid appstart importeras tabellrader vars port inte redan finns i databasen
(så manuellt tillagda tjänster från gamla flödet inte tappas); databasen
vinner vid konflikt.

## Docker (reservspår - systemd är primär driftväg)

Containern behöver host-nätverk och host-PID-namespace för att `ss -tlnp`
ska se värdens portar och processer, samt volymer för databasen och liggaren:

```bash
docker build -t portal .
docker run -d --name portal \
    --network host --pid host \
    -v ~/workspace/portal/data:/app/data \
    -v ~/.claude/running-services.md:/root/.claude/running-services.md \
    -e PORTAL_LEDGER_PATH=/root/.claude/running-services.md \
    portal
```
