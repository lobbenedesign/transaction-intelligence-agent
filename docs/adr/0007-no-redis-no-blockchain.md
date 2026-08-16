# ADR 0007 — Nessun Redis, nessuna blockchain

## Stato
Accettata

## Contesto
Due domande distinte, sollevate esplicitamente: serve un sistema stile
Redis? Serve una blockchain?

## Decisione: Redis — non nello scope attuale, ma è il secondo candidato più chiaro del portfolio dopo `psd3-open-banking-gw`
Non aggiunto, ma il commento già presente in `api/main.py` sopra
`_sessions` lo dice esplicitamente: quel dizionario python
(`session_id -> messages`) è **in-memory e per-processo**, esattamente lo
stesso trade-off dichiarato per `TransactionStore`. Per una demo a singola
istanza è corretto. Per un deployment reale multi-istanza, la sessione di
chat multi-turno (docs/adr/0006) smetterebbe di funzionare in modo
affidabile: una richiesta instradata a un'istanza diversa da quella che ha
gestito il turno precedente non troverebbe la history in memoria, e la
conversazione "dimenticherebbe" il contesto in modo silenzioso e
imprevedibile — il tipo di bug che si nota solo in produzione sotto carico.

Redis è la risposta naturale a questo problema specifico: le sessioni di
chat sono per natura dati con TTL (una conversazione abbandonata non deve
vivere per sempre) e devono essere condivise fra repliche — esattamente le
due proprietà che un semplice `dict` non ha e Redis fornisce nativamente
(`SETEX` per sessione). Non implementato qui perché farlo contro un
singolo processo locale senza un secondo nodo da testare avrebbe prodotto
un adattatore Redis mai verificato sotto le condizioni per cui esiste.

## Decisione: blockchain — non pertinente
Non aggiunta. Questo agente legge dati transazionali che la banca (o
l'utente, tramite un aggregatore autorizzato) già possiede — non c'è un
problema di consenso multi-parte da risolvere. Il tool-call trace
(`docs/adr/0003`) esiste per rendere le azioni dell'agente ispezionabili
da un revisore umano, non per farle concordare fra attori indipendenti: un
log append-only in un database relazionale copre questo bisogno
interamente. Stessa conclusione, per ragioni analoghe, negli ADR
equivalenti degli altri repository di questo portfolio.

## Conseguenze
- Nessun cambiamento di codice da questo ADR.
- Se questo servizio venisse deployato multi-istanza, il primo cambiamento
  architetturale sarebbe spostare `_sessions` su Redis con TTL — non una
  riscrittura, perché l'interfaccia già usata (`_sessions.get(session_id,
  [])` / assegnazione) mappa direttamente su `GET`/`SETEX`.
