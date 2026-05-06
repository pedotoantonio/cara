# Cap 2 — Setup ambiente di sviluppo

> *Sintesi 30 secondi.* Questo capitolo ti guida da "ho un mini-PC con
> NanoPC-T6 nuovo di pacca" a "CARA gira sulla mia rete e posso
> accedere dal browser di casa". Tempo richiesto: 2-3 ore se sai cosa
> fai, 4-6 ore se è la prima volta.

## 2.1 Prerequisiti hardware

CARA è progettata per il **NanoPC-T6** di FriendlyARM, ma può girare
su altre board RK3588 o anche su PC x86 (con limitazioni AI).

### Configurazione raccomandata
- **Board**: NanoPC-T6 con SoC RK3588 (8 core ARM, NPU 6 TOPS)
- **RAM**: 16 GB (8 GB sufficiente ma stretto)
- **Storage**: eMMC 64+ GB e SSD NVMe esterno via M.2 PCIe (per Postgres
  + dati famiglia)
- **Rete**: ethernet gigabit
- **Alimentazione**: 12V/3A stabile

### Configurazione minima
- 8 GB RAM (il modello LLM + Postgres + Redis stanno dentro, ma sotto
  carico Frigate la NPU rallenta)
- 32 GB storage interno
- Ethernet 100 Mbps

### Configurazione su altri hardware
Se non hai NanoPC-T6:
- **Raspberry Pi 5** + AI HAT 26 TOPS — possibile, richiede porting di
  RKLLM bindings (non ufficialmente supportato)
- **PC x86 + GPU** — il modello Qwen 2.5-1.5B gira su CPU/GPU
  qualsiasi, ma perdi la KV cache RKLLM. Sostituisci `cara/ai/llm.py`
  con un wrapper su `transformers` o `llama-cpp`.
- **Mac M1+** — ottimo per sviluppo, MLX o `llama-cpp` sostituiscono
  RKLLM. Performance simili al NanoPC.

Le istruzioni sotto presumono NanoPC-T6.

## 2.2 Prerequisiti software

Sull'host (NanoPC) deve essere già installato:

- Debian 11 bullseye (immagine FriendlyARM standard) o Ubuntu 22.04 ARM64
- **Kernel custom 6.1.141-cara1** con driver rknpu v0.9.8 — vedi
  `/home/apedo/CLAUDE.md` per la procedura di flash
- Docker 20.10+ e Docker Compose v2
- AppArmor (pacchetto `apparmor`)
- Git

Verifica:

```bash
uname -r          # → 6.1.141-cara1
docker --version  # → Docker version 20.10.5+
sudo cat /sys/kernel/debug/rknpu/version  # → v0.9.8
ls /dev/dri/      # deve contenere card0
```

> **⚠️ Attenzione** — senza il kernel custom RKLLM **non funziona**.
> Il driver standard di Debian non include `rknpu` con la versione
> richiesta. La procedura di flash è in `/home/apedo/CLAUDE.md`.

## 2.3 Clone del repository + dipendenze

CARA vive in `/opt/cara/` sul NanoPC. La convenzione è quella — gli
script hanno path hardcoded.

```bash
# Crea la directory e prendi i permessi
sudo mkdir -p /opt/cara
sudo chown $USER:$USER /opt/cara
cd /opt/cara

# Clona il repo (sostituisci con la tua URL git)
git clone https://github.com/<tuo-fork>/cara.git .

# Verifica la struttura
ls
# CHANGELOG.md  Makefile  backend/  data/  docker-compose.yml
# docs/  frontend/  scripts/
```

### Backend: virtualenv per i test locali

Il backend gira in container in produzione, ma per i test unit servono
le dipendenze localmente.

```bash
cd /opt/cara/backend
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"

# Verifica
.venv/bin/python -m pytest tests/unit -q
# Atteso: 641 passed, 4 skipped
```

> **💡 Suggerimento** — su NanoPC `python3 -m pip install` è lento
> (ARM64 + qualche pacchetto compila wheels). Aspettati 10-15 minuti
> la prima volta.

### Frontend: npm install

```bash
cd /opt/cara/frontend
npm install

# Verifica
./node_modules/.bin/tsc --noEmit
# Atteso: nessun output (= zero errori)
```

## 2.4 Variabili `.env`

CARA legge la configurazione da `/opt/cara/.env`. Se il file non
esiste, usa default ragionevoli (modalità sviluppo). Per produzione,
**alcuni** valori sono obbligatori.

Crea il file:

```bash
cp /opt/cara/.env.example /opt/cara/.env
$EDITOR /opt/cara/.env
```

Variabili **obbligatorie** per partire:

```ini
# Ambiente
CARA_ENV=development

# Database — il backend gira in container, ma postgres anche; usano
# il nome service Compose come hostname.
DATABASE_URL=postgresql+asyncpg://cara:cara@postgres:5432/cara

# Redis
REDIS_URL=redis://redis:6379/0

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=cara
MINIO_ROOT_PASSWORD=<32+ caratteri random>

# JWT — generato auto se non c'è, ma meglio settarlo
JWT_SECRET=<32+ caratteri random>
```

Variabili **opzionali** (servono solo per le rispettive feature):

```ini
# Push notifications — generate via /setup/vapid/generate
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:tu@example.com

# Google OAuth — solo se vuoi Calendar/Gmail
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
OAUTH_ENCRYPTION_KEY=<32 byte hex random>

# Cloud LLM Anthropic — DEFERRED, lascialo vuoto
ANTHROPIC_API_KEY=

# Telegram bot — opzionale
CARA_TELEGRAM_BOT_TOKEN=
CARA_TELEGRAM_ALLOWED_CHAT_IDS=
```

Per generare valori random sicuri:

```bash
# JWT secret / MinIO password
openssl rand -hex 32

# OAuth encryption key (32 byte = 64 char hex)
openssl rand -hex 32
```

> **🔒 Sicurezza** — il `.env` contiene segreti in chiaro. Non
> committarlo in git (`.gitignore` lo esclude già). Backuppalo a
> parte, in modo sicuro.

## 2.5 Avvio docker compose

CARA si compone di due profili Compose:
- **default**: solo l'infrastruttura (postgres, redis, minio, chroma)
- **app**: aggiunge backend, frontend, celery

Step-by-step:

```bash
cd /opt/cara

# 1. Avvia l'infra. Postgres deve diventare healthy prima di proseguire.
docker compose up -d
docker compose ps
# Aspettati: cara-postgres + cara-redis + cara-minio + cara-chroma "healthy"

# 2. Build dei container app (backend + frontend)
DOCKER_BUILDKIT=0 docker compose --profile app build backend
DOCKER_BUILDKIT=0 docker compose --profile app build frontend

# 3. Avvia tutto incluso app
docker compose --profile app up -d

# 4. Controlla che tutti i 6 container siano running + healthy
docker compose ps
```

> **⚠️ Attenzione** — `DOCKER_BUILDKIT=0` è obbligatorio. Docker
> daemon 20.10.5 non ha buildx, quindi il classic builder è l'unica
> opzione. BuildKit darebbe errore "buildx not found".

### Cosa succede al primo avvio del backend

Il container `cara-backend` esegue `cara/main.py` e:

1. Si connette a Postgres, Redis, MinIO, Chroma. Se uno è giù, ritenta
   per ~30 secondi poi si arrende.
2. Carica il modello LLM via RKLLM. Output atteso nei log:
   ```
   I rkllm: rkllm-runtime version: 1.1.0, rknpu driver version: 0.9.8, platform: RK3588
   llm.load.done   seconds=6.0
   ```
3. Inizializza il servizio TTS (lazy — la voce si carica solo alla prima
   sintesi).
4. Avvia tutti gli scheduler condizionali (push, proattività, calendar,
   gmail, ha_events).

Se vedi `llm.load.failed` significa che il modello non si è caricato.
Cause comuni:

- File `data/models/qwen2.5-1.5b-instruct-w8a8.rkllm` mancante →
  scaricalo (vedi cap 24 — Manutenzione)
- `librkllmrt.so` mancante → installa il runtime (`/home/apedo/cara-poc-rkllm/runtime-v1.1.0/lib/`)
- `/dev/dri/card0` non accessibile → controlla che il container abbia
  `group_add: ["44"]` e che il device sia mountato

## 2.6 Migration database (Alembic)

Le tabelle Postgres si creano via Alembic. Al primo avvio sono vuote —
`cara-backend` NON applica migration auto.

```bash
docker exec cara-backend alembic current
# La prima volta è vuoto. Allora:

docker exec cara-backend alembic upgrade head
# Atteso: catena di "Running upgrade ... -> ..."

docker exec cara-backend alembic current
# Atteso: c0647a0... (head) o l'hash corrente
```

Le migration vivono in `backend/alembic/versions/`. Sono numerate per
hash, non per data. La catena è documentata in
`docs/HANDOFF-v1.0-epic-0-1.md`.

## 2.7 Bootstrap del primo amministratore

Due strade:

### Strada A — Setup wizard nel browser (raccomandato)

Apri `https://192.168.1.23:8455/setup`. Vedi il wizard di prima
configurazione. Compila lo Step 1 (email, password, nome, fuso
orario). Il backend crea l'utente admin e ti porta avanti agli step
successivi.

> **💡 Suggerimento** — al primo accesso il browser si lamenterà del
> certificato self-signed. Clicca "Avanzate" → "Procedi". Il setup
> wizard ti propone subito di rigenerare il cert con mkcert.

### Strada B — CLI bootstrap (per scripting)

```bash
docker exec cara-backend python -m cara.bootstrap create-admin <email> [password]
```

Se ometti la password, ne genera una random e te la mostra (una volta
sola).

## 2.8 Verifica che tutto funzioni

Tre check dal vivo:

```bash
# 1. Backend health
curl -sk https://192.168.1.23:8455/health
# {"status":"ok","env":"development","version":"1.1.0"}

# 2. Backend chat health (verifica anche che il modello sia caricato)
curl -sk https://192.168.1.23:8455/api/v1/chat/health
# {"status":"ok","model_path":"qwen2.5-1.5b-instruct-w8a8.rkllm"}

# 3. Frontend
curl -sk https://192.168.1.23:8455/
# <!doctype html><html lang="it">... (HTML del frontend)
```

Poi nel browser:

1. Apri `https://192.168.1.23:8455/`
2. Login con le credenziali admin appena create
3. Vedi la home page con la rosa avatar di CARA
4. Vai su `/chat`, scrivi "ciao" → CARA risponde

Se l'ultimo step funziona, l'installazione è OK.

## 2.9 Setup secondario: cert per i device famiglia

Per non avere warning di sicurezza ogni volta sui telefoni di casa,
installa la CA mkcert su ognuno:

1. Su ogni device della famiglia apri `http://192.168.1.23/cara-ca.crt`
   (HTTP plain, no warning)
2. Installa il certificato come "Trusted Root":
   - Android: Impostazioni → Sicurezza → Cifratura e credenziali →
     Installa un certificato → CA
   - iPhone: Safari → scarica → Impostazioni → Generali → VPN e
     gestione dispositivi → installa, poi Impostazioni → Generali →
     Info → Impostazioni di fiducia certificati → attiva
   - Windows: doppio click → "Computer locale" → "Autorità radice attendibili"
   - Mac: doppio click → portachiavi "Sistema" → "Considera sempre
     attendibile"

Dopo l'installazione, `https://192.168.1.23:8455/` apre senza warning
e la PWA è installabile come app vera.

## 2.10 Comandi quotidiani che userai

```bash
# Logs
make logs-backend       # docker logs -f cara-backend
make logs-frontend      # docker logs -f cara-frontend

# Test
make test-unit          # in-memory SQLite, ~10s
make test-smoke         # vs backend live, ~50s

# Build + restart dopo modifica codice
DOCKER_BUILDKIT=0 docker compose --profile app build backend
docker compose --profile app up -d backend
# Per il frontend:
DOCKER_BUILDKIT=0 docker compose --profile app build frontend
docker compose --profile app up -d frontend

# Reload modulo singolo (sviluppo, senza rebuild completo)
docker cp backend/cara/api/v1/setup.py cara-backend:/app/cara/api/v1/setup.py
docker restart cara-backend
sleep 8 && curl -sk https://192.168.1.23:8455/health

# Migration
docker exec cara-backend alembic revision --autogenerate -m "descrizione"
docker exec cara-backend alembic upgrade head
```

> **💡 Suggerimento** — durante lo sviluppo, la sequenza `docker cp` +
> `docker restart` è 10x più veloce del rebuild completo (~10s contro
> ~3 minuti). Funziona per file Python puri; per modifiche al
> Dockerfile o pyproject.toml devi rebuildare.

## 2.11 Setup VPN per accedere da fuori casa

Per accedere a CARA quando non sei in casa, usa la VPN WireGuard
preconfigurata sul NanoPC.

Vedi `/home/apedo/CLAUDE.md` § "WireGuard (wg-easy)" per:
- Generare un client config QR via web UI a `https://192.168.1.23:8446/`
- Importarlo nell'app WireGuard del telefono
- Connetterti — vedrai 192.168.1.23 anche dal cellulare in 4G

CARA stessa non si configura per la VPN — è un'astrazione di rete
sotto, indipendente.

## 2.12 Errori comuni

| Sintomo | Causa probabile | Risoluzione |
|---|---|---|
| `502 Bad Gateway` | Backend si sta caricando | Aspetta 8-15 secondi |
| `cara-backend` in restart loop | Modello LLM non si carica | Vedi `docker logs cara-backend`, controlla `data/models/` |
| `network not found: proxy-net` | nginx-proxy non running | `docker compose up -d nginx-proxy` (in `/opt/nginx-proxy/`) |
| `relation "users" does not exist` | Migration non applicate | `docker exec cara-backend alembic upgrade head` |
| `No such device: /dev/dri/card0` | DRI device mancante | Controlla che il kernel custom sia attivo |
| Login web fa "Failed to fetch" | Cert non fidato dal browser | Installa la CA mkcert (§2.9) |

## 2.13 Disinstallazione

Se vuoi liberare il NanoPC:

```bash
cd /opt/cara
docker compose --profile app down
docker compose down -v  # ATTENZIONE: -v cancella i volumi → perdi tutti i dati
docker rmi cara-backend:0.1.0 cara-frontend:0.1.0
sudo rm -rf /opt/cara
```

Se vuoi solo sospendere temporaneamente:

```bash
docker compose --profile app down
# I dati restano in data/postgres/, data/minio/, ecc. Riavvi quando vuoi.
```

---

[← Cap 1 Architettura](01-architettura.md) · [README](README.md) · [Cap 3 Struttura repo →](03-struttura-repo.md)
