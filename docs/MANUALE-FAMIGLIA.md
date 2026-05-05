# Cara — manuale per la famiglia

Aggiornato: 2026-05-05.

> Cara è l'assistente di casa che vive sul NanoPC in salotto. Parla italiano,
> ricorda le tue cose, gestisce task e spesa, e non manda nulla in cloud
> senza il tuo permesso esplicito.

Questo manuale è per chi usa Cara tutti i giorni — non per chi la
configura. Se sei l'admin, vedi `docs/MANUALE-ADMIN.md`.

---

## 1. Come accedere

Apri sul telefono o sul tablet:

- **In casa**: https://192.168.1.23:8455/
- **Fuori casa via VPN WireGuard**: stesso indirizzo dopo aver attivato la VPN

Al primo avvio inserisci email + password. Cara salva il login per
30 giorni — non devi rifare login ad ogni apertura.

**App installabile**: Chrome / Safari → menu → "Aggiungi alla schermata
home". Da quel momento Cara apre come un'app vera, senza barre del
browser.

---

## 2. Le cinque schermate principali

In basso (mobile) o nella barra a sinistra (desktop) hai:

1. **Casa** — la pagina con la faccia di Cara, il mic e le didascalie. È da qui
   che parli a Cara con la voce.
2. **Wallet** — la dashboard personalizzabile con i widget che vuoi vedere
   appena apri l'app.
3. **Chat** — la chat scritta con Cara, come WhatsApp ma con un'AI dentro.
4. **Task** — la lista delle cose da fare (con scadenze + notifiche).
5. **Tu** — il tuo profilo.

In più ci sono **Spesa**, **Note**, **News**, **Radio**, **Memoria**,
**Scoperte** nel menu "Altro" (icona +).

---

## 3. Parlare a Cara

### Iniziare una conversazione

Vai su **Casa**. Tocca la faccia di Cara o il microfono in basso. Inizia a
parlare. Quando hai finito, tocca di nuovo per inviare. Cara ti risponde
a voce.

Se hai attivato la wake word: dì semplicemente **"Cara, …"** e parla
(serve permesso microfono permanente — il browser te lo chiede).

### Cosa puoi chiederle a voce

Tutto quello che fai per scritto puoi farlo a voce:

| Voce | Cosa succede |
|---|---|
| "Cosa puoi fare?" | Elenco di tutte le sue capacità |
| "Aggiungi pane alla spesa" | Aggiunge "pane" alla lista della spesa |
| "Aggiungi pane, latte e uova alla spesa" | Aggiunge tutti e tre |
| "Ricordami di chiamare il dentista" | Crea una task |
| "Ricordami domani alle 9 di chiamare la zia" | Crea una task con scadenza domani 9:00 |
| "Ricordami tra due ore di portare il cane fuori" | Crea task scadenza tra 2h |
| "Cosa devo fare oggi?" | Elenca le task con scadenza oggi |
| "Cosa devo comprare?" | Legge la lista della spesa |
| "Ho comprato il pane" | Marca "pane" come preso |
| "Cancella la task pulire il garage" | Elimina quella task |
| "Quali sono i miei appuntamenti?" | Elenca tutti gli appuntamenti |
| "Mostrami gli appuntamenti di domani" | Filtra per domani |
| "Salvami una nota: chiamare l'idraulico" | Salva una nota |
| "Chi è in casa?" | Riconoscimento facciale dalle telecamere |
| "Che ore sono?" | Risposta istantanea |
| "Quanti giorni mancano a Natale?" | Conta i giorni esatti |
| "Quanto fa 6 per 7?" | Calcolo deterministico (no AI errors) |
| "Che tempo fa domani a Ferrara?" | Cerca su internet |
| "Spiegami cos'è il sistema solare" | Cerca + estrae 2-3 frasi dall'articolo |
| "Mettimi RAI Radio 1" | Avvia la radio |
| "Accendi la luce del salotto" | Comanda Home Assistant |

Se Cara non capisce, ti chiede di ripetere. Se non riconosce un comando,
passa il messaggio al modello AI locale che cerca di rispondere.

### Interrompere Cara

Tocca il mic mentre Cara sta parlando per fermarla. Tocca di nuovo per
ricominciare.

---

## 4. La chat scritta

Vai su **Chat**. Scrivi quello che vuoi — funziona uguale alla voce,
solo che non parla.

### Bottoni nel composer

- 📎 — allega un file (foto, PDF, DOCX, TXT, CSV, XLSX, JSON, YAML, MD).
  Cara lo legge prima di rispondere.
- 🎤 — detta a voce dentro la chat (riempie il campo testo).
- ✨ **Risposta migliore** — manda QUESTO messaggio al cloud (Anthropic
  Haiku) per una risposta più ragionata. Da usare per domande complesse.
  Solo questo turno va in cloud, niente storia. Da attivare in admin se
  off.
- ➤ Invia.

### Foto scontrino → spesa aggiornata

Allega una foto di uno scontrino. Apparirà un bottone **"Analizza"**
sulla pill del file. Toccalo e Cara:

1. Estrae il testo (OCR)
2. Riconosce vendor, totale, articoli, data
3. Mostra una **carta di anteprima** con le azioni proposte:
   - Registrare la spesa nel budget
   - Spuntare gli articoli dalla lista della spesa
4. Tu confermi o annulli con un tap.

Stesso flusso per **bollette in PDF** (riconosce Enel, A2A, TIM, Wind,
scadenza, importo) e **link a ricette** (estrae ingredienti).

Dopo 3 conferme dello stesso tipo, Cara propone di farlo automaticamente
in futuro.

### Pin di un fatto

Sotto ogni tuo messaggio (al passaggio del mouse, sempre visibile su
mobile) c'è un'icona ✨. Toccala per dire a Cara "ricorda quello che ho
appena scritto". Va a finire nella tua memoria personale.

---

## 5. Task

Sezione **Task**. La lista delle tue cose da fare.

### Creare

In alto c'è il campo "Aggiungi una cosa da fare…". Scrivi e premi
Aggiungi. Opzionalmente metti una **scadenza** (data + ora) — riceverai
una notifica 15 minuti prima.

### Modificare

Tocca il titolo per editarlo inline. Enter salva, Esc annulla.

### Riprogrammare o cancellare

Tocca l'icona calendario sulla destra → si apre un pannello con:

- Picker data+ora
- 4 chip rapidi: "Stasera 18:00", "Domani 9:00", "Tra 1 ora", "Senza data"
- Pulsante **Elimina** in mattone

### Marcare fatta

Tocca il quadratino a sinistra. Se la riapri, ridiventa attiva. Una
task fatta resta visibile a meno che non attivi "Nascondi completate".

### Notifiche promemoria

Quando aggiungi una task con scadenza, vedrai un banner che propone
"Vuoi un promemoria sul telefono?". Tocca **Attiva notifiche** → il
browser ti chiede il permesso → accetta. Da quel momento ricevi una
notifica nativa OS, anche con il browser chiuso, 15 minuti prima della
scadenza.

---

## 6. Spesa

Sezione **Spesa**. La lista della spesa condivisa con tutta la famiglia.

- Aggiungi un articolo dal campo in alto, oppure dicendo "Aggiungi X
  alla spesa" alla voce.
- Tocca un articolo per spuntarlo (preso).
- Lo swipe (mobile) o l'icona cestino lo elimina.

Quando uno di famiglia segna "preso" un articolo, gli altri lo vedono
sparire dalla lista in tempo reale.

---

## 7. Note

Sezione **Note**. Note rapide auto-salvate mentre scrivi.

- Click su "+ Nuova nota" oppure dì "Salvami una nota: ..."
- Le note hanno titolo (prima riga) e corpo.
- Nessun limite di lunghezza pratico.

---

## 8. Appuntamenti

Non c'è una sezione separata: gli appuntamenti sono task con una
scadenza impostata. Per vederli tutti insieme:

- A voce: "Quali sono i miei appuntamenti?", "Cosa ho in programma
  domani?", "Mostrami gli impegni di questa settimana".
- In chat: stessa cosa.
- In Task: filtra con la cinella in alto.

---

## 9. La tua memoria

Sezione **Memoria**. Tutto quello che Cara ricorda DI TE.

I fatti possono arrivare da:

- **tu hai detto** — hai scritto/detto "ricorda che..." o cose
  che Cara ha riconosciuto come fatti espliciti.
- **rilevato automaticamente** — hai detto "sono allergico a X" e Cara
  ha riconosciuto il pattern.
- **salvato manualmente** — hai pinnato un messaggio in chat con ✨.

Per ogni fatto puoi:

- ✏️ **Toccare il testo** per editarlo.
- ✓ **Disattivarlo** (Cara non lo userà ma resta nello storico).
- 🗑 **Cancellarlo definitivamente**.

In fondo alla pagina:

- **Esporta JSON** — scarica un backup di tutta la tua memoria (GDPR).
- **Cancella tutto** — purge completo, niente undo.

---

## 10. Wallet

Sezione **Wallet**. La dashboard personalizzabile.

Ognuno della famiglia può scegliere quali widget vedere:

- **Genitore impegnato** (preset): riassunto giornata, task in scadenza,
  spesa, budget, presenza famiglia.
- **Adolescente** (preset): scuola, amici, news, radio.
- **Bambino sicuro** (preset): solo quello che ti serve a 8 anni.
- **Anziano essenziale** (preset): grandi card con poche info.

Per personalizzare:

1. Vai su Wallet.
2. **Preset** apre uno dei 4 setup pronti.
3. **Aggiungi** apre il catalogo dei widget (una decina disponibili).
4. **×** su un widget lo rimuove.
5. **Mobile / Desktop / Parete** sopra il Wallet ti permette di avere
   layout diversi per superficie.

I widget si aggiornano da soli. Tap su un widget per andare alla pagina
relativa.

---

## 11. Notifiche promemoria

Già spiegate sopra (sezione Task), ricapitolo:

1. Crea una task con scadenza.
2. Quando appare il banner "Vuoi un promemoria sul telefono?", tocca
   **Attiva notifiche**.
3. Concedi il permesso al browser.
4. Da quel momento, 15 min prima di ogni scadenza, arriva una notifica
   nativa OS sul telefono, anche con browser chiuso.

Cosa serve per riceverle:

- Browser moderno (Chrome / Safari iOS 16+ / Firefox).
- Permesso notifiche concesso.
- Connessione internet (le notifiche arrivano dal server VPN/WiFi).

---

## 12. Privacy

- **Tutto resta in casa**. Voce, chat, foto degli scontrini, fatti
  ricordati: nulla esce dal NanoPC tranne che per esplicita richiesta
  ("Risposta migliore" cloud).
- **Cancellazione totale**: GDPR-friendly. Vai su Memoria → Cancella
  tutto. La tua memoria sparisce. Le tue task/note/spesa restano (sono
  tue, non "memoria").
- **Riconoscimento facciale**: la telecamera Frigate identifica chi è
  in casa solo per il widget "Chi è in casa". Se non vuoi essere
  riconosciuto, chiedi all'admin di disattivare il facial recognition.

### Privacy delle email (Gmail)

Se hai connesso Gmail (`/me/integrazioni`), vale questa garanzia
esplicita:

- **Le email che hai non lette restano non lette.** Cara non rimuove
  MAI l'etichetta "Non letto" da una tua email. Quando apri Gmail
  dopo che Cara ha proposto un task partendo da un messaggio, il
  pallino blu del "non letto" è esattamente dove l'hai lasciato.
- Cara legge solo i messaggi delle ultime 24 ore, salta promozioni
  e social automaticamente.
- Nessun corpo email viene salvato sul NanoPC — solo un'anteprima
  di 200 caratteri associata alla proposta che vedi su `/me/proposte`.
- Niente risposte automatiche, niente cancellazioni, niente etichette,
  niente inoltri. Cara è un lettore strettamente passivo.
- Disconnetti in qualsiasi momento da Connessi → Disconnetti Gmail.
  La revoca avviene anche lato Google: il token diventa invalido
  immediatamente.

---

## 13. Cosa fare se Cara non risponde

1. **Rete**: vedi un banner rosso "Offline"? Riconnettiti al WiFi.
   Le modifiche fatte offline restano in coda e si sincronizzano
   automaticamente quando torni online.
2. **Voce non funziona**: il browser ha bisogno del permesso microfono.
   Vai nelle impostazioni del sito (icona lucchetto nell'URL bar) e
   abilita il microfono.
3. **Cara è muta**: TTS richiede una voce installata. Vai in **Tu →
   Impostazioni** e scegli un'altra voce.
4. **Risposta lenta**: il modello AI locale è veloce ma non istantaneo.
   La prima domanda dopo molto silenzio prende ~15 secondi (è il
   "warm-up"). Le successive sono molto più rapide.
5. **Cara dice cose strane**: il modello locale (1.5 miliardi di
   parametri) ha dei limiti. Per domande complesse, usa il bottone
   **✨ Risposta migliore** che manda la domanda al cloud (più preciso,
   ma esce di casa).

---

## 14. Comandi rapidi cheatsheet

Stampa questa pagina e mettila sul frigo.

| Comando | Effetto |
|---|---|
| "Cosa puoi fare?" | Elenco capacità |
| "Cosa devo fare oggi?" | Task di oggi |
| "Aggiungi X alla spesa" | Spesa |
| "Ricordami di X domani alle 9" | Task con scadenza |
| "Ho comprato pane" | Marca pane preso |
| "Quali sono i miei appuntamenti?" | Tutti gli appuntamenti |
| "Salvami una nota: X" | Salva nota |
| "Chi è in casa?" | Riconoscimento facciale |
| "Che ore sono?" | Ora |
| "Quanto fa N per M?" | Calcolo |
| "Mettimi radio X" | Avvia radio |
| "Le notizie di oggi" | News |
| "Buona notte" | Cara va in standby |

---

## 15. Aggiornamenti

Cara si aggiorna automaticamente. Quando viene rilasciata una nuova
versione, l'app ricarica da sola (ti potresti perdere un secondo di
contenuto a schermo). I tuoi dati non vengono mai toccati.

L'ultimo changelog è sempre in `docs/CARA-CHANGELOG.md`.

Domande tecniche? Chiedi all'admin di casa (Antonio).
