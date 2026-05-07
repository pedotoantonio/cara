# Cap 24 — Manutenzione

> *Sintesi 30 secondi.* CARA è low-maintenance ma non zero. Tre task
> ricorrenti: backup Postgres giornaliero, cleanup KV cache settimanale,
> aggiornamento modello LLM/voci/dipendenze quando esce qualcosa di
> nuovo. Più qualche occasionale: rotation chiavi, swap modello,
> archive log vecchi.

## 24.1 Backup Postgres

**Script**: `scripts/backup-postgres.sh`.

```bash
#!/bin/bash
set -e
BACKUP_DIR=/opt/cara/backups
TIMESTAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR"
docker exec cara-postgres pg_dump -U cara cara | gzip > \
  "$BACKUP_DIR/cara-$TIMESTAMP.sql.gz"
# Cancella backup più vecchi di 30 giorni
find "$BACKUP_DIR" -name 'cara-*.sql.gz' -mtime +30 -delete
echo "Backup OK: $BACKUP_DIR/cara-$TIMESTAMP.sql.gz"
```

### Cron giornaliero

```bash
crontab -e
# Aggiungi:
30 3 * * * /opt/cara/scripts/backup-postgres.sh >> /var/log/cara-backup.log 2>&1
```

Backup a 3:30 ogni notte. Output a log per troubleshooting.

### Restore

```bash
# Stop services
docker compose --profile app down

# Drop + recreate DB (CAREFUL!)
docker exec cara-postgres psql -U postgres -c "DROP DATABASE cara;"
docker exec cara-postgres psql -U postgres -c "CREATE DATABASE cara OWNER cara;"

# Restore
gunzip -c /opt/cara/backups/cara-20260507-0330.sql.gz | \
  docker exec -i cara-postgres psql -U cara cara

# Restart
docker compose --profile app up -d
```

> **🔒 Sicurezza** — il backup `.sql.gz` contiene password hashate
> (bcrypt OK) MA contiene `oauth_credentials.encrypted_refresh_token`.
> Senza la `OAUTH_ENCRYPTION_KEY` corrispondente in `.env`, gli
> OAuth token sono inutilizzabili. **Backup il `.env` separatamente.**

### Off-site backup (consigliato)

I backup locali su `/opt/cara/backups/` non sopravvivono a un disastro
hardware (incendio, furto). Sync periodico off-site:

```bash
# rsync a NAS Synology / Nextcloud / S3
rsync -avz --delete /opt/cara/backups/ \
  /mnt/nas/cara-backups/

# o nightly cron
0 4 * * * rsync -avz /opt/cara/backups/ user@nas.lan:/backup/cara/
```

Se hai Nextcloud sul NanoPC stesso (cap 1.3), backup da CARA → cartella
sincronizzata Nextcloud → cloud Nextcloud (se configurato).

## 24.2 KV cache cleanup

**Script**: `scripts/cleanup-kv-cache.sh`.

I file in `data/kv-cache/<sha1>.bin` (~50MB ognuno) si accumulano per
ogni conversation. Senza pulizia, riempiono il disco in mesi.

```bash
#!/bin/bash
# Cancella file KV cache più vecchi di 30 giorni
find /opt/cara/data/kv-cache/ -name '*.bin' -mtime +30 -delete
```

### Cron settimanale

```bash
0 4 * * 0 /opt/cara/scripts/cleanup-kv-cache.sh
```

Domenica alle 4. Janitor leggero, non interrompe nulla.

### Dimensione attuale

```bash
du -sh /opt/cara/data/kv-cache/
# Tipico: ~500 MB - 5 GB per famiglia di 4 attiva

# Quanti file
ls /opt/cara/data/kv-cache/ | wc -l
```

## 24.3 Aggiornamento modello LLM

Periodicamente esce un nuovo Qwen o un nuovo modello migliore. Procedura
per swap:

### 1. Scarica il nuovo modello

`.rkllm` files vengono pre-converti su x86 con `rkllm-toolkit`. Non
puoi convertire un modello generico HuggingFace direttamente sul
NanoPC. Sources:

- HuggingFace: cerca "rkllm" repos (es. `Pelochus/qwen2.5-1.5b-rkllm`)
- Self-conversion: usa una macchina x86 con CUDA + `rkllm-toolkit`
  (procedura in `docs/LORA-FINE-TUNE-PIPELINE.md`)

```bash
# Scarica nel data dir
cd /opt/cara/data/models/
curl -L -o qwen2.5-3b-instruct-w8a8.rkllm \
  https://huggingface.co/.../qwen2.5-3b-instruct-w8a8.rkllm
```

### 2. Configura CARA

Aggiorna `cara/config.py` o `.env`:

```ini
LLM_MODEL_PATH=/app/models/qwen2.5-3b-instruct-w8a8.rkllm
```

Se vuoi mantenere il vecchio come fallback, aggiungi anche
`LLM_MODEL_FALLBACK_PATH`.

### 3. Test su staging

Idealmente staging = istanza separata di CARA. Senza staging, fai
backup e prova in produzione fuori orari di punta.

```bash
# Backup
docker exec cara-postgres pg_dump -U cara cara > pre-llm-swap.sql.gz

# Restart
docker compose --profile app restart backend

# Verifica caricamento
docker logs --tail 30 cara-backend | grep "llm.load"
# Attesi: llm.load.start ... llm.load.done seconds=...
```

### 4. Verifica qualità

Manda ~10 chat di test variate:
- Conversazione casual
- Chiamata tool ("aggiungi pasta alla spesa")
- Domanda fattuale italiana ("capitale Brasile?")
- Compito ragionamento ("qual è il numero più grande tra 17 e 19?")

Se la qualità peggiora rispetto al vecchio, rollback.

### 5. Rollback se necessario

```ini
LLM_MODEL_PATH=/app/models/qwen2.5-1.5b-instruct-w8a8.rkllm
```

Restart. Vecchio modello torna.

## 24.4 Aggiornamento voci Piper

Le voci sono in `data/tts/piper/voices/`. Auto-scaricate al primo
uso. Per upgrade manuale a una voce migliore:

```bash
cd /opt/cara/data/tts/piper/voices/

# Esempio: voce Riccardo medium (futuro)
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/riccardo/medium/it_IT-riccardo-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/riccardo/medium/it_IT-riccardo-medium.onnx.json
```

Nessun restart necessario. La voce diventa selezionabile dall'utente
in `SettingsPage`.

## 24.5 Aggiornamento dipendenze Python

```bash
cd /opt/cara/backend

# Vedi outdated
.venv/bin/python -m pip list --outdated

# Aggiorna mirato (es. fastapi)
.venv/bin/python -m pip install -U fastapi

# Test
.venv/bin/python -m pytest tests/unit -q

# Rebuild container
cd /opt/cara
DOCKER_BUILDKIT=0 docker compose --profile app build backend
docker compose --profile app up -d backend
```

> **⚠️ Attenzione** — alcune librerie hanno breaking changes silenziosi.
> Aggiorna una alla volta, esegui test fra ogni step.

## 24.6 Aggiornamento dipendenze Node

```bash
cd /opt/cara/frontend

# Vedi outdated
npm outdated

# Aggiorna minor/patch (rispetta semver)
npm update

# Major update mirato
npm install --save react@^19.0.0

# Test
./node_modules/.bin/tsc --noEmit
npm run build

# Rebuild container
cd /opt/cara
DOCKER_BUILDKIT=0 docker compose --profile app build frontend
docker compose --profile app up -d frontend
```

## 24.7 Aggiornamento RKLLM runtime

Quando Rockchip rilascia una nuova `librkllmrt.so`:

1. Scarica da https://github.com/airockchip/rknn-llm/releases
2. Backup quella corrente:
   ```bash
   sudo cp /home/apedo/cara-poc-rkllm/runtime-v1.1.0/lib/librkllmrt.so \
     /home/apedo/cara-poc-rkllm/runtime-v1.1.0/lib/librkllmrt.so.bak
   ```
3. Sostituisci con la nuova
4. Restart `cara-backend`
5. Verifica caricamento + qualità inferenza
6. Se peggiora, ripristina `.bak`

> **⚠️ Attenzione** — un upgrade RKLLM major può richiedere kernel
> driver matching nuovo. Verifica compatibilità prima.

## 24.8 Pulizia tabelle log/episodic

Le tabelle `events`, `tool_call_metrics`, `audit_log` crescono nel
tempo. Cleanup automatico:

```sql
-- events: retention 90 giorni
DELETE FROM events WHERE ts < NOW() - INTERVAL '90 days';

-- tool_call_metrics: retention 180 giorni
DELETE FROM tool_call_metrics WHERE ts < NOW() - INTERVAL '180 days';

-- audit_log: retention 1 anno (o forever, scelta admin)
DELETE FROM audit_log WHERE created_at < NOW() - INTERVAL '1 year';

-- VACUUM dopo grandi delete
VACUUM ANALYZE events;
VACUUM ANALYZE tool_call_metrics;
VACUUM ANALYZE audit_log;
```

CARA ha `episodic.cleanup_old(retention_days=90)` chiamabile da
maintenance. Manca un cron job dedicato per ora — eseguilo manualmente
mensile o aggiungi al `cara.cda.maintenance`.

## 24.9 Rotazione chiavi

### `JWT_SECRET`

Vedi cap 19.2.4. Cambio = re-login forzato di tutti.

### `OAUTH_ENCRYPTION_KEY`

Vedi cap 19.4.5. Migrazione token cifrati richiede script futuro.
Senza, gli utenti devono ri-OAuth.

### `MINIO_ROOT_PASSWORD`

```bash
# Cambia in .env
sed -i "s/^MINIO_ROOT_PASSWORD=.*/MINIO_ROOT_PASSWORD=$(openssl rand -hex 32)/" /opt/cara/.env

# Restart MinIO
docker compose restart minio

# Aggiorna gli altri container che lo usano (backend principalmente)
docker compose --profile app restart backend
```

## 24.10 Monitoraggio salute hardware

NPU + temperatura + dischi:

```bash
# Temperatura CPU/NPU
sudo cat /sys/class/thermal/thermal_zone0/temp
# Output in millidegree (es. 65000 = 65°C)

# Quando CARA è sotto carico LLM, atteso 60-75°C. Sopra 85°C =
# preoccupante (ventola KO o ambiente troppo caldo)

# Dischi
df -h /opt/cara/data
# Sopra 90% → cleanup KV cache + log + considerare archive backup off-site

# RAM
free -h
# Backend + Postgres + Redis + MinIO + Chroma + LLM caricato = ~6-7GB
# typical. Sopra 14/16GB = preoccupante
```

Sysadmin Dashboard (cap 21.1) automatizza alerting per disco/RAM.

## 24.11 Aggiornamenti sistema operativo

Periodicamente Debian rilascia aggiornamenti di sicurezza:

```bash
sudo apt update && sudo apt upgrade -y
```

> **⚠️ Attenzione** — non aggiornare il **kernel** automaticamente!
> CARA usa kernel custom 6.1.141-cara1 con `rknpu` driver patched. Un
> aggiornamento kernel rompe RKLLM.

```bash
# Hold del kernel
sudo apt-mark hold linux-image-* linux-headers-*
```

## 24.12 Calendario manutenzione consigliato

| Frequenza | Task |
|---|---|
| Ogni notte (cron) | Backup Postgres |
| Ogni domenica (cron) | KV cache cleanup |
| Mensile (manuale) | Pulizia tabelle log + VACUUM |
| Mensile (manuale) | Verifica `df -h` + alert se >85% |
| Trimestrale | `apt upgrade` (no kernel) |
| Trimestrale | npm audit + pip audit |
| Annuale | Rotation `JWT_SECRET` + `OAUTH_ENCRYPTION_KEY` |
| Annuale | Test restore da backup (senza il quale è solo speranza) |
| Quando esce | Aggiornamento RKLLM runtime |
| Quando esce | Aggiornamento modello LLM |

## 24.13 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| Disco pieno | KV cache + Postgres growth | Cleanup KV + VACUUM Postgres |
| RAM crescente nel tempo | Memory leak applicativo | Restart `cara-backend` ogni N giorni come palliativo; investiga |
| Backup falliscono | Permission denied su backups/ | `chown apedo:users /opt/cara/backups` |
| Restore non parte | DB attivo con connection | Stop CARA prima del restore |
| RKLLM rotta dopo apt | Kernel updated | Reflasha 6.1.141-cara1 da `kernel-backup/` (CLAUDE.md) |

---

[← Cap 23 Deploy](23-deploy.md) · [README](README.md) · [Cap 25 Estendere CARA →](25-estendere-cara.md)
