# Roadmap

Idéer för framtida utveckling, i ungefärlig prioritetsordning.

## Nära till hands

- **Statushistorik**: logga uppe/nere/konflikt-övergångar per tjänst i en
  history-tabell och visa senaste händelser på kortet.
- **Städkommando**: `svc prune` som listar registrerade tjänster vars port
  inte längre lyssnar och erbjuder avregistrering (aldrig automatiskt -
  liggarens regler om okänt ägarskap gäller).
- **Reservationsvy**: visa aktiva portreservationer i webbgränssnittet
  och i `svc ports`.

## Senare

- **Auto-discovery-registrering**: förslag i UI:t att registrera en
  oregistrerad lyssnande port med ett klick (förifyllt från ss-datan).
- **Notifieringar**: webhook eller ntfy-push när en tjänst går ner eller
  hamnar i konflikt.
- **Enkla hälsokollar**: valfri HTTP-check per tjänst (GET url_path,
  förväntad status) utöver port-lyssning.
- **Taggning/gruppering**: tagga tjänster (dev/publik/experiment) och
  filtrera kortvyn.
