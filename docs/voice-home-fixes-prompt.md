# CARA — Spec di correzione: Home vocale

## Bug 1: Il bottone microfono non avvia l'ascolto · Bug 2: Sottotitoli desincronizzati e a capo

> **Status**: bloccante per la modalità voice-first. Da risolvere prima di
> proseguire con la roadmap (RAG, smart home, profili famiglia).

---

## <<<INIZIO PROMPT — VOICE HOME FIXES>>>

<extension_request>

# Contesto

La home page voice-first di CARA (`/`) ha due problemi reali osservati
dall'utente:

1. **Il bottone "interroga CARA" non funziona**. L'utente tocca il
   microfono al centro della home (o tocca il volto stesso, che condivide
   il gesto) e CARA non avvia l'ascolto. Nessun feedback visivo, nessuna
   reazione. Sembra muta.

2. **I sottotitoli che mostrano la risposta di CARA sono sbagliati come
   layout e come timing**:
   - vanno a capo su più righe e si **sovrappongono** con la faccia
     animata sopra o con il microfono sotto;
   - l'utente vorrebbe che il testo si comporti come **una unica riga che
     scorre** lateralmente fino alla fine della risposta, mai sovrapposta
     ad altri elementi;
   - il timing del testo è **scollegato dall'audio**: la voce di Piper
     parla, ma le parole nei sottotitoli appaiono in un altro momento (o
     tutte insieme alla fine, o in posizione casuale rispetto all'audio
     reale). L'utente lo vive come "sincronizzazione rotta".

# Obiettivi della correzione

## Bug 1 — Microfono che non risponde

- Diagnosticare la causa esatta. Le possibilità più probabili sono:
  - race condition tra il listener "wake word" sempre attivo e l'STT
    conversazionale richiesto al tap (entrambi vogliono il microfono);
  - il browser non espone `SpeechRecognition` (Firefox su Linux, qualche
    Chromium senza voci) ma la HomePage non lo segnala: il bottone
    sembra cliccabile ma il `start()` esce silenziosamente;
  - permessi del microfono non concessi sul dominio (Chrome Android, iOS
    Safari);
  - context audio bloccato finché non c'è un user-gesture esplicito.
- Risolvere la causa rilevata, NON aggirare. Se è la race del wake word,
  metto un pause sincrono prima di far partire l'STT. Se è il browser
  senza STT, mostro un messaggio chiaro all'utente con suggerimento
  ("apri /chat, qui non hai il microfono").
- Aggiungere feedback visivo robusto:
  - quando il tap arriva a destinazione, animare il bottone
    immediatamente (non aspettare che l'STT si avvii);
  - se l'STT fallisce o è negato il permesso, mostrare un toast/banner
    con messaggio onesto (es. "permesso microfono negato — vai nelle
    impostazioni del browser");
  - log strutturato in console (con prefisso `[cara-voice]`) di ogni
    transizione di stato, così l'utente può catturarli e mandarmeli se
    succede di nuovo.

## Bug 2 — Sottotitoli single-line scrolling sincronizzati

- Riprogettare `<LiveCaption>` per il role `assistant`:
  - **Layout**: una riga sola, `white-space: nowrap`, `overflow: hidden`,
    contenitore `mask-image` con sfumatura agli estremi così le parole
    non appaiono/scompaiono di colpo;
  - **Posizionamento**: deve stare in una banda fissa fra il volto e il
    bottone microfono, mai sovrapposto a nulla. Su mobile, altezza
    minima ~3.5 rem; su desktop ~4.5 rem;
  - **Comportamento**: man mano che CARA parla, le parole "passate"
    scrollano verso sinistra e nuove parole entrano da destra; la parola
    correntemente in pronuncia è centrata e evidenziata
    (es. testo emerald, le passate slate-500, le future leggermente
    fade);
  - **Fine messaggio**: quando l'audio finisce, il testo continua a
    scorrere ancora 1 secondo per far leggere l'ultima parola, poi sfuma
    via in 600 ms.
- **Sincronizzazione audio-testo**:
  - per la voce browser (`SpeechSynthesisUtterance`): usare i `boundary`
    event reali (`event.charIndex` + `event.charLength`), che sono già
    captati dal bus `onSpeakEvent` esistente. Il loro timing è quello
    vero del browser TTS;
  - per Piper (server-side): nel `lib/piperTts.ts` calcoliamo i pulse
    spalmati uniformemente sulla durata dell'audio (`buffer.duration`),
    usando un timer ad alta precisione (`AudioContext.currentTime`) e
    NON `setTimeout` (che drifta). I pulse devono essere driveati dal
    PROGRESSO REALE del playback, non da una stima statica;
  - in entrambi i casi, ogni `pulse` evento porta `{word, charIndex,
    elapsedMs}` e `<LiveCaption>` lo usa per posizionare il cursore;
  - se il modello produce un testo MOLTO lungo (>500 char), il chunking
    di Piper crea utterance multiple in sequenza — il caption deve
    capire dove siamo nel testo concatenato, non resettare ad ogni
    chunk.
- **Edge cases da gestire**:
  - testo in revisione (`event: revision` SSE → l'agent loop sostituisce
    la risposta a metà): il caption deve passare al testo nuovo
    smoothly, magari con un piccolo flash di transizione;
  - utente preme stop (mic button durante speak): il caption smette di
    scorrere e mostra l'ultima parola pronunciata, poi sfuma;
  - voce browser non parla (audio del sistema mutato): il caption deve
    comunque scorrere a velocità "media stimata" (~150 parole/minuto)
    in fallback, così l'utente non vede il testo immobile.

# Vincoli

- **Non riscrivere** `useVoiceConversation` da capo. Mantenere la
  state-machine `idle | listening | thinking | speaking` esistente.
- **Non aggiungere** nuove dipendenze npm. Tutto si fa con CSS standard
  (`transform: translateX`, `mask-image`) + Web Audio API + l'event bus
  `onSpeakEvent` già presente in `lib/speech.ts`.
- **Mantenere accessibilità**: il caption deve avere `aria-live="polite"`
  così gli screen reader leggono comunque tutto il messaggio (la
  scrittura visiva è solo decorazione).
- **Mantenere `prefers-reduced-motion: reduce`**: in quel caso il caption
  NON scrolla, mostra il testo intero in modalità statica (multi-line se
  serve), e si limita ad evidenziare la parola corrente in posizione.

# File da toccare

- `frontend/src/lib/speech.ts` — verificare event bus + handler stop
- `frontend/src/lib/piperTts.ts` — sostituire i `setTimeout` per i pulse
  con un timer guidato da `AudioContext.currentTime` (poll a 60 Hz via
  `requestAnimationFrame` mentre l'audio scorre)
- `frontend/src/lib/voiceConversation.ts` — pause sincrono del wake word
  prima di `startListening()`; log strutturato; surface dell'errore di
  permesso
- `frontend/src/components/MicButton.tsx` — animazione immediata al tap
  indipendente dallo stato di listening (feedback istantaneo)
- `frontend/src/components/LiveCaption.tsx` — riscrittura completa per il
  role `assistant`: single-line scroll, sync su pulse events, auto-scroll
  via `requestAnimationFrame`. Il role `user` (transcript STT live) può
  rimanere multi-line come adesso, è una misurazione diversa
- `frontend/src/routes/HomePage.tsx` — eventuale aggiunta di un banner
  di errore nella top-strip se `conv.sttError` è settato
- `frontend/src/index.css` — keyframe per il fade-out del caption a fine
  messaggio (durata 600 ms)

# Test di accettazione

1. **Mic ok su Chrome desktop con permesso**: tap → bottone si anima
   istantaneamente → STT parte entro 200 ms → "Sto ascoltando…" appare
   sotto la faccia.
2. **Mic ok su iPhone con permesso**: identico al desktop.
3. **Permesso negato**: tap → bottone si anima → toast appare
   ("microfono bloccato dal browser") → state torna a idle.
4. **Browser senza STT (Firefox Linux)**: il bottone è disabilitato a
   livello visivo (icona slate, label "non disponibile") + toast con
   suggerimento di andare a `/chat`.
5. **Wake word + tap entro 2 secondi**: il listener wake word viene
   messo in pause sincrono PRIMA che `startListening` venga chiamato;
   nessun crash, nessun "doppio mic".
6. **Sottotitoli su risposta corta** (1 frase, ~10 parole): tutte le
   parole entrano una alla volta, sincronizzate con la voce, scorrono
   verso sinistra, finiscono al centro pronunciate, poi sfumano via.
7. **Sottotitoli su risposta lunga** (3 frasi, ~50 parole): scorrimento
   continuo, mai a capo, mai sovrapposto al volto. Sync mantenuto fra le
   tre frasi.
8. **Stop a metà**: tap su mic durante speak → audio si ferma → caption
   si congela sull'ultima parola pronunciata → fade-out dopo 600 ms.
9. **Revisione mid-message** (agent loop): caption mostra prima il
   testo allucinato, poi al `revision` event passa smoothly al testo
   grounded — niente flash brutali, niente reset di scroll.
10. **Reduced motion**: utente con `prefers-reduced-motion: reduce` →
    caption è statico multi-line, parola corrente solo evidenziata, no
    scroll.

</extension_request>

## <<<FINE PROMPT — VOICE HOME FIXES>>>

---

## Note di esecuzione

Questo non è un cambio architetturale, è bugfix più rifinitura UX. Effort
stimato 4-6 ore: ~1 h diagnosi + 1 h mic, ~2-3 h LiveCaption riscritto,
1 h test cross-browser e cross-device (desktop Chrome, iPhone Safari,
Android Chromium se disponibile).

Da implementare ora, prima di proseguire con la roadmap.
