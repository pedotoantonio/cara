# Cap 0 — Prefazione

> *Sintesi 30 secondi.* CARA è un assistente AI domestico self-hosted
> per la famiglia. Gira interamente in casa su un mini-PC con NPU,
> parla italiano, e non manda dati fuori. Questo capitolo spiega perché
> esiste, chi la usa, e in che stato si trova oggi.

## 0.1 Cosa è CARA

CARA è un'applicazione web installabile come app (PWA) che permette a
una famiglia di parlare con un'intelligenza artificiale in casa. Il
nome significa **C**asa **A**I for **R**outines & **A**ctivities — ed
è anche l'acronimo che si dice ad alta voce per attivarla.

Concretamente CARA fa queste cose:

- **Conversazione naturale** in italiano, a voce o per testo. Parla con
  voce sintetizzata realistica (Piper TTS) e ascolta sia da microfono
  che da tastiera.
- **Gestione casa**: task, lista della spesa, note rapide, calendario,
  promemoria via push.
- **Controllo smart home** tramite Home Assistant (luci, tapparelle,
  scene, climatizzazione).
- **Lettura email Gmail** in sola lettura, con estrazione automatica di
  appuntamenti e task da proposte all'utente.
- **Sincronizzazione Google Calendar** in entrambe le direzioni.
- **Apprendimento**: ricorda i fatti che le dici ("sono allergico ai
  pomodori"), riconosce abitudini ricorrenti, suggerisce in modo
  proattivo.
- **Skill personalizzate** componibili in JSON, che chiunque (con un
  po' di pratica) può creare.

L'aspetto fondante è che **tutto gira in casa**. L'AI è un modello
Qwen 2.5 (1.5 miliardi di parametri) eseguito sulla NPU del NanoPC-T6,
non in cloud. Le tue email, i tuoi task, le foto della famiglia,
restano sul server di casa. Il tuo provider Internet vede solo le
richieste che CARA fa per scaricare news o ricette — non vede mai cosa
chiedi a CARA.

## 0.2 Perché esiste

CARA nasce da una scelta di Antonio Pedoto: avere un'AI di casa che
**non vende i dati di famiglia** ad aziende terze e che funziona anche
quando salta Internet. Le grandi aziende offrono prodotti simili
(Alexa, Google Home, Apple Intelligence) ma sono tutti basati su cloud
che leggono e conservano le interazioni.

CARA risponde alla domanda: *posso avere un assistente AI che mi
risparmi davvero tempo, ma di cui sono io l'unico proprietario dei
dati?*

La risposta tecnica è arrivata nel 2025-2026 con due cose insieme:

1. **NPU consumer abbastanza potenti**: la RK3588 sul NanoPC-T6 ha
   una unità neurale dedicata da 6 TOPS che esegue un Qwen 2.5-1.5B
   quantizzato a 8 bit a circa 9 token/secondo. Sufficiente per
   conversazione naturale.
2. **Modelli LLM piccoli ma capaci**: Qwen 2.5 a 1.5B parametri è già
   buono per la maggior parte dei task casalinghi (con tool calling
   per le operazioni concrete).

CARA è la prima implementazione completa di questa idea per uso di
famiglia. Niente di magico: ogni pezzo è software open-source
combinato con cura.

## 0.3 Chi la usa

**Antonio** (l'amministratore) la configura, aggiunge utenti, abilita
integrazioni, definisce le regole proattive.

**Sara, Marco, e gli altri membri famiglia** la usano per parlare,
chiedere informazioni, gestire le proprie task, salvare note,
ricevere promemoria. Ognuno ha il proprio profilo (parent, teen,
child, elder) che modifica permessi e UI.

**Ospiti** possono accedere come `guest` con accesso limitato
(read-only sulla maggior parte delle cose).

CARA non è progettata per accessi singoli da fuori casa di default —
è una rete privata. Per accedere da fuori (vacanza, ufficio) serve la
VPN WireGuard di casa, che è già configurata sul NanoPC-T6.

## 0.4 In che stato si trova oggi

Versione corrente al momento di scrivere questo manuale: **CARA
v1.1.0** (rilasciata 2026-05-06).

Cosa funziona ed è in produzione presso la famiglia Pedoto:

- ✅ Conversazione voce + testo
- ✅ Task, spesa, note, calendario, news, radio
- ✅ Integrazioni Google Calendar/Gmail
- ✅ Smart home Home Assistant
- ✅ Wallet con widget personalizzabili
- ✅ Skill Factory completa (Phase B + C + E)
- ✅ Memoria episodica + semantica
- ✅ Proattività con 10 regole concrete
- ✅ Multi-device pairing
- ✅ Setup wizard per nuove installazioni
- ✅ PWA installabile + cert mkcert per HTTPS LAN

Cosa è progettato ma rinviato:

- ⏳ **Cloud LLM (Anthropic Haiku)** — ganci pronti, disabilitato di
  default. Si attiva quando Antonio decide.
- ⏳ **Hardware Wall (Pi 5 con touchscreen)** — software già pronto
  via `surface_class=wall`, manca l'installazione fisica.
- ⏳ **Skill Factory Phase F/G** — migrare gli intent hardcoded come
  skill JSON.
- ⏳ **LoRA fine-tune** — pipeline pronta, da eseguire in cloud per
  alzare il tool-calling oltre l'85%.

## 0.5 Filosofia di design

Tre principi guidano ogni decisione di design in CARA:

**Privacy come default.** Quando una nuova feature richiede di mandare
dati fuori (cloud, web search, push notification), parte sempre
disabilitata. L'amministratore la attiva consapevolmente. Non c'è una
modalità "pratica" che apre tutti i flussi — devi scegliere.

**Italiano prima.** L'interfaccia è in italiano e CARA parla italiano
naturale. Il modello AI è prompt-modellato per conoscenze italiane
(ricette, modi di dire, contesto culturale). Il codice e i commenti
sono in inglese (è la convenzione del settore, e rende più facile
contribuire a librerie esterne), ma la UI utente è 100% italiana.

**Zero terminale.** Una famiglia non deve mai aprire un terminale
SSH. Tutto si configura dal browser: il setup wizard, l'aggiunta di
utenti, la gestione skill, la regolazione voci, gli alias smart home.
L'amministratore tecnico (Antonio) può comunque entrare via SSH se
serve, ma non è la strada principale.

## 0.6 A chi serve questo manuale

Questo manuale serve a:

- **Programmatori che vogliono modificare CARA** — tu, fra sei mesi,
  quando dovrai aggiungere una feature e non ricorderai dove vive il
  routing.
- **Sviluppatori esterni** che vogliono fare un fork o una versione
  per la loro famiglia/azienda.
- **Studenti / curiosi** che vogliono capire come si costruisce un'AI
  domestica privata fatta bene.

Non serve a:

- L'utente finale che vuole solo usare CARA (vai a `MANUALE-FAMIGLIA.md`).
- Chi cerca un'introduzione a Python o React (presupponiamo che li
  conosci già a livello intermedio).
- Chi vuole imparare le basi di LLM, NPU, embedding (consigliamo le
  letture in cap 30 — Glossario).

Detto questo, abbiamo cercato di spiegare ogni concetto specifico di
CARA da zero — quindi se sei un programmatore Python che non ha mai
toccato AI, dovresti riuscire a seguire.

## 0.7 Ringraziamenti

CARA è costruita su giganti open-source: FastAPI, React, Postgres,
Redis, MinIO, ChromaDB, Qwen, Piper, Whisper, Home Assistant. Senza
questi progetti, niente di tutto questo sarebbe possibile.

Buona lettura.

---

[← README](README.md) · [Cap 1 — Architettura →](01-architettura.md)
