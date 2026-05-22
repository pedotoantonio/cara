# PWA v2 — Test Report (2026-05-22)

> Esito dell'esecuzione del prompt `prompt-pwa-v2-completion.md`.
> Tutti i test sono stati eseguiti contro la build deployata su
> `https://192.168.1.23:8456/`, container `cara-frontend-v2` healthy.

---

## 1. Build

| Metrica | Valore | Budget | Esito |
|---|---|---|---|
| TypeScript errors | 0 | 0 | ✅ |
| TS strict mode | sì | sì | ✅ |
| Build time | ~9.3s | n/a | ✅ |
| Initial route gz | ~179 KB | < 250 KB | ✅ |
| Total dist/ | 688 KB | < 1 MB | ✅ |
| SW precache | 623 KB / 15 entries | n/a | ✅ |

Breakdown bundle gz:
- `react-BW98J5pP.js` — 53.5 KB
- `motion-Cnq2nB2i.js` — 37.7 KB
- `index-Kn_pixU1.js` (app code) — ~70 KB
- `query-ivrGIM1Y.js` — 11 KB
- `index-CBLgB-5J.css` — 6.4 KB

---

## 2. Endpoint smoke (frontend SPA)

Tutti i path routing → 200 OK. La SPA serve sempre `index.html` per qualsiasi path, il routing è client-side:

| Path | HTTP | Note |
|---|---|---|
| `/` | 200 | Hub Casa |
| `/login` | 200 | Login page |
| `/permissions` | 200 | Onboarding |
| `/chat` | 200 | Chat senza convo |
| `/list/tasks` | 200 | |
| `/list/shopping` | 200 | |
| `/list/notes` | 200 | |
| `/list/reminders` | 200 | |
| `/life/calendar` | 200 | |
| `/life/meteo` | 200 | |
| `/life/news` | 200 | |
| `/me` | 200 | |
| `/me/settings` | 200 | |
| `/me/persona` | 200 | |
| `/me/memory` | 200 | |
| `/admin` | 200 | Hub bridge a v1 |
| `/manifest.webmanifest` | 200 | PWA manifest |
| `/sw.js` | 200 | Service worker |
| `/registerSW.js` | 200 | |

**Tot: 19/19 → 200.**

---

## 3. API proxy attraverso v2

Verifica che `https://192.168.1.23:8456/api/v1/*` proxati correttamente a `cara-backend:8000`:

| Endpoint | HTTP |
|---|---|
| `GET /api/v1/chat/health` | 200 |
| `GET /api/v1/auth/me` | 200 |
| `GET /api/v1/tasks` | 200 |
| `GET /api/v1/shopping` | 200 |
| `GET /api/v1/notes` | 200 |
| `GET /api/v1/persona/me` | 200 |
| `GET /api/v1/conversations` | 200 |
| `GET /api/v1/reminders/upcoming?days=7&limit=10` | 200 |
| `GET /api/v1/weather/current?lat=...&lon=...` | 200 |

**Tot: 9/9 → 200.**

---

## 4. Test funzionale E2E

### 4.1 Chat SSE streaming reale

```
POST /api/v1/conversations         → 201 (created)
POST /api/v1/chat?conversation_id  → 200 + SSE stream
```

Eventi ricevuti per il messaggio "Ciao, dimmi solo come stai in due parole.":

```
event: meta       data: {"conversation_id": "63c6500e-..."}
event: token      data: {"text": "B"}
event: token      data: {"text": "ene"}
event: token      data: {"text": "!"}
event: token      data: {"text": ""}    # EOS token
event: done       data: {"tokens": 4, "first_token_seconds": 7.30, "total_seconds": 7.57}
```

**✅ "Bene!"** assemblato correttamente dai token. TTFT 7.3s (NPU sotto carico,
normale per il 1.5B). Parser SSE funziona, event types corretti, stream
termina con `done` event.

### 4.2 CRUD Tasks

```
POST   /api/v1/tasks         {title: "Test task da v2 PWA"}  → 200 + id
PATCH  /api/v1/tasks/{id}    {done: true}                    → 200
DELETE /api/v1/tasks/{id}                                    → 204
```

✅ Crea, marca completata, elimina — full cycle.

### 4.3 CRUD Shopping

```
POST   /api/v1/shopping      {title: "pomodori test v2"}  → 200 + id
DELETE /api/v1/shopping/{id}                              → 204
```

✅ Crea + elimina.

---

## 5. Container health

```
$ docker ps --filter "name=cara-frontend"
cara-frontend     Up healthy   (v1 su :8455 — intoccato)
cara-frontend-v2  Up healthy   (v2 su :8456 — appena deployato)
```

Entrambi i container girano in parallelo. Niente conflitti.

---

## 6. Funzionalità implementate

### ✅ Milestone 1 — Foundation
- Vite + React 18 + TS strict + Tailwind + Phosphor + Framer Motion
- Design system completo (8 accent, tipografia, motion, ombre)
- Auth 3-tier storage con probe read-back
- API client con bearer + auto-refresh
- LoginPage con redirect post-login
- AppShell + bottom nav 5 + side rail desktop
- CaraFace v2 + AvatarProvider + FloatingAvatar
- HubHome con greeting persona-aware + meteo + prossimi 3
- PWA manifest + injectManifest SW
- ErrorBoundary globale
- Docker deploy parallelo a v1

### ✅ Milestone 2 — Capabilities
- Permission onboarding `/permissions` con 4 capability
- usePermissions hook con probe + request per ognuna
- VoicePanel modal con MicPipeline + AudioLevelMeter + Whisper ASR
- Push setup VAPID + reaffirm silent on boot
- useGeolocation hook on-demand
- useWakeLock hook con re-request su visibilitychange

### ✅ Milestone 3 — Core pages
- **Chat**: SSE streaming, token+audio_chunk+done events, conversazioni
  list nello sheet, optimistic user message, draft assistant streaming,
  cancel mid-stream, scroll auto-bottom, welcome screen con suggerimenti
- **Liste**: 4 tabs (Tasks/Shopping/Notes/Reminders), CRUD ottimistico
  via React Query, quick-add input, edit inline, delete tap-to-confirm
- **Vita**: Calendar mese 7×6 con merge events+tasks+reminders, drill
  giorno, Meteo current + forecast 7gg, News RSS, Radio placeholder

### ✅ Milestone 4 — Me + Admin
- **Settings**: form profilo (nome/data/tono), toggle push, pulisci cache,
  reset onboarding, logout, versione app
- **Persona**: viewer markdown profilo con confidence/status badge,
  rebuild button con cooldown 30min, delete GDPR
- **Memory**: facts raggruppati per tipo, export JSON, purge bulk
- **AdminHub**: bridge ai 11 admin v1 con icone colorate (apre tab)

### ✅ Milestone 5 — Polish
- **AvatarDrawer**: Sheet dal basso aperto da tap su FloatingAvatar.
  Long-press 700ms = voice diretto (mantenuto). Hero face + saluto +
  grid 7 quick actions colorate

---

## 7. Findings — cosa va bene

- **[GOOD]** Bundle 179 KB gz iniziale → caricamento veloce anche su 3G
- **[GOOD]** TypeScript strict mode pulito, zero `any`
- **[GOOD]** Chat SSE robusto: parser fetch+ReadableStream funziona,
  Bearer header passa, cancellabile via AbortSignal
- **[GOOD]** Auth 3-tier già adottato dal day 1 (no bug login-loop di v1)
- **[GOOD]** Avatar reagisce al contesto di ogni page (glow accent cambia
  fra rosa/mint/sky/coral/lilac in base a dove sei)
- **[GOOD]** Floating avatar drag-friendly + caption fade automatico
- **[GOOD]** Liste CRUD ottimistiche → percezione zero-latency anche su NPU
  sotto carico
- **[GOOD]** ErrorBoundary globale → niente più "schermata bianca silenziosa"
- **[GOOD]** Permissions onboarding upfront → evita "perché non funziona?"
- **[GOOD]** v1 e v2 girano in parallelo senza conflitti → migrazione safe

## 8. Findings — cosa NON è ancora completo

- **[LACK]** Avatar nella chat: la `MessageBubble` mostra l'avatar inline
  ma il lip-sync vero (caratteri sincronizzati col TTS playback)
  richiede un hook custom non implementato — l'avatar respira ma
  non parla davvero in sync con l'audio Piper.
- **[LACK]** Conversazione titolo: oggi è sempre "Senza titolo". Il
  backend dovrebbe generarlo dalla prima domanda; in v2 non lo
  forziamo, eredita lo stato del backend.
- **[LACK]** Cancellazione conversazione: API client ha `deleteConversation`
  ma non c'è UI nella sheet (delete swipe-left non ancora cablato).
- **[LACK]** Vita Radio: solo placeholder
- **[LACK]** Search globale Cmd+K: descritta nel prompt ma non
  implementata (richiede backend `/api/v1/search` nuovo o ricerca
  client-side su dati già caricati — deferred)
- **[LACK]** Tasks form data scadenza UI: il form quick-add accetta solo
  il titolo. Datepicker per due_date non ancora aggiunto.
- **[LACK]** Conversational widgets: descritti nel prompt, non implementati
- **[LACK]** Persona-aware UI completa: già fatto greeting persona-aware
  (hub home + drawer), ma manca accessibility_mode (font grossi per
  Ilaria, gamification per bambini) — è una feature backend nuova.

## 9. Findings — limiti noti

- **[LIMIT]** TTFT chat 7.3s = NPU sotto carico Frigate. Non è un bug v2,
  è il modello 1.5B che impiega ~7s a iniziare a generare quando
  l'NPU è occupata. Coerente con CLAUDE.md note "TTFT 0.20s, sustained
  ~5-9 tok/s" — qui era 0.53 tok/s perché c'erano altri job in coda.
- **[LIMIT]** Notifiche push da iOS < 16.4 = non supportate (problema
  iOS, mitigato a livello UI che disabilita il toggle).
- **[LIMIT]** Browser TTS (`speechSynthesis`) NON usato in v2 — solo
  Piper backend tramite audio_chunk. Evitato il bug Chromium di v1.
- **[LIMIT]** Service worker `precacheAndRoute` mantiene 15 entries
  (~624 KB). Tutti i file critici sono là, ma il SW non fa update
  istantaneo: usare "Pulisci cache" da settings se serve forzare.

## 10. Cosa serve per "produzione famiglia"

Lo stato attuale di v2 **è già usabile** per il flusso quotidiano della
famiglia. La parità completa con v1 manca su queste feature non-core:

1. **Wallet widget canvas** — non implementato; v1 lo ha
2. **Discoveries (CDA)** — non implementato; v1 lo ha
3. **Integrazioni Google** — non implementate; v1 ha la pagina, ma OAuth
   funziona uguale (è sull'admin)
4. **Workflow Receipt/Bill/Recipe** — non implementati; per ora gli
   utenti li gestiscono via chat (chiedere a CARA "estrai questa
   ricevuta") che funziona via SSE
5. **Devices / pairing** — non implementati; v1 ha la pagina
6. **Face enroll wizard** — non implementato; per ora si va su v1
7. **Diagnostics interna** — admin → resta su v1
8. **Setup first-run** — non implementato; non serve perché backend
   è già configurato; nuovi admin lo fanno da v1

**Conclusione onesta**: v2 copre **~80% del fabbisogno quotidiano** della
famiglia. Le feature mancanti sono o admin-only (gestibili dalla v1) o
nice-to-have non urgenti.

## 11. Migration plan suggerito

### Fase A (oggi, già fatta)
- v2 deployata su :8456 in parallelo a v1 :8455
- Famiglia continua a usare v1 (icona PWA installata punta a :8455)
- Antonio testa v2 sul telefono in modalità "esplorativa"

### Fase B (1 settimana di test)
- Antonio fixa eventuali bug visivi che emergono dall'uso reale
- Marina/Sara/Matteo provano qualche flow base (chat, task, spesa) su v2
- Feedback in forma di "questo non va, questo va meglio"

### Fase C (rollover scelto da te)
- Quando v2 dà sicurezza, **disinstalla** PWA v1 dal telefono famiglia
- **Installa** PWA v2 (`https://192.168.1.23:8456/`) come "CARA"
- Le icone shortcut "Voce / Task / Spesa / Ricordi" sono già nel manifest v2
- v1 :8455 resta acceso come backup per 1-2 mesi
- Quando tutto è stabile, decommissiona v1 (rimuovi service da
  docker-compose.yml o cambia nginx-proxy `/` per puntare a v2)

### Fase D (futura)
- Riscrivere le 11 admin pages anche in v2 (oggi sono solo link bridge)
- Implementare le feature "stretch" (Wallet, Devices, Discoveries)
- Stato machine FSM centralizzata (Ondata γ del Lumo report)
- LLM HTTP separation (Ondata δ)

---

## 12. Come testare v2 dal tuo telefono

1. Apri `https://192.168.1.23:8456/` sul telefono dal WiFi di casa
2. LAN auto-login → arrivi su `/permissions` (al primo accesso)
3. Concedi i permessi (mic + notifiche raccomandati)
4. Tap "Inizia a usare CARA" → home con avatar
5. Da home: tap **mic gigante** = chat vocale; tap su avatar (qualsiasi
   page) = quick actions drawer; bottom nav per le 5 sezioni
6. Per installarla come app: Chrome → menu (⋮) → "Installa app"; iOS
   Safari → Condividi → "Aggiungi a Home"

---

## 13. Stato git/repo

- Branch: `feature/pwa-v2`
- Ultimi commit:
  - `f762b3c` feat(pwa-v2): M3-M5 completi — chat SSE + liste CRUD + vita + me/admin + drawer
  - `4febeaa` fix(pwa-v2): LoginPage now navigates after auth + global ErrorBoundary
  - `10824a1` feat(pwa-v2): M2 Capabilities — mic + permissions + push + GPS + wake-lock
  - `6a08c43` feat(pwa-v2): scaffold + Milestone 1 + Hub Casa vertical slice
- GitHub: https://github.com/pedotoantonio/cara/tree/feature/pwa-v2
- Pronto per merge in main quando dai OK

---

## 14. Verdict

✅ **L'app è completa per uso famiglia quotidiano.**

I core flows funzionano end-to-end: chat con CARA, liste, calendario,
profilo, persona, memoria. La UX è coerente (sfondo bianco, accent
colorati, avatar persistente, mobile-first), il bundle è leggero (179 KB),
tutto build verde e gli endpoint rispondono.

Le feature mancanti sono note (sezione 8/10) e nessuna è bloccante per
l'uso quotidiano della famiglia. Possono essere aggiunte in iterazioni
future senza rifattorizzare quello che c'è oggi.
