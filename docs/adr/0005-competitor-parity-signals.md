# ADR 0005 — Tre segnali aggiunti per parità con i prodotti di categoria

## Stato
Accettata

## Contesto
Il rilevamento ricorrenze della v1 rispondeva a una sola domanda: "quali
pagamenti ricorrenti esistono?". I prodotti di riferimento nel settore
(Plaid Recurring Transactions come infrastruttura B2B, Rocket Money e Cleo
come prodotto consumer) rispondono anche a tre domande che la v1 non poteva
rispondere, perché il dato necessario non veniva calcolato affatto — non era
solo un tool mancante nell'agente, mancava il segnale a monte:

1. **"Questo abbonamento è aumentato di prezzo?"** — Rocket Money invia alert
   dedicati per gli aumenti di prezzo delle sottoscrizioni, oltre a
   canoni annuali dimenticati e servizi duplicati.
2. **"Ho abbonamenti che si sovrappongono?"** — stesso alert Rocket Money,
   sui "duplicate charges" e servizi ridondanti.
3. **"Questa è già una serie affidabile o l'hai appena vista?"** — Plaid
   restituisce esplicitamente uno status `early_detection` per gli stream
   con meno di 3 occorrenze osservate, invece di ometterli silenziosamente
   fino a maturazione.

## Decisione
1. `RecurringSeries` guadagna le property computate `first_amount`,
   `last_amount`, `price_change_pct`, `price_increased`
   (`PRICE_INCREASE_THRESHOLD = 5%`, `models.py`) — pure funzioni della
   history di transazioni già presente sull'oggetto, nessun nuovo stato da
   sincronizzare.
2. `RecurringSeries.status: SeriesStatus` (`early_detection` |
   `established`) sostituisce il comportamento precedente in cui una serie
   con 2 occorrenze veniva trattata esattamente come una con 12: ora è
   ancora restituita (non nascosta, a differenza di chi aspetta 3+
   occorrenze per mostrare qualcosa) ma etichettata onestamente.
   `ESTABLISHED_MIN_OCCURRENCES = 3` in `detection/recurring.py` replica
   esattamente la soglia di Plaid.
3. Nuovo modulo `detection/duplicates.py` con
   `find_overlapping_subscriptions`: raggruppa le serie per categoria e
   segnala le categorie con 2+ commercianti distinti — deliberatamente
   ristretto a `SUBSCRIPTION` ed `ENTERTAINMENT` (vedi
   `OVERLAP_CATEGORIES`), perché due fornitori attivi in `UTILITIES` o
   `RENT_MORTGAGE` è normale, non un segnale di spesa ridondante.
4. Tre nuovi tool (`list_price_increases`, `list_subscription_overlaps`,
   più i campi `status`/`price_increased` aggiunti al payload di
   `list_recurring_series`) e i corrispondenti endpoint REST
   (`/price-increases`, `/subscription-overlaps`).

## Alternative scartate
- **Un solo tool "insights" onnicomprensivo** che restituisce aumenti,
  sovrapposizioni e nuove serie in un'unica chiamata. Più comodo per un
  singolo giro di query, ma perde la possibilità per il modello (o un vero
  LLM) di chiedere selettivamente solo ciò che serve — e rende il singolo
  payload più difficile da testare in isolamento (`tests/test_tools.py`
  verifica ogni tool sulla propria forma esatta).
- **Confronto prezzo su tutta la serie** (regressione lineare sull'importo
  nel tempo) invece di solo primo-vs-ultimo. Più robusto al rumore, ma
  richiede più occorrenze di quante ne servano per essere "established" e
  aggiunge complessità statistica che il confronto diretto non giustifica
  ancora a questa scala — un'estensione naturale se il segnale
  primo-vs-ultimo si rivelasse troppo sensibile al rumore in pratica.

## Conseguenze
- Nessun re-training o nuova classe di modello: tutti e tre i segnali sono
  funzioni pure di dati già raccolti dal detector esistente — coerente con
  `docs/adr/0002` (niente black-box dove una regola spiegabile basta).
- `PRICE_INCREASE_THRESHOLD` fisso al 5% è una scelta di giudizio
  ingegneristico, non calibrata su un dataset reale di variazioni tariffarie
  italiane — stesso limite dichiarato per le soglie VoP in
  `instant-payments-core/docs/adr/0002`.
- Il rilevamento di sovrapposizione è per categoria, non per tipo di
  servizio: due abbonamenti SUBSCRIPTION vengono sempre segnalati insieme
  anche se in realtà sono, ad esempio, Netflix e una palestra — falsi
  positivi plausibili che un utente scarta in un secondo, non un errore che
  nasconde informazione.
