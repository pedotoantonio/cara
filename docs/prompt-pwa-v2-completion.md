# Prompt — Completamento PWA CARA v2 + test approfondito

> Documento operativo per portare la PWA CARA v2 da Milestone 1+2 (già live
> su `https://192.168.1.23:8456/`) fino a uno stato **"completo e usabile
> per la famiglia"**, seguito da una **batteria di test approfonditi** e
> da un **report onesto** dei risultati.
>
> Versione: 1.0 — 2026-05-22
> Branch: `feature/pwa-v2`
> Backend: invariato (FastAPI Python su NPU RK3588, 37+ REST router)

---

## 0. Stato di partenza (snapshot 2026-05-22)

### Già fatto
- ✅ Scaffold Vite + React 18 + TS strict + Tailwind + Phosphor + Framer Motion
- ✅ Design system: tokens (sfondo bianco + 8 accent), Button/Card/Badge/Input/Sheet/Toast/Skeleton
- ✅ Auth 3-tier storage + API client con bearer/refresh
- ✅ LoginPage con redirect post-login (fix bug recente)
- ✅ AppShell con bottom nav 5 entry mobile + side rail desktop
- ✅ CaraFace v2 portato + AvatarProvider Zustand + FloatingAvatar persistente
- ✅ HubHome con saluto persona-aware + meteo + prossimi 3 (tasks+reminders)
- ✅ Permission onboarding `/permissions` (4 capability)
- ✅ Voice flow E2E: VoicePanel + MicPipeline + AudioLevelMeter + ASR Whisper
- ✅ Push setup VAPID + reaffirm silent
- ✅ useGeolocation + useWakeLock hooks
- ✅ PWA manifest + service worker injectManifest
- ✅ Dockerfile + nginx proxy + deploy parallelo a v1 (porta 8456)
- ✅ ErrorBoundary globale

### Non fatto
- ❌ Chat SSE streaming reale (`/chat` è placeholder)
- ❌ Liste CRUD vere (`/list/*` placeholder)
- ❌ Vita timeline (`/life/*` placeholder)
- ❌ `/me/*` page reali (Settings, Persona, Memory)
- ❌ Admin hub
- ❌ Avatar drawer (oggi tap+long-press fanno entrambi voice)
- ❌ Test E2E approfondito

---

## 1. Goal

Portare la PWA v2 dallo stato corrente a una versione **usabile dalla famiglia
in produzione** — non perfetta, ma con tutte le feature core funzionanti.

L'obiettivo NON è feature parity al 100% con v1: è coprire l'**80% dell'uso
quotidiano della famiglia** (chat, liste, profilo) con UX **migliore** della v1.

### Definition of done per "completa"

L'utente Antonio deve poter:

1. Loggare (✅ già fatto)
2. Vedere la home con saluto, meteo, prossimi (✅ già fatto)
3. **Avere una conversazione completa con CARA**: scrivere o parlare,
   ricevere risposta streaming con voce sintetizzata, vedere l'avatar
   reagire
4. **Gestire le sue task**: aggiungere, completare, modificare, eliminare
5. **Gestire la spesa**: aggiungere item, marcare comprato, rimuovere
6. **Scrivere note** con autosave
7. **Cambiare le sue impostazioni**: tono voce, password, logout
8. **Vedere il proprio profilo persona** + chiederne il rebuild
9. **Vedere il calendario unificato** (eventi + tasks)
10. **Andare alle pagine admin** (che restano su v1 — link cross-app)

Non c'è bisogno per ora di:
- News reading + TTS articolo
- Radio streaming
- Reminders form wizard (la home già li mostra)
- Search globale
- Conversational widgets

Quelli sono "stretch goal", se avanza tempo.

---

## 2. Vincoli

- **Backend invariato.** Tutto consuma `/api/v1/*` come oggi.
- **Stile invariato.** Sfondo bianco, 8 accent, Inter + Source Serif 4.
- **Avatar sempre presente.** Ogni nuova page deve chiamare `setAvatar(...)`
  al mount per esprimere il suo stato.
- **TypeScript strict.** Zero `any`. `unknown` + narrow se serve.
- **Mobile-first.** Ogni layout testato su viewport 390×844 + 412×915.
- **Touch target ≥44px.** Non negoziabile.
- **Italian-or-English.** Commenti inglese, stringhe UI italiano.
- **No regressioni v1.** Frontend v1 su :8455 continua a girare intoccato.

---

## 3. Milestone 3 — Core pages

### 3.1 Chat SSE streaming (`/chat`)

**Requisiti**:
- Lista conversazioni nello sheet laterale (apribile da icona menu in topbar)
- Nuova conversazione = `POST /conversations` poi navigate
- Selezione conversazione = `/chat/:conversationId`, fetch `GET /conversations/{id}/messages`
- Input testuale in fondo: textarea autoresize + send button + mic button
- Send → `POST /chat` con `messages: [{role:'user', content:'...'}]` + `conversation_id` query
- SSE stream parsing per: `meta`, `token`, `audio_chunk`, `done`, `error`, `revision`
- Token accumulati in un message bubble assistente (typing dots → tokens streaming)
- audio_chunk: base64 → blob → MediaSource o `<audio>` queue, playback inline
- Avatar inline 40px accanto a ogni bubble assistente
- Avatar globale (floating o hero) speaking=true quando TTS in playback, lip-sync
- "Sto pensando…" durante l'attesa del primo token
- Auto-scroll a fondo conversazione
- WelcomeScreen se empty conversation (greeting + 3 prompt suggeriti)

**File da creare**:
- `src/lib/chatStream.ts` — wrapper `fetch` + `ReadableStream` per SSE
- `src/lib/ttsPlayback.ts` — coda audio_chunk WAV → playback ordinato
- `src/api/chat.ts` — list conversations, get messages, send (returns Response)
- `src/components/chat/MessageBubble.tsx`
- `src/components/chat/ConversationList.tsx`
- `src/components/chat/ChatInput.tsx`
- `src/routes/chat/ChatPage.tsx` (sostituisce placeholder)

**SSE parsing pattern** (essenziale):
```ts
const response = await authFetch('/chat?conversation_id=...', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ messages, max_new_tokens: 600 }),
});
const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = '';
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const events = buffer.split('\n\n');
  buffer = events.pop() ?? '';
  for (const ev of events) {
    // parse "event: token\ndata: {json}" pattern
  }
}
```

### 3.2 Liste CRUD (`/list/*`)

**4 sub-route**:
- `/list/tasks` — tasks
- `/list/shopping` — spesa
- `/list/notes` — note
- `/list/reminders` — reminders (read-only o quick-add minimo)

**Pattern comune**:
- Page con tabs interne (Tasks / Spesa / Note / Promemoria) sempre visibili in top
- Per ogni list:
  - Input quick-add in top con placeholder contestuale ("Nuova task…")
  - List items con:
    - Checkbox/done state (tasks, shopping)
    - Titolo editable inline su tap
    - Meta (data scadenza per tasks, qty per shopping, last edit per notes)
    - Menu actions su long-press o swipe-left (Modifica, Elimina, Marca completato)
  - Floating avatar reagisce al numero items (peeking se >10 overdue)
  - Pull-to-refresh (Framer Motion + boundary detection)
  - Optimistic updates via React Query `useMutation` con `onMutate` + rollback su error

**File da creare**:
- `src/api/tasks.ts`, `src/api/shopping.ts`, `src/api/notes.ts`, `src/api/reminders.ts`
- `src/routes/list/ListLayout.tsx` (tabs + outlet)
- `src/routes/list/TasksPage.tsx`
- `src/routes/list/ShoppingPage.tsx`
- `src/routes/list/NotesPage.tsx`
- `src/routes/list/RemindersPage.tsx`
- `src/components/lists/ListItemCard.tsx`
- `src/components/lists/QuickAddInput.tsx`

### 3.3 Vita (`/life/*`)

**Sub-route**:
- `/life/calendar` — calendario unificato eventi + tasks del mese
- `/life/news` — RSS news con TTS
- `/life/radio` — radio streaming (rimandato — solo placeholder)
- `/life/meteo` — meteo dettaglio (current + forecast)

**Priorità**: Calendar + Meteo. News come bonus. Radio rimandato.

**File da creare**:
- `src/api/calendar.ts` — events + tasks merge
- `src/api/news.ts`, `src/api/weather.ts` (extend)
- `src/routes/life/LifeLayout.tsx` (tabs)
- `src/routes/life/CalendarPage.tsx`
- `src/routes/life/MeteoPage.tsx`
- `src/routes/life/NewsPage.tsx`
- `src/components/life/MonthGrid.tsx`

---

## 4. Milestone 4 — `/me/*` + Admin

### 4.1 Settings (`/me/settings`)

- Form full_name + birth_date + tone_preference (dropdown 5 toni) →
  `PATCH /auth/me`
- Toggle "Notifiche push" che chiama `setupPushSubscription` o
  `unsubscribePush`
- Bottone "Cambia password" → `POST /auth/change-password`
- Bottone "Esci" → `logout()` + navigate /login
- Sezione "App": versione, link reset cache (unregister SW), link
  resetta onboarding permessi

### 4.2 Persona self-service (`/me/persona`)

- `GET /persona/me` → mostra markdown + confidence + last_built_at + status
- Bottone "Aggiorna profilo" → `POST /persona/me/rebuild` (con cooldown
  30min lato server → catch 429 e mostra messaggio attesa)
- Bottone "Cancella mio profilo" (GDPR) → `DELETE /persona/me` con
  conferma modal
- Render markdown con sezioni H3 + bullet STABILE/EPISODICO color-coded

### 4.3 Memory self-service (`/me/memory`)

- `GET /memory/facts` → lista fatti raggruppati per tipo
- Per ogni fatto: testo + confidence + source + bottone "Elimina"
- Bottone export "Esporta i miei dati" → `POST /memory/export` → JSON download
- Bottone purge "Cancella tutta la mia memoria" → `POST /memory/purge` con
  doppia conferma

### 4.4 Admin hub (`/admin`)

- Page semplice che mostra "Le pagine admin avanzate sono sulla v1 di CARA."
  con link che aprono in nuova tab `https://192.168.1.23:8455/admin/*`:
  - `/admin/persona` (la abbiamo appena creata su v1)
  - `/admin/memory`
  - `/admin/users`
  - `/admin/face`
  - `/admin/smart-home`
  - `/admin/skills`
  - `/admin/devices`
  - `/admin/proactivity`
  - `/admin/telegram`
  - `/admin/diagnostics`
- Quando le admin pages saranno riscritte in v2 (futuro), questo hub diventerà
  il vero entry point. Per ora è solo un bridge.

---

## 5. Milestone 5 — Polish & innovations

### 5.1 Avatar drawer

Oggi tap su FloatingAvatar = voice. Cambia in:
- **Tap** = apre AvatarDrawer (Sheet dal basso)
- **Long-press 700ms** = voice immediato (mantieni)

AvatarDrawer:
- Hero CaraFace inline 96px + saluto contestuale
- Quick actions persona-aware:
  - "Parla con CARA" (voice)
  - "Aggiungi una task"
  - "Cosa devo fare oggi?" (chat preloaded)
  - "Aggiungi alla spesa"
  - "Nuova nota"
- Link "Apri chat completa" → `/chat`

### 5.2 Skeleton states + delight

- Skeleton screen per ogni page che fa fetch (Hub Casa, Tasks list, ecc.)
- `AnimatePresence` su route transitions
- Haptic `navigator.vibrate(10)` su tap su bottoni primari (Android only)

### 5.3 Ottimizzazioni

- React Query cache più aggressiva (staleTime 30s per liste, 5min per persona)
- Image lazy-loading dove serve
- Prefetch on hover (link "Apri chat" prefetcha messaggi)

---

## 6. Test approfondito

Dopo aver completato M3-M5, esegui questa batteria di test e produci un
**report onesto**.

### 6.1 Build verification

```bash
cd /opt/cara/frontend-v2
npm run build
# Verifica: TS strict zero errors, no warnings critici, build success
# Bundle size: < 250 KB gz iniziale (route Casa)
```

### 6.2 Smoke test endpoint (curl)

```bash
TOKEN=$(curl -sk -X POST https://192.168.1.23:8456/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Endpoint v2 deve servire HTML
curl -sk https://192.168.1.23:8456/ -o /dev/null -w "/  HTTP=%{http_code}\n"
curl -sk https://192.168.1.23:8456/manifest.webmanifest -o /dev/null -w "manifest  HTTP=%{http_code}\n"
curl -sk https://192.168.1.23:8456/sw.js -o /dev/null -w "sw.js  HTTP=%{http_code}\n"
curl -sk https://192.168.1.23:8456/registerSW.js -o /dev/null -w "registerSW.js  HTTP=%{http_code}\n"

# API proxy attraverso v2 deve raggiungere il backend
curl -sk https://192.168.1.23:8456/api/v1/chat/health -o /dev/null -w "chat/health  HTTP=%{http_code}\n"
curl -sk -H "Authorization: Bearer $TOKEN" https://192.168.1.23:8456/api/v1/tasks -o /dev/null -w "tasks  HTTP=%{http_code}\n"
curl -sk -H "Authorization: Bearer $TOKEN" https://192.168.1.23:8456/api/v1/auth/me -o /dev/null -w "auth/me  HTTP=%{http_code}\n"
curl -sk -H "Authorization: Bearer $TOKEN" https://192.168.1.23:8456/api/v1/persona/me -o /dev/null -w "persona/me  HTTP=%{http_code}\n"
```

Tutti devono ritornare 200 (200 OK, anche se la GET ritorna null come body).

### 6.3 Bundle size

```bash
cd /opt/cara/frontend-v2
ls -la dist/assets/*.js dist/assets/*.css | awk '{print $9, $5}'
du -sh dist/
```

Verifica:
- Initial route (chunk principale + react + motion + query + CSS) < 250 KB gz totale
- Singolo chunk > 200 KB raw deve essere lazy-loaded

### 6.4 TypeScript strict

```bash
cd /opt/cara/frontend-v2
npx tsc --noEmit
```

Deve passare con ZERO errori. Niente `any`, niente `@ts-ignore` lasciati.

### 6.5 Routes accessibility

```bash
for path in / /login /permissions /chat /list /list/tasks /list/shopping /list/notes /list/reminders /life /life/calendar /life/meteo /me /me/settings /me/persona /me/memory /admin; do
  echo "$path → $(curl -sk -o /dev/null -w "%{http_code}" https://192.168.1.23:8456$path)"
done
```

Tutti devono ritornare 200 (la SPA serve sempre `index.html`, il routing è
client-side).

### 6.6 Container health

```bash
docker ps --filter "name=cara-frontend-v2" --format "{{.Names}}\t{{.Status}}"
docker logs cara-frontend-v2 --tail 20 | grep -iE "error|fatal" | head -5
```

### 6.7 Browser flow manuale (descrittivo nel report)

Procedura che l'autore del prompt deve eseguire mentalmente / simulare:
1. Apri `https://192.168.1.23:8456/` con LAN auto-login → atterri su `/`
2. Hub Casa: vedi avatar, saluto, prossimi
3. Tap "Parla con me" → VoicePanel si apre → permission mic → registra
4. Vai a `/chat` → vedi conversazioni → tap "+ Nuova" o invia messaggio
5. Aspetti che la chat risponda con streaming (vedi tokens arrivare)
6. Vai a `/list/tasks` → aggiungi una task → la vedi nella lista
7. Marca task completata → vedi diventare strikethrough
8. Vai a `/list/shopping` → aggiungi "pomodori" → checkbox completato
9. Vai a `/me/settings` → cambia tono → salva
10. Torna a `/` → il saluto è diverso (nuovo tono applicato)

Per ognuno: documenta se funziona, se ci sono bug visivi, latency notevoli.

### 6.8 Cosa cercare attivamente (failure mode tipici)

- White page silenziosa → ErrorBoundary catturerebbe ma magari no
- 404 sui chunk JS dopo deploy → service worker stale
- React Query infinite loop di refetch
- Avatar che non aggiorna lo stato fra route changes
- Mic che chiede permission ripetutamente
- Push non subscribe (server backend VAPID configured?)
- Bundle troppo grosso per dial-up rurale
- Touch target < 44px su qualche bottone
- Console warnings su `aria-*` mancanti

### 6.9 Reporting format

Il report finale deve includere:

```markdown
## PWA v2 — Test Report (data)

### Build
- TS errors: 0
- Bundle gz: XXX KB
- Build time: XXs

### Endpoint smoke
- Tabella path → HTTP code

### Browser flow
- Step 1: ✅ / ⚠️ / ❌
- Step 2: ...

### Findings
- [BUG] descrizione bug
- [LACK] feature mancante x
- [GOOD] qualcosa che funziona bene

### Cosa serve ancora per "produzione famiglia"
- ...

### Migration plan
- Quando Antonio può cambiare DNS PWA-icon-mobile dal v1 al v2
```

---

## 7. Cosa NON fare in questa fase

- Implementare backend nuovo (search globale, geofence, MCP server) — sono
  future feature, qui solo frontend
- Voice cloning, TTS espressivo — Piper esistente basta
- State machine FSM γ — è un altro Epic
- LLM HTTP separation δ — è un altro Epic
- A11y audit completo Lighthouse — basta una verifica empirica delle basi

---

## 8. Quality bar prima di considerare "completa"

- [ ] Build verde senza errori TS
- [ ] Bundle iniziale < 250 KB gz
- [ ] Routes 200 OK
- [ ] Chat reale stream messaggio + risposta
- [ ] Tasks CRUD funziona end-to-end
- [ ] Shopping CRUD funziona end-to-end
- [ ] Notes autosave funziona
- [ ] Settings tone preference salva e si applica
- [ ] Persona viewable + rebuild button
- [ ] Calendar mostra eventi reali del mese
- [ ] Meteo dettaglio
- [ ] Admin hub link
- [ ] Avatar drawer
- [ ] Test report scritto

---

## 9. Tempi attesi

Esecutore solo (un singolo agente AI):
- M3 chat + liste + vita: ~4-6 ore di lavoro focused
- M4 me + admin: ~2-3 ore
- M5 polish: ~1-2 ore
- M6 test report: ~30-60 minuti

Totale realistico: **una sessione lunga** (8-12 ore di context).

Se l'AI ha context limitato, può fare M3.1 (Chat) + M3.2 (Liste) +
M4 (Me) e fermarsi lì — il resto è polish.

---

**Fine prompt.**
