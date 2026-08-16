# ADR 0003 — Schema dei tool condiviso e trace come audit trail, non come debug log

## Stato
Accettata

## Contesto
Un agente che ha accesso ai dati finanziari di un cliente e può rispondere
in linguaggio naturale è, nei fatti, un sistema decisionale automatizzato
verso l'utente finale. Anche se questo progetto non rientra nel perimetro
*high-risk* dell'AI Act (non decide su credito, assunzioni, accesso a
servizi essenziali), il principio di **tracciabilità delle decisioni
automatizzate** che l'Art. 12 richiede per i sistemi high-risk è comunque la
pratica corretta per qualunque agente che agisce su dati sensibili.

## Decisione
1. **Uno schema dei tool, due consumatori.** `TOOL_SCHEMAS` in
   `agent/tools.py` segue il formato di function-calling OpenAI (ormai
   standard de facto multi-vendor). Sia `OpenAIClient` che `FakeLLM` leggono
   la stessa lista — non esistono due rappresentazioni dei tool da tenere
   sincronizzate.
2. **`AgentRun.trace` non è un log di debug rimovibile.** È il record
   strutturato, ordinato e con timestamp di ogni passo dell'agente: quale
   tool è stato invocato, con quali argomenti, con quale risultato, prima
   della risposta finale. In produzione questo verrebbe scritto su uno
   store append-only (stesso principio del log immutabile discusso in
   `instant-payments-core/docs/adr/0004`), non tenuto solo in memoria.
3. Il layer di storage (`TransactionStore`) è disaccoppiato dall'agente:
   sostituirlo con un repository Postgres-backed richiede di implementare
   le stesse quattro funzioni pubbliche, senza toccare `agent/core.py` né
   `agent/tools.py`.

## Alternative scartate
- **Loggare solo la risposta finale.** Sufficiente per un chatbot
  "conversazionale", insufficiente per rispondere alla domanda "perché
  l'agente ha detto che spendo 340 € in abbonamenti" — serve il tool
  effettivamente invocato e il suo risultato grezzo.
- **Un logger esterno (es. framework di observability LLM) fin dal primo
  commit.** Rimandato: la trace strutturata qui definita è già il contratto
  minimo corretto; un domani si aggiunge uno *sink* (Langfuse, OpenTelemetry)
  senza cambiare cosa viene tracciato, solo dove viene scritto.

## Conseguenze
- Ogni test sull'agente può assegnare sull'`AgentRun.trace`, non solo sulla
  stringa di risposta finale — è quello che rende `test_agent.py`
  verificabile e non un semplice snapshot testuale.
