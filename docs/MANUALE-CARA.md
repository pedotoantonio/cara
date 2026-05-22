# CARA — Manuale di casa

> *La tua assistente di casa Pedoto.*
>
> Versione del manuale: 2026-05-22 · Per la famiglia, per gli ospiti.

---

## Indice

1. [Cos'è CARA in 30 secondi](#1-cosè-cara-in-30-secondi)
2. [Come accedo](#2-come-accedo)
3. [Parlare con CARA — la voce](#3-parlare-con-cara--la-voce)
4. [Le mie cose da fare (Task)](#4-le-mie-cose-da-fare-task)
5. [La spesa di famiglia](#5-la-spesa-di-famiglia)
6. [Le mie note](#6-le-mie-note)
7. [Promemoria — Vita Quotidiana](#7-promemoria--vita-quotidiana)
8. [Calendario, meteo, news, radio](#8-calendario-meteo-news-radio)
9. [Memoria e profilo personale](#9-memoria-e-profilo-personale)
10. [Casa intelligente (luci, tapparelle, telecamere)](#10-casa-intelligente-luci-tapparelle-telecamere)
11. [CARA via Telegram](#11-cara-via-telegram)
12. [Il display da parete (Wall)](#12-il-display-da-parete-wall)
13. [Notifiche push](#13-notifiche-push)
14. [Riconoscimento del volto](#14-riconoscimento-del-volto)
15. [Cose che CARA capisce a voce — frasario](#15-cose-che-cara-capisce-a-voce--frasario)
16. [Per i bambini](#16-per-i-bambini)
17. [Per l'amministratore (Antonio)](#17-per-lamministratore-antonio)
18. [Risoluzione problemi](#18-risoluzione-problemi)
19. [Cosa CARA non sa fare ancora](#19-cosa-cara-non-sa-fare-ancora)

---

## 1. Cos'è CARA in 30 secondi

CARA è una **persona digitale di casa**, non un'app. Vive sul piccolo
computer NanoPC-T6 nascosto sopra l'armadio dello studio, non manda
niente di tuo su internet (tranne quando lo decidi tu), e parla
italiano.

Sa fare cose pratiche di tutti i giorni:

- 💬 chiacchierare e rispondere a domande
- 🎤 ascoltare quando parli al microfono
- ✅ gestire **task** (cose da fare)
- 🛒 gestire la **lista della spesa** di famiglia
- 📝 prendere **note** veloci
- ⏰ ricordarti **promemoria** (compleanni, visite mediche, scadenze)
- 📅 vedere il **calendario** unificato
- 🌤️ darti **meteo, news, radio**
- 💡 spegnere e accendere **luci, tapparelle, scenari** in casa
- 📸 riconoscere i **volti** della famiglia (opzionale)
- 🤖 inviarti **notifiche** sullo schermo o su Telegram

Tutto questo da telefono, tablet, computer, o dal display da parete.

---

## 2. Come accedo

### Da casa (WiFi famiglia o WireGuard VPN)

Apri il browser e vai a:

```
https://192.168.1.23:8456/
```

**Login automatico**: se sei sulla rete di casa o connesso alla VPN
WireGuard, CARA ti riconosce subito senza chiederti password.

Se ti chiede credenziali:
- **Email**: la tua (es. `pedotoa@gmail.com`)
- **Password**: quella che ti ha dato Antonio

### Da fuori casa (dati mobile, internet pubblico)

L'accesso esterno richiede la connessione VPN WireGuard sul tuo
telefono. Antonio ti darà il file di configurazione (`.conf`) o un
QR code. Una volta connesso alla VPN, vale come essere a casa.

In alternativa, c'è un accesso pubblico via Cloudflare Tunnel se
attivo (chiedi ad Antonio).

### Installare CARA come app sul telefono

#### iPhone / iPad (Safari)
1. Apri `https://192.168.1.23:8456/`
2. Tocca l'icona **Condividi** (il quadrato con la freccia in alto)
3. Scorri e tocca **"Aggiungi a Home"**
4. CARA appare come app, con la sua icona

#### Android (Chrome)
1. Apri `https://192.168.1.23:8456/`
2. Tocca il menù **⋮** (tre puntini)
3. Scegli **"Installa app"** (o "Aggiungi a schermata Home")
4. CARA appare nella lista app

#### Computer (Chrome / Edge)
1. Apri `https://192.168.1.23:8456/`
2. Vedi un'icona piccola **"+"** nella barra degli indirizzi
3. Cliccala → **"Installa"**

### Permessi al primo accesso

Al primo accesso CARA chiede 4 permessi (puoi accettarli tutti, o
saltarne alcuni, e cambiare idea dopo da **Tu → Impostazioni**):

| Permesso | A cosa serve |
|---|---|
| 🎤 **Microfono** | Per ascoltarti quando parli |
| 🔔 **Notifiche** | Per ricordarti le cose importanti |
| 📍 **Posizione** | Per il meteo "dove sei" e promemoria sui luoghi |
| 📷 **Fotocamera** | Per riconoscerti quando torni a casa (opzionale) |

---

## 3. Parlare con CARA — la voce

### Come iniziare a parlare

#### Dalla Home
Tocca il grande pulsante rosa **"Parla con me"** al centro della
schermata principale. CARA inizia ad ascoltarti.

#### Da qualsiasi altra pagina
In basso a destra c'è sempre l'avatar piccolo di CARA (la "compagna"
che ti segue). **Tieni premuto** il volto per 1 secondo → CARA
inizia ad ascoltare subito.

#### Dalla chat
Apri la **Chat** (icona ChatCircle nel menù in basso) → c'è un
pulsante mic accanto al campo di testo.

### Come parlare

1. Aspetta che CARA dica "Sto ascoltando" (vedi l'avatar pulsare)
2. Parla normalmente, come a una persona
3. Quando smetti di parlare per 1 secondo, CARA capisce e va avanti
   (puoi anche premere "Ho finito")
4. CARA ti mostra cosa ha capito ("Hai detto: …")
5. Se è sicura, risponde subito. Se non è sicura, ti chiede conferma
   prima di proseguire

### Cosa fare se CARA "non capisce"

- **Parla più vicino al microfono** del telefono
- **Parla più lentamente** (la trascrizione automatica fatica con
  voci troppo veloci o sussurrate)
- **Riprova** premendo "Parla ancora"
- Se ti dice "Ho capito bene?", controlla il testo: se è giusto
  tocca "Sì, è giusto", se è sbagliato "Riprova"
- Se inventa risposte strane = la frase non era abbastanza chiara,
  riformula

### Cambiare il tono di voce di CARA

Vai su **Tu → Impostazioni → Tono della voce**. Scegli fra:

| Tono | Quando usarlo |
|---|---|
| **Standard** | Caldo e diretto, va bene per quasi tutto |
| **Calmo** | Frasi brevi, pause naturali. Perfetto per la sera |
| **Energico** | Vivace, propulsivo. Buono al mattino |
| **Formale** | Usa il "lei", registro educato. Per le situazioni in cui serve |
| **Giocoso** | Leggerezza e ironia gentile. Bambini lo adorano |

Il cambio è immediato sulle prossime risposte. Ogni membro della
famiglia ha il **suo** tono indipendente.

---

## 4. Le mie cose da fare (Task)

### Dove

Menù in basso → **Liste** → tab **Task**.

### Cosa puoi fare

#### Aggiungere una task

**A voce**:
> "Aggiungi alla mia lista: chiamare il dottore"
> "Aggiungi una task: comprare la batteria del telecomando"
> "Ricordami di parlare con il professore di Sara"

**Da UI**:
- Nella tab Task, c'è un campo "Nuova task — premi invio"
- Scrivi e premi Invio
- Se vuoi una scadenza: sotto al campo c'è un selettore data/ora
  opzionale

#### Marcare completata

Tocca il **cerchio verde** a sinistra. Diventa una spunta. Le task
completate vanno nella sezione "Fatte" in fondo.

#### Modificare

Tocca il **titolo** della task. Si apre l'editor inline. Modifica
titolo o scadenza, poi premi "Salva".

#### Eliminare

Tocca il **cestino** a destra. CARA chiede conferma (tocca di nuovo
entro 2 secondi). Una task eliminata è irrecuperabile.

#### Vedere le task in scadenza

In **Home** CARA mostra automaticamente i **Prossimi 3** impegni
(task + promemoria + eventi calendario), ordinati per data.

---

## 5. La spesa di famiglia

### Dove

Menù in basso → **Liste** → tab **Spesa**.

### Cosa puoi fare

#### Aggiungere alla lista

**A voce**:
> "Aggiungi pomodori alla spesa"
> "Aggiungi due chili di pane alla spesa"
> "Ho bisogno di detersivo per i piatti"

**Da UI**:
- Campo "Aggiungi alla spesa — es. pomodori"
- Scrivi e premi Invio

#### Marcare come comprato

Quando sei al supermercato e prendi un articolo, **tocca il
cerchietto rosa** a sinistra → l'articolo va in "Già comprate" in
fondo.

#### Vedere solo da comprare

Le sezioni sono separate automaticamente: "Da comprare" sopra,
"Già comprate" sotto.

#### Pulire la lista dei comprati

Tocca "Pulisci" accanto alla sezione "Già comprate". Rimuove tutti
gli articoli marcati come acquistati, lascia quelli ancora da
comprare.

### Lista condivisa

La spesa è **della famiglia**: Antonio, Marina, Sara, Matteo possono
aggiungere e marcare comprato. Sara e Matteo (bambini) vedranno una
nota "in attesa di approvazione" sui loro articoli, finché un adulto
non li conferma (vedi sezione [Per i bambini](#16-per-i-bambini)).

---

## 6. Le mie note

### Dove

Menù in basso → **Liste** → tab **Note**.

### Cosa puoi fare

- **Crea una nota**: tocca "Nuova nota" → si apre l'editor
- **Scrivi**: testo libero (poesie, idee, ricette, indirizzi…). CARA
  salva automaticamente dopo 1 secondo che hai smesso di scrivere
- **Elimina**: tocca "Elimina" nell'editor
- **Cerca**: dalla lista, usa la ricerca in alto

Le note sono **private**: solo tu vedi le tue note. Non sono mai
condivise con la famiglia a meno che tu non lo decida (funzione in
arrivo).

---

## 7. Promemoria — Vita Quotidiana

### Dove

Menù in basso → **Liste** → tab **Promemoria**.

### Cosa sono

Sono i **promemoria importanti** della vita quotidiana, distinti dalle
task pratiche. Tipo:

- 🎂 Compleanno della nonna (ogni 12 marzo)
- 🩺 Visita dal cardiologo (martedì 25 alle 10:30)
- 📄 Scadenza carta d'identità (fra 30 giorni)
- 💊 Promemoria farmaco quotidiano alle 9
- 🏫 Riunione con i professori di Sara

### Come crearne uno

**A voce**:
> "Ricordami di chiamare il dottore domani alle 16:30"
> "Tra 20 minuti controlla il forno"
> "Ogni lunedì alle 9 butta la carta"
> "Ricordami il compleanno di mamma il 12 marzo"

**Da UI**: tab Promemoria → "Nuovo promemoria" → scegli categoria
(famiglia / salute / documenti / eventi) → compila il form guidato.

### Quando CARA ti ricorda

- **24 ore prima** della scadenza (notifica "preparati")
- **2 ore prima** della scadenza
- **All'orario** esatto

Puoi rispondere:
- ✅ **Fatto** — il promemoria sparisce (o si rinnova se ricorrente)
- ⏰ **Tra 1 ora** — rimanda di 60 minuti
- ⏰ **Domani** — rimanda di 24 ore

### Categorie disponibili

| Categoria | Cosa metterci |
|---|---|
| 👨‍👩‍👧 **Famiglia** | Compleanni, anniversari, eventi familiari |
| ❤️ **Salute** | Visite mediche, farmaci, controlli |
| 📄 **Documenti** | Scadenze CI, patente, bollette, abbonamenti |
| 🎉 **Eventi** | Scuola, sport, riunioni, appuntamenti |

---

## 8. Calendario, meteo, news, radio

### Dove

Menù in basso → **Vita** → 4 tab.

### Calendario (tab 1)

- Vedi una griglia del **mese corrente** con eventi + task + promemoria mergiati
- I diversi tipi sono codificati per colore:
  - 🟢 mint = task
  - 🟠 corallo = promemoria
  - 🔵 cielo = eventi (Google Calendar)
- Tocca un giorno per vedere il **dettaglio** di tutto quello che
  succede
- Sopra puoi navigare avanti/indietro fra mesi

### Meteo (tab 2)

- **Adesso**: temperatura corrente di Ferrara, icona condizione
  attuale, percepito
- **Prossimi 7 giorni**: card per giorno con max/min, icona, pioggia
  prevista
- Le icone seguono il sistema WMO standard (sole, nuvole, pioggia,
  neve, temporale, nebbia)

### News (tab 3)

- Notizie dei principali feed italiani aggregati (Corriere, Repubblica,
  Sole24Ore, RaiNews, ANSA, ecc.)
- Categoria, fonte, ora di pubblicazione
- Tocca un articolo → apre l'originale in una nuova scheda

### Radio (tab 4)

⚠️ Funzionalità in arrivo. Per ora chiedi a CARA via voce: *"Metti
Radio Capital"* — gestita dal modulo CDA.

---

## 9. Memoria e profilo personale

### Dove

Menù in basso → **Tu** → due sezioni:

- **Profilo persona**
- **Memoria**

### Profilo persona — il "chi sei"

CARA costruisce automaticamente un **profilo longitudinale di te**
basato sulle vostre conversazioni. Lo aggiorna **ogni notte alle
3:15** (durante il sonno, niente disturbi).

Il profilo contiene 9 sezioni:

- Identità (chi sei, dove vivi, lavoro)
- Famiglia
- Lavoro
- Abitudini
- Gusti
- Salute
- Valori
- Stato emotivo recente
- Relazioni

Ogni fatto è classificato:
- **STABILE** = cose che durano (sei allergico ai pomodori)
- **EPISODICO** = cose recenti (stamattina eri stanco)

#### Cosa puoi fare

- **Vedere** il tuo profilo → cosa CARA sa di te, leggibile
- **Aggiornarlo subito** (bottone "Aggiorna ora", massimo 1 volta
  ogni 30 minuti)
- **Cancellarlo** se non ti va bene (irreversibile — GDPR)

CARA usa questo profilo per rispondere in modo più personale. Tipo
quando ti saluta al mattino con "Buongiorno Antonio" invece di "Buongiorno utente".

### Memoria — i fatti specifici

In **Tu → Memoria** vedi tutti i singoli **fatti** che CARA ha
imparato di te (separati per tipo: preferenze, allergie, abitudini,
informazioni personali).

Puoi:

- **Eliminare** singoli fatti se non ti piacciono
- **Esportare** tutto in JSON (per scaricare i tuoi dati)
- **Cancellare tutta la memoria** con doppia conferma (irreversibile)

---

## 10. Casa intelligente (luci, tapparelle, telecamere)

### Cosa controlla CARA

CARA è collegata a **Home Assistant** che a sua volta parla con i
dispositivi di casa. Oggi può:

- ✅ Vedere il **meteo** in casa (sensori temperatura/umidità)
- ✅ Riconoscere chi è **a casa** (presence detection)
- 🔧 In configurazione: luci, tapparelle, prese smart, TV (LG, Samsung)
- 📷 **Telecamere** Frigate: vedere il feed live dei 4 ingressi

### Come usarla

**A voce** (quando le luci saranno configurate):
> "Accendi la luce del salotto"
> "Spegni tutte le luci di sotto"
> "Apri le tapparelle della camera di Sara"

**Da admin** (`/admin/smart-home`): vedere lo stato di tutti i
dispositivi, mappare alias italiani (es. "lampada nonno" → entity HA
specifica).

### Permessi per ruolo

| Ruolo | Cosa può fare |
|---|---|
| Antonio (admin) | Tutto |
| Marina (parent) | Tutto |
| Sara (teen) | Luci stanza sua + soggiorno |
| Matteo (child) | Luci stanza sua |
| Ilaria (elder) | Luci, tapparelle, niente sicurezza |
| Ospiti (guest) | Niente |

---

## 11. CARA via Telegram

C'è un **bot Telegram** dedicato che fa da accesso secondario.
Comodo quando sei fuori casa e non vuoi aprire l'app.

### Bot

Nome bot: **@cara_pedoto_bot**

Per attivarlo: chiedi ad Antonio (deve registrare il tuo `chat_id`
in `/admin/telegram`).

### Cosa puoi fare via Telegram

#### Scrivere
Manda un messaggio normale. CARA risponde come nell'app — stesso
LLM, stesse skill.

#### Vocale
Mandi una **nota vocale** → CARA la trascrive con Whisper → risponde
in testo (e in vocale se hai attivato `notify_voice_message_enabled`).

#### Comandi slash

| Comando | Cosa fa |
|---|---|
| `/oggi` | Riassunto della giornata: task, eventi, meteo |
| `/domani` | Cosa hai domani |
| `/settimana` | Riepilogo settimanale |
| `/appuntamenti` | Solo i tuoi eventi calendario |
| `/spesa` | La lista della spesa (`/spesa add pane` per aggiungere) |
| `/note` | Le tue note (`/note new Lunedì visita`) |
| `/task` | Le task (`/task Comprare patate`) |
| `/meteo Ferrara` | Meteo della città indicata |
| `/casa` | Stato della casa (sensori, presenza) |
| `/news sport` | Notizie filtrate per categoria |
| `/cam ingresso` | Snapshot live di una telecamera |
| `/diag` | Diagnostica sistema (admin) |
| `/qr` | QR code per riconnettersi alla VPN |
| `/credenziali` | Le credenziali principali (admin only) |
| `/reboot` | Riavvia il sistema (admin only) |
| `/help` | Lista comandi |

#### Azioni inline
I promemoria e le notifiche su Telegram hanno **bottoni inline**:
✅ Fatto · ⏰ Tra 1h · ⏰ Domani · ✕ Ignora. Tocca per agire senza
scrivere niente.

---

## 12. Il display da parete (Wall)

### Cos'è

Una **superficie pubblica** pensata per un tablet o monitor sempre
acceso in cucina/ingresso. Niente login, mostra le info di tutta la
famiglia.

### Dove

```
https://192.168.1.23:8456/wall
```

Solo dalla rete di casa o VPN (l'accesso esterno è bloccato).

### Cosa mostra

- ⏰ **Orologio gigante** + data lunga in italiano
- 🎭 **Avatar CARA** che reagisce in tempo reale (qualcuno è
  arrivato, CARA sta parlando, ecc.)
- 🌤️ **Meteo** di Ferrara (icone custom: sole, nuvole, pioggia,
  neve…)
- 👥 **Presence**: chi è in casa adesso
- 📅 **Oggi**: timeline di eventi + task con colori per proprietario
- 📅 **Settimana**: vista 7-giorni
- 📅 **Calendario**: vista mese completa
- 🛒 **Spesa**: lista raggruppata per categoria (frutta/verdura,
  latticini, ecc.)
- 📷 **Telecamere**: rotazione delle telecamere Frigate (refresh 6s)
- 📰 **News ticker** in basso, scrolling continuo
- 🎤 **Microfono push-to-talk** in alto a destra (parla, CARA
  risponde a voce ad alta voce)

### Wake word "CARA"

Sul Wall puoi attivare l'**ascolto continuo della parola "CARA"**.
Quando la pronunci, parte la registrazione e CARA ti risponde.

⚠️ Funziona solo su Chrome / Edge (Web Speech API). Su Safari /
Firefox usa il pulsante manuale.

### Voci famiglia

Ogni membro ha il suo **colore + emoji** sulle chip:
- Antonio: 🦁 emerald
- Marina: 🌺 rose
- Sara: 🦋 sky
- Matteo: 🐯 amber
- Ilaria: 🌹 violet

---

## 13. Notifiche push

### Cosa ti arriva

CARA ti manda notifiche per:

- 🔔 **Promemoria** che scattano (24h prima, 2h prima, all'orario)
- 📧 **Email importanti** estratte da Gmail (proposte di task)
- 🌧️ **Allerte meteo** (se piove forte all'orario in cui esci di
  solito)
- 👋 **Buongiorno / buonasera** se hai attivato i suggerimenti
  proattivi
- 🚪 **Door open long** (porta lasciata aperta > 5 min)
- 🛒 **Spesa weekend** (sabato mattina riepilogo)
- 🎂 **Compleanni** (la mattina, fra famiglia/amici)
- ⚠️ **Task in scadenza** (24h prima della deadline)

### DND (Do Not Disturb)

Di default, le notifiche **non urgenti** sono **silenziate dalle
22:00 alle 07:00**. Le urgenti (farmaci, promemoria critici) passano
sempre.

Antonio può cambiare l'orario silenzioso da `/admin` → Funzionalità
→ "Notifiche orari silenziosi".

### Bundling

Se ti arrivano **5+ notifiche in 5 minuti**, CARA le **raggruppa in
una sola** ("5 novità da CARA"). Niente bombardamento.

### Attivare / disattivare

**Tu → Impostazioni → Notifiche → Attiva/Disattiva**

Quando attivi, il browser ti chiede il permesso. Se neghi, devi
abilitarle a mano nelle impostazioni del browser.

Su iOS: serve iOS 16.4+ in modalità PWA installata (non in Safari
browser). Su Android: Chrome funziona da anni.

---

## 14. Riconoscimento del volto

### Cosa fa

CARA può **riconoscerti dalla webcam** del telefono o display. Quando
ti vede:

- Saluta col tuo nome ("Ciao Sara!")
- Adatta il **tono** alla persona (saluti formali per Antonio,
  giocosi per Matteo)
- Non mostra contenuti privati di altri (es. se Marina è davanti al
  telefono di Antonio, CARA non legge ad alta voce un promemoria
  personale di Antonio)
- I bambini vedono solo i contenuti adatti alla loro età

### Come abilitarlo

1. Vai su `https://192.168.1.23:8455/face/enroll` (su v1 per ora)
2. Concedi il permesso fotocamera
3. Segui il wizard 6-step: 5 pose diverse del tuo volto + conferma
4. Fatto: CARA ti riconosce nelle prossime sessioni

### Privacy

- ✅ **Niente foto** lascia mai il telefono. CARA salva solo un
  vettore matematico di 128 numeri che rappresenta il tuo volto
- ✅ Tutta l'elaborazione è **on-device** (face-api.js in un Web
  Worker)
- ✅ Puoi **cancellare** il tuo profilo volto in qualsiasi momento
  (`/face` → "Elimina")
- ✅ Consenso esplicito + datato registrato in audit log

### Se sei un ospite

Gli ospiti **non sono mai riconosciuti** (per design). CARA mostra
"Qualcuno è arrivato" e non legge contenuti privati.

---

## 15. Cose che CARA capisce a voce — frasario

Una raccolta di frasi che funzionano:

### Task

- "Aggiungi alla mia lista chiamare il dottore"
- "Aggiungi una task: comprare la batteria"
- "Cosa devo fare oggi?"
- "Quali sono le mie task in scadenza?"

### Spesa

- "Aggiungi pomodori alla spesa"
- "Aggiungi due chili di pane alla spesa"
- "Cosa c'è nella lista della spesa?"
- "Ho preso il latte" (segna come comprato)

### Note

- "Scrivimi un appunto: lunedì ho la visita medica"
- "Trovami le note sui medici"

### Promemoria

- "Ricordami di chiamare il medico domani alle 16:30"
- "Tra 20 minuti controlla il forno"
- "Ogni lunedì alle 9 butta la carta"
- "Ricordami il compleanno di nonna il 12 marzo"

### Meteo

- "Che tempo fa?"
- "Pioverà domani?"
- "Quanti gradi ci sono a Ferrara?"
- "Mi serve l'ombrello?"

### News

- "Quali sono le novità nelle news?"
- "Notizie di sport"
- "Cosa è successo oggi?"

### Casa

- "Spegni le luci del salotto" (quando configurato)
- "Apri le tapparelle"
- "Chi è in casa?"

### Generali

- "Cosa devo fare oggi?" (riepilogo del giorno)
- "Quando è il prossimo evento?" 
- "Raccontami una storia" (Modalità storytelling per bambini)
- "Aiutami con i compiti" (modalità help)

### Domande che CARA non può sapere

CARA è onesta quando non sa. Se chiedi:

- ❌ "Quanto costa la benzina oggi?" → "Non lo so, non ho accesso a
  questi dati"
- ❌ "Chi ha vinto la partita?" → "Non lo so"
- ❌ "Cosa pensi di X politico?" → CARA evita politica

Non si inventa risposte. Se "inventa", probabilmente non aveva
capito la trascrizione → ripeti più chiaramente.

---

## 16. Per i bambini

### Sara e Matteo

CARA conosce i bambini di casa e parla con loro adattando il tono e
i contenuti.

#### Cosa possono fare i bambini

- 💬 Chattare con CARA
- 🎤 Parlare a voce
- ✅ Vedere i loro task
- 📝 Scrivere note (private)
- 📖 Chiedere storie ("CARA raccontami una storia")
- 🎮 Giochi (a tempo, max 30 min al giorno)
- 📚 Aiuto compiti (matematica, italiano)

#### Cosa serve approvazione di un adulto

Se Sara o Matteo aggiungono qualcosa alla **lista della spesa** di
famiglia, CARA mette l'articolo "in attesa di approvazione":

1. Sara dice: "Aggiungi caramelle alla spesa"
2. CARA: "Ok, l'ho aggiunto ma serve l'approvazione di mamma o papà"
3. Marina riceve una notifica push: "Sara ha aggiunto 'caramelle'
   alla spesa. Confermi?"
4. Marina tocca **Approva** → l'articolo diventa normale
5. Marina tocca **Rifiuta** → l'articolo sparisce gentilmente

L'articolo resta in coda per 48 ore. Se nessuno decide, scade.

#### Cosa CARA NON dice mai a un bambino

- Notizie violente o sessuali
- Politica
- Risposte a domande su droghe, alcol, armi
- Contenuti privati di altri familiari
- Bestemmie (anche se le sente nei vocali) — vengono filtrate

Se un bambino chiede qualcosa di delicato, CARA risponde con
gentilezza tipo "Questa è una cosa da chiedere a mamma o papà".

---

## 17. Per l'amministratore (Antonio)

### Accesso admin

Login con il tuo account `pedotoa@gmail.com`. Vedrai un badge "admin"
nel profilo + accesso a `/admin`.

### Cosa c'è in admin

`https://192.168.1.23:8456/admin` (PWA v2) o `:8455/admin` (v1)

#### Hub principale (`/admin`)

- **Feature flags**: 20+ toggle per attivare/disattivare moduli
  (internet, news, radio, CDA, validation, cognitive mode, smart home,
  push notifications, telegram, riconoscimento facciale, voce, ecc.)
- **System prompt CARA**: il prompt fondamentale che definisce la
  personalità di CARA (~3000 char). Modificalo per cambiare radicalmente
  il modo in cui risponde
- **Voce TTS**: nome voce Piper, rate, pitch, volume. Override
  anglicismi (dizionario di parole inglesi → pronuncia italiana)
- **Audit log**: ogni modifica admin con actor + IP + diff
- **Riavvia CARA** (exit code 42 + restart automatico Docker)

#### Sezioni admin specifiche

| Sezione | URL | Cosa fa |
|---|---|---|
| Famiglia | `/admin/users` | Aggiungi membri, ruoli, permessi |
| Persona | `/admin/persona` | Vedi e rigenera profili LLM di ogni utente |
| Memoria | `/admin/memory` | Fatti memorizzati per utente, purge |
| Volti | `/admin/face` | Enroll volti, soglie, attivazione |
| Smart Home | `/admin/smart-home` | Config Home Assistant |
| Proattività | `/admin/proactivity` | Regole + suggerimenti automatici |
| Skill Factory | `/admin/skills` | Skill data-driven + dispatcher |
| Dispositivi | `/admin/devices` | Pairing wall/mobile |
| Diagnostica | `/admin/diagnostics` | Health checks live |
| Telegram | `/admin/telegram` | Mappings chat ↔ utenti |

### Comandi utili dalla shell

```bash
# Bootstrap nuovo utente admin
docker exec cara-backend python -m cara.bootstrap create-admin <email> [password]

# Riavviare il backend manualmente
docker restart cara-backend

# Vedere i log live
docker logs -f cara-backend
docker logs -f cara-frontend

# Smoke test backend
curl -sk https://192.168.1.23:8456/health

# Riavviare tutto lo stack
cd /opt/cara && docker compose --profile app down && docker compose --profile app up -d

# Backup database manuale
cd /opt/cara && bash scripts/backup-postgres.sh

# Applicare migration nuove
docker exec cara-backend alembic upgrade head

# Vedere a che migration siamo
docker exec cara-backend alembic current
```

### Manutenzione mensile

- ☑️ Verifica spazio disco: `df -h /` (allarme > 85%)
- ☑️ Verifica backup recenti: `ls -la /opt/cara/backups/`
- ☑️ Aggiorna password se serve (in `.env` e DB)
- ☑️ Verifica IP esterno aggiornato (WireGuard updater)
- ☑️ Test restore da backup (almeno 1 volta/anno)

---

## 18. Risoluzione problemi

### "Login OK ma poi pagina bianca"

Premi **Ctrl+Shift+R** (Windows/Linux) o **Cmd+Shift+R** (Mac) per
fare un hard refresh. Pulisce la cache del service worker vecchio.

Se non basta: vai in **Tu → Impostazioni → App → Pulisci cache e
ricarica**.

### "Non sente quando parlo / non capisce"

1. Controlla che hai concesso il permesso microfono (rotella URL
   del browser → "Permessi")
2. Parla **più vicino** al microfono
3. Verifica che non ci sia troppo rumore di fondo (TV accesa, ecc.)
4. Se trascrive ma poi inventa: la frase non era abbastanza chiara,
   prova a riformulare

### "Non arrivano notifiche"

1. Verifica permesso notifiche (Tu → Impostazioni → Notifiche)
2. Se è disattivato: tocca "Attiva notifiche"
3. Se il permesso è negato: vai nelle impostazioni del browser e
   sblocca le notifiche per `https://192.168.1.23:8456/`
4. iOS richiede 16.4+ in modalità PWA installata
5. Verifica che siamo nelle ore non-silenziose (default: 7-22)

### "Si è bloccato tutto"

Riavvia il backend da admin: **/admin → Sistema → Riavvia
cara-backend**. Richiede 5 secondi. Tutti gli utenti devono
ricaricare la pagina.

Se non funziona neanche quello: chiama Antonio via Telegram (al
peggio SSH al NanoPC e `docker restart cara-backend`).

### "La voce di CARA non si sente"

1. Verifica il volume del telefono
2. Verifica che non sia in modalità silenziosa
3. In `/admin → Voce`, controlla che TTS sia abilitato
4. Test rapido: chat di test → CARA dovrebbe rispondere con audio
   inline

### "CARA risponde male / inventa"

Diversi motivi possibili:

- **Trascrizione vocale errata**: ripeti più chiaramente, conferma
  quando ti chiede "Ho capito bene?"
- **Senza context**: dopo aver chiuso e riaperto la VoicePanel, la
  conversazione voice ripartirebbe da zero. Conviene fare le
  domande di follow-up nella **stessa sessione** (bottone "Parla
  ancora" senza chiudere)
- **Modello piccolo**: il modello 1.5B su NPU ha limiti. Per domande
  complesse, la chat scritta è più affidabile

### "Disco quasi pieno"

Vai su `/admin → Diagnostica`. Se il disco è > 90%:
- `docker image prune -af` (libera immagini vecchie)
- Pulisci backup vecchi: `find /opt/cara/backups -mtime +30 -delete`
- Pulisci KV cache: `rm -rf /opt/cara/data/kv_cache/*.bin`

---

## 19. Cosa CARA non sa fare ancora

In sviluppo / roadmap futura (non aspettartele subito):

- 🚧 **Voce sincronizzata** (lip-sync con l'audio Piper)
- 🚧 **Radio streaming** completa (per ora solo via chat)
- 🚧 **Wallet finance** (registrazione spese, contabilità famiglia) —
  in arrivo con **LifeOps M2**
- 🚧 **Routine famiglia** multimediali ("ogni mattina alle 7 sveglia
  Sara con musica") — in arrivo con LifeOps M3
- 🚧 **Search globale** (cerca in tutte le tue conversazioni + note +
  tasks)
- 🚧 **Workflow Receipt** con UI dedicata (per ora via chat: "estrai
  questa ricevuta")
- 🚧 **Lip-sync della voce di CARA** mentre parla
- 🚧 **MCP server** per integrazione con Claude Desktop
- 🚧 **Display fisico Wall** (oggi solo su tablet/monitor)
- 🚧 **Voice cloning** (la voce di papà/mamma per i bambini)

Vedi `docs/CARA_Prompt_Modulo_LifeOps.md` per la roadmap dettagliata
del modulo LifeOps in arrivo.

---

## Come scaricare questo manuale

Questo file è in `/opt/cara/docs/MANUALE-CARA.md` sul NanoPC.

### Da Antonio (admin):

```bash
# Copia in casa tua
scp apedo@192.168.1.23:/opt/cara/docs/MANUALE-CARA.md ~/MANUALE-CARA.md

# Oppure aprirlo da GitHub
# https://github.com/pedotoantonio/cara/blob/main/docs/MANUALE-CARA.md
```

### Per gli altri membri famiglia:

Chiedi ad Antonio di mandarti il file via Telegram o email, oppure
apri il link GitHub se hai accesso al repo.

### Stampare:

Puoi convertirlo in PDF con qualsiasi visualizzatore Markdown
(VS Code, Typora, Marked, pandoc). Esempio con pandoc:

```bash
pandoc MANUALE-CARA.md -o MANUALE-CARA.pdf --pdf-engine=xelatex
```

---

## Domande, suggerimenti, segnalazioni

Per ora, scrivi su Telegram ad Antonio (`@pedotoa`). Se trovi un bug
o una funzione che non funziona come descritto in questo manuale,
segnalalo — il manuale viene aggiornato spesso.

---

*Buona vita con CARA. 💙*

*Versione manuale: 2026-05-22 · 19 sezioni · ~650 righe.*
