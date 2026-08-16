# ADR 0004 — Una chiamata a strumento fallita non deve mai interrompere il loop dell'agente

## Stato
Accettata

## Contesto
`name` e `arguments` di un `ToolCall` arrivano dalla scelta del modello, non da
codice applicativo fidato. Con `FakeLLM` questo non si vede mai, perché il
router a keyword genera solo chiamate valide per costruzione — ma con un vero
LLM (`OpenAIClient`) è un evento ordinario: il modello può passare una
categoria fuori dall'enum (`sum_spending_by_category(category="dining out")`
invece di `"entertainment"`), un argomento con nome sbagliato, o il nome di
uno strumento inesistente per un refuso interno del modello. La prima
versione di `ToolRegistry.dispatch` chiamava l'handler senza try/except:
qualunque di questi casi propagava l'eccezione fino a `TransactionAgent.ask`,
terminando l'intera richiesta con un errore non gestito — su un endpoint che
risponde su dati finanziari di un cliente, un 500 opaco è il comportamento
peggiore possibile.

## Decisione
`ToolRegistry.dispatch` cattura `ValueError` (valore fuori enum, tipicamente
da `Category(category)`) e `TypeError` (argomento non atteso o mancante) e le
trasforma in un risultato strutturato `{"_tool": name, "error": "..."}`,
restituito al chiamante come se fosse un normale risultato di tool. Il layer
che sintetizza la risposta (`FakeLLM._synthesize`, e in prospettiva il
prompt che un vero modello riceve come `tool` message) riconosce la chiave
`error` e produce una risposta onesta ("non sono riuscito a recuperare
questo dato") invece di tentare di leggere campi che non esistono nel
risultato.

## Alternative scartate
- **Validare gli argomenti con Pydantic prima della chiamata.** Più
  strutturato, ma per tre strumenti con parametri quasi tutti opzionali
  aggiunge un livello di indirection (schema Pydantic + schema tool
  OpenAI-style da tenere sincronizzati) senza un guadagno proporzionato in
  questo scope. Diventerebbe la scelta giusta con più strumenti o parametri
  obbligatori — non qui.
- **Lasciare che l'eccezione propaghi e farla gestire da un middleware FastAPI
  generico.** Risolverebbe il 500 lato HTTP (vedi comunque
  `unhandled_exception_handler` in `api/main.py` come rete di sicurezza per
  errori davvero imprevisti), ma non aiuta il modello a *recuperare* dentro
  il loop ReAct: un vero LLM può leggere l'errore e riprovare con argomenti
  corretti solo se l'errore gli torna come risultato di tool, non se la
  richiesta HTTP muore prima.

## Conseguenze
- `tests/test_tools.py` verifica esplicitamente tool sconosciuto, categoria
  non valida e argomento inatteso: nessuno dei tre casi solleva un'eccezione,
  tutti tornano un dizionario con `error`.
- Un vero LLM (`OpenAIClient`) che sbaglia un argomento riceve l'errore nel
  messaggio `tool` del turno successivo e può correggersi entro
  `MAX_STEPS = 4`, invece di far fallire la conversazione al primo errore.
