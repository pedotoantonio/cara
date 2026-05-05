#!/bin/bash
# KV cache cleanup. Each conversation's prefill is ~50-80 MB. Without
# pruning the dir grows unbounded. Strategy: drop files not accessed in
# the last KV_RETENTION_DAYS days (default 30).
#
# The cache lives INSIDE the cara-backend container (no host mount), so
# we shell into it via `docker exec` and use find there.
#
# Cron: 03:30 daily. Quiet on success.

set -euo pipefail

KV_DIR_IN_CONTAINER=/app/cache/kv
RETENTION_DAYS=${KV_RETENTION_DAYS:-30}
LOG_TAG=cara-kv-cleanup
CONTAINER=cara-backend

if ! docker exec "$CONTAINER" test -d "$KV_DIR_IN_CONTAINER" 2>/dev/null; then
    logger -t "$LOG_TAG" "kv dir missing in container: $KV_DIR_IN_CONTAINER"
    exit 0
fi

BEFORE=$(docker exec "$CONTAINER" sh -c "
    cd $KV_DIR_IN_CONTAINER
    n=\$(find . -name '*.bin' -type f | wc -l)
    kb=\$(du -sk . | cut -f1)
    echo \"\$n \$kb\"
")
BEFORE_N=$(echo "$BEFORE" | cut -d' ' -f1)
BEFORE_KB=$(echo "$BEFORE" | cut -d' ' -f2)

# atime is the right metric (each KV cache hit touches it).
docker exec "$CONTAINER" sh -c "
    find $KV_DIR_IN_CONTAINER -name '*.bin' -type f -atime +$RETENTION_DAYS -delete
"

AFTER=$(docker exec "$CONTAINER" sh -c "
    cd $KV_DIR_IN_CONTAINER
    n=\$(find . -name '*.bin' -type f | wc -l)
    kb=\$(du -sk . | cut -f1)
    echo \"\$n \$kb\"
")
AFTER_N=$(echo "$AFTER" | cut -d' ' -f1)
AFTER_KB=$(echo "$AFTER" | cut -d' ' -f2)

REMOVED=$((BEFORE_N - AFTER_N))
FREED=$((BEFORE_KB - AFTER_KB))

logger -t "$LOG_TAG" "removed=$REMOVED files freed=${FREED}KB total=${AFTER_N} files (${AFTER_KB}KB)"
