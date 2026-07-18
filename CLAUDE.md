# Portal - kodbasbeskrivning för Claude

Tjänsteportal för den delade dev-VM:en ubuntu-ai. Sanningskällan för vilka
portar/tjänster som körs. Kör själv på port 8890 (host 0.0.0.0).

## Stack

- Python 3.12, FastAPI, uvicorn. Beroenden hanteras med uv (`uv sync`).
- Rå sqlite3 (inte SQLAlchemy - litet lokalt verktyg). DB i `data/portal.db`.
- Jinja2 för serverrenderad dokumentationsvy, python-markdown
  (extensions: fenced_code, tables) för rendering. Delade .md-filer renderas
  också (extensions: tables, fenced_code, toc, codehilite) med Pygments-
  syntaxfärgning och saneras med nh3 (rå-HTML i källan tas bort).
- Frontend: vanilla JS utan bundler + self-hostad Pico CSS (`pico.min.css`)
  som basstil, egen `tokens.css` ovanpå för identitet (accent, statusbadges,
  kort-grid). Semantisk HTML (article/hgroup/section). Ljust/mörkt läge via
  prefers-color-scheme (ingen data-theme; tokens har mörka statusvarianter).
- Ingen auth (internt verktyg på privat nät). Inga IP-loggar.

## Filstruktur

- `app/main.py` - app-instans, lifespan (init_db, liggarimport,
  självregistrering, liggarskrivning), router-registrering. Swagger på
  /api/docs (inte /docs - den sökvägen används av dokumentationsvyn).
- `app/config.py` - sökvägar, portar, TTL. Allt överridbart via env
  (se .env.example).
- `app/database.py` - schema, init_db() med ALTER TABLE-guard-mönster
  (`_ensure_column`), CRUD för services, reservations och shares
  (delningar; äger både rad och fil i `data/shares/<uid>/`).
- `app/ports.py` - `ss -tlnp`-skanning (subprocess), ledig-port-logik,
  statusbedömning, reservationsstädning.
- `app/ledger.py` - genererar och importerar
  `~/.claude/running-services.md`.
- `app/routes/api.py` - JSON-API (/api/...), inkl. delnings-endpoints
  (/api/shares).
- `app/routes/pages.py` - kortvyn (/), dokumentationsvyn (/docs/{name})
  och delningsservering (/share/{uid}/{filnamn}; .md renderas som läsvy).
- `app/share_render.py` - renderar delade .md-filer till självbärande,
  sanerade HTML-läsvyer (inline CSS med portalens palett). render_text_page
  finns för framtida .txt.
- `app/backlog.py` - read-only läsvy mot backlog-verktyget (mazen160/backlog).
  Skalar ut till `backlog task list --json` (stabilt gränssnitt, aldrig rå
  SQLite), kort cache, robust felhantering. Portalen äger inga todos - backlog
  skriver, portalen visar (/api/todos, Todos-sektionen på förstasidan).
- `app/templates/` - index.html (klientrenderad via fetch), docs.html.
- `app/static/` - pico.min.css (self-hostad Pico 2), tokens.css (portalens
  egen stil ovanpå Pico), utils.js (apiFetch, escapeHtml), app.js.
- `cli/svc` - stdlib-only CLI mot API:t (fungerar utan venv). Utöver
  register/port/list även share/unshare/shares för fildelning.
- `deploy/portal.service` - systemd user unit (primär driftväg).
- `install.sh` - uv sync + unit-installation + svc-symlink. Idempotent.
- `Dockerfile` - reservspår, kräver --network host --pid host.

## Designbeslut

- **Portalen är master för liggaren.** `~/.claude/running-services.md`
  skrivs om från DB efter varje mutation (create/update/delete) och vid
  appstart. Vid appstart importeras först rader vars port inte finns i DB
  (gamla manuella flöden tappas inte); DB vinner vid konflikt.
- **Reservations-TTL 15 minuter.** Reservationer äldre än TTL ignoreras och
  städas vid nästa läsning. Registrering på en reserverad port tar bort
  reservationen.
- **Statuslogik** (`app/ports.py:service_status`): "docs" om posten saknar
  port (ren dokumentationspost); annars "up" om porten lyssnar och
  registrerad PID är okänd, ss-PID saknas (annan ägare) eller PID:erna
  matchar; "conflict" om porten lyssnar med annan känd PID; "down" annars.
- **Dokumentationsposter (port NULL).** En registrering utan port är en
  ren dokumentationspost och kräver docs_path eller docs_md (valideras i
  POST /api/services). Portkolumnen tillåter NULL men behåller UNIQUE
  (SQLite tillåter flera NULL i UNIQUE-kolumn). API:ts url-fält pekar för
  portlösa poster på /docs/{name} på portalen själv. Posten uppgraderas
  senare med PATCH (eller `svc update NAMN --port N --pid P`) när tjänsten
  startas. I liggaren skrivs portlösa poster med "-" i portkolumnen;
  import_ledger hoppar över sådana rader (regexen kräver siffror).
  Migreringen till nullable port sker i `_migrate_port_nullable()` i
  database.py (tabell-rebuild, idempotent - SQLite kan inte droppa
  NOT NULL med ALTER TABLE).
- **HTML-dokumentation.** Slutar docs_path på .html/.htm serverar
  GET /docs/{name} filens innehåll rakt av som text/html (fristående sida,
  inte inbäddad i docs-templaten). Övriga docs_path renderas som markdown.
- **Delningar (`svc share`).** Fildelning utan att låsa en port per fil:
  portalen serverar delningar på sin egen port under
  `/share/{uid}/{filnamn}` (kanonisk URL; `/share/{uid}` 302-redirectar
  dit). Egen `shares`-tabell (inte `services`) - delningar har ingen
  port/PID och hamnar därför inte i liggaren. `svc share` läser filen och
  POST:ar den base64-kodad i JSON till `/api/shares` (håller CLI:t
  stdlib-rent utan multipart); portalen genererar `uid`
  (`secrets.token_hex(6)`), sparar filen i `data/shares/{uid}/` och en rad.
  Serveras med `content_disposition_type="inline"` så bilder/PDF/HTML visas
  i webbläsaren. `database.py` äger hela livscykeln (rad + fil) så städning
  tar bort båda atomärt. **TTL** (`SHARE_TTL_MINUTES`, default 120; `--ttl 0`
  = aldrig) städas lazily vid `list_shares()`/`get_share()` och vid
  appstart (`clean_expired_shares` i lifespan) - samma lata mönster som
  reservationer. Maxstorlek `SHARE_MAX_BYTES` (default 25 MB).
- **Markdown-delningar renderas som läsvy.** Slutar filnamnet på
  `.md`/`.markdown` renderar `GET /share/{uid}/{fil}` källan server-side
  (vid visning, så uppdaterad källa syns) till en självbärande, stylad
  HTML-sida (`app/share_render.py`): inline CSS med portalens palett,
  mörkt/ljust via prefers-color-scheme, mobil-först, ~52rem, kod/tabeller
  scrollar internt (aldrig sidbreddsscroll). `?raw=1` ger källan som
  text/plain, och en "visa källa"-länk pekar dit. Kodblock med angivet språk
  (```python etc) syntaxfärgas med Pygments/codehilite - CSS-klasser (inte
  inline-style, som nh3 hade strippat), och temats CSS inline:as (`default`
  ljust, `monokai` mörkt, bytbara överst i share_render.py). guess_lang=False:
  bara block med angivet språk färgas. **Säkerhet:** python-markdown släpper
  igenom rå-HTML i källan oavsett md_in_html, så outputen saneras med nh3
  (allowlist av taggar/attribut, class bevaras för codehilite) - en delad
  `.md` kan inte köra skript. Andra filtyper är oförändrade (även HTML-
  delningar serveras rakt av; deras highlighting är uppladdarens ansvar).
  Renderaren är generell (`render_text_page` för framtida `.txt`).
- **`PORTAL_BASE_URL`.** Bas-URL för länkar portalen serverar själv (docs,
  delningar). Utelämnar porten när `PORTAL_PORT == 80` så `http://ubuntu-ai`
  räcker. Beräknas vid import i config.py.
- **Länkar alltid till http://ubuntu-ai:PORT** (config.SERVICE_HOST),
  aldrig localhost - användaren når VM:en via hostnamn/Tailscale.
- Portalen registrerar sig själv vid start (name "portal", pid
  os.getpid(), docs_path pekar på README.md).

## Vanliga förändringar

- Ny kolumn i services: lägg till i `_SCHEMA` OCH som
  `_ensure_column`-anrop i `init_db()` (guard-mönstret är migreringen).
  Uppdatera även `allowed` i `update_service`, Pydantic-modellerna i
  api.py och ev. CLI-flaggor.
- Ändring av kolumnconstraints (NOT NULL o.l.): kan inte göras med
  ALTER TABLE i SQLite - följ rebuild-mönstret i `_migrate_port_nullable()`
  (rename, ny tabell från `_SCHEMA`, kopiera gemensamma kolumner, droppa
  gamla) och gör kontrollen idempotent via `PRAGMA table_info`.
- Nytt API-endpoint: `app/routes/api.py`, prefix /api.
- Ändring i liggarformatet: `_HEADER` och `write_ledger()` i
  `app/ledger.py`; tänk på att `import_ledger()` måste kunna parsa
  formatet (regexen `_ROW_RE`).

## Verifiering

```bash
cd /home/rasmus/workspace/portal
uv run python -c "from app.main import app; print('OK')"
```

Live-test: starta med `.venv/bin/uvicorn app.main:app --host 0.0.0.0
--port 8890` (logga till dev.log), curl:a /api/health, stoppa exakt den
PID du startade. Kom ihåg att appstart skriver om liggarfilen.
