# Cap 23 — Deploy

> *Sintesi 30 secondi.* Deploy = `docker compose --profile app build` +
> `up -d`. Sul NanoPC con `DOCKER_BUILDKIT=0` (daemon 20.10.5 non ha
> buildx). Nessun zero-downtime: il backend riparte (~10s di pausa)
> ma il frontend resta servito durante il build. Le migration Alembic
> si applicano dopo l'up.

## 23.1 Workflow standard

```bash
cd /opt/cara

# 1. Pull latest (se hai un remote)
git pull origin main

# 2. Build (cambia se hai modificato Dockerfile o pyproject.toml/package.json)
DOCKER_BUILDKIT=0 docker compose --profile app build backend
DOCKER_BUILDKIT=0 docker compose --profile app build frontend

# 3. Apply migrations (se ci sono nuove)
docker exec cara-backend alembic upgrade head

# 4. Restart container
docker compose --profile app up -d

# 5. Verifica
sleep 15
curl -sk https://192.168.1.23:8455/health
curl -sk https://192.168.1.23:8455/api/v1/chat/health
```

> **⚠️ Attenzione** — `DOCKER_BUILDKIT=0` è obbligatorio. Docker
> daemon 20.10.5 non ha BuildKit. Senza il flag, `docker compose
> build` fallisce con `failed to solve: ...`.

## 23.2 Quick redeploy senza rebuild (sviluppo)

Per modifiche solo Python (no nuove deps), bypassa il rebuild:

```bash
# Copia i file modificati nel container running
docker cp backend/cara/api/v1/foo.py cara-backend:/app/cara/api/v1/foo.py

# Restart per riavviare uvicorn
docker restart cara-backend
sleep 10

# Smoke
curl -sk https://192.168.1.23:8455/health
```

Tempo: ~10 secondi totali (vs ~3 minuti per build completo).

> **💡 Suggerimento** — questo workflow funziona perché il Dockerfile
> backend copia il codice sorgente in `/app/`. Modifiche al Dockerfile
> stesso, a `pyproject.toml`, o ai `requirements` richiedono build
> completo.

Per il **frontend**, ovvero modifiche a `frontend/src/*`, il rebuild
è **necessario** (Vite trasforma TypeScript in JS, fa bundle, etc.).
Non c'è quick redeploy frontend.

## 23.3 Migration Alembic in produzione

```bash
# Genera (su sviluppo)
docker exec cara-backend alembic revision --autogenerate -m "descrizione"

# Verifica il file generato in backend/alembic/versions/
# IMPORTANTE: Alembic non sempre indovina (NULL constraint, indici,
# enum). Edita a mano se serve.

# Apply su staging
docker exec cara-backend alembic upgrade head

# Test che funzioni

# Apply su produzione
docker exec cara-backend alembic upgrade head
```

> **⚠️ Attenzione** — alcune migration **non sono reversibili** (es.
> DROP COLUMN, DROP TABLE). Alembic genera comunque la `downgrade()`
> ma se hai dati persi non li recuperi. Backup PRIMA di migration in
> produzione:

```bash
docker exec cara-postgres pg_dump -U cara cara > /home/apedo/cara-backups/pre-migration-$(date +%Y%m%d-%H%M%S).sql
```

### Catena migrazioni corrente

```bash
docker exec cara-backend alembic current
# c0647a0c1d4b (head)

docker exec cara-backend alembic history | head -20
# Mostra la catena completa
```

Le migration vivono in `backend/alembic/versions/`. Sono numerate per
hash, non timestamp.

## 23.4 Rollback di una release

Tre scenari:

### A) Rollback solo codice (nessuna migration)

```bash
git checkout v1.0.0   # tag precedente
DOCKER_BUILDKIT=0 docker compose --profile app build
docker compose --profile app up -d
```

Sicuro. Il DB è intatto, il codice torna indietro.

### B) Rollback codice + migration retrocompatibile

```bash
# 1. Downgrade DB di N step
docker exec cara-backend alembic downgrade -1

# 2. Codice
git checkout vX.Y.Z
DOCKER_BUILDKIT=0 docker compose --profile app build
docker compose --profile app up -d
```

Funziona solo se la migration ha una `downgrade()` reversibile
(non DROP DATA).

### C) Rollback con perdita di dati (DROP TABLE)

L'unica strada è il restore di un backup. Vedi cap 24.1.

## 23.5 Configurazione produzione

In produzione "vera" (non sviluppo), aggiorna `.env`:

```ini
CARA_ENV=production
LOG_LEVEL=WARNING

# Disable Swagger
# (auto-disabled da main.py se CARA_ENV=production)

# Cert TLS valido
# (mkcert OK per LAN; Let's Encrypt per pubblico)

# Backup automatici
# (cron entry chiama scripts/backup-postgres.sh)
```

Altri changes consigliati:

- nginx-proxy: aumenta `proxy_read_timeout` per chat lunghe (3600s)
- Postgres: `shared_buffers = 256MB` se hai >8GB RAM
- Redis: `maxmemory 200mb maxmemory-policy allkeys-lru`

## 23.6 Build di un'immagine specifica

Solo backend:

```bash
DOCKER_BUILDKIT=0 docker compose --profile app build backend
docker compose --profile app up -d backend
```

Solo frontend:

```bash
DOCKER_BUILDKIT=0 docker compose --profile app build frontend
docker compose --profile app up -d frontend
```

Solo infra (postgres/redis/minio/chroma):

```bash
docker compose up -d
```

## 23.7 Restart "intelligente" senza downtime

CARA non ha veri zero-downtime updates. Il backend riparte = ~10
secondi di 502 sul `/api/*`. Mitigazioni:

### Graceful shutdown

`cara-backend` reagisce a SIGTERM:
1. Smette di accettare nuove connection
2. Aspetta che le request in-flight terminino (`uvicorn --graceful-shutdown 30`)
3. Cancella i task asyncio (scheduler, ws subscriber)
4. Scarica il modello LLM
5. Chiude DB

`docker stop cara-backend --time=30` rispetta il graceful.

### Rolling deploy (futuro)

Vero zero-downtime richiederebbe:
- Due `cara-backend` repliche (impossibile con NPU singolo)
- nginx-proxy upstream con health-check + retire automatic
- Sticky sessions per chat in corso

Per CARA single-NPU: meglio accettare 10s di 502 con un avviso UI ("CARA
sta aggiornando, riprova fra qualche secondo").

## 23.8 Frontend asset versioning

Vite genera bundle hashed: `assets/index-Cr4sKm2w.js`. Cosi un nuovo
deploy ha bundle diverso → browser scarica fresh, niente cache stantia.

Service worker ha la sua versione interna che cambia ad ogni build.
La PWA installata sui device famiglia rileva il nuovo SW e:
- Mostra prompt "nuova versione disponibile, ricarica?"
- O auto-update silenzioso al prossimo `registerType: autoUpdate`

In `vite.config.ts:VitePWA({registerType: 'autoUpdate'})` significa
auto-update silenzioso: l'utente vede la nuova UI alla prossima visita
senza azione.

## 23.9 Persistenza dati

I dati sopravvivono al rebuild dei container:

- Postgres: `/opt/cara/data/postgres/` bind-mount
- Redis: `/opt/cara/data/redis/` (con persistenza opzionale; di default
  RAM-only — perdita accettabile, è cache)
- MinIO: `/opt/cara/data/minio/`
- Chroma: `/opt/cara/data/chroma/`
- Modelli LLM/TTS: `/opt/cara/data/models/`, `data/tts/`

Per disinstallare CARA mantenendo i dati:

```bash
docker compose --profile app down
# data/ resta. Reinstall in qualsiasi momento.
```

Per **distruggere** tutto (cancellazione totale):

```bash
docker compose --profile app down -v
# -v cancella i volumi → data/ pulito
```

## 23.10 Health checks

```bash
# Backend health
curl -sk https://192.168.1.23:8455/health
# {"status":"ok","env":"development","version":"1.1.0"}

# Backend chat health (verifica anche LLM caricato)
curl -sk https://192.168.1.23:8455/api/v1/chat/health
# {"status":"ok","model_path":"qwen2.5-1.5b-instruct-w8a8.rkllm"}

# Frontend
curl -sk https://192.168.1.23:8455/ | head -c 200

# Container status
docker compose ps
# Tutti devono essere "healthy" (alcuni "running" senza healthcheck)
```

## 23.11 Logs in production

`docker logs` mostra solo da quando il container è partito. Per
storia lunga:

```bash
# Limita rotation in compose
services:
  cara-backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

Per logging **persistente** + searchable (futuro):

- Forward a un Loki / Elasticsearch / Grafana stack
- `journald` driver e `journalctl -u docker`
- Sysadmin Dashboard ha SNMP traps + log tail (cap 21.1)

## 23.12 Deploy checklist pre-release

Prima di taggare e deployare una nuova versione:

- [ ] Tutti i test verdi (`make test`)
- [ ] CHANGELOG.md aggiornato con nuova entry
- [ ] Bump versione (`frontend/package.json`)
- [ ] Branch verde su `main`
- [ ] Backup DB recente (<7 giorni vecchio)
- [ ] Annunciato a famiglia se è un breaking change UX
- [ ] (Pre-prod) Self-test post-deploy passa

Una volta deployata:

- [ ] Health checks rispondono 200
- [ ] Login funziona (smoke manuale)
- [ ] Chat completa un turno
- [ ] Push notifica di test arriva
- [ ] Rule proattività al prossimo tick fira (controlla logs)

## 23.13 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| `failed to solve: ...buildkit` | BuildKit attivo | `DOCKER_BUILDKIT=0` esplicito |
| Backend in restart loop | Migration mancante | `alembic upgrade head` |
| Backend si carica ma `chat/health` 503 | Modello LLM corrupted | Verifica `data/models/` integrità |
| Frontend serve vecchia versione | SW cache | Bump versione package.json |
| WebSocket 502 dopo deploy | nginx-proxy non riavviato | `docker exec nginx-proxy nginx -s reload` |
| `network not found: proxy-net` | nginx-proxy giù | Riavvia nginx-proxy in `/opt/nginx-proxy` |

## 23.14 Strategia di release

CARA segue **trunk-based**:

```
main (sempre rilasciabile)
  │
  ├── epic-12-setup-wizard ──┐
  │                            │
  │                          merge --no-ff
  │  ←─────────────────────── ┘
  │
  v1.1.0  (tag)
```

Process:

1. `git checkout -b epic-N-name`
2. Lavora in branch, commit logici
3. PR (anche solo locale) → review
4. Merge `--no-ff` su main per preservare history del branch
5. Tag annotato `git tag -a vX.Y.Z -m "..."`
6. Build + deploy

Niente release branches separati (per ora). Non multi-environment
(solo "production" sul NanoPC di Antonio + il dev locale di chiunque
altro).

---

[← Cap 22 Test](22-test.md) · [README](README.md) · [Cap 24 Manutenzione →](24-manutenzione.md)
