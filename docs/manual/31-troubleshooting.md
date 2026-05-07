# Cap 31 — Troubleshooting

> *Sintesi 30 secondi.* Problemi comuni e come risolverli. Organizzati
> per sintomo. Per ogni voce: cosa vedi, cause probabili, sequenza di
> diagnosi, fix.

## 31.1 Backend si riavvia in loop

**Sintomo**: `docker compose ps` mostra `cara-backend` come `Restarting`
ogni 30-60 secondi.

**Diagnosi**:

```bash
docker logs --tail 100 cara-backend
```

Cerca:

| Errore | Causa | Fix |
|---|---|---|
| `relation "users" does not exist` | Migration non applicate | `docker exec cara-backend alembic upgrade head` |
| `connection refused: postgres:5432` | Postgres non healthy | `docker compose ps` + restart Postgres |
| `Failed to load librkllmrt.so` | Path mount sbagliato | Verifica bind-mount del runtime in compose |
| `No such device: /dev/dri/card0` | DRI non esposto | Aggiungi `devices: [/dev/dri/card0]` |
| `model file not found` | `data/models/` vuota | Scarica modello Qwen .rkllm |
| `cannot allocate memory` | NPU contesa Frigate | Cap CPU Frigate: `docker update --cpus=2.0 frigate` |
| `bind: address already in use` | Port collision | Chiudi altri service che usano la porta |

## 31.2 LLM non risponde — chat sempre 503

**Sintomo**: chat ritorna `503 Service Unavailable`, `chat/health`
ritorna `{status: "model_not_loaded"}`.

**Diagnosi**:

```bash
docker logs cara-backend | grep "llm.load"
```

Atteso:
```
llm.load.start lib=/usr/lib/rkllm/librkllmrt.so model=...
llm.load.done seconds=6.0
```

Se vedi `llm.load.failed`:

| Causa | Fix |
|---|---|
| Driver kernel non corretto | `sudo cat /sys/kernel/debug/rknpu/version` deve essere `v0.9.8` |
| Modello corrotto | Re-scarica `.rkllm` |
| Permission `/dev/dri/card0` | `group_add: ["44"]` nel compose |
| Memoria NPU insufficiente | Riduci modello (1.5B invece di 3B) |

## 31.3 PWA non si installa

**Sintomo**: il pulsante "Installa CARA" non appare nel banner; oppure
appare solo "fallback" istruzioni manuali.

**Diagnosi**:

1. **Cert fidato dal browser?** Apri DevTools → Security tab →
   verifica "Connection is secure".
2. Apri DevTools Application → Manifest. Devi vedere il manifest
   parsato senza errori.
3. Application → Service Workers → SW deve essere registrato e in
   stato "activated and is running".

**Fix più comuni**:

- **Cert self-signed**: installa la CA mkcert sul device (cap 2.9).
  Senza CA fidata, Chrome non offre install.
- **HTTP plain**: solo HTTPS può installare PWA. Usa
  `https://192.168.1.23:8455/`, non `http://`.
- **iOS Safari**: usa "Aggiungi a Home" dal menu Condividi (Apple non
  ha l'API beforeinstallprompt).
- **Engagement insufficiente**: Chrome a volte richiede "engagement"
  prima di offrire install. Naviga la app per 30 secondi.

## 31.4 Login "Failed to fetch" o credenziali sbagliate

**Sintomo**: digitando credenziali corrette compare "Failed to fetch"
o "Invalid credentials".

**Diagnosi backend**:

```bash
# Login via curl
curl -sk -X POST https://192.168.1.23:8455/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}'
```

Se `200 + token` → backend OK, problema browser.
Se `401` → password sbagliata.

**Browser-side fix**:

1. **Cert non fidato**: installa CA (cap 2.9). Failed to fetch è
   tipicamente cert error che blocca le fetch JS.
2. **Service worker stale**: F12 → Application → SW → Unregister →
   Clear Site Data → reload.
3. **Cert exception cambiata**: il vecchio cert era memorizzato come
   exception, ora è cambiato → reset HSTS via `chrome://net-internals/#hsts`.
4. **Chrome flag wrong port**: se hai launchato Chrome con
   `--unsafely-treat-insecure-origin-as-secure=https://x:8451`
   ma stai usando porta diversa, il flag non si applica.

## 31.5 Push notifications non arrivano

**Sintomo**: registrato ma il push non arriva al device.

**Diagnosi**:

```bash
# 1. VAPID configurato?
grep VAPID /opt/cara/.env

# 2. Push scheduler avviato?
docker logs cara-backend | grep "push_scheduler"
# Se vedi "skipped reason=vapid_not_configured" → setup VAPID

# 3. Subscription esiste?
docker exec cara-postgres psql -U cara -d cara -c \
  "SELECT user_id, endpoint FROM push_subscriptions LIMIT 5;"
```

**Fix**:

- VAPID mancante → setup wizard step 6c
- Subscription scaduta (410 Gone) → re-subscribe dal frontend
- iOS Safari: solo PWA installata può ricevere push (no Safari tab)
- Browser ha negato permission → reset in Settings browser

## 31.6 OAuth Google fallisce

**Sintomo**: click "Connetti Google" → redirect → errore "redirect_uri_mismatch"
o callback con errore.

**Diagnosi**:

```bash
# .env ha le credenziali?
grep GOOGLE /opt/cara/.env
```

**Fix**:

| Errore | Causa | Fix |
|---|---|---|
| `redirect_uri_mismatch` | URI in console.cloud.google diverso | Aggiungi exact `https://192.168.1.23:8455/api/v1/oauth/google/callback` |
| `invalid_client` | Client ID/Secret sbagliati | Re-copia da console.cloud.google |
| `access_denied` | Utente ha cliccato "Annulla" | Riprova consent |
| Callback ma scope mancante | Scope set non corrispondente | Verifica `cara/integrations/google_oauth.py:SCOPE_PRESETS` |
| OAUTH_ENCRYPTION_KEY missing | Cifratura fallisce | Genera key + restart backend |

## 31.7 Smart home non funziona

**Sintomo**: "accendi la luce" non fa nulla, oppure `503 Smart home disabled`.

**Diagnosi**:

```bash
# Flag abilitato?
curl -sk -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/admin/settings | jq '.smart_home_enabled'

# HA raggiungibile dal backend?
docker exec cara-backend curl -sk -H "Authorization: Bearer $HA_TOKEN" \
  http://172.31.0.1:8123/api/states | head -c 100

# Log recenti
docker logs cara-backend | grep "smarthome"
```

**Fix**:

- `smart_home_enabled=false` → abilita in `/admin/settings`
- HA non raggiungibile → verifica HA running + `network_mode: host`
- Token HA invalido → rigenera in HA Profilo → token
- NLU non capisce → aggiungi alias custom in `/admin/smart-home`

## 31.8 Voce muta / TTS non parla

**Sintomo**: chat scrive ma non si sente niente.

**Diagnosi browser**:

1. Volume sistema OK?
2. Volume tab non muto?
3. Audio nel browser autorizzato?

**Diagnosi backend**:

```bash
# Test sintesi diretta
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"text":"prova"}' \
  https://192.168.1.23:8455/api/v1/voice/synthesize \
  -o /tmp/test.wav
file /tmp/test.wav
# Atteso: WAVE audio
```

Se WAV ok → backend OK, problema frontend.

**Fix**:

- Voci Piper mancanti → `data/tts/piper/voices/` deve avere `.onnx`
- Streaming disabled ma frontend si aspetta streaming → toggle
  `tts_streaming_enabled` in admin settings
- AudioContext sospeso (Chrome autoplay policy) → user interaction
  prima di triggerare audio

## 31.9 Skill Factory: skill non matcha

**Sintomo**: hai creato una skill ma il chat va sempre al LLM.

**Diagnosi**:

```bash
# Skill è approved/active?
docker exec cara-postgres psql -U cara -d cara -c \
  "SELECT name, status FROM skills;"
```

Eventi:

```sql
SELECT kind, payload->>'reason'
FROM events
WHERE kind LIKE 'router.%' AND ts > now() - interval '5 min'
ORDER BY ts DESC;
```

**Fix**:

- `status='pending'` → approva in `/admin/skills`
- Tier-1 regex non matcha → testa il regex con `re.search()`
  manualmente
- Tier-2 cosine sotto soglia → abbassa threshold (`skill_dispatcher_tier2_threshold`)
  o aggiungi più `intent_examples`
- Skill cache stale → `skill_dispatcher.invalidate_cache()` (auto su
  CRUD, manuale via restart)

## 31.10 Migration Alembic falliscono

**Sintomo**: `alembic upgrade head` errore.

**Errori comuni**:

| Errore | Causa | Fix |
|---|---|---|
| `Multiple head revisions` | Branch divergenti | `alembic merge -m "..."` |
| `Can't locate revision identified by 'xxx'` | File migration mancante | Re-clone repo o restore dal backup |
| `column "x" already exists` | Migration parziale precedente | `alembic stamp <previous>` poi rerun |
| `relation does not exist` | Migration order wrong | Verifica `down_revision` di ognuna |

> **⚠️ Attenzione** — `alembic stamp` salta migration senza eseguirle.
> Usalo solo se sai cosa fai (recovery di stati inconsistenti).

## 31.11 Disco pieno

**Sintomo**: `df -h /opt/cara/data` mostra >90% pieno.

**Diagnosi + cleanup**:

```bash
# Vedi cosa occupa
du -h --max-depth=1 /opt/cara/data

# KV cache (può essere GB)
du -sh /opt/cara/data/kv-cache
# Cleanup
/opt/cara/scripts/cleanup-kv-cache.sh

# Backup vecchi
du -sh /opt/cara/backups
find /opt/cara/backups -name '*.sql.gz' -mtime +60 -delete

# Log Docker
sudo du -sh /var/lib/docker/containers/*/*-json.log

# VACUUM Postgres (recupera spazio cancellato)
docker exec cara-postgres psql -U cara -d cara -c "VACUUM FULL;"
```

## 31.12 RAM crescente nel tempo

**Sintomo**: `docker stats cara-backend` mostra RAM che cresce
linearmente nel tempo.

**Diagnosi**: probabile memory leak. Difficili da risolvere senza
profiler.

**Mitigazione**:

```bash
# Restart periodic come palliativo
0 4 * * * docker restart cara-backend

# Aggiungi limite memory nel compose
services:
  cara-backend:
    deploy:
      resources:
        limits:
          memory: 4g
```

Se vuoi indagare seriamente, py-spy o tracemalloc dump.

## 31.13 Frontend fetch CORS errors

**Sintomo**: console browser mostra `Cross-Origin Request Blocked`.

**Diagnosi**: il backend ha CORS aperto (`Allow-Origin: *`). Se non
funziona:

- Stai chiamando un origin diverso da quello caricato (preflight OPTIONS
  rifiutato)
- nginx-proxy non passa Authorization header

**Fix**:

```nginx
# nginx-proxy config
location /api {
    proxy_pass http://cara-backend:8000;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
}
```

## 31.14 Errori "module not found" Python

**Sintomo**: `docker logs cara-backend` mostra
`ModuleNotFoundError: No module named 'X'`.

**Diagnosi**: dipendenza mancante.

```bash
# Verifica installato nel container
docker exec cara-backend pip show <module>
```

**Fix**:

```bash
# 1. Aggiungi a backend/pyproject.toml dependencies
# 2. Rebuild
DOCKER_BUILDKIT=0 docker compose --profile app build backend
docker compose --profile app up -d backend
```

> **💡 Suggerimento** — per fix temporaneo (senza rebuild):
> `docker exec cara-backend pip install <module>` + restart. Si
> perde al prossimo rebuild ma è OK per emergenze.

## 31.15 Setup wizard non parte

**Sintomo**: `https://192.168.1.23:8455/setup` ridireziona a `/` o
mostra schermata vuota.

**Diagnosi**:

```bash
curl -sk https://192.168.1.23:8455/api/v1/setup/status
```

Risposta atteso `{"completed": false, "current_step": "admin"}`.

Se `completed: true`: il wizard è già finito. Reset:

```bash
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/setup/reset
```

Se l'admin non c'è ancora: il wizard deve apparire automaticamente.
Se non lo fa, controlla la auth gate in `App.tsx`.

## 31.16 Generale — quando fallisce, leggi i log

90% dei problemi si diagnostica con:

```bash
docker logs --tail 200 cara-backend
docker logs --tail 200 cara-frontend
docker compose ps
```

Pattern di errore:
- `[error]` — il backend ha fatto raise; cerca lo stacktrace
- `[warning]` — qualcosa di non bloccante; può essere root cause
  silenzioso
- `502 Bad Gateway` da nginx-proxy → backend giù o riavvio in corso
- `503 Service Unavailable` da CARA → feature flag off o servizio
  ausiliario giù

Se non riesci a capire, salva i log + `docker compose ps` + descrivi
in un issue (futuro: GitHub) o chiedi su Discord/forum.

---

[← Cap 30 Glossario](30-glossario.md) · [README](README.md) · [Cap 32 Changelog + roadmap →](32-changelog-roadmap.md)
