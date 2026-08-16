# ADR 0001 — Il core dell'agente non dipende da un vendor LLM specifico

## Stato
Accettata

## Contesto
Il progetto deve dimostrare un pattern agentico (tool-calling, loop
ReAct, audit trail) più che le capacità di un modello specifico. In un
contesto bancario reale, la scelta del provider LLM (hosted vs on-prem,
EU-hosted per data residency, cambio di vendor per costi o per policy di
governance AI) è una decisione che si ripresenta più volte nel ciclo di
vita di un prodotto — non è una decisione "una volta per tutte" presa in
fase di design.

## Decisione
Il pacchetto `txnagent.llm` espone un `Protocol` (`LLMClient.complete`) con
due sole responsabilità: ricevere `(system_prompt, messages, tools)` e
restituire o del testo o una lista di `ToolCall`. Nessun modulo fuori da
`txnagent/llm/` importa un SDK di un vendor specifico.

Sono forniti due client concreti:
- `FakeLLM`: deterministico, basato su regole, zero dipendenze esterne e
  zero chiavi API. È il client di default in test, demo CLI e servizio
  FastAPI — chiunque clona il repo e lancia `make demo` ottiene un output
  riproducibile bit-per-bit, senza configurare nulla.
- `OpenAIClient`: wrapper sottile sull'SDK `openai`, compatibile anche con
  endpoint self-hosted (vLLM, TGI) via `base_url`. Si attiva automaticamente
  se `OPENAI_API_KEY` è settata.

## Alternative scartate
- **Hardcodare l'SDK OpenAI ovunque.** Più veloce da scrivere, ma lega
  irreversibilmente agent loop e tool schema a un vendor. Il primo
  cambio di provider richiederebbe di riscrivere `agent/core.py`.
- **Usare un framework agentico general-purpose (LangChain/LangGraph).**
  Valutato e scartato per questo progetto specifico: la superficie di
  astrazione necessaria è piccola (un loop di 4 step, 3 tool), e un
  framework generico avrebbe nascosto la logica dietro livelli di
  indirection che qui non aggiungono valore dimostrativo. In un contesto
  di produzione con orchestrazioni più complesse (multi-agente, subgraph
  paralleli) la scelta sarebbe diversa — è un trade-off dichiarato, non un
  rifiuto categorico.

## Conseguenze
- Testare l'agent loop non richiede mock di rete né chiavi API: `FakeLLM`
  gioca lo stesso ruolo architetturale di un vero LLM.
- Il costo è che `FakeLLM` non generalizza a domande non previste dalle sue
  regole — è un limite dichiarato in README, non nascosto.
