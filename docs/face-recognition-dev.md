# Riconoscimento facciale — guida per chi scrive il codice

Note di architettura, contratti e punti di estensione per la feature di
face recognition. Per la panoramica utente vedi
[`face-recognition.md`](./face-recognition.md).

## Stack

| Strato | Libreria | Note |
|--------|----------|------|
| Frontend ML | `@vladmandic/face-api` 1.7 | Fork mantenuto di face-api.js; usa TF.js sotto, supporta `OffscreenCanvas`. |
| Frontend storage | `idb-keyval` 6.2 | Cache locale degli snapshot di enrollment (Phase 3+). |
| Backend ORM | `pgvector` 0.3 + SQLAlchemy 2 | `Vector(128)` con HNSW cosine index. |
| Backend DB | Postgres 16 + pgvector 0.8 | Estensione installata in `cara-postgres-pgvector:16-0.8.0`. |

Modelli scaricati al primo avvio in `frontend/public/models/face-api/`
(7.1 MB totali, serviti dallo stesso host). Niente CDN: il service
worker li mette in cache-first per renderli offline.

## Pipeline a runtime

```
            ┌──────────────┐
 webcam ──▶ │  <video>     │
            └──────┬───────┘
                   │ getImageData (OffscreenCanvas, 480×360)
                   ▼
            ┌────────────────────────────┐
            │  Web Worker (face.worker)  │
            │                            │
            │   tinyFaceDetector         │
            │      ↓                     │
            │   faceLandmark68Net (lazy) │
            │      ↓                     │
            │   faceRecognitionNet (lazy)│
            │      ↓                     │
            │   match vs profile cache   │
            └──────┬─────────────────────┘
                   │ Float32Array(128) (transferable)
                   ▼
       ┌──────────────────────────────┐
       │  FaceContext (main thread)   │
       │                              │
       │  - cap 4 facce, sort by area │
       │  - smoothing 3 frame / 1 s   │
       │  - lost 2 s                  │
       │  - adaptive throttle         │
       │  - idle 30 s → 1 FPS         │
       │  - anti-spoof (centroid std) │
       │  - continuous learning       │
       │  - event bus (face.*)        │
       └──────┬───────────────────────┘
              ▼
   ActiveProfileContext  ──▶  data-cara-* on <html>
   FaceOverlay           ──▶  SVG boxes + name
   any subscriber        ──▶  greet, load profile, …
```

## Frontend — moduli pubblici

```ts
import {
  // Provider + accessors
  FaceProvider, useFaceContext,
  ActiveProfileProvider, useActiveProfile,

  // Components
  FaceOverlay, ActiveProfileBadge,

  // Hooks
  useFaceDetection,

  // Permission gate
  canPerformAction, useChildSafe,
} from 'src/features/face';
```

Solo questi simboli sono il contratto. Il worker, il context interno e
i singoli step del wizard non lo sono — possono cambiare in patch.

### `useFaceContext()` — API completa

| Campo | Tipo | Cosa è |
|-------|------|--------|
| `detections` | `FaceDetection[]` | Volti visibili (≤ 4), ordinati per area. `identity` è popolato solo per identità *confermate*. |
| `primarySubject` | `FaceIdentity \| null` | L'addressee. Il box più grande = la persona più vicina. |
| `companions` | `FaceIdentity[]` | Altri identificati nella scena. |
| `confirmedIdentity` | alias di `primarySubject` | Backwards-compat. |
| `lastDurationMs` / `currentIntervalMs` / `idle` | numeri / bool | Diagnostica + adaptive throttle. |
| `spoofingSuspected` | `bool` | True quando il centroide del primario è statico > 1 s. |
| `modelsReady` / `recognitionReady` | `bool` | Modelli caricati. |
| `profilesCount` | `number` | Profili nella cache del worker. |
| `lastError` | `string \| null` | Ultimo errore (worker init, detect, network). |
| `start(video)` / `stop()` | | Apri/chiudi il loop. |
| `refreshProfiles()` | | Ricarica la cache dal backend. Chiamare dopo un enrollment. |
| `enableRecognition()` | | Carica i modelli `landmark68` + `recognition` (~6.8 MB). |
| `onEvent(handler)` | `() => unsubscribe` | Sottoscrive al bus locale. |

### Event bus

Quattro eventi, descritti in `types.ts`:

- `face.detected` — un frame ha visto un volto. Frequenza alta.
- `face.identified` — un volto noto è stato confermato (3 frame / 1 s).
  Una sola volta per (profilo, sessione). Payload include `companions`.
- `face.unknown_present` — un volto con descrittore valido che NON
  matcha nessun profilo. Utile per offrire l'enrollment.
- `face.lost` — un'identità precedentemente confermata è uscita di
  scena per > 2 s.

### Active profile e modalità bambino

`ActiveProfileContext` ascolta gli eventi e tiene "chi è l'addressee
attivo". Mirror al DOM:

```html
<html data-cara-active-profile="<uuid>" data-cara-child-mode="true">
```

CSS hooks: `html[data-cara-child-mode="true"] .my-component { … }`.

Smart-home gate: `canPerformAction(action, profile)` torna
`{ allowed, reason }`. È **first line**, non l'unica: la lista è
substring-match su `CHILD_BLOCKED_ACTIONS`. Per aggiungere nuove
integrazioni sensibili, espandi la lista in `permissions.ts`.

## Backend — endpoint

Tutti sotto `/api/v1/face/`, tutti dietro `require_admin`.

| Metodo | Path | Cosa |
|--------|------|------|
| `GET`  | `/profiles` | Lista profili con `descriptor_count`. |
| `POST` | `/profiles` | Crea profilo. 409 su `display_name` duplicato attivo. Scrive `consent_given_at`. |
| `GET`  | `/profiles/{id}` | Dettaglio. |
| `PATCH`| `/profiles/{id}` | Rinomina, soglia, child, attivo. |
| `DELETE`| `/profiles/{id}` | Cancella + cascade descrittori. |
| `POST` | `/profiles/{id}/descriptors` | Bulk add (1-10). Source `enrollment` o `continuous`. Retention auto-prune oltre 30. |
| `GET`  | `/profiles/{id}/descriptors` | Lista descrittori (per seed del worker cache). |
| `POST` | `/match` | Server-side nearest-neighbor (L2) con stessa ambiguity guard del client. |
| `GET/PUT` | `/settings` | Singleton: enabled, default_threshold, expression_enabled, age_gender_enabled. |

Ogni mutazione scrive una entry in `audit_log` con `action="face.*"`.

## Schema DB

Migration head per la feature: `e7f4c2a18b5d_add_face_recognition_tables.py`.

- **`face_profiles`** — identity + consent + recognition stats.
- **`face_descriptors`** — `descriptor vector(128)` + HNSW cosine index
  + check su `source ∈ {enrollment, continuous}`.
- **`face_settings`** — singleton (`CHECK id = true`).

## Performance attese

| Device | TTFT primo riconoscimento | FPS sustained |
|--------|---------------------------|---------------|
| M1 desktop | ~600 ms | 15–20 FPS in "active" |
| PC i5 medio | ~800 ms | 10–15 FPS |
| Tablet Android medio | ~1.2 s | 5–8 FPS |
| Pi 4 / RK3588 (CARA Wall) | ~1.5 s | 4–6 FPS |

Lo step dominante è la coppia `landmark68 + recognition`, ~50-150 ms
per frame su CPU. Il detector da solo è ~30 ms.

## Punti di estensione

### 1. Aggiungere un'altra azione smart-home pericolosa

Editare `frontend/src/features/face/permissions.ts`:

```ts
const CHILD_BLOCKED_ACTIONS = [
  // ...existing
  'fan.set_speed_extreme',
] as const;
```

E aggiungere un test in `permissions.test.ts`.

### 2. Aggiungere una source nuova per i descrittori

Servono 3 cambi coordinati:

1. Migration alembic per allargare il `CHECK source IN (...)`.
2. Pydantic `DescriptorIn.source` regex.
3. UI: aggiornare l'admin (badge / filtri).

### 3. Cambiare il modello di detection

Se vuoi `ssdMobilenetv1` invece di `tinyFaceDetector`:

1. Scaricare i pesi (`ssd_mobilenetv1_model-*`) in
   `public/models/face-api/`.
2. In `face.worker.ts` sostituire `faceapi.nets.tinyFaceDetector`
   con `faceapi.nets.ssdMobilenetv1` e usare `SsdMobilenetv1Options`.
3. Rivedere la soglia (ssd usa una scala diversa).

### 4. Server-side match per device freschi

Già supportato in Phase 2: `POST /face/match` (vedi tabella endpoint).
Usato dal frontend solo come fallback — il match locale evita un
round-trip per frame e funziona offline.

## Test

- Backend smoke (richiede backend live):
  `make smoke` → `tests/smoke/test_face_api.py` (7 test).
- Frontend unit (puro logic, no DOM):
  `npm test` → `quality.test.ts` (6) + `permissions.test.ts` (4).
- Frontend E2E (Playwright): non ancora — richiede video sintetico in
  `e2e/fixtures/faces/` per pilotare lo stream.

## Cosa non c'è ancora (debiti tecnici)

- Cifratura at-rest del campo `descriptor`. Per ora si confida nel
  disk-encryption dell'OS. Una migrazione pgcrypto-wrapped è
  praticabile ma costringe a rinunciare all'indice pgvector.
- LoRA / fine-tune del recognition net sul dataset di casa. Pesante per
  il RK3588, vale la pena solo se la cluster-tolerance dei descrittori
  base non basta.
- Stato di idle non sincronizzato fra dispositivi. Se due tablet
  guardano la stessa scena, ognuno gira il proprio loop.
- Hook diretto della voce TTS in modalità bambino. Per ora c'è solo il
  data-attribute sul `<html>`; chi sintetizza deve leggerlo.
