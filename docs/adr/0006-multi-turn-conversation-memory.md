# ADR 0006 — Memoria conversazionale multi-turno

## Stato
Accettata

## Contesto
`TransactionAgent.ask()` nella v1 era senza stato: ogni chiamata costruiva
`messages` da zero con un solo messaggio utente, eseguiva il loop, e
scartava tutto alla fine — un follow-up come "e il mese scorso?" dopo
"quanto ho speso in ristoranti?" non aveva modo di essere risolto, perché il
turno precedente semplicemente non esisteva più per il modello. È esattamente
la differenza fra un router di comandi singoli e un assistente
conversazionale. Cleo, il prodotto consumer più citato nel confronto
competitivo di questo README, ha lanciato la memoria a lungo termine come
funzionalità di punta della sua versione 3.0 (2025) — non è un dettaglio
implementativo, è una capacità che l'utente percepisce direttamente.

## Decisione
1. `TransactionAgent.ask(query, history=None)` accetta un transcript
   `AgentRun.messages` precedente e lo antepone al nuovo messaggio utente. Il
   budget `MAX_STEPS` resta per-turno, non cumulativo sull'intera
   conversazione — un problema di un turno non deve consumare il budget dei
   turni successivi.
2. `AgentRun` guadagna il campo `messages`: il transcript completo del
   turno, comprese le risposte finali (prima mancanti — vedi sotto),
   restituito al chiamante per essere passato al turno successivo.
3. `api/main.py` aggiunge un session store in-memory (`_sessions`,
   `MAX_SESSION_MESSAGES = 20`) keyed su un `session_id` generato o
   riutilizzato: `POST /chat` accetta un `session_id` opzionale e lo
   restituisce sempre nella risposta, così un client può continuare la
   conversazione senza gestire lo stato lato proprio.
4. Corretto un bug scoperto implementando questa feature: il loop non
   appendeva mai la risposta testuale finale dell'assistente a `messages`
   prima di restituire — un secondo turno costruito su quel transcript
   avrebbe visto la domanda dell'utente e i tool-call intermedi, ma non
   *cosa aveva risposto l'agente*. Ora `messages.append({"role":
   "assistant", "content": answer})` avviene su entrambi i percorsi di
   uscita (risposta normale e fallback per step esauriti).

## Alternative scartate
- **Memoria semantica/vettoriale** (embedding delle conversazioni passate,
  retrieval per rilevanza) — quello che "long-term memory" spesso significa
  nei prodotti citati nella ricerca. Scartata per questo scope: aggiunge una
  dipendenza (vector store) e un livello di non-determinismo che il resto
  del progetto evita deliberatamente (docs/adr/0002); la memoria a transcript
  completo è sufficiente per il caso d'uso "continua questa conversazione" e
  resta ispezionabile riga per riga nell'audit trail.
- **Stato lato client** (il chiamante rimanda l'intero transcript ad ogni
  chiamata, niente session store server-side). Più semplice da implementare,
  ma sposta sul client la responsabilità di non perdere lo stato e apre alla
  possibilità che un client malevolo inietti un transcript arbitrario nel
  contesto del modello — il session store server-side, per quanto in-memory
  e non ancora persistente, tiene il confine di fiducia dove deve stare.

## Conseguenze
- `FakeLLM` non usa la history per il routing (legge solo l'ultimo messaggio
  utente, docs/adr/0001) — la memoria multi-turno per `FakeLLM` è quindi
  plumbing testato ma senza effetto osservabile sulla risposta finché non
  viene collegato `OpenAIClient`, che invece riceve e usa l'intera
  `messages` list per costruzione (nessuna modifica necessaria lì: era già
  agnostico dal contenuto della history).
- Il session store è in-memory e process-local (stesso trade-off dichiarato
  per `TransactionStore`, docs/adr/0003): non sopravvive a un riavvio, non
  funziona dietro un load balancer con più istanze senza affinità di
  sessione. Estensione naturale: Redis o una tabella con TTL, a interfaccia
  invariata (`_sessions` è già un semplice `dict[str, list[dict]]`).
