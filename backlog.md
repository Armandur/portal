# Backlog Export

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

## [P3][todo] [portal] Stöd flera accentfärger i ett tema (exportera följefärger)

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

