#!/bin/bash
# Postgres dump → /opt/cara/backups/cara-YYYYMMDD-HHMM.sql.gz
# Cron: 03:15 daily. 7-day retention. Quiet on success, mail-on-fail.

set -euo pipefail

BACKUP_DIR=/opt/cara/backups
RETENTION_DAYS=7
NOW=$(date +%Y%m%d-%H%M)
LOG_TAG=cara-backup

mkdir -p "$BACKUP_DIR"

DUMP="$BACKUP_DIR/cara-$NOW.sql.gz"

# pg_dump runs INSIDE the postgres container so we don't need a client
# binary on the host. The output is streamed (no intermediate file).
if ! docker exec cara-postgres pg_dump -U cara cara | gzip -c >"$DUMP"; then
    logger -t "$LOG_TAG" "DUMP FAILED for $DUMP"
    rm -f "$DUMP"
    exit 1
fi

# Sanity: dump must be at least 1 KB (the schema alone is bigger).
if [ "$(stat -c %s "$DUMP")" -lt 1024 ]; then
    logger -t "$LOG_TAG" "DUMP TOO SMALL ($DUMP)"
    rm -f "$DUMP"
    exit 1
fi

# Mirror to MinIO bucket "cara-backups". Best-effort: failure logged but
# doesn't fail the cron — the local copy is the authoritative one.
MIRROR_STATUS="ok"
if ! docker exec -i cara-minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && mc pipe "local/cara-backups/cara-'"$NOW"'.sql.gz" >/dev/null' <"$DUMP"; then
    MIRROR_STATUS="failed"
    logger -t "$LOG_TAG" "MINIO MIRROR FAILED for cara-$NOW.sql.gz (local copy still ok)"
fi

# Retention: drop dumps older than RETENTION_DAYS days (local + minio).
find "$BACKUP_DIR" -name 'cara-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -delete

docker exec cara-minio sh -c '
    mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 || exit 0
    cutoff_epoch=$(date -d "'"$RETENTION_DAYS"' days ago" +%s)
    mc ls local/cara-backups/ 2>/dev/null | awk "{ print \$5, \$6 }" | while read -r dt name; do
        [ -z "$name" ] && continue
        case "$name" in cara-*.sql.gz) ;; *) continue;; esac
        # mc ls output time is recent enough; rely on filename date instead.
        ymd=$(echo "$name" | sed -n "s/^cara-\([0-9]\{8\}\)-.*/\1/p")
        [ -z "$ymd" ] && continue
        file_epoch=$(date -d "$ymd" +%s 2>/dev/null) || continue
        [ "$file_epoch" -lt "$cutoff_epoch" ] && mc rm "local/cara-backups/$name" >/dev/null 2>&1
    done
' >/dev/null 2>&1 || true

logger -t "$LOG_TAG" "OK $DUMP ($(du -h "$DUMP" | cut -f1)) [mirror=$MIRROR_STATUS]"
