# CARA — Spec di correzione: cattura STT e stop sul tap

## Bug 3: "Sto ascoltando" parte ma la frase non viene mai intercettata · Bug 4: il secondo tap non interrompe

> **Status**: bloccante per la modalità voice-first. Continuazione del round
> precedente (`voice-home-fixes-prompt.md`) — i due bug residui dopo il primo
> giro di fix.

---

## <<<INIZIO PROMPT — STT CAPTURE FIX>>>

<extension_request>

# Sintomi osservati

L'utente, dopo la deploy del round precedente, riporta:

1. *"Il pulsante si attiva, scrive 'Sto ascoltando' ma non intercetta la
   domanda, non la scrive."* CARA visualmente entra in stato `listening`,
   il microfono mostra l'animazione rossa, ma **la trascrizione non
   compare** sotto la faccia e di conseguenza **niente viene mai
   inviato** al backend. La conversazione resta bloccata in `listening`
   finché il timeout del browser non chiude da solo la sessione (o
   l'utente non clicca un'altra cosa).

2. *"Quando ripremo il pulsante non interrompe."* L'utente prova a
   uscire dallo stato `listening` toccando di nuovo il microfono, ma
   nulla cambia: nessuna submit, nessuno stop, nessun ritorno a `idle`.

# Diagnosi probabile

- L'STT è in modalità `continuous = false`. Su iOS Safari (e Chrome
  Android in alcune versioni) l'API `SpeechRecognition` chiude la sessione
  alla prima micro-pausa dell'utente. Quando l'utente parla con un
  attimo di esitazione (frequente, soprattutto in italiano dove ci sono
  pause naturali tra "Cara…" e la frase), il browser termina senza mai
  emettere un `onresult` con `isFinal = true`.
  Il nostro codice attualmente fa la submit SOLO su `isFinal`, quindi
  l'interim transcript viene buttato via.
- Lo `start()` durante `phase === 'listening'` fa `listenRef.current?.stop()`
  ma NON usa il contenuto interim che intanto è arrivato. Il cleanup di
  `onEnd` poi setta phase a `idle` senza submit. L'utente percepisce il
  tap come "non funziona".
- Manca un fallback: se l'utente preme di nuovo, va comunque catturato
  quello che ha già detto (anche se incompleto) e mandato al modello, NON
  cestinato.

# Obiettivi della correzione

## Capture robusto

- Modalità `continuous = true` per il riconoscitore conversazionale,
  così non chiude alla prima pausa.
- Tracciare l'**ultima trascrizione interim** in un `useRef`
  (`interimRef`), aggiornato dentro `onText` insieme a `setUserText`.
  In questo modo abbiamo sempre disponibile il transcript più recente
  anche quando l'evento isFinal non arriva mai.
- All'arrivo di `isFinal === true` con testo non vuoto: submit
  immediato come oggi.
- All'arrivo di `onEnd` (sessione chiusa dal browser per silenzio /
  timeout / errore "no-speech") **se** abbiamo un `interimRef` non
  vuoto, fare la submit comunque. Con un piccolo timer di 300 ms così
  diamo all'eventuale `isFinal` finale (che a volte arriva subito
  prima di onEnd) la priorità.

## Stop con submit-or-cancel intelligente

- Quando l'utente preme il bottone durante `listening`:
  1. Stoppa il recognizer (`handle.stop()`).
  2. Annulla `interimRef` come "consumato" così onEnd non fa una
     seconda submit.
  3. Se `interimRef` ha del testo (anche solo poche parole) → submit
     subito al backend, vai in `thinking`.
  4. Se `interimRef` è vuoto → vai a `idle` (l'utente ha annullato).
- Aggiungi un `cancelByTap` distinto da `submit-on-end` per non
  duplicare le submit.

## Diagnostica avanzata

- In `lib/speech.ts::startListening`, log di TUTTI gli eventi
  `SpeechRecognition` con prefisso `[cara-stt]`:
  `onstart`, `onaudiostart`, `onspeechstart`, `onresult` (con
  `transcript` e `isFinal`), `onspeechend`, `onaudioend`, `onnomatch`,
  `onerror` (con `error`), `onend`. Questo ci permette di vedere ESATTAMENTE
  cosa sta succedendo sul dispositivo dell'utente quando il bug si
  ripresenta.
- In `voiceConversation.ts`, log su ogni transizione di `interimRef` e
  ogni decisione di submit / cancel.

## UX di feedback

- Sotto al microfono in stato `listening`, mostrare la trascrizione
  interim in tempo reale (già fatto via `LiveCaption` user-mode), ma
  ESPLICITAMENTE renderla visibile anche con poche lettere (oggi viene
  collapsed se `text` è vuoto e arriva pulse-tardi).
- Etichetta dinamica del bottone: "Sto ascoltando…" → "Tocca per
  inviare" quando interimRef è popolato. Questo orienta l'utente sul
  cosa fare.

# Vincoli

- Niente nuove dipendenze npm.
- Mantenere il comportamento esistente per browser TTS e Piper TTS.
- Mantenere il banner d'errore introdotto nel round precedente.
- Mantenere il wake-word lifecycle e la pause sincrona prima di
  startListening.

# File da toccare

- `frontend/src/lib/speech.ts` —
  `startListening`: aggiungi tutti gli event handlers diagnostici
  + parametro `continuous` opzionale (default true per il path
  conversazionale, false per il wake word) + propagazione del
  testo interim più recente nel callback `onText` (già fatto, ma
  asseverarne la robustezza).
- `frontend/src/lib/voiceConversation.ts` —
  - aggiungi `interimRef` (ref a string),
  - aggiorna `onText` per scrivere in `interimRef` insieme a
    `setUserText`,
  - in `start()` quando phase=='listening' usa `interimRef.current` per
    decidere submit vs cancel,
  - in `onEnd`, se phase=='listening' E `interimRef.current` ha testo
    non vuoto E non abbiamo già fatto submit, fai submit con piccolo
    delay di 300 ms (così se arriva un isFinal nel frattempo prevale).
  - reset `interimRef` ad ogni nuovo `start()`.
- `frontend/src/components/MicButton.tsx` —
  accetta opzionalmente una `label` runtime per "Tocca per inviare"
  quando l'utente sta ascoltando ed ha già detto qualcosa.
- `frontend/src/routes/HomePage.tsx` —
  passa label dinamica al MicButton in base a `conv.phase` e
  `conv.userText` (`if listening && userText.trim() → "Tocca per inviare"`).

# Test di accettazione

1. **Frase con pausa naturale**: utente dice "Cara… fammi ascoltare la
   radio". Recognizer va in pausa per ~600 ms tra "Cara" e "fammi". Con
   continuous=true il recognizer continua. La frase intera viene
   raccolta e inviata al backend con isFinal.
2. **Frase senza isFinal mai**: utente parla, recognizer chiude per
   silenzio prima di emettere isFinal. Il fallback su onEnd con
   interimRef pieno triggera una submit dopo 300 ms.
3. **Tap secondo durante listening con interim popolato**: utente dice
   "che giorno è" e tocca il mic. Submit immediata di "che giorno è",
   passaggio a `thinking`.
4. **Tap secondo durante listening con interim vuoto**: utente tocca il
   mic, ci ripensa, lo tocca di nuovo prima di parlare. Cancel pulito,
   ritorno a `idle`, niente submit di stringa vuota.
5. **Errore di permesso**: rifiuto microfono → banner rosso (già
   funzionante dal round precedente), nessun cambio rispetto a oggi.
6. **Log diagnostici visibili**: ogni evento del recognizer appare in
   console con prefisso `[cara-stt]` ordinato cronologicamente.
7. **Etichetta dinamica**: durante listening con userText vuoto =
   "Sto ascoltando…"; appena arrivano parole = "Tocca per inviare".

</extension_request>

## <<<FINE PROMPT — STT CAPTURE FIX>>>

---

## Note di esecuzione

Effort stimato: 1-2 ore. Solo frontend, niente backend, niente nuove deps.
