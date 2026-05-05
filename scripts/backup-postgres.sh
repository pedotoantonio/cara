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

# Retention: drop dumps older than RETENTION_DAYS days.
find "$BACKUP_DIR" -name 'cara-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -delete

logger -t "$LOG_TAG" "OK $DUMP ($(du -h "$DUMP" | cut -f1))"
