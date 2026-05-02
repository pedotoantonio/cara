# CARA — Casa AI for Routines & Activities

Home cloud privato self-hosted: PWA multi-utente per la famiglia, AI on-device,
nessun dato lascia casa senza opt-in.

## Status

- Fase 0 — Fondamenta: in corso
- Fase 1 — AI core: bloccata in attesa driver NPU (`/dev/rknpu` non esposto sul kernel attuale)

## Quick start (NanoPC-T6)

```bash
cd /opt/cara

# 1. Genera .env reale (una volta sola)
cp .env.example .env
# poi sostituisci i `changeme_*` con secret veri, oppure rigenera con:
sed -i "s|changeme_postgres_password|$(openssl rand -hex 24)|g" .env
sed -i "s|changeme_redis_password|$(openssl rand -hex 24)|g" .env
sed -i "s|changeme_minio_password_min_8_chars|$(openssl rand -hex 24)|g" .env
sed -i "s|changeme_generate_with_openssl_rand_hex_32|$(openssl rand -hex 32)|g" .env

# 2. Infra only (Postgres, Redis, MinIO, Chroma)
docker compose up -d

# 3. Stack completo (richiede backend + frontend buildati)
docker compose --profile app up -d --build
```

## Networks & ports

- `cara-net` (172.30.0.0/24): rete interna, solo CARA
- `proxy-net` (172.31.0.0/16): rete esistente del NanoPC, condivisa con `nginx-proxy`
  - `cara-frontend` → 172.31.0.20:80
  - `cara-backend`  → 172.31.0.21:8000
- Esposizione esterna: tramite il tuo `nginx-proxy` su porta `8455` (da configurare)

## Esposizione via nginx-proxy esistente

Aggiungi un server block in `/opt/nginx-proxy/conf.d/cara.conf`:

```nginx
server {
  listen 8455 ssl http2;
  server_name 192.168.1.23 cara.casa;

  ssl_certificate     /etc/nginx/ssl/server.crt;
  ssl_certificate_key /etc/nginx/ssl/server.key;

  client_max_body_size 100M;

  # WebSocket-friendly upstream
  location / {
    proxy_pass http://172.31.0.20:80;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
  }
}
```

Poi `docker exec nginx-proxy nginx -t && docker restart nginx-proxy`.

Aggiungi anche la regola DNAT su `wg-easy` per accesso VPN:
porta `8455` → `172.31.0.5:8455`.

## Struttura

```
/opt/cara/
├── docker-compose.yml          # stack completo
├── .env / .env.example         # secret + config
├── backend/                    # FastAPI Python 3.11
├── frontend/                   # React 18 + TS + Vite PWA
├── data/                       # volumi persistenti (postgres, minio, ...)
├── config/                     # config aux
├── scripts/                    # helper operativi
└── docs/                       # documentazione progetto
```

## Comandi utili

```bash
# Logs
docker compose logs -f backend

# DB shell
docker exec -it cara-postgres psql -U cara

# Redis shell
docker exec -it cara-redis redis-cli -a "$(grep ^REDIS_PASSWORD .env | cut -d= -f2)"

# Rebuild app dopo cambiamenti
docker compose --profile app build && docker compose --profile app up -d

# Stop totale
docker compose --profile app down
```
