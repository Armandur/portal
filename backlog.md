# Backlog Export

## [P2][todo] [portal] Projektkortens todo- och testlänkar matchar inte backlog-projektnamn

Todo från Rasmus 2026-08-03: pågår-notisen som finns i todo-listan borde också synas på korten. Vid undersökning visade det sig vara ett matchningsproblem, inte en saknad funktion.

BADGEN FINNS REDAN. renderProjectTodos i app/static/app.js (~rad 112) renderar '<N> pågår' när counts.doing är satt. Den syns bara aldrig.

ROTORSAK: kortet matchar backlog-projektet mot portalens projektnamn med exakt strängjämförelse, och de sammanfaller inte. Vid kontroll 2026-08-03 hade fyra projekt pågående todos - hemslojd (5), duharfagel (1), kt-rss (1), sr-rss (1) - och inget av dem matchar ett kort:

- hemslojd (backlog) vs anmalningssystem (portalen)
- kt-rss / sr-rss (backlog) vs sverigesradio-rss (portalen)
- duharfagel har inget kort alls

Det gäller INTE bara doing-badgen: hela todo-raden och de öppna testlistorna på kortet träffas av samma sak. Testlistorna handpatchades 2026-08-03 genom att sätta project=anmalningssystem på sex sessioner, vilket är en lapp, inte en lösning - nästa session som skapas med backlog-projektets namn hamnar fel igen.

FÖRSLAG: en aliasmappning mellan backlog-projekt och portalprojekt. Rimligen ett fält på tjänsten (backlog_project) som sätts via svc register/update, med fallback på exakt namnmatchning som i dag. Då kan både todos och testlistor slå upp rätt kort utan att den som skapar dem behöver känna till portalens namngivning.

Klart när: anmalningssystem-kortet visar '5 pågår' och sina öppna testlistor utan att någon handpatchat project-fältet. Verifiera: svc list visar kortet, /api/todos har doing>0 för det backlog-projekt kortet är kopplat till, och badgen syns i DOM.

- ID: `01KZ3GHNXV8STKT4EEA6C0T52V`
- Type: bug
- Actor: ai:claude-opus-5

---

## [P2][done] [portal] Städa döda efemära tjänsteposter automatiskt

## Kontext
Tjänsteregistret växer monotont eftersom reservationer och delningar städas lazily men tjänsteposter aldrig tas bort. Vid senaste inventeringen var 14 av 26 poster döda. TASK-354 behöver skilja sådant skräp från stoppade managed-tjänster, som ska finnas kvar och kunna startas igen.

## Acceptanskriterier
- [ ] En post med `kind='ephemeral'` tas bort när dess registrerade PID inte lever och dess port inte lyssnar.
- [ ] En efemär post tas inte bort om PID fortfarande lever eller om porten fortfarande lyssnar.
- [ ] En dokumentationspost utan port tas inte bort av städningen.
- [ ] Poster med `kind='systemd'` eller `kind='docker'` tas aldrig bort automatiskt, oavsett PID- eller portstatus.
- [ ] Städning körs vid lifespan-start och före eller i samband med `list_services()`.
- [ ] Borttagning uppdaterar liggaren på samma sätt som annan tjänsteborttagning.
- [ ] Registrera en fejkad efemär post med död PID och tyst port; nästa `GET /api/services` tar bort den.
- [ ] Registrera motsvarande systemd-post; nästa listning behåller den.

## Implementationshänvisningar
Återanvänd mönstret för `clean_expired_shares` och reservationsstädning. Port- och PID-bedömning finns i `app/ports.py`, medan DB-livscykel och liggarskrivning behöver hållas samordnade med `app/database.py` och `app/main.py`. Undvik att hålla en SQLite-transaction öppen medan `ss` körs.

- ID: `01KY7XQVD82XW1K8TKXMDBQKS1`
- Type: improvement
- Actor: ai:claude-code

---

## [P2][done] [portal] Utöka tjänsteschemat med supervisor-metadata

## Kontext
TASK-354 behöver skilja kortlivade, manuellt startade processer från tjänster som ägs av systemd eller Docker. Utan den skillnaden kan portalen varken behålla stoppade projekt, städa säkert eller begränsa start och stopp till tillåtna resurser.

## Acceptanskriterier
- [ ] Tabellen `services` har `kind TEXT DEFAULT 'ephemeral'`, `unit TEXT` och `autostart INTEGER DEFAULT 0`.
- [ ] Tillåtna värden för `kind` är `ephemeral`, `systemd` och `docker`; ogiltiga API- och CLI-värden avvisas vid systemgränsen.
- [ ] Befintliga rader får `kind='ephemeral'` och behåller övriga data.
- [ ] Migreringen är idempotent och fungerar vid upprepade starter.
- [ ] `create_service` och `update_service` kan skriva de nya fälten.
- [ ] API-modeller och JSON-svar innehåller fälten.
- [ ] `svc register` och `svc update` kan ange relevanta supervisor-fält utan att ta emot eller lagra startkommandon.
- [ ] Import och export av liggaren fortsätter fungera; nya fält behöver inte läggas till i liggarformatet.
- [ ] `uv run python -c "from app.main import app; print('OK')"` lyckas.
- [ ] `PRAGMA table_info(services)` visar kolumnerna efter initiering och omstart.

## Implementationshänvisningar
Lägg kolumnerna både i `_SCHEMA` för nya databaser och som `_ensure_column`-anrop i `init_db()` för befintliga databaser. Uppdatera tillåtna fält i `app/database.py`, Pydantic-modellerna i `app/routes/api.py` och flaggorna i `cli/svc`. Följ befintligt guard-mönster och gör ingen tabell-rebuild för denna ändring.

- ID: `01KY7XQVB4K5CF2CPF2H04QD42`
- Type: task
- Actor: ai:claude-code

---

## [P2][done] [portal] Gör portalen till en startbar katalog över alla projekt

## Kontext
Portalen behöver utvecklas från ett register över processer som kör just nu till en beständig projektkatalog. Ett registrerat projekt ska finnas kvar när det är stoppat och kunna styras genom en befintlig supervisor.

Portalen binder till 0.0.0.0 utan autentisering. Den får därför aldrig lagra eller exekvera godtyckliga startkommandon via HTTP. systemd eller Docker äger processens livscykel, medan portalen endast visar tillstånd och proxar till förregistrerade resurser.

## Acceptanskriterier
- [ ] Tjänsteposter skiljer mellan efemära processer och beständiga systemd- eller Docker-tjänster.
- [ ] Managed-tjänster ligger kvar i katalogen när de är stoppade.
- [ ] Döda efemära poster kan städas utan att managed-tjänster försvinner.
- [ ] Ett lokalt CLI-flöde kan skapa en supervisor-konfiguration utan att startkommandot skickas till portalens HTTP-API.
- [ ] HTTP-API:t kan endast starta eller stoppa supervisor-resurser som redan är tillåtna genom en DB-post.
- [ ] Kortvyn visar supervisor-status och erbjuder start eller stopp enbart för managed-tjänster.
- [ ] Drift mellan supervisor-status och faktisk portstatus visas tydligt.
- [ ] Befintliga flöden för portreservationer, dokumentationsposter, delningar och liggare fortsätter fungera.

## Säkerhetsgräns
- Portalen lagrar supervisor-typ och unit- eller containernamn, aldrig ett startkommando.
- Startkommandon skrivs endast lokalt av `svc install`.
- Ett namn från URL eller request body får aldrig användas direkt som subprocess-argument utan uppslagning mot DB.
- Docker-stöd ska följa samma allowlist-princip men behöver inte implementeras innan systemd-spåret fungerar.

## Deluppgifter
- TASK-355: utöka services-schemat.
- TASK-356: städa döda efemära poster.
- TASK-357: rensa kända dubbletter och spökposter.
- TASK-358: skapa systemd user-units via lokalt CLI.
- TASK-359: exponera säkra start- och stoppendpoints.
- TASK-360: spegla supervisor-status och upptäck drift.
- TASK-361: lägg till start- och stoppkontroller i kortvyn.

## Implementationshänvisningar
Berör främst `app/database.py`, `app/ports.py`, `app/routes/api.py`, `app/static/app.js` och `cli/svc`. Full design finns i `tmp/tjansteregister-hantering.md`. TASK-306 behandlar separat vilken roll todos-vyn ska ha.

- ID: `01KY7XPSZDWD8567V24Y41MWW7`
- Type: feature
- Actor: ai:claude-code

---

## [P2][done] [portal] Tema-round-trip: spara/återför tema till Claude + skill-integration

Sista biten av tema-visionen (ur TASK-118): när ett nytt projekt byggs ska Claude fråga om tema, föreslå en färgkombo som en builder-URL ELLER länka buildern till Rasmus, som designar och FÖR TILLBAKA temat för implementering. URL-state finns redan (delbar/återöppningsbar länk) - det som saknas är återföringsvägen och skill-kopplingen. Steg 1 = designbeslut om mekanismen: (a) paste av tokens.css-text (funkar redan, noll backend), (b) server-endpoint som renderar tokens.css ur query-params så Claude kan WebFetch:a (kräver färgmatte i Python ELLER att klienten POSTar genererad CSS), (c) namngivna teman i DB: buildern POSTar spec+genererad tokens.css, /api/themes/{namn} returnerar den (ingen Python-matte, ger persistens). Sedan skill-integration (theme-preview-skillen eller ny). Inte brådskande men strategiskt nästa steg.

- ID: `01KXXSBWGTS2K2G3HC8QZJ776B`
- Type: feature
- Actor: ai:claude-code

---

## [P2][done] [portal] Filtrera task-listan på status så öppna todos inte tappas vid --limit

## Context
_run_list hämtar utan status-filter, så done-tasks ingår (verifierat). Med --sort priority och --limit 500 kan lågprioriterade öppna todos tryckas ut ur svaret när klarmarkerade ackumuleras, utan att available:false signalerar avkortning.

## Acceptance criteria
- [ ] CLI-anropet i _run_list hämtar bara öppna tasks (todo + doing), inte done.
- [ ] Med >500 done-tasks i projektet returnerar /api/todos fortfarande alla öppna todos.
- [ ] Om resultatet ändå avkortas signaleras det (inte tyst available:true).

## Implementation hints
app/backlog.py:_run_list. `backlog task list` stödjer --status men ett värde per anrop - antingen två anrop (todo, doing) som slås ihop, eller behåll klientfiltret men höj/ta bort --limit. archived exkluderas redan.

## Verifiera
Skapa >10 done-tasks + en lågprio öppen; bekräfta att den öppna syns i /api/todos.

- ID: `01KXV7TYRTSJJ12NKZKHSXVYSJ`
- Type: bug
- Actor: ai:code-review

---

## [P3][todo] [portal] Sortera delningssektionen, med skapad-när som kolumn

Todo från Rasmus 2026-08-03 (dokumenterad, inte påbörjad).

Delningssektionen på framsidan listar aktiva delningar utan ordning man kan styra. Två saker:

1. Lägg till en kolumn för när delningen skapades. Datan finns redan - shares-tabellen har created_at, och API:t returnerar den.
2. Gör kolumnerna sorterbara genom att klicka på rubriken. Minst skapad-när, rimligen även namn och storlek. Nyast först som default är sannolikt vad man vill ha.

Sorteringen kan ske klientsidan - listan är kort och hämtas ändå i sin helhet var 30:e sekund.

Att tänka på: sektionen renderas av renderShares i app/static/app.js. Todo-sektionen intill har redan en tabell att härma stilen från. Verifiera vid 390px också - en tabell med fyra kolumner kan bli trång i mobil.

- ID: `01KZ3GGZTMSRVNAXARAYSNGWD3`
- Type: improvement
- Actor: ai:claude-opus-5

---

## [P3][done] [portal] Förslag: Kunna visa en strömmande logg från projektet/applikationen via en knapp på kortet

- ID: `01KYG6QM64N8AYRY2613KSED6N`
- Type: task
- Actor: human:rasmus

---

## [P3][done] [portal] Lägg till start- och stoppkontroller för managed-tjänster

## Kontext
När backend kan styra tillåtna systemd-tjänster behöver katalogens kortvy ge ett enkelt sätt att starta stoppade projekt och stoppa aktiva. Kontrollerna ska bara synas när tjänsten faktiskt är managed och ska spegla både pågående anrop och uppdaterad status.

## Acceptanskriterier
- [ ] En stoppad systemd-tjänst visar en tydlig startknapp.
- [ ] En aktiv systemd-tjänst visar en tydlig stoppknapp.
- [ ] Efemära tjänster och rena dokumentationsposter visar ingen start- eller stoppknapp.
- [ ] Klick anropar rätt endpoint från TASK-359 och uppdaterar det berörda kortet utan helsidomladdning.
- [ ] Knappen inaktiveras under pågående request så att dubbla anrop undviks.
- [ ] Lyckat anrop visar ny status och rätt nästa åtgärd.
- [ ] Misslyckat anrop återställer kontrollen och visar ett tydligt svenskt fel utan att dölja befintlig status.
- [ ] Ett drifttillstånd från TASK-360 visas tydligt och erbjuder inte en missvisande standardåtgärd.
- [ ] Kontrollerna är tangentbordsåtkomliga och har begripliga tillgängliga namn.
- [ ] Vid cirka 390 px finns ingen horisontell overflow och knappen är lätt att träffa.
- [ ] Vid minst 1280 px passar kontrollen in i befintligt kort utan layoutregression.
- [ ] Obscura-dump visar kontroll på managed-kort men inte på efemära kort.

## Implementationshänvisningar
Kortvyn renderas huvudsakligen i `app/static/app.js` med struktur från `app/templates/index.html` och stil i `app/static/tokens.css`. Återanvänd `apiFetch` från `app/static/utils.js`. Browser-verifiera både mobil och desktop enligt projektets browser-verify-skill innan uppgiften markeras klar.

- ID: `01KY7XRSB5ZK1NSVXTPR07JBFA`
- Type: feature
- Actor: ai:claude-code

---

## [P3][done] [portal] Spegla systemd-status och upptäck drift för managed-tjänster

## Kontext
Portstatus ensam räcker inte för managed-tjänster. En systemd-unit kan vara stoppad samtidigt som en föräldralös process lyssnar på dess port, eller vara aktiv utan att den förväntade porten lyssnar. Portalen måste visa supervisor-status och drift i stället för ett missvisande `up`.

## Acceptanskriterier
- [ ] Tjänster med `kind='systemd'` får sin supervisor-status från `systemctl --user is-active <unit>`.
- [ ] Efemära tjänster behåller nuvarande PID- och portbaserade statuslogik.
- [ ] En aktiv unit med lyssnande port visas som normal `up`.
- [ ] En inaktiv unit med tyst port visas som normal `down`.
- [ ] En inaktiv unit med lyssnande port får ett eget drifttillstånd.
- [ ] En aktiv unit vars förväntade port inte lyssnar får ett eget drifttillstånd.
- [ ] Saknat unit-namn eller fel från systemctl hanteras deterministiskt och visas inte som falskt `up`.
- [ ] API-svaret innehåller tillräcklig strukturerad information för att UI:t ska kunna skilja normal status från drift.
- [ ] Befintliga statusvärden för dokumentationsposter och portkonflikter fortsätter fungera.
- [ ] Det dokumenterade duharfagel-fallet visas som drift när uniten är inactive men port 8001 lyssnar.

## Implementationshänvisningar
Utöka statusbedömningen i `app/ports.py` och formningen av svar i `app/routes/api.py`. Kör systemctl utan shell och undvik ett subprocess-anrop per tjänst om status kan hämtas samlat eller cacheas kort. Definiera statuskontraktet på ett ställe så att API, CLI och UI använder samma betydelse. Docker-status kan läggas till senare men ska inte antas fungera genom systemd-koden.

- ID: `01KY7XRSA4KCC4R3YE0288S3Y0`
- Type: improvement
- Actor: ai:claude-code

---

## [P3][done] [portal] Lägg till säkra endpoints för start och stopp av systemd-tjänster

## Kontext
Kortvyn i TASK-361 behöver kunna starta och stoppa projekt, men portalen saknar autentisering och binder till hela VM-nätet. Endpointsen måste därför vara strikt begränsade till systemd-units som redan finns i tjänstedatabasen.

## Acceptanskriterier
- [ ] `POST /api/services/{name}/start` och `POST /api/services/{name}/stop` finns.
- [ ] Endpointsen slår först upp tjänsten efter namn och använder endast `unit` från den hämtade DB-posten.
- [ ] Okänd tjänst ger 404.
- [ ] En efemär tjänst, fel supervisor-typ eller saknat unit-namn avvisas med ett tydligt 400-svar.
- [ ] Ett unit-namn från URL, query eller request body kan aldrig skickas direkt till subprocess.
- [ ] `systemctl --user start|stop <unit>` körs utan shell.
- [ ] Supervisor-fel översätts till ett tydligt API-fel och lämnar tillräcklig serverlogg för felsökning.
- [ ] Ett lyckat svar innehåller tjänstens aktuella status så klienten kan uppdatera kortet.
- [ ] Start och stopp fungerar mot en registrerad testunit.
- [ ] Försök mot okänd eller efemär tjänst startar ingen process.

## Implementationshänvisningar
Lägg endpointsen i `app/routes/api.py` och håll subprocess-logiken i en avgränsad modul eller funktion som kan testas utan att starta riktiga tjänster. Array-baserade subprocess-argument är obligatoriska; använd inte `shell=True`. Docker-stöd ligger utanför denna deluppgift.

- ID: `01KY7XRS96RVBS8MMBNT3FC7C8`
- Type: feature
- Actor: ai:claude-code

---

## [P3][done] [portal] Lägg till svc install för systemd-hanterade projekt

## Kontext
TASK-354 behöver ett lokalt och säkert sätt att göra ett projekt startbart. Startkommandot ska skrivas till en systemd user-unit på VM:en och får aldrig skickas till eller lagras av portalens HTTP-API.

## Acceptanskriterier
- [ ] `svc install <projekt> --cmd <kommando> --cwd <katalog> [--port N]` finns och validerar projekt, katalog och övrig input.
- [ ] Kommandot skapar en giltig user-unit under `~/.config/systemd/user/<projekt>.service`.
- [ ] Unit-filen innehåller minst `WorkingDirectory` och `ExecStart`, samt ett dokumenterat restart-beteende.
- [ ] Unit-namnet kan inte användas för path traversal eller för att skriva utanför systemd user-katalogen.
- [ ] Befintlig unit skrivs inte över oavsiktligt; beteendet vid konflikt är tydligt och säkert.
- [ ] `systemctl --user daemon-reload` körs efter lyckad skrivning.
- [ ] Portalen registreras eller uppdateras med `kind='systemd'` och det genererade unit-namnet.
- [ ] Portalens request innehåller aldrig startkommandot.
- [ ] En testunit kan startas med systemctl, lyssnar på vald port och kan stoppas igen.
- [ ] CLI:t ger tydliga svenska felmeddelanden vid ogiltig input eller systemd-fel.

## Implementationshänvisningar
Implementera subkommandot i `cli/svc`. Unit-filen är en lokal sidoeffekt och bör skrivas atomärt. Använd systemd-kompatibel hantering av argument i stället för att bygga ett shell-kommando som senare evalueras. Verifiera mot ett avgränsat testprojekt och städa endast de testresurser som skapats av denna uppgift.

- ID: `01KY7XRS7Y8B7HY1GEA3WEBN1V`
- Type: feature
- Actor: ai:claude-code

---

## [P3][done] [portal] Ta bort kända spökposter och dubbletter ur tjänsteregistret

## Kontext
Fyra verifierat döda poster skräpar ned katalogen och försvårar kontrollen av det nya katalogspåret. Städningen är fristående från övriga delar av TASK-354 och ska bara omfatta de uttryckligen angivna posterna.

## Acceptanskriterier
- [ ] Verifiera på nytt att PID och port är inaktiva för `portal-8002`, `portal-8007`, `portal-8009` och `gamlatidtabeller-8871`.
- [ ] Kontrollera `svc list` och tjänsteregistret innan borttagning så att namnen fortfarande avser de kända döda posterna.
- [ ] Ta bort exakt dessa fyra poster och inga andra.
- [ ] Liggaren skrivs om utan de borttagna posterna.
- [ ] `svc list` och `GET /api/services` saknar samtliga fyra efteråt.
- [ ] Den avsedda posten `gamlatidtabeller-8870` finns kvar oförändrad.

## Implementationshänvisningar
Detta är en dataåtgärd via befintligt `svc unregister` eller motsvarande DELETE-endpoint, inte en kodändring. Om någon PID eller port inte längre matchar den dokumenterade situationen ska uppgiften stoppas och omvärderas i stället för att posten tas bort.

- ID: `01KY7XQVEG851YKBBTR9B7KCZG`
- Type: chore
- Actor: ai:claude-code

---

## [P3][todo] [portal] Utgången/saknad delning visar rå JSON istället för snygg felsida

GET /share/{uid}/... för en delning som gått ut eller inte finns svarar med rå JSON: {"detail":"Delningen finns inte eller har gått ut."}. Bör rendera en enkel HTML-felsida (svensk, icke-teknisk, portalens palett) för denna användarvända route istället för JSON. Gäller sannolikt även andra HTML-vända GET-routes.

- ID: `01KY5SSDGM96E788V68K4J5P9N`
- Type: bug
- Actor: ai:claude-code

---

## [P3][done] [portal] Todos-vyn blev spretig - fundera på bättre överblick

Rasmus använder mest backlog-CLI direkt. Portalens todos-sektion på förstasidan känns spretig med många öppna tasks. Idéer att utvärdera: visa bara blockerade tasks, ev. i en gemensam lista över projekt istället för per-projekt. Bör resoneras kring VAD portalens todos-vy ska göra som CLI:t inte gör (annars ta bort/banta den).

- ID: `01KY4691RJJXD34JXF430NCD9H`
- Type: improvement
- Actor: ai:claude-code

---

## [P3][done] [portal] Stöd flera accentfärger i ett tema (exportera följefärger)

Tema-buildern väljer i dag EN accent; harmonischemat/hjulet visar följefärger (komplement/triad osv) i swatchar men de exporteras inte som tokens. Låt ett tema kunna ha mer än en accent: exportera följefärgerna som t.ex. --svk-accent-2/-3 (+ hover/focus/ink och mörkvarianter, samma mönster som --svk-accent) och remappa ev. en sekundär Pico-roll. Öppna frågor: hur många, hur de namnges, och om alla schemats färger ska med eller ett urval. Uppstod ur schema-arbetet 2026-07-19 (TASK-118). Inte brådskande.

- ID: `01KXXQ5GTZRET95PVD3WMHWFXA`
- Type: improvement
- Actor: ai:claude-code

---

## [P3][done] [portal] Fäll bara ihop långa todo-beskrivningar och ge prosa-summary

## Context
TASK-16 la alla task-descriptions i en <details> med summary = första raden. Men alla enhance:ade descriptions börjar med "## Context", så summaryn blir alltid ordet "Context" (värdelös preview). Korta beskrivningar får dessutom en meningslös utfällning som visar samma text igen, och tomma descriptions (t.ex. håvens todos) ger inget att fälla ut alls.

## Acceptance criteria
- [ ] Summaryn previewar faktiskt innehåll: rena rubrik-/listmarkörsrader (t.ex. "## Context") hoppas över, första meningen av prosa används, trunkerad till ~100 tecken.
- [ ] Korta beskrivningar (under en tröskel, eller där summaryn ~ hela texten) renderas inline UTAN <details> - ingen utfällning som visar samma sak.
- [ ] Långa/strukturerade beskrivningar fälls fortfarande ihop i <details> med den nya prosa-summaryn.
- [ ] Tomma descriptions (håvens todos) ger ingen expander och inget tomt <details> - oförändrat korrekt.
- [ ] Ingen horisontell overflow vid 390px och 1280px, kollapsad + expanderad.

## Implementation hints
- app/backlog.py:_shape - description_summary: hoppa över rader som är rena markdown-rubriker/listmarkörer utan prosa; ta första meningen. Överväg ett collapse-fält (True när plain-text-längd > tröskel) som klienten följer.
- app/static/app.js:renderTodoRow - rendera inline (bara description_html) när collapse=False, annars <details>.
- Tröskel t.ex. plain-text > ~160 tecken eller > 2 rader.

## Verifiera (browser)
- håven: ingen expander (tomma descriptions).
- Ett kort fynd: inline, ingen <details>, ingen redundant utfällning.
- Ett långt fynd: hopfällt, summary = en prosamening (inte "Context").
- shot vid 390px OCH 1280px, ingen overflow kollapsad + expanderad; obscura-dump bekräftar. Se browser-verify-skillen.

- ID: `01KXVARFCG90BY2RJYBPH8NMYV`
- Type: bug
- Actor: ai:claude-code

---

## [P3][done] [portal] Rendera task-markdown i portalkorten server-side och fäll ihop långa

## Context
Berikade task-descriptions är strukturerad markdown, men portalkortet visar dem som rå text (`white-space: pre-wrap`) - `## Context`, `- [ ]` osv syns oformaterat och blir rörigt när flera tasks har full spec. Rendera markdown korrekt, och fäll ihop långa beskrivningar (mergat från f.d. TASK-15).

## Acceptance criteria
- [ ] Task-descriptions renderas som formaterad markdown i kortet (rubriker, listor, checkboxar), inte rå text.
- [ ] Rendering sker server-side i /api/todos och skickas som `description_html` - återanvänd `markdown`-libbet som redan används i app/routes/pages.py. Inget nytt frontend-lib, ingen CDN (per CLAUDE.md).
- [ ] Den renderade HTML:en saneras eller begränsas så inget injektionsutrymme öppnas (samma yta som TASK-11 handlar om).
- [ ] Långa beskrivningar fälls ihop: visa Context/första stycket, fäll ut resten på klick (t.ex. <details>). Detaljen finns ändå via deep-linken till backlog web.

## Implementation hints
- app/routes/api.py (backlog._shape eller endpointen): rendera description -> description_html via `markdown.markdown(..., extensions=[...])`, sanera output.
- app/static/app.js:renderTodoRow: injicera description_html (innerHTML) i stället för escapeHtml-text; lägg <details>/collapse för långa.
- app/static/tokens.css: stil för renderad markdown + hopfällning.
- Alternativ om klientrendering föredras: marked.js self-hostad i static/ (aldrig CDN).

## Verifiera (browser)
`obscura`-dump visar renderad markdown i kortet (t.ex. <h2>/<ul>/<li> i description, inte rå `##`). `shot` vid 390px OCH 1280px - ingen horisontell overflow, hopfällningen fungerar. En task vars description innehåller ett citattecken eller HTML injicerar inte. Se browser-verify-skillen.

- ID: `01KXV92ZGADNAHHEB8D82KAGM2`
- Type: improvement
- Actor: ai:claude-code

---

## [P3][done] [portal] Rendera fel per kort i refresh() så ett fetch-fel inte fastnar övriga

## Context
Promise.all över fyra fetchar (services, todos, ports, shares). Om en rejectar sätter catch bara servicesEl, med hårdkodat 'Kunde inte hämta tjänster'. Övriga kort fastnar i placeholder ("Laddar...") tills nästa lyckade refresh.

## Acceptance criteria
- [ ] Ett fel i en fetch lämnar inte de andra korten i evig "Laddar..."-placeholder.
- [ ] Felmeddelandet pekar ut vad som faktiskt fallerade, inte alltid "tjänster".

## Implementation hints
app/static/app.js:refresh(). Överväg Promise.allSettled, eller sätt fel per element.

## Verifiera (browser)
Ta ned en endpoint (t.ex. stoppa backlog-web); ladda portalen och bekräfta att todos/shares/portar renderar ändå. `shot` vid 390px OCH 1280px, ingen horisontell overflow. Se browser-verify-skillen.

- ID: `01KXV7TYSTCDE0WDWTKCE8065M`
- Type: bug
- Actor: ai:code-review

---

## [P3][done] [portal] Fånga AttributeError/TypeError i open_todos så vyn aldrig ger 500

## Context
Om backlog ger giltig icke-objekt-JSON kastar .get('tasks') AttributeError; om project/actor blir icke-dict kastar _shape AttributeError/TypeError. Inget fångas av except-tuppeln -> /api/todos ger rå 500, tvärtemot open_todos docstring ("aldrig en 500").

## Acceptance criteria
- [ ] open_todos returnerar {available: false, error: ...} även vid AttributeError/TypeError.
- [ ] Icke-dict JSON-svar (t.ex. [] eller null) från CLI ger inte en 500.
- [ ] /api/todos svarar alltid 200 med giltig struktur.

## Implementation hints
app/backlog.py: lägg AttributeError, TypeError i except-tuppeln, eller validera isinstance(resultat, dict) innan .get.

## Verifiera
Mocka _run_list att returnera en lista/None; bekräfta available:false och HTTP 200.

- ID: `01KXV7TYSA6EEG8GXWB7WCH6XE`
- Type: bug
- Actor: ai:code-review

---

## [P3][done] [portal] Städa portal-repot och pusha todos-vyn

## Context
Todos-vyn är committad lokalt (main ligger före origin). README nämner inte vyn, och git-export-spegeln backlog.md är otrackad.

## Acceptance criteria
- [ ] README.md nämner todos-vyn i funktionslistan.
- [ ] backlog.md-beslut fattat och verkställt (committad ELLER gitignorerad).
- [ ] Kodfynden i opushad kod (TASK-8, 9, 10, 11, 12) åtgärdade FÖRE push.
- [ ] main pushad till origin.

## OBS - inte helt loop-bar
Pushen är Rasmus beslut - `/backlog-loop` ska INTE pusha själv, så det kriteriet är människo-grindat och Judgen kan inte PASSa det autonomt. Tasken beror dessutom på kluster A (backlog.py-buggarna). Bäst att köra manuellt, inte via loop.

## Implementation hints
README.md, .gitignore/backlog.md.

- ID: `01KXV646FKHSPFTQQW7PF55X06`
- Type: chore
- Actor: ai:claude-code

---

## [P3][done] [portal] Lagg till Todos-sektion i forstasidan

- ID: `01KXV5764CX6564FPW6H89A51B`
- Type: feature
- Actor: ai:claude-code

---

## [P4][done] [portal] Central tema-builder (färghjul + komplementscheman)

Ett centralt verktyg på VM:en (portalen) för att GENERERA temafärger, inte bara förhandsvisa dem. Komplement till theme-preview-skillen (som visar ett befintligt tema): builder:n skapar temat från grunden.

Idé/funktioner:
- Färghjul för att välja bas-/accentfärg.
- Välj harmonischema: komplement, split-komplement, triad/tertiär, analog, monokrom osv. (som coolors.co, Adobe Color, Paletton).
- Generera ljus- OCH mörkvarianter (matchar tokens.css prefers-color-scheme-mönstret) + statusfärger (ok/warn/danger/marker).
- Exportera som en tokens.css-snutt (--svk-accent m.fl.) redo att droppa i ett Pico-projekt.
- Ev. WCAG-kontrastkoll mot bakgrund/knapptext.

Bakgrund: uppstod ur svk-panorama-temaarbetet. theme-preview-skillen scaffoldar en GALLERI-sida i ett projekt; det här skulle vara en fristående GENERATOR på portalen. Referens: coolors.co, color.adobe.com, paletton.com.

Prioritet: idé/backlog - inte brådskande. Nästa steg: bestäm om det blir en portal-vy eller eget litet projekt.

- ID: `01KXX5C6C067FQ99NRHW6GMPBZ`
- Type: improvement
- Actor: human:rasmus

---

## [P4][done] [portal] Visa avkortningsvarning i portalen när truncated=true

Spawnad från TASK-8. /api/todos returnerar nu 'truncated' men app.js visar det inte. När truncated=true, visa en diskret varning i Todos-sektionen (öppna todos kan saknas). Verifiera: obscura-dump visar varningstexten när API:t ger truncated=true.

- ID: `01KXV9MBTQ9EPMAFFNC7MA6SAP`
- Type: improvement
- Actor: ai:claude-opus-4-8

---

## [P4][done] [portal] Lägg till self-hostad favicon i portalen

## Context
Ingen favicon idag - webbläsarfliken visar defaultikon.

## Acceptance criteria
- [ ] En favicon-fil ligger self-hostad i app/static/ (aldrig CDN).
- [ ] templates/index.html <head> refererar den med <link rel="icon">.
- [ ] Filen serveras (GET returnerar 200).

## Implementation hints
app/static/ + app/templates/index.html head. SVG-favicon räcker och skalar. Följ portalens identitet (accent #2563eb).

## Verifiera (browser)
`curl` favicon-URL:en -> 200; `obscura`-dump visar <link rel="icon"> i head. (Flikikonen syns inte i en shot av viewporten, så verifiera via DOM + HTTP.)

- ID: `01KXV8HGSN5GNWMGDDY35HVQ68`
- Type: chore
- Actor: ai:claude-code

---

## [P4][done] [portal] Lås _cache-fyllningen så samtidiga trådar inte spawnar flera subprocesser

## Context
list_todos är sync -> FastAPI-threadpool. check-then-act på modul-globalen _cache saknar lås; vid TTL-utgång kan flera trådar starta backlog-CLI parallellt, tvärtemot docstringens syfte. Benignt (ingen korruption), bara extra processer.

## Acceptance criteria
- [ ] En threading.Lock skyddar cache-läsning + fyllning i open_todos.
- [ ] Vid samtidiga anrop precis efter TTL-utgång startas subprocessen bara en gång.

## Implementation hints
app/backlog.py: threading.Lock runt cache-miss-grenen (double-checked locking).

- ID: `01KXV7TYTW6MCRRN1MH29ATBXG`
- Type: improvement
- Actor: ai:code-review

---

## [P4][done] [portal] Escapa citattecken i attributkontext (escapeHtml) för href/class

## Context
escapeHtml (textContent->innerHTML) escapar inte citattecken. renderTodoRow interpolerar web_url i href och prio i class. web_url byggs server-side av ref (seq/ULID) så ej nåbart idag, men mönsterbristen återanvänds för nytt fält och gäller även svc.url/s.url.

## Acceptance criteria
- [ ] Ett värde med citattecken i ett attribut (href/class) bryter inte ut ur attributet.
- [ ] Befintliga textnod-användningar av escapeHtml påverkas inte.

## Implementation hints
app/static/utils.js:escapeHtml. Antingen attribut-säker variant (ersätt citattecken) eller sätt href via setAttribute i stället för stränginterpolation.

## Verifiera (browser)
Rendera en post där fältet innehåller ett citattecken; `obscura`-dump ska visa att ingen attributbrytning sker (attributet håller ihop). Kontrollera vid 390px och 1280px att inget visuellt bröts.

- ID: `01KXV7TYTDCGYZ2QVDY19BBQF0`
- Type: improvement
- Actor: ai:code-review

---

