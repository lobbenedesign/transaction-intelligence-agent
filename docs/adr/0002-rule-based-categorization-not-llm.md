# ADR 0002 — La categorizzazione delle transazioni è basata su regole, non su LLM

## Stato
Accettata

## Contesto
Ogni transazione postata su un conto deve essere categorizzata
(subscription, utilities, groceries, ...). Un cliente retail genera
tipicamente centinaia-migliaia di transazioni l'anno; su scala di
portafoglio clienti, questo significa milioni di classificazioni.
L'agente conversazionale, al contrario, gestisce query saltuarie
dell'utente.

## Decisione
La categorizzazione (`txnagent.detection.categorize`) è un classificatore
deterministico a regole/keyword, eseguito in-process su ogni transazione al
caricamento nello store. L'agente LLM non ricategorizza mai le transazioni:
le riceve già categorizzate come risultato dei tool (`list_transactions`,
`sum_spending_by_category`).

## Motivazione
- **Costo e latenza**: una chiamata LLM per transazione, a quel volume, è
  economicamente insostenibile e introduce una dipendenza di rete su un
  path che deve restare veloce e disponibile.
- **Auditabilità**: un regolatore (o un cliente che contesta una categoria)
  deve poter ricostruire *perché* una transazione è stata classificata in un
  certo modo. Una regola per keyword è ispezionabile a colpo d'occhio; una
  classificazione LLM richiederebbe di loggare l'intero prompt/risposta per
  offrire lo stesso livello di spiegabilità.
- **Determinismo**: la stessa transazione deve produrre sempre la stessa
  categoria. I modelli LLM, anche a temperatura 0, non garantiscono questo
  in modo affidabile tra versioni di modello diverse.

## Conseguenze
- Il classificatore ha un fallback esplicito a `OTHER` con confidenza bassa
  (0.3) quando nessuna regola matcha — non forza mai una categoria non
  giustificata.
- Il limite dichiarato: il classificatore a regole non generalizza a nuovi
  merchant fuori dal dizionario. In un'estensione futura, la strategia
  naturale è un modello di classificazione supervisionato (non un LLM
  general-purpose) addestrato sulle correzioni manuali degli utenti,
  mantenendo la stessa interfaccia `categorize(transaction) -> (Category,
  confidence)` — non richiederebbe di toccare l'agente.
