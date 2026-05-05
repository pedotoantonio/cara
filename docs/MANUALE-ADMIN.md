# Cara — manuale admin

Aggiornato: 2026-05-05. Per la documentazione utente finale, vedi
`docs/MANUALE-FAMIGLIA.md`.

> Questo documento è per chi configura e mantiene Cara sul NanoPC-T6.
> Assume familiarità con Linux, Docker, SSH. Non richiede di saper
> programmare.

---

## 0. Inventario rapido

| Cosa | Dove |
|---|---|
| Server fisico | NanoPC-T6 (RK3588) `192.168.1.23` |
| Codebase | `/opt/cara/` |
| Compose | `/opt/cara/docker-compose.yml` |
| Backend container | `cara-backend` (`172.31.0.21:8000`) |
| Frontend container | `cara-frontend` (`172.31.0.20:80`) |
| Postgres | `cara-postgres:5432` (database `cara`, user `cara`) |
| Redis | `cara-redis:6379` |
| Reverse proxy | `nginx-proxy` su `192.168.1.23:8455` (HTTPS self-signed) |
| Modelli LLM | `/opt/cara/data/models/` (1.5B + 3B w8a8 RKLLM) |
| Backup automatici | `/opt/cara/backups/` (cron 03:15 daily, 7 gg retention) |
| Log container | `journalctl CONTAINER_NAME=cara-backend` o `docker logs cara-backend` |
| Audit admin | `cara-postgres` → tabella `audit_log` |
| Admin login | `pedotoa@gmail.com` / la password sai |

---

## 1. Comandi quotidiani

### Stato dei servizi

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep cara
```

Tutti dovrebbero essere `Up (healthy)`. Se uno è `unhealthy` o `restarting`:

```bash
docker logs cara-backend --tail 50
```

### Riavviare un servizio

```bash
cd /opt/cara
docker compose --profile app restart backend     # solo backend
docker compose --profile app restart frontend
docker compose --profile app restart             # tutto lo stack app
```

Il riavvio del backend prende ~15 secondi (caricamento modello LLM
sull'NPU). Durante questo lasso le chat rispondono 503.

### Logs in tempo reale

```bash
docker logs -f cara-backend                      # tutto
docker logs -f cara-backend 2>&1 | grep proactivity   # solo proattività
journalctl -t cara-backup --since today          # backup cron
```

### Aggiornare il codice

Lavori in `/opt/cara/` (quasi sempre `backend/cara/` o `frontend/src/`):

```bash
cd /opt/cara
DOCKER_BUILDKIT=0 docker compose --profile app build backend
DOCKER_BUILDKIT=0 docker compose --profile app build frontend
docker compose --profile app up -d backend frontend
```

**Importante**: `DOCKER_BUILDKIT=0` è obbligatorio col daemon 20.10.5 di
Debian Bullseye — buildx non c'è. Senza, il build fallisce.

### Migration DB

```bash
docker exec cara-backend alembic upgrade head           # applica
docker exec cara-backend alembic current                # versione corrente
docker exec cara-backend alembic history                # storia
```

Le migration vivono in `backend/alembic/versions/`. Una nuova
si crea con:

```bash
docker exec cara-backend alembic revision --autogenerate -m "msg breve"
```

Edita il file generato (a volte servono manual fix), poi `alembic upgrade head`.

---

## 2. Pannello admin

Apri https://192.168.1.23:8455/admin (login admin).

### `/admin` — settings principali

13 categorie. I più importanti:

- **Voce** — engine TTS (Piper o browser), nome voce, rate, pitch.
  - Se l'audio è "lento": riporta `voice_rate` a 1.0.
  - Se "meccanico": prova a cambiare engine (Piper paola-medium è il
    migliore disponibile). Per maggior naturalezza serve un voice
    "high" che oggi non è pubblicato.
- **Modello LLM** — switch fra `fast` (1.5B, default, 3.5 tok/s) e
  `quality` (3B, 1.6 tok/s). 3B più accurato ma più lento.
- **CDA** (Content Discovery Agent) — toggle per le ricerche internet
  (meteo, definizioni, ecc).
- **Cloud LLM** — abilita/disabilita il cloud Haiku per il bottone
  "✨ Risposta migliore". Default OFF (privacy first).
- **Validation pipeline** — DEFAULT OFF e va lasciato così. Il 1.5B
  non sa validare sé stesso, vedi CLAUDE.md.

### `/admin/memory` — moderazione memoria

Lista utenti + conteggio fatti attivi/totali. Click su un utente per
vedere/disattivare/cancellare i suoi fatti.

Ogni azione di moderazione finisce in `audit_log` con il tuo
`actor_email`, IP, e il fact preview. Trasparenza totale.

### `/admin/smart-home` — Home Assistant

1. URL HA: `http://192.168.1.x:8123` (porta interna).
2. Token long-lived: in HA, **Profilo → Token di accesso** → genera.
3. Salva. Lo status badge in alto diventa "connesso" se tutto va bene.
4. Sotto vedi tutte le entità HA raggruppate per dominio.
5. **Prova mappatura vocale**: scrivi una frase ("accendi la luce della
   cucina") e vedi come Cara la risolve. Utile per debuggare entity
   alias mancanti.
6. Click su un'entità per accendi/spegni/inverti rapido.

Quando colleghi HA per la prima volta, il backend apre subito una
WebSocket persistente verso HA e scrive ogni `state_changed` in
episodic. Riconnect automatico su drop con backoff esponenziale.

### `/admin/proactivity` — regole proattive

Le 6 regole concrete:

| Rule | Cooldown | Quando fira |
|---|---|---|
| `morning_greeting` | 20h | 07:00–10:00, saluta + summary giornata |
| `undone_tasks_evening` | 18h | 19:00–22:00, ricorda task aperte di oggi |
| `rain_alert` | 4h | Pioggia in arrivo nelle 3h (richiede weather adapter) |
| `door_open_long` | 1h | Porta/finestra aperta da >20 min (richiede HA WS events) |
| `bedtime_routine` | 20h | 22:30–23:30, "buona notte, spengo le luci?" |
| `birthday_today` | 23h | Compleanno di un membro famiglia |

Toggle per disattivare quelle troppo invasive. **Esegui adesso** mostra
cosa Cara avrebbe inviato in questo istante (utile per debug).

### `/admin/diagnostics` — telemetria

- Tool calling success rate
- Episodic events recenti
- Stato modelli + KV cache
- Latenza endpoint chat

### `/admin/audit` — audit log

Cronologia di tutte le modifiche admin (chi, quando, cosa, da dove).
Ricerca + filtri + export CSV.

---

## 3. Backup & ripristino

### Backup automatici

Cron utente `apedo`:

```cron
15 3 * * * /opt/cara/scripts/backup-postgres.sh
30 3 * * * /opt/cara/scripts/cleanup-kv-cache.sh
```

- **03:15** — pg_dump → gzip → `/opt/cara/backups/cara-YYYYMMDD-HHMM.sql.gz`
- **03:30** — purge KV cache files non toccati da 30+ giorni
- Retention: 7 giorni (i backup più vecchi vengono cancellati)

Verifica:

```bash
ls -lh /opt/cara/backups/         # dump più recente
journalctl -t cara-backup -t cara-kv-cleanup --since today
```

### Backup manuale

```bash
/opt/cara/scripts/backup-postgres.sh
```

### Ripristino da backup

```bash
# Stop il backend per evitare scritture concorrenti
docker compose --profile app stop backend

# Restore (sostituisci YYYYMMDD-HHMM con il dump che ti serve)
gunzip -c /opt/cara/backups/cara-YYYYMMDD-HHMM.sql.gz | \
  docker exec -i cara-postgres psql -U cara -d cara

# Riavvia
docker compose --profile app start backend
```

Lo schema viene ricreato dal dump; non serve `alembic upgrade`.

---

## 4. Push notifications (Web Push)

Già configurate. Le credenziali stanno in `/opt/cara/.env`:

```
VAPID_PRIVATE_KEY=...
VAPID_PUBLIC_KEY=...
VAPID_CONTACT_EMAIL=mailto:pedotoa@gmail.com
```

Il backend ha un asyncio task (`push_scheduler`) che ogni 60 secondi
guarda i task con `due_date <= now + 15min` e manda push agli utenti
sottoscritti.

### Per ricevere push su un nuovo telefono

1. L'utente apre Cara sul telefono.
2. Va su Task. Crea una task con scadenza.
3. Clicca "Attiva notifiche" sul banner.
4. Concede il permesso del browser.

Da quel momento il browser è registrato nella tabella
`push_subscriptions` e riceve le notifiche.

### Rotazione VAPID keys

Se mai serve rotare:

```bash
docker exec cara-backend python3 -c "
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64
priv = ec.generate_private_key(ec.SECP256R1())
priv_bytes = priv.private_numbers().private_value.to_bytes(32, 'big')
pub = priv.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint)
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b'=').decode()
print('PRIV=' + b(priv_bytes))
print('PUB=' + b(pub))
"
```

Aggiorna `.env` con i nuovi valori, restart backend, **ogni dispositivo
deve ri-iscriversi** (i vecchi endpoint vengono purgati alla prossima
push fallita 410).

---

## 5. Modelli LLM

### Cambiare modello

`Admin → Modello LLM`. Lo swap è hot, prende ~7s.

### Aggiungere un nuovo modello RKLLM

1. Mettilo in `/opt/cara/data/models/<nome>.rkllm` (1-4 GB).
2. Aggiorna `/opt/cara/.env`: `LLM_MODEL_PATH=...` (per il fast) oppure
   `LLM_MODEL_PATH_QUALITY=...` (per il quality).
3. Restart backend.

### LoRA fine-tune

Documentazione in `docs/LORA-FINE-TUNE-PIPELINE.md`. Richiede ~$10 di
GPU rental + un weekend di lavoro.

---

## 6. Telegram bot (opzionale)

Già configurato:

```bash
grep CARA_TELEGRAM /opt/cara/.env
```

Se vuoi disattivarlo: cancella il token, restart backend.

Per aggiungere un utente: aggiungi il suo `chat_id` a
`CARA_TELEGRAM_CHAT_OWNERS` o a `CARA_TELEGRAM_CHAT_USER_MAP`.

---

## 7. Frigate-faces (riconoscimento facciale)

Servizio separato in `/opt/frigate-faces/`. Cara legge l'API REST per
il widget "Chi è in casa".

Per aggiungere/rimuovere un volto:
1. Apri https://192.168.1.23:8452/
2. Sezione "Persone sconosciute" → trovi i volti rilevati ma non
   etichettati.
3. Click su un volto → metti nome → conferma.

Da quel momento Cara saluta quella persona per nome ("Ciao Maria") e
il riconoscimento confluisce nel widget di presenza.

---

## 8. Smart Home setup

### Prerequisiti

Home Assistant Container running (già configurato, vedi CLAUDE.md
sezione `homeassistant`).

### Connessione

1. In HA: Profilo → Token di accesso → "Crea token".
2. Copia il token (lungo, ~1500 char).
3. In Cara: `/admin/smart-home`.
4. URL: `http://192.168.1.23:8123` (HA è in network host).
5. Incolla token.
6. Salva. Status badge "connesso".

### Voice control

Da quel momento "accendi luce salotto", "spegni tutto al piano di
sopra", "imposta il termostato a 20" funzionano via voce e via chat.
Cara usa il NLU 4-stadi:

1. Match esatto sull'alias (`light.salotto` → "luce salotto")
2. Substring match
3. Embedding similarity (semantica)
4. Disambigua per area (se l'utente è in cucina, "luce" → cucina)

### Permission matrix

`device_permissions` table — chi può fare cosa per ogni dominio HA.
Per default i bambini non possono spegnere allarme/serrature. Modifica
da `/admin/smart-home → Permessi`.

---

## 9. Troubleshooting

### "L'audio è meccanico/lento"

```bash
# Ripristina sampling sani
curl -sk -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"settings":{"voice_rate":1.0,"voice_pitch":1.0}}' \
  https://192.168.1.23:8455/api/v1/admin/settings
```

### "Cara non risponde su qualsiasi domanda"

```bash
# Status NPU
docker exec cara-backend python3 -c "
from cara.ai.llm import get_llm_service
print(get_llm_service().mode, 'loaded')
"

# Riavvia se serve
docker compose --profile app restart backend
```

### "Le notifiche push non arrivano"

```bash
# Subscriptions registrate?
docker exec cara-postgres psql -U cara -d cara -c \
  "SELECT user_id, endpoint, last_pushed_at FROM push_subscriptions LIMIT 5"

# Scheduler vive?
docker logs cara-backend --since 10m | grep push_scheduler

# Test manuale
curl -sk -X POST -H "Authorization: Bearer $TOKEN" \
  https://192.168.1.23:8455/api/v1/push/test
```

Errore "credit balance too low" su un push test? È un push reale, ma
quel device non è raggiungibile. Verifica con un test browser locale.

### "Il chat dice 'sono solo un assistente virtuale'"

È un comportamento da fixare. Il 1.5B drifta. Le tue opzioni:

1. Verifica che il system prompt sia quello aggiornato:
   `cara/config.py` → `llm_system_prompt`.
2. Per la query specifica, controlla se non sia intercettabile da un
   intent_router rule. Se sì, aggiungi la rule (vedi
   `cara/services/intent_router.py`).
3. Se è una domanda complessa, attiva il cloud Haiku e usa "Risposta
   migliore".

### "App offline ma riconnessa, modifiche perse"

Le modifiche offline sono in `localStorage` chiave `cara.offlineQueue.v1`.
Apri la console del browser:

```js
JSON.parse(localStorage.getItem('cara.offlineQueue.v1'))
```

Se ci sono entry, prova:

```js
import('/src/lib/offlineQueue.ts').then(m => m.flushQueue())
```

(Solo in dev.) In produzione, ricarica l'app: il flush parte automatico.

### "Il KV cache è enorme"

```bash
docker exec cara-backend du -sh /app/cache/kv
```

Se >5GB, runna manualmente:

```bash
/opt/cara/scripts/cleanup-kv-cache.sh
```

Cron lo fa già ogni notte alle 03:30.

### "Ho fatto una modifica admin che ha rotto qualcosa"

`audit_log` ha tutto. Puoi rollbackare manualmente:

```sql
SELECT id, action, target_kind, detail, created_at
FROM audit_log
ORDER BY created_at DESC LIMIT 20;
```

E fare la modifica inversa via `/admin → settings`.

---

## 10. Rollback completo

In caso di disastro:

1. Fermati: `docker compose --profile app stop backend frontend`.
2. Restore Postgres dal backup notturno (vedi sezione 3).
3. Se il problema è nel codice: `git -C /opt/cara checkout <commit-sha>`
   poi rebuild.
4. Se il problema è nel modello LLM: torna a `qwen2.5-1.5b-instruct-w8a8.rkllm`
   in `.env` e restart.
5. Riavvia.

In casi estremi, l'intero `/opt/cara/` può essere ricreato da zero da
git clone + restore Postgres.

---

## 11. Cose da NON fare

1. **Non aggiungere `default` o secondi network nei compose.** Daemon 20.10.5
   non lo supporta. Vedi CLAUDE.md → "Docker daemon 20.10.5".
2. **Non lanciare 2 worker uvicorn col modello 1.5B.** NPU memory cap. 1
   worker fisso.
3. **Non scrivere `prompt_cache_path` con prefix instabili.** L'admin
   handler già flusha la KV cache su edit prompt — non bypassare.
4. **Non disabilitare `tts_streaming_enabled` senza sostituirlo.** Senza,
   l'utente sente l'audio dopo la fine del testo (UX lenta).
5. **Non mettere credenziali nel codebase.** Sempre nel `.env`.

---

## 12. Aggiornare questo documento

Quando aggiungi una feature, una migration, o cambi un default:

1. Aggiorna `CLAUDE.md` (rapido pin di stato).
2. Aggiorna `MANUALE-FAMIGLIA.md` se l'utente vede qualcosa di diverso.
3. Aggiorna QUESTO file se l'admin deve fare azioni nuove.
4. `CARA-CHANGELOG.md` per dettagli temporali.

---

## 13. Contatti emergenza

| Cosa | Chi | Note |
|---|---|---|
| Problemi sistema OS | Antonio | proprietario hardware |
| Problemi rete WiFi/VPN | Antonio | router, WireGuard |
| Frigate / camere | Antonio | configurazione streams |
| Ottimizzazione modelli LLM | Antonio + claude-code | RKLLM tuning |
| LoRA fine-tune | Antonio (RunPod) | doc in LORA-FINE-TUNE-PIPELINE.md |

Buon lavoro.
