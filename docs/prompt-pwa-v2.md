# Prompt professionale — CARA PWA v2 ("Cara la Compagna")

> Specifica completa per la riscrittura della PWA CARA da zero.
>
> **Destinatario**: un singolo agente AI senior (es. Claude Code, Cursor Composer,
> futuro agente custom) che riceverà questo documento come prompt iniziale
> per implementare il progetto in un repository nuovo.
>
> **Versione**: 1.0 — 2026-05-21
> **Autore**: definito da `docs/pwa-audit-2026-05-21.md`
> **Stato backend**: rimane invariato — vedi §3.
>
> **Come usarlo**: passa il contenuto integrale di questo file come system prompt
> + primo turno utente al tuo agente di sviluppo. Tutto il contesto necessario è
> contenuto qui dentro; il file `pwa-audit-2026-05-21.md` è la fonte delle
> failure-mode da NON ripetere.

---

# 0. TL;DR

Costruisci la PWA frontend di **CARA — l'assistente AI di casa Pedoto** da zero.
Tutto il backend (FastAPI Python su NPU RK3588, 37+ REST router, Postgres + Redis +
MinIO) **rimane identico**: la tua app consuma le API esistenti senza modificarle.

Il prodotto è una **PWA mobile-first con sfondo bianco e icone colorate**, in cui
**l'avatar CaraFace è il filo conduttore di ogni interazione** — non un dettaglio
della HomePage, ma il compagno persistente che reagisce al tuo flusso quotidiano.

Deve **funzionare benissimo su Chrome Android e iOS Safari** (le due piattaforme
reali della famiglia), gestire correttamente **microfono, notifiche push, posizione
GPS, wake lock e permissioni**, e dare l'impressione di parlare con un'amica reale
— non con un'app.

La Wall surface esistente (`/wall/*`) **resta separata** e viene riusata as-is. Tu
costruisci la PWA "personale" (mobile + desktop responsivo) — il display da parete
non è oggetto di questo lavoro.

---

# 1. Mission & vision

## 1.1 Cosa CARA È

CARA è l'**assistente AI domestica** della famiglia Pedoto a Ferrara (Italia):
Antonio (admin, sysadmin, 51), Marina (moglie), Sara (13), Matteo (10), Ilaria
(nonna). Gira on-device su NanoPC-T6 (RK3588 NPU), niente cloud, voce sintetizzata
locale (Piper TTS) + STT locale (Whisper) + LLM locale (Qwen2.5-1.5B).

CARA conosce ogni membro della famiglia (profilo persona longitudinale costruito
dall'LLM), parla un italiano caldo e specifico per ognuno (tono per-utente),
gestisce task, spesa, note, promemoria, calendario condiviso, smart-home, news,
radio, riconoscimento facciale, telecamere Frigate, e mantiene una memoria
semantica delle preferenze.

## 1.2 Cosa la PWA v2 deve trasmettere

> "**Una persona, non un'app.** CARA è la coinquilina più gentile e ordinata della
> casa. Sa chi sei appena entri, parla con la voce che ti piace, ricorda quello
> che è importante. Ti guarda mentre lavori — non come una macchina, ma come
> qualcuno che è lì con te."

Trasmetti questo nel **tono**, nel **timing**, nelle **micro-interazioni**, e
soprattutto nella **presenza costante dell'avatar**.

## 1.3 Target

- **Antonio** (51, sysadmin, power user) — fa di tutto da admin, vuole velocità
  + controllo
- **Marina** (moglie) — usa task, spesa, calendario, voce dal telefono
- **Sara** (13) — usa voce, compiti, lista cose da fare, foto eventi
- **Matteo** (10) — voce, compiti, gioco
- **Ilaria** (nonna, 70+) — usa quello che le serve: voce, compleanni, meteo,
  niente UI complicata

5 esigenze radicalmente diverse, **una sola PWA**. Il segreto è il **ruolo +
profilo persona**: la stessa UI ma con priorità, suggerimenti e default
adattati a chi ha fatto login.

---

# 2. Failure mode da NON ripetere

Estratti da `docs/pwa-audit-2026-05-21.md` — **non andare oltre senza averli letti
e capiti tutti**.

## 2.1 Bug Chromium che richiede workaround
- **`speechSynthesis` pause queue dopo ~15s**: la PWA v1 pompa `resume()` ogni 4s
  + chunka testo a ≤180 char. **Non rifare così**. Usa Piper server-side (audio
  WAV inline via SSE) come default; browser TTS solo come emergency fallback.
- **Conseguenza**: il tuo player audio è basato su `<audio>` + Web Audio API +
  MediaSource, non su `speechSynthesis`. Più affidabile su Chrome.

## 2.2 iOS Safari standalone PWA + Web Speech rotto
- **Mai usare `webkitSpeechRecognition`** come default. Sempre MediaRecorder →
  upload `/wall/asr` o `/asr` → Whisper backend.
- Web Speech può essere un opzionale "se disponibile" per il **wake-word "CARA"**
  (passive listening sul desktop), ma anche lì con fallback.

## 2.3 Auth storage frammentato
- Replicate il pattern `lib/authStorage.ts` 3-tier (localStorage → sessionStorage
  → in-memory) dal day 1. Non scoprire il bug "login OK ma token perso" in produzione.

## 2.4 Permission UX assente
- **Onboarding upfront** per i permessi che ti servono (vedi §7.1). Mai chiedere
  permessi "al volo" senza spiegazione. Se l'utente nega, fornisci sempre un
  path di recovery chiaro (deep-link a Settings browser via istruzioni
  context-sensitive per browser).

## 2.5 Stale cache dopo deploy
- Service worker con strategy bene definita: `skipWaiting()` + `clients.claim()`
  + `Cache-Control: no-cache` sui file critici (`index.html`, `manifest.json`,
  `sw.js`). Eredita questo da `vite.config.ts` esistente.

## 2.6 Tipografia inadatta alla UI quotidiana
- Source Serif 4 è **bellissima ma editoriale**. La v1 la usa ovunque — sbagliato.
  Riserva i serif a **momenti editoriali** (titoli grossi, hero, Wall) e usa
  **Inter** o **system stack** per UI quotidiana (form, liste, bottoni, etichette).

## 2.7 Avatar che sparisce nelle page secondarie
- CaraFace deve essere **sempre** sullo schermo (vedi §5). Mai una page senza
  almeno un avatar piccolo che reagisce. La promessa "amica reale" si tradisce
  appena entri in un dettaglio.

## 2.8 30+ route senza gerarchia
- Massimo **5 top-level destinations** in bottom nav. Tutto il resto è
  raggiungibile via **hub centrali + search globale + suggerimenti contestuali
  + avatar drawer**. Vedi §6.

## 2.9 Tema day/night automatico
- **Default: tema chiaro (sfondo bianco) per tutti, sempre**. Toggle manuale per
  scuro disponibile, ma niente "in base all'ora del dispositivo": confonde.

## 2.10 Notifiche stupide
- Implementa bundling + DND **dal day 1**, non come feature add. Vedi §7.2.

---

# 3. Backend invariato (vincoli)

## 3.1 API da consumare (read-only per te)

Il backend FastAPI vive in `/opt/cara/backend/` ed espone 37+ router REST sotto
`/api/v1/`. **Non li modifichi.** Schema OpenAPI live su `https://192.168.1.23:8455/api/openapi.json`
in ambiente dev. Endpoint principali:

| Dominio | Endpoint chiave |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/lan-login`, `GET/PATCH /auth/me`, `POST /auth/refresh`, `POST /auth/change-password` |
| Chat | `POST /chat` (SSE: `meta` / `token` / `audio_chunk` / `done` / `error` / `revision`), `GET /chat/health` |
| Conversations | `GET/POST /conversations`, `GET /conversations/{id}/messages` |
| Tasks | `GET/POST /tasks`, `PATCH/DELETE /tasks/{id}` |
| Shopping | `GET/POST /shopping`, `PATCH/DELETE /shopping/{id}`, `POST /shopping/clear-bought` |
| Notes | `GET/POST /notes`, `PATCH/DELETE /notes/{id}` |
| Reminders | `GET /reminders/templates`, `GET/POST /reminders`, `PATCH/DELETE /reminders/{id}`, `POST /reminders/{id}/done`, `POST /reminders/{id}/snooze` |
| Memory | `GET /memory/facts`, `POST /memory/facts/extract`, `POST /memory/export`, `POST /memory/purge` |
| Persona | `GET /persona/me`, `POST /persona/me/rebuild` (cooldown 30min), `DELETE /persona/me` |
| Wallet | `GET/PUT /wallet/layout?surface=...`, `GET /widgets/render?ids=...`, `GET /wallet/presets` |
| Weather | `GET /weather/current?lat=...&lon=...`, `GET /weather/forecast?...` (Open-Meteo proxy) |
| Smart home | `GET /smarthome/entities`, `POST /smarthome/resolve`, `POST /smarthome/execute` |
| News | `GET /news?category=...&limit=...` |
| Radio | `GET /radio/stations`, `POST /radio/play`, `POST /radio/stop` |
| CDA (discovery) | `POST /cda/discover?kind=...&query=...`, `GET /cda/items?kind=...` |
| Voice TTS | `POST /voice/synthesize` (return WAV) |
| ASR | `POST /asr` (multipart audio) |
| Push | `GET /push/public-key`, `POST /push/subscribe`, `DELETE /push/subscribe` |
| OAuth | `GET /oauth/google/start`, `GET /oauth/google/callback` |
| Integrations | `GET/POST /integrations/google/*` (Calendar + Gmail) |
| Files | `POST /files` (multipart, status `pending|processing|ready|failed`), `GET /files/{id}` |
| Setup | `GET/POST /setup/state` (first-run wizard) |
| Face | `GET /face/profiles`, `POST /face/profiles/{id}/descriptors`, `POST /face/match`, `GET /face/settings` |
| Devices | `GET /devices`, `POST /devices/pair-start`, `POST /devices/pair-finish` |
| Proposals | `GET /proposals` (email-extracted), `POST /proposals/{id}/accept|reject` |
| Events (SSE) | `GET /wall/events/stream` (LAN-only) — riusabile dal personal PWA se autenticato? VERIFICA |

**Estremamente importante**: leggi lo schema OpenAPI live prima di iniziare,
non assumere parametri.

## 3.2 Auth model

- **JWT Bearer** in header `Authorization: Bearer <token>`.
- Token in `localStorage` (con fallback 3-tier già discusso).
- Refresh token separato; refresh automatico in fetch wrapper su 401.
- **LAN auto-login**: `POST /auth/lan-login` ritorna JWT senza password se il
  client è da CIDR LAN (192.168.1.0/24, 10.8.0.0/24, 127.0.0.0/8). Esterno → 403.

## 3.3 SSE — Server-Sent Events

`/chat` ritorna SSE. Eventi: `meta`, `token` (string), `audio_chunk` (base64 WAV
chunk), `done`, `error`, `revision`. Usa `EventSource` o `fetch` + `ReadableStream`
(EventSource non manda Auth header su domini self-signed — usa il secondo approccio
con bearer in URL query o adapter custom).

## 3.4 Reverse proxy & TLS

L'app finale gira dietro nginx-proxy su `https://192.168.1.23:8455/`. La PWA
serve l'app shell + chiama `/api/*` same-origin. Niente CORS.

mkcert CA `.crt` scaricabile da `/cara-rootCA.crt` per HTTPS valido — importante
per la PWA (mic, notifiche, install richiedono secure context).

---

# 4. Stack tecnico vincolato

Devi usare:

| Layer | Scelta | Motivazione |
|---|---|---|
| Build tool | **Vite 5+** | Già in prod, hot-reload immediato |
| Framework | **React 18** | Già in prod backend SSE wiring |
| Routing | **React Router 6** | Già adottato |
| State management | **Zustand** (preferito) o React Query per server-state | Leggero, evita Redux overkill |
| Styling | **Tailwind CSS 3** + **CSS Modules per componenti complessi** | Velocità + flessibilità |
| Components | **shadcn/ui** o **Radix UI primitives** | Accessibili, customizabili |
| Icons | **Phosphor** o **Lucide** (sceglierne UNA) + icone custom SVG per CARA-brand | Phosphor ha più stile/personalità per "amica" |
| Fonts | **Inter** (UI body, da Google Fonts variable) + **Source Serif 4** (display moments) | Vedi §5.2 |
| Animations | **Framer Motion** | Standard de-facto, ottime perf |
| PWA plugin | **vite-plugin-pwa** | Già in prod, riusalo |
| Tests | **Vitest** (unit) + **Playwright** (e2e) | Già in prod |
| Linter | **ESLint + Prettier** | Già in prod |
| TypeScript | **strict mode ON** | Non negoziabile |

Niente: Redux, MobX, Bootstrap, Material UI, jQuery, moment.js (usa
`date-fns` o `Intl`).

---

# 5. Design system v2 — "Foglio bianco con persone colorate"

## 5.1 Identità visiva

**Mood**: una casa luminosa al mattino. Sfondo bianco, dettagli colorati con
intenzione, ombre morbide e calde, niente buio. Una via di mezzo fra **iOS 17
Home Screen** (icone colorate squadrate) e **Apple Watch faces** (informazione
densa ma calma).

## 5.2 Palette

Sfondo neutro chiaro **dovunque**:
```
--bg-base:        #FFFFFF   /* sfondo app */
--bg-surface:     #F7F8FA   /* card, drawer, surface elevate */
--bg-elevated:    #FFFFFF   /* modal, popover */
--border-soft:    #E8EAEE   /* divider, separatori sottili */
--border-strong:  #C7CAD1   /* bordi attivi */
```

Testo:
```
--text-primary:   #0E1116   /* titoli, body principale */
--text-secondary: #4B5563   /* etichette, meta */
--text-muted:     #9AA0AB   /* placeholder, hint, timestamp */
--text-inverse:   #FFFFFF   /* su backgrounds colorati */
```

Accenti colorati (usati per icone, bottoni primari, illustrazioni, NON per testo
ordinario):
```
--accent-coral:   #FF6B6B   /* primary action, mic active, urgenza */
--accent-mint:    #2EC4B6   /* success, "fatto", task done */
--accent-sun:     #FFD166   /* warning leggero, attenzione, persona happy */
--accent-sky:     #4ECDC4   /* info, meteo, sereno */
--accent-lilac:   #9381FF   /* memoria, persona, sogno */
--accent-rose:    #FFB5C5   /* shopping, casa, family */
--accent-grass:   #06D6A0   /* smart-home active, presenza */
--accent-clay:    #E76F51   /* radio, news, energia */
```

**Regola d'oro**: lo sfondo è sempre `--bg-base` o `--bg-surface`. Il colore vive
nelle **icone**, nei **bottoni di azione primaria**, nelle **illustrazioni**, e
nelle **emoji di personalità della avatar**.

## 5.3 Tipografia

```
font-family-ui:      "Inter", system-ui, -apple-system, sans-serif
font-family-display: "Source Serif 4", "Times New Roman", serif
font-family-mono:    "JetBrains Mono", monospace
```

Scale modulare 1.200 (minor third) — più piccola della v1, più moderna:

| Token | px | Use |
|---|---|---|
| `text-xs` | 12 | meta, timestamp |
| `text-sm` | 14 | etichette, body secondario |
| `text-base` | 16 | body |
| `text-md` | 18 | sotto-titoli |
| `text-lg` | 21 | titoli card |
| `text-xl` | 24 | titoli sezione |
| `text-2xl` | 28 | titoli page |
| `text-3xl` | 32 | hero |
| `text-4xl` | 40 | display, momenti editoriali |
| `text-5xl` | 48 | hero massimo |

`text-base` minimo per body. Su mobile usa preferred-size 16px per evitare zoom-on-focus iOS.

## 5.4 Spacing

Sistema 4-based: `1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24` (× 4px). Niente
spacing arbitrario.

Layout grid: 4 colonne mobile (≤640px), 8 desktop (≥1024px). Gutter 16px mobile,
24px desktop.

## 5.5 Radii

```
--radius-xs:  4px   /* chip piccola, badge */
--radius-sm:  8px   /* input, bottone secondario */
--radius-md:  12px  /* bottone primario, card piccola */
--radius-lg:  16px  /* card */
--radius-xl:  24px  /* modal, drawer */
--radius-2xl: 32px  /* card hero, avatar container */
--radius-pill: 9999px
```

## 5.6 Ombre

Solo ombre **calde, basse, soffuse** (mai grigio puro):
```
--shadow-1: 0 1px 2px rgba(20, 24, 40, 0.04), 0 1px 1px rgba(20, 24, 40, 0.02)
--shadow-2: 0 4px 12px rgba(20, 24, 40, 0.06), 0 2px 4px rgba(20, 24, 40, 0.03)
--shadow-3: 0 12px 32px rgba(20, 24, 40, 0.08), 0 6px 12px rgba(20, 24, 40, 0.04)
--shadow-glow: 0 0 24px var(--avatar-glow-color)  /* solo per avatar attiva */
```

## 5.7 Motion

```
--motion-quick:   120ms ease-out      /* hover, focus */
--motion-base:    220ms cubic-bezier(0.2, 0, 0, 1)  /* default transition */
--motion-smooth:  400ms cubic-bezier(0.2, 0, 0, 1)  /* enter/exit */
--motion-spring:  500ms cubic-bezier(0.3, 1.4, 0.4, 1)  /* delight */
--motion-slow:    800ms ease-in-out   /* avatar breathing */
```

**Rispetta sempre `prefers-reduced-motion: reduce`** — disabilita le animazioni
decorative (avatar breathing, fade-in, parallax), mantieni solo quelle funzionali
(loading spinner, progress).

## 5.8 Icone

Usa Phosphor (o Lucide) **con weight `duotone` o `regular`**, colorate con
`--accent-*` per categoria. Mai monocromatiche su sfondo bianco — sembrano spente.

Logica colore icone:
- Voice/mic → `--accent-coral`
- Tasks → `--accent-mint`
- Shopping → `--accent-rose`
- Notes → `--accent-sun`
- News → `--accent-clay`
- Radio → `--accent-clay`
- Memory → `--accent-lilac`
- Persona → `--accent-lilac`
- Smart home → `--accent-grass`
- Weather → `--accent-sky`
- Settings → `--text-secondary` (questa sola monocromatica)
- Admin → `--accent-coral` (rosso = "attenzione, sei admin")

---

# 6. Information architecture

## 6.1 Top-level (sempre raggiungibili)

5 destinations in bottom nav mobile + side rail desktop:

1. **🏠 Casa** (`/`) — hub home, avatar grande, "ciao Antonio", suggerimenti
   contestuali, voice mic prominente, prossimo evento, meteo veloce
2. **💬 Chat** (`/chat`) — conversazione con CARA, full screen, avatar piccola
   in alto, lista conversazioni nello sheet laterale
3. **📝 Liste** (`/list`) — hub unificato per Tasks + Shopping + Notes +
   Reminders, tabs interne, search globale
4. **📅 Vita** (`/life`) — calendario unificato (eventi + tasks + reminders) +
   meteo + news + radio, vista timeline
5. **👤 Tu** (`/me`) — profilo + persona + memoria + settings + integrazioni,
   admin link se admin

## 6.2 Avatar drawer (sempre disponibile via tap su CaraFace)

Tap sull'avatar (presente in ogni page, vedi §7) apre una drawer dal basso
con:
- "Cosa posso fare per te?" (input vocale prominente)
- Quick actions personalizzate (basate su persona): "Aggiungi a spesa", "Nuovo
  task", "Cosa devo fare oggi?"
- Link rapidi a sotto-page meno frequenti: Discoveries, Wallet, Diagnostics
  (admin), Face Lab (admin)

L'avatar drawer è il sostituto del MenuPage v1 — non separato in /menu, **emerge
dall'avatar**.

## 6.3 Search globale (cmd+K / pull-to-search)

Search bar accessibile da:
- Tap su icona search nella top bar
- Gesture pull-down da hub home
- Shortcut tastiera `Cmd+K` / `Ctrl+K` desktop

Cerca trasversale in:
- Conversazioni (semantic via embeddings)
- Tasks, Shopping, Notes
- Reminders
- Memoria (facts)
- Discoveries (radio/articoli)
- Smart home entities

Backend: implementa `/api/v1/search?q=...&kinds=...` (vedi proposta features
del 2026-05-21).

## 6.4 Admin & system

Admin pages restano sotto `/admin/*` ma accessibili solo da `/me/admin` link
(no shortcut top-level), 11 admin page disponibili come oggi.

## 6.5 Wall (intoccato)

`/wall/*` resta com'è. La PWA v2 può **linkare** al Wall (es. "apri sul
display di cucina") ma non lo include.

## 6.6 Routes complete

```
Pre-auth:
  /login                  schermata accesso (LAN auto-login provato per primo)
  /pair                   device pairing wizard
  /setup                  first-run admin wizard
  /face/enroll            iscrizione volto

Post-auth (5 top-level + drill-down):
  /                       Hub Casa
  /chat                   Chat fullscreen
  /chat/:conversationId   Conversazione specifica
  /list                   Hub liste (tabs: tasks/shopping/notes/reminders)
  /list/tasks             Tab tasks
  /list/shopping          Tab shopping
  /list/notes             Tab notes
  /list/reminders         Tab reminders
  /list/reminders/new/:slug      Nuovo reminder
  /life                   Hub vita (tabs: calendar/news/radio/meteo)
  /life/calendar          Calendario completo
  /life/news              News
  /life/radio             Radio
  /life/meteo             Meteo dettagliato
  /me                     Profilo
  /me/persona             Profilo persona longitudinale
  /me/memory              Memoria semantica
  /me/integrations        Google Calendar/Gmail
  /me/wallet              Widget Wallet
  /me/settings            Impostazioni
  /me/admin               (admin only) link hub admin
  /me/proposals           Email-extracted task proposals

Admin (gated):
  /admin                  Hub admin
  /admin/persona          → vista admin persona di tutti gli utenti
  /admin/memory           → vista admin memoria
  /admin/face, /admin/face/debug
  /admin/skills
  /admin/devices, /admin/users
  /admin/smart-home, /admin/proactivity
  /admin/telegram
  /admin/diagnostics

Search:
  /search?q=...&kinds=... overlay accessible from anywhere

Discoveries (low-frequency):
  /discoveries            tutte le scoperte CDA

Wall (link out):
  /open-wall              redirect a /wall/today (browser nuovo se desktop)
```

**Totale**: 5 top-level + drill-down + admin. **Niente HomePage voice-only
separata** — la voce è integrata nell'hub Casa.

---

# 7. Avatar persistente — il pezzo che cambia tutto

## 7.1 Design

L'avatar è una **versione evoluta di CaraFace v2 "atomo neurale"** (esistente in
`frontend/src/components/CaraFace.tsx`). NON ricostruirla da zero — riusala, ma
estendi:

1. **Pose**: oltre alle 12 emozioni × 9 stati energia attuali, aggiungi
   **postura** (3 valori):
   - `attentive` — quando l'utente sta facendo qualcosa attivamente (default)
   - `peeking` — quando CARA vuole interrompere educatamente (notifica
     proattiva)
   - `resting` — DND mode, schermo idle 60s+
2. **Companion mode**: lo stesso avatar in 4 dimensioni:
   - **`hero`** (240px) — Hub Casa center stage
   - **`floating`** (72px) — pip persistente in basso a destra ogni altra page
   - **`inline`** (40px) — accanto a messaggi chat, badge
   - **`micro`** (24px) — favicon, splash, badge OS notification

3. **Compagnia reattiva**: l'avatar **reagisce ai contenuti della page**:
   - Sei in `/list/tasks` con 3 task overdue → avatar `thoughtful` + sun
   - Sei in `/list/shopping` con 12 item → avatar `happy` + rose
   - Sei in `/me/persona` profilo basso confidenza → avatar `confused` + sky
   - Sei in `/admin/diagnostics` con un alert rosso → avatar `surprised` + coral

## 7.2 Floating avatar (l'innovazione)

In **ogni page eccetto la Casa**, mostra un **floating avatar in basso a destra**,
72px, con:
- L'attuale stato persona + emozione (sync col contesto della page)
- **Pulse** quando CARA ha qualcosa da dire (notifica in arrivo, proattività)
- **Halo** colorato che cambia (vedi `--avatar-glow-color`) — ogni accent palette
- **Tap → apre Avatar Drawer** (§6.2)
- **Long-press** (700ms) → start voice immediato senza aprire la drawer
- **Drag** → repos sull'arco di destra (basso/centro/alto)
- Mai sopra contenuti critici: il layout deve dare safe-area-padding sufficiente

## 7.3 Modalità "amica reale"

Quando l'utente sta in chat:
- L'avatar `floating` si **trasforma in `inline`** sopra ogni bubble assistente
- Il tono dell'avatar matcha il sentiment del messaggio (testo "tristezza" →
  `thoughtful + sad`)
- Mentre CARA "parla" (TTS), l'avatar `speaking + happy/neutral` con lip-sync
  sincronizzato all'audio

Quando l'utente arriva (riconoscimento facciale via face-api in worker, opzionale):
- L'avatar saluta con il nome: "Ciao Sara, eccoti"
- Cambia il tono in `playful` (Sara) o `calmo` (Antonio matticio).

## 7.4 Implementazione

Crea un **`AvatarProvider`** React Context al root dell'app:
```ts
interface AvatarState {
  size: 'hero' | 'floating' | 'inline' | 'micro';
  energy: EnergyState;   // 9 valori esistenti
  emotion: Emotion;      // 12 valori esistenti
  posture: 'attentive' | 'peeking' | 'resting';
  glowAccent: AccentToken;
  caption?: string;      // brief text shown next to avatar
  speaking: boolean;     // for lip-sync
  pendingNotifications: number;  // for pulse
}

const setAvatar = (next: Partial<AvatarState>) => void;
```

Ogni page può chiamare `setAvatar(...)` al mount per esprimere il suo stato.
Default reset on unmount.

**`AppShell`** renderizza il floating avatar globalmente, ascoltando
`AvatarProvider`.

---

# 8. Capability handling (da risolvere bene)

## 8.1 Permission onboarding upfront

Dopo il primo login, mostra una **page `/permissions`** prima dell'app:

```
"Ciao Antonio, prima di iniziare:
 CARA ha bisogno di alcune autorizzazioni per esserti utile."

 [🎤 Microfono]    "Per ascoltarti parlare"           [Concedi] [Salta]
 [🔔 Notifiche]    "Per ricordarti le cose importanti" [Concedi] [Salta]
 [📍 Posizione]    "Per il meteo e i promemoria sui luoghi" [Concedi] [Salta]
 [📷 Fotocamera]   "Per riconoscerti quando torni a casa"   [Concedi] [Salta]

 Puoi cambiare queste impostazioni in qualsiasi momento da Tu → Impostazioni.
```

Ogni "Concedi" triggera il permission API del browser (1 click = 1 prompt
nativo). Salta = mostra il banner "abilita più tardi" nei punti rilevanti.

Lo stato dei permessi va in `localStorage` (`{mic:'granted'|'denied'|'prompt', ...}`)
e viene letto da `usePermissionState()` hook usato ovunque serva sapere se una
feature è disponibile.

## 8.2 Notifiche push (sostituire la v1)

### A. Setup
- Su click "Concedi", chiama `Notification.requestPermission()`.
- Se granted, ottieni `vapidKey` da `GET /push/public-key`.
- `PushManager.subscribe({ userVisibleOnly: true, applicationServerKey: ... })`.
- POST a `/push/subscribe` con `{endpoint, keys, user_agent, label}`.

### B. Rich notifications (nuovo)
Service worker `push` event handler decora la notifica nativa:
- `tag` per dedup
- `actions` per quick reply: `[{action:'done', title:'Fatto'}, {action:'snooze', title:'+1h'}]`
- `image` per anteprima (es. foto persona riconosciuta, snapshot telecamera)
- `data: {url, kind, idempotency_key}` per il click handler

Click action → `clients.openWindow(url)` → focus tab esistente o nuova.

### C. Bundling + DND lato client (rinforza il backend)
Anche se il backend bundle, il client deve:
- Group notifications by `kind` nel notification center via `tag` prefix
- Rispettare DND user setting (no buzz, ma visualizza in app badge)
- Mantenere "badge count" via `navigator.setAppBadge(n)` (API supportata Chrome 81+)

### D. Recovery flow
Su ogni app start, chiama `reaffirmSubscriptionSilently()`:
1. Se `Notification.permission === 'granted'` ma `subscription` locale persa:
   1. Ri-subscribe da `PushManager.getSubscription()` o `subscribe()` fresh.
   2. Re-POST a `/push/subscribe` con stesso `user_agent` ma nuovo endpoint.
   3. Backend deduplica per user+device.
2. Se permission persa nel mezzo (utente l'ha revocata):
   1. Mostra banner non-intrusivo in `/me/settings`: "Notifiche disabilitate.
      [Riabilita]"
   2. Click → istruzioni context-sensitive per browser (Chrome/Safari/Firefox/Edge).

## 8.3 GPS (nuovo)

`navigator.geolocation` finalmente usato per:

### A. Meteo "qui"
Su tap del widget meteo: "Vuoi meteo nella tua posizione attuale invece che a
Ferrara casa?" → granted → `getCurrentPosition()` once → API `/weather/current?lat=...&lon=...`.

### B. Reminders geofence (futuro, opzionale)
Crea reminder "Quando arrivo al supermercato, ricordami la spesa". Geofence via
`watchPosition()` con `enableHighAccuracy: false` (battery save). Trigger se
distanza < 200m dal punto. **Opzionale** — backend deve supportarlo (vedi
proposte feature). Se non implementato, **non mostrare l'UI**.

### C. Presence
Quando in casa (WiFi LAN), presence inferito automaticamente. Fuori casa,
optional GPS per "Antonio è a 15min da casa".

## 8.4 Microfono

**Stack** (eredita la pipeline v1 quasi as-is):
- MediaRecorder + Web Audio AnalyserNode
- VAD adattivo + diagnostics
- Fallback Whisper backend

**Differenza chiave dalla v1**:
- Mic disponibile da **floating avatar long-press** + **search bar** +
  **hub home centro stage**, in più context.
- Stato mic globale via `useMicState()` hook — solo 1 mic attivo per volta in
  tutta la PWA.
- Live audio level visualizzato come **halo dell'avatar** (non più barra
  separata in basso), `--avatar-glow-color` cambia con dB.

## 8.5 Wake lock

Per cucina + conversazione lunga:
- `/list/shopping` in modalità "spesa attiva" (è la prima volta che mostri
  questo item dopo un add) → `navigator.wakeLock.request('screen')`
- `/chat` quando l'avatar sta parlando (TTS in playback) → wake lock
- `/life/radio` con stazione in play → wake lock
- `/face/enroll` durante l'enrollment → wake lock

Release on visibility hidden / route change. Niente wake lock 24/7 — solo
contestuale.

## 8.6 Hooks da implementare

```ts
usePermissionState()      // {mic, camera, notifications, geolocation}
useMicState()             // {recording, level, transcript, error}
useNotificationState()    // {permission, subscription, badgeCount}
useGeoState()             // {position, error, accuracy}
useWakeLock(active: boolean, reason: string)
useFaceRecognition()      // optional — only if /face/enroll completed
useAvatar()               // setAvatar(...)
useFamilyBus()            // SSE family-bus
useChatStream()           // chat SSE
useTtsPlayback()          // play audio_chunk events
useAuth()                 // user, login, logout, refresh
useTheme()                // (light only by default, manual dark optional)
useToast()                // toast notifications
```

---

# 9. Page-by-page

Resoconto ad alto livello — sviluppa ogni page come stand-alone componente
testabile.

## 9.1 `/` — Hub Casa

```
┌─────────────────────────────────────────┐
│  ☀️ Ferrara · 18°    🔔 3        ⚙️    │
├─────────────────────────────────────────┤
│                                         │
│           [Hero CaraFace 240px]         │
│           "Ciao Antonio"                │
│           "Sono qui per te"             │
│                                         │
│     ┌──────────────────────────────┐   │
│     │  🎤  Parla con me            │   │
│     │   (input voice prominente)   │   │
│     └──────────────────────────────┘   │
│                                         │
│  📅 Prossimi 3                          │
│   • 14:00 Riunione lavoro               │
│   • 15:30 Compiti Sara                  │
│   • 18:00 Spesa coop                    │
│                                         │
│  🌅 Suggerimenti                        │
│   ▸ "C'è il sole oggi, vuoi uscire?"   │
│   ▸ "Marina ha aggiunto pane alla spesa"│
│                                         │
└─────────────────────────────────────────┘
[ 🏠  💬  📝  📅  👤 ]   (bottom nav)
```

- Avatar **hero** (240px), reagisce in real-time alle notifiche/presenza
- Saluto personalizzato dal `persona_profile` (es. tono `calmo` per Antonio)
- Input voce prominente (no mic button separato, è inline nell'avatar)
- Prossimi 3 eventi/task (semantically merged da calendar + tasks + reminders)
- Suggerimenti contestuali dal proactivity engine + persona

## 9.2 `/chat` — Conversazione full

```
┌─────────────────────────────────────────┐
│ ←  CARA · Antonio              📞 ⋮    │
├─────────────────────────────────────────┤
│                                         │
│  10:24 · Antonio                        │
│  "Ricordami di chiamare il dottore"     │
│                                         │
│  10:24 · CARA  [avatar inline 40px]     │
│  "Certo, quando?"                       │
│                                         │
│  10:24 · Antonio                        │
│  "Stamattina alle 11"                   │
│                                         │
│  10:24 · CARA  [avatar inline 40px]     │
│  "Promemoria salvato per le 11:00.     │
│   Ti avviso fra 30 minuti."             │
│  [📌 ricorda] [✏️ modifica] [↩ annulla] │
│                                         │
├─────────────────────────────────────────┤
│  🎤   Scrivi qualcosa...        ➤      │
└─────────────────────────────────────────┘
```

- SSE chat stream con audio_chunk Piper playback inline
- Live caption durante TTS sincronizzata con audio
- Workflow preview (Receipt/Bill/Recipe) prima di confermare actions
- Conversation history nello sheet laterale
- Persistent voice mic (tap o long-press)

## 9.3 `/list` — Liste unificate

Tabs interne: Tasks, Spesa, Note, Promemoria. Ognuna è uno scroll vertical
infinito con:
- Quick add input in top
- Filter chips (mio / famiglia / overdue / oggi)
- Item card touch-target ≥44px iOS
- Floating avatar bottom-right (peek su nuovo item)
- Pull-to-refresh

## 9.4 `/life` — Calendario, news, radio, meteo

Vista unificata "vita oltre le liste":
- Tab calendario: timeline visivo + week/month switch
- Tab news: cards image-rich (RSS feed)
- Tab radio: stazioni come grid colorato + mini-player persistent
- Tab meteo: dettaglio orario + settimana + warning (alert pioggia, gelo)

## 9.5 `/me` — Profilo e settings

Hub personale con cards che linkano:
- Persona (mostra Markdown profile + rebuild)
- Memoria (facts + GDPR purge)
- Integrazioni (Google Calendar / Gmail toggle)
- Wallet (widget canvas customizable)
- Impostazioni (tono, password, audio, theme manual)
- Admin (se admin) → entry point a tutte le admin page

## 9.6 Permission/Setup (pre-app)

- `/login` — form email + password, LAN auto-login try-first
- `/setup` — first-run wizard (riusa esistente, ma styling nuovo)
- `/permissions` — onboarding permessi (§8.1)
- `/face/enroll` — opzionale, link da `/me/persona` o setup

---

# 10. Innovazioni richieste esplicitamente

L'utente ha chiesto **"un progetto davvero innovativo"**. Implementa:

## 10.1 Voice-everywhere, non solo home
Avatar floating con long-press = mic in qualsiasi page. Mai dover "tornare alla
home" per parlare con CARA.

## 10.2 Color-coded categories
Ogni dominio ha la sua icona colorata (vedi §5.8). L'app diventa **visivamente
mappata** — l'utente impara dopo 1 giorno "rosa = spesa, mint = task, lilac =
memoria".

## 10.3 Conversational widgets
I widget Wallet non sono statici: ogni widget è "interrogabile" — tap su widget
meteo → "Cosa vuoi sapere del meteo?" → chat preloaded con context.

## 10.4 Persona-aware UI
Profilo persona injectato non solo nel system prompt LLM ma anche nella UI:
- Antonio → saluti formali "Buongiorno Antonio"
- Sara → saluti giocosi "Ehi Saretta!"
- Ilaria → font leggermente più grande, tap target ≥48px, niente icone
  ambigue (testo accanto sempre), TTS sempre disponibile

Setting `accessibility_mode` per-utente nel backend (estensione `users`):
- `default` — UI normale
- `simplified` — testo grande, target grandi, TTS auto
- `child` — colori più vibranti, gamification (streak compiti, stelle)

## 10.5 Offline-first per le viste
Service worker cache delle GET principali (tasks, shopping, notes, persona,
weather). Mutations (POST/PATCH) **non offline** — meglio un "Sei offline,
riprova quando torni online" che dati incoerenti.

## 10.6 Avatar che impara la routine
Dopo 1 settimana di uso, l'avatar mostra una **palette personalizzata** basata
sull'orario:
- 7:00 — caffè coral, avatar `attentive + happy`
- 14:00 — pomeriggio lilac, avatar `peeking` (chiede se serve aiuto)
- 22:00 — sera sage, avatar `resting`

Le palette emergono dalla combinazione `tone_preference` + `proactive_rules` +
orario corrente. Niente magia AI — solo configurazione dichiarativa.

## 10.7 Skeleton + delight
Mai una page bianca durante il fetch:
- Skeleton screen con shapes morbidi (Tailwind `animate-pulse`)
- Avatar mostra `thinking` durante il caricamento
- Transizioni fluide fra route (Framer Motion `AnimatePresence`)

## 10.8 Haptic feedback (mobile)
Su tap su mic, su completamento task, su notifica nuova → `navigator.vibrate()`
pattern leggero (Android only — iOS Safari ignora silenziosamente).

---

# 11. Performance budget

Misurabili su Chrome Android Pixel 7 (target hardware famiglia):

| Metric | Budget |
|---|---|
| First Contentful Paint (FCP) | < 1.5s |
| Largest Contentful Paint (LCP) | < 2.5s |
| Time to Interactive (TTI) | < 3.5s |
| Cumulative Layout Shift (CLS) | < 0.05 |
| Bundle JS gz total | < 250 KB |
| Bundle JS gz initial route (Home) | < 120 KB |
| Lighthouse PWA score | > 95 |
| Lighthouse Performance score | > 90 |
| Lighthouse Accessibility score | > 95 |

Test su:
- iPhone 12+ (Safari, mobile config)
- Pixel 7+ (Chrome, mobile config)
- Desktop Chrome (1280px width default)
- Desktop Firefox (smoke only)

---

# 12. Accessibility

Non negoziabile:

- **Touch target ≥44px** (iOS) ovunque
- **Color contrast WCAG AA**: testo body ≥4.5:1, large text ≥3:1
- **Keyboard navigation completa**: ogni interaction raggiungibile via Tab/Enter
- **Screen reader friendly**: `aria-label`, `aria-live` per toast, `role="dialog"` per modali
- **Focus visible**: outline 2px solid `--accent-coral` su elementi focused (no `outline: none`)
- **Reduced motion**: rispetta `prefers-reduced-motion: reduce`
- **High contrast mode**: testa con Windows High Contrast / iOS Smart Invert
- **TTS available on demand**: ogni testo lungo (notizie, articoli, persona MD)
  ha pulsante "ascolta" che usa Piper backend

---

# 13. Service worker & PWA

## 13.1 Manifest
```json
{
  "name": "CARA — Casa Pedoto",
  "short_name": "CARA",
  "lang": "it",
  "theme_color": "#FFFFFF",
  "background_color": "#FFFFFF",
  "display": "standalone",
  "orientation": "any",
  "start_url": "/?source=pwa",
  "scope": "/",
  "icons": [
    { "src": "/icons/cara-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/cara-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/cara-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ],
  "shortcuts": [
    { "name": "Parla con CARA", "url": "/?action=voice", "icons": [...] },
    { "name": "Nuova task", "url": "/list/tasks?new=1" },
    { "name": "Spesa", "url": "/list/shopping" },
    { "name": "Promemoria", "url": "/list/reminders" }
  ],
  "screenshots": [
    { "src": "/screenshots/home.png", "sizes": "1080x1920", "form_factor": "narrow" },
    { "src": "/screenshots/home-desktop.png", "sizes": "1920x1080", "form_factor": "wide" }
  ]
}
```

## 13.2 Strategy

- `/api/*` — **NetworkOnly** (no cache)
- `/_assets/*` (CSS/JS hashed) — **CacheFirst**, immutable
- `index.html`, `manifest.json`, `sw.js` — **NetworkFirst** + `Cache-Control: no-cache`
- `/icons/*`, `/static/*` — **CacheFirst**
- Audio playback `/api/v1/voice/synthesize` blob — **NetworkOnly** (non cachare,
  cambia col tono)
- Modelli face-api `/models/face-api/*` — **CacheFirst**, versioning URL

## 13.3 Update flow

- `vite-plugin-pwa` con `registerType: 'autoUpdate'`
- `skipWaiting()` + `clients.claim()` immediati
- Toast non intrusivo: "Nuova versione, ricarica per applicare" se utente attivo
- Auto-reload silenzioso se app idle > 5 min

---

# 14. State management

## 14.1 Server state — React Query

Tutto ciò che viene dal backend usa **TanStack Query** (React Query):
- `useQuery` per GET con TTL (es. `tasks` TTL 30s, `weather` TTL 5min)
- `useMutation` per POST/PATCH/DELETE
- Optimistic updates per task done/shopping bought
- Background refetch on focus

## 14.2 Client state — Zustand

Solo state veramente client:
- `useAvatarStore` — avatar state (size/energy/emotion/posture)
- `usePermissionStore` — permission status
- `useMicStore` — recording state
- `useThemeStore` — theme manual override (default light)
- `useToastStore` — toast queue
- `useAuthStore` — user JWT + refresh logic

## 14.3 SSE / WebSocket

- Chat SSE — wrapped in custom hook `useChatStream(conversationId)`
- Family bus SSE (se accessible da personal PWA) — `useFamilyBus()` provider al root

---

# 15. Testing strategy

## 15.1 Unit (Vitest)
- Tutti gli hook custom (mock fetch, mock browser APIs)
- Pure utility functions
- Component snapshot tests per elementi design system
- Target coverage: ≥70% lines

## 15.2 Integration (Vitest + Testing Library)
- Form flows (login, setup, permissions)
- Avatar reacts to context (mount page X → assert avatar state Y)
- Chat SSE handling (mock EventSource)
- Permission state transitions

## 15.3 E2E (Playwright)
- Login + LAN auto-login
- Onboarding permissions (mocked granted/denied)
- Crea task via voice (mock MediaRecorder + ASR)
- Hub home → list/tasks → completa task → torna home
- Avatar drawer apre, mic registra, response arriva
- Service worker install + update flow
- Test su mobile viewport 390×844 (iPhone 12) + 412×915 (Pixel 7)

## 15.4 Visual regression
- Chromatic o Playwright screenshots per:
  - Hub Casa (light)
  - Liste con > 0 item / 0 item / overdue
  - Avatar in tutti i 9×12 = 108 stati (regression test importante!)
  - Chat con messaggio assistant inline avatar
  - Permission onboarding 4 step

---

# 16. Deliverables & milestones

## Milestone 1 — Foundation (1-2 settimane)
- Vite + React + TS strict + Tailwind + Phosphor icons setup
- Design system: tokens, Typography, Button, Card, Badge, Input, Modal, Toast, Sheet
- Auth flow: login + LAN auto-login + 3-tier storage
- Service worker + manifest + PWA install prompt iOS/Android/desktop
- Layout shell + bottom nav + side rail desktop
- AvatarProvider + CaraFace integration in shell

→ Acceptance: app installabile, login funzionante, avatar visibile in shell

## Milestone 2 — Capabilities (1 settimana)
- Permission onboarding page + hooks
- Push notification setup + service worker push handler + rich notification UI
- Mic pipeline (riusa libreria v1) + integration nel floating avatar
- Geolocation hook (only on demand)
- Wake lock hook

→ Acceptance: tutti i permessi richiedibili, notifiche push ricevute,
mic registra + Whisper backend trascrive

## Milestone 3 — Core pages (2 settimane)
- Hub Casa con avatar hero + voice + suggerimenti
- Chat fullscreen con SSE + audio playback + avatar inline
- Liste hub (tasks + shopping + notes + reminders) con CRUD + optimistic
- Vita hub (calendar timeline + news + radio + meteo)
- Tu/Me hub (profilo + persona + memoria + settings + integrazioni)

→ Acceptance: tutte le 5 top-level navigabili, CRUD funzionante, voice
attiva ovunque, avatar reagisce al contesto

## Milestone 4 — Admin & search (1 settimana)
- Search globale (overlay)
- Admin hub + admin pages essenziali (persona, memory, users, diagnostics)
- Discoveries page (CDA history)

→ Acceptance: admin può governare tutti i sotto-sistemi, search trova
across kinds

## Milestone 5 — Innovations & polish (1-2 settimane)
- Avatar drawer (voice anywhere + quick actions persona-aware)
- Persona-aware UI (saluti dinamici + accessibility_mode)
- Conversational widgets
- Color-coded categories applicato ovunque
- Skeleton + delight (Framer Motion transitions)
- Haptic feedback
- Offline-first per GET viste
- Avatar che impara routine

→ Acceptance: app sembra "viva", non statica; persona detection visibile
ovunque; UX delightful

## Milestone 6 — Performance & accessibility (1 settimana)
- Bundle size budget rispettato
- Lighthouse > 95 PWA, > 90 Performance, > 95 Accessibility
- Test su iPhone 12+ + Pixel 7+ reale
- E2E test suite verde
- Visual regression baseline

→ Acceptance: i numeri stanno dentro § 11 + § 12

## Milestone 7 — Migration & rollout (1 settimana)
- Deploy nuovo PWA in parallelo a v1 (URL diversi: `/v2/` o subdomain)
- Migrazione token / settings utente — no breaking change backend
- A/B testing 1 settimana
- Rollover finale

→ Acceptance: famiglia Pedoto migra senza ri-login, niente regressioni

---

# 17. Out of scope esplicito

Cose che **NON** fai in questo progetto:

1. **Wall surface** (`/wall/*`) — invariata, non toccare
2. **Backend Python** — non modifichi i 37+ router, solo li consumi
3. **Hardware Wall fisico** — è progetto separato per il Mese 6
4. **Migration del DB** — niente schema change
5. **MCP server** — è feature separata pianificata, vedi `docs/...`
6. **State machine FSM consolidamento** — feature γ separata
7. **LLM HTTP separation** — feature δ separata
8. **Voice cloning / TTS custom** — Piper basta finché non c'è hardware migliore

Se trovi un caso che richiede una di queste, fermati e segnala.

---

# 18. Quality bar

Una PR è ready quando:

- [ ] Tutti i TS strict checks passano
- [ ] ESLint zero errors zero warnings
- [ ] Unit tests dei file toccati passano
- [ ] Visualmente verificato su iPhone 12 viewport (390×844) Chrome DevTools mobile mode
- [ ] Verificato su Pixel 7 viewport (412×915) Chrome DevTools mobile mode
- [ ] Verificato su desktop 1280×720
- [ ] Accessibility: nessuna riduzione del Lighthouse a11y score
- [ ] Performance: nessuna regression > 5% nei budget
- [ ] Service worker registrato e cache strategy invariata o intenzionalmente
  cambiata
- [ ] Documentation: ogni nuovo hook + componente design system ha un commento
  TSDoc con esempio d'uso

---

# 19. Stile codice

- Funzioni preferite a classi (`export function FooBar() {}` non `export class FooBar`)
- Hook custom per logica riusabile: `useXxx()` convention
- File component max 400 righe; oltre → split
- Cartelle per dominio in `routes/`, non per tipo:
  ```
  routes/
    home/                # /
      HubHome.tsx
      HubHome.test.tsx
      hooks.ts
      types.ts
    chat/
    list/
    life/
    me/
    admin/
  components/
    avatar/              # CaraFace + Avatar drawer + floating
    chat/                # MessageBubble, ChatInput
    common/              # Button, Card, etc.
    voice/               # MicButton, AudioMeter
    ...
  design/                # tokens.ts, theme.ts, motion.ts
  lib/                   # authStorage, micPipeline, etc.
  api/                   # tasks.ts, chat.ts, etc.
  ```
- Naming: PascalCase componenti, camelCase variabili/funzioni, SCREAMING_SNAKE_CASE costanti
- Niente `any`, mai. Se non sai il tipo, usa `unknown` + narrow.
- Commenti: solo per il "perché", non per il "cosa". Il codice è il cosa.
- Italian-or-English mixing nei commenti: **commenti in inglese**, **stringhe UI in italiano**.

---

# 20. Una nota finale al tuo agente

CARA non è un'app da costruire bene. È **una persona da fare sentire vera**.

Ogni decisione tecnica deve essere subordinata a questa: "Quando Marina prende il
telefono alle 8 del mattino e tap sull'icona CARA, in quel mezzo secondo prima
che il primo frame sia disegnato — cosa deve provare?"

La risposta corretta è: "Mi sembra che mi conosca."

Non un caricamento. Non un logo. Non un menu. **L'avatar**, che la guarda, che le
sorride, che sa che sono le 8 del mattino, che le ricorda con una frase gentile
quello che è importante oggi.

Costruisci la PWA così.

Buon lavoro.

---

**Fine prompt.**

Versione di questo documento: v1.0 — 2026-05-21
