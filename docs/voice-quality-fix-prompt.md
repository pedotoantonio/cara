# CARA — Spec di correzione: trascrizione lenta/imprecisa + risposte fuori tema

## Bug 5: STT trascrive lentamente · Bug 6: trascrizione imprecisa · Bug 7: la risposta non rispetta la domanda

> **Status**: bloccante per la voice-first. Sequenza dei round precedenti
> (`voice-home-fixes-prompt.md`, `voice-stt-capture-fix-prompt.md`).

---

## <<<INIZIO PROMPT — VOICE QUALITY FIX>>>

<extension_request>

# Sintomi

L'utente segnala dopo l'ultima deploy:

1. *"È molto lento nella trascrizione di quello che sente."* L'interim
   nella caption arriva con ritardo apprezzabile rispetto al parlato; il
   submit avviene tardi e la risposta vocale di CARA arriva ancora più
   tardi. Sensazione complessiva: "ho parlato e CARA è in ritardo".
2. *"Non trascrive bene quello che ascolta."* Il transcript ricostruito
   dal browser SR è impreciso (parole mancate, parole sostituite,
   articoli divorati). Conseguenza: la query inviata al backend NON è
   quella pronunciata.
3. *"Risponde non rispettando la domanda."* CARA risponde a UN'ALTRA
   domanda. Possibili tre cause concorrenti:
   - il router intent appena introdotto sta classificando una richiesta
     ambigua come comando radio/news/tasks (false positive);
   - il transcript è già sbagliato per via del Bug 6, e il LLM risponde
     coerentemente alla query SBAGLIATA;
   - il LLM (1.5B) si distrae e risponde alla domanda PRECEDENTE perché
     nel prompt c'è ancora la cronologia.

# Diagnosi probabile

## Lentezza percepita (Bug 5)

- L'interim browser SR è praticamente real-time (~50-200 ms di lag).
  Quando l'utente percepisce "lentezza nella trascrizione" probabilmente
  parla del **time-to-first-token della risposta di CARA**, non
  dell'interim. Il TTFT è 6-12 s sul 1.5B sotto carico Frigate.
- Comunque, anche l'interim può sembrare lento se il browser
  inserisce un buffer audio prima del primo onresult. Per accenti meno
  comuni iOS Safari prende 1-2 s prima di emettere il primo interim.

## Trascrizione imprecisa (Bug 6)

- Il browser SR è un servizio del produttore (Apple/Google), non
  controlliamo né il modello né l'accento. Per italiano:
  - Apple "Siri ASR": OK su Paolo/Paola standard, debole su accenti
    regionali.
  - Google Chrome ASR (cloud): solitamente migliore per italiano
    standard, peggio offline.
- `maxAlternatives` di default è 1: il browser dà SOLO la trascrizione
  più probabile, scartando silenziosamente alternative valide.
- Niente filtraggio "did you mean": una mis-recognition diventa input
  per il LLM senza correzioni.

## Risposte fuori tema (Bug 7)

- **Pattern troppo greedy nel router**: la regola audio `(?:fammi
  ascoltare|metti(?:mi)?|accendi|riproduc[ei])\s+(?:la\s+)?(?:radio\s+)?(.+)`
  è ANCHE-troppo-permissiva. La frase "metti a posto la cucina" non
  parla di radio MA matcha la regex e finisce in `discover_audio
  query="a posto la cucina"`. Stessa cosa per
  "fammi sentire bene", "accendi la luce" e altre richieste smart-home.
- **Trascrizione mediocre amplifica il problema**: una mis-recognition
  cambia "metti il latte alla spesa" → "metti il latte alla", che
  potrebbe matchare altre regole.
- **Cronologia conversazione**: il LLM vede gli ultimi 7 turni con
  troncamento a 400 char. Se il transcript del turno corrente è povero,
  il modello può "ricostruire" la domanda dai turni precedenti
  rispondendo a quella vecchia.

# Obiettivi della correzione

## A — Tightening del router (eliminare false positive)

- La regola `discover_audio` deve richiedere ESPLICITAMENTE una delle
  parole chiave dominio: `radio|stazione|podcast|musica`, oppure il
  prefisso "fammi sentire/ascoltare" SENZA che la parte dopo possa
  contenere verbi di azione fisica ("metti a posto", "accendi la
  luce", "spegni").
- Aggiungere una **stop-list** di sostantivi che, anche se presenti,
  bloccano il match radio: `luce, luci, lampada, finestra, porta,
  riscaldamento, condizionatore, allarme, cucina, salotto, camera`.
  Quando uno di questi compare, il router NON cattura: la richiesta
  passa al LLM (o, in futuro, all'integrazione smart-home).
- Stessa logica per le altre regole con `(?P<q>.+)` aperto: controllare
  che il `q` non sia palesemente fuori dominio.

## B — Migliorare il transcript

- Settare `maxAlternatives = 3` sul `SpeechRecognition` e prendere
  l'alternativa con confidence più alta (esposta su Chrome; Safari la
  ignora ma non danneggia).
- Aggiungere debounce di 300 ms sulla submit dopo `isFinal`: se nel
  frattempo arriva una nuova alternativa più lunga, vince quella. Tipico
  caso iOS dove la stessa frase arriva due volte in rapida sequenza,
  la seconda è solitamente più completa.
- Esporre nella `<LiveCaption>` un'icona piccolissima (✏︎) che permette
  all'utente di **correggere** prima della submit: tap su icona →
  appare un input editabile con il transcript, conferma → submit.
  Da-fare dopo l'auto-submit, come retry.

## C — Migliorare l'allineamento risposta-domanda

- Inserire all'inizio del prompt LLM, subito DOPO la persona e PRIMA
  della cronologia, una riga di "FOCUS" che esplicita la domanda
  corrente e istruisce il modello: *"Rispondi SOLO a questa domanda.
  Non rispondere a domande di turni precedenti."*
- Quando il router decide di non matchare, e la domanda è ambigua o
  troppo corta (< 6 caratteri di sostanza), CARA invece di chiamare il
  LLM dovrebbe chiedere un chiarimento: *"Non ho capito bene, puoi
  ripetere?"* — meglio una pausa pulita di una risposta inventata.
- Su `interim` ricevuti dopo `isFinal` con testo molto diverso (>50%
  edit-distance), considera la possibilità che il browser stia
  correggendo: aspetta 500 ms, prendi la più recente, submit. Già
  parzialmente coperto dalla logica `submittedRef`, ma vale la pena
  tightening.

## D — Visibilità del problema (debug)

- Aggiungere all'evento SSE `done` un campo `routed: <kind>` quando il
  router ha catturato la query. Già presente nel codice del router
  (`routed: routed.kind`), ma non esposto nella UI: la `Chat` page
  potrebbe mostrare un piccolissimo badge in fondo alla bolla "scoperto
  via radio shortcut" così l'utente capisce perché ha avuto quella
  risposta.
- I log `[cara-stt]` continuano a esistere, ma aggiungere uno
  **strumento admin** "Diagnosi voce" che cattura gli ultimi 20 eventi
  STT con timestamp + transcript + tempo trascorso, così quando
  ricapita possiamo vederlo senza F12.

# Vincoli

- Niente cambi di engine STT in questa iterazione (il fallback Whisper
  è già lì come opzione, ma cambiare il default riduce la velocità reale
  da ~200 ms a ~3-5 s di upload+decode — peggio per la latenza
  percepita).
- Non toccare l'agent loop (R3 della migrazione Lumo): è ortogonale.
- Mantenere il routing tier-1: la maggior parte dei false positive
  arriva da regole troppo larghe, non dall'idea del routing.

# File da toccare

- `backend/cara/services/intent_router.py` — tighten `discover_audio`
  + stop-list smart-home + proteggere altre regex con `(?P<q>.+)`
  aperti.
- `backend/cara/api/v1/chat.py` — aggiungi una "FOCUS line" subito
  prima dell'ultimo user turn nel prompt LLM; opzionalmente filtra
  query troppo brevi/sospette prima di invocare il LLM.
- `frontend/src/lib/speech.ts::startListening` — `maxAlternatives = 3`,
  scegli alternativa con confidence più alta nel callback `onresult`,
  estendi log `[cara-stt]` con la confidence.
- `frontend/src/lib/voiceConversation.ts` — debounce 300-500 ms su
  isFinal: se entro la finestra arriva un transcript più lungo, prendi
  quello.
- *(opzionale, fuori prima iter)* `frontend/src/components/LiveCaption.tsx`
  — pulsante ✏︎ per correzione manuale del transcript prima del submit.

# Test di accettazione

1. **Stop-list smart-home funziona**: "metti a posto la cucina" →
   non più `discover_audio`, NESSUN match → LLM. "accendi la luce
   in salotto" idem.
2. **Radio match preservato**: "metti rai radio 1", "fammi ascoltare
   radio capital", "accendi la radio" → tutti `discover_audio`.
3. **maxAlternatives**: il primo SR di una frase complessa restituisce
   2-3 alternative; il backend riceve la più lunga / con confidence
   più alta.
4. **Debounce iOS**: pronunciato "che ore sono", il browser emette due
   risultati in rapida sequenza ("che ore" final + "che ore sono"
   final). Il secondo arriva entro 500 ms → solo "che ore sono" viene
   inviato.
5. **FOCUS line nel prompt**: il LLM, dato un turno breve precedente
   ("ciao") e un turno corrente ambiguo ("a Roma?"), risponde alla
   nuova domanda — non ricicla la risposta del turno "ciao".
6. **Query troppo corta → chiarimento**: input transcript di 1-3
   caratteri o di sole stop-word ("ehm", "uhm", "ok") → CARA chiede
   "non ho capito, puoi ripetere?" senza chiamare il LLM.

</extension_request>

## <<<FINE PROMPT — VOICE QUALITY FIX>>>
