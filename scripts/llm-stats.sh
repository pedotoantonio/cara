#!/bin/bash
# Aggrega metriche LLM dai log strutturati di cara-backend.
# Usage:
#   /opt/cara/scripts/llm-stats.sh          # last 24h
#   /opt/cara/scripts/llm-stats.sh 1h       # last 1 hour
#   /opt/cara/scripts/llm-stats.sh 7d       # last 7 days
set -euo pipefail
WINDOW="${1:-24h}"
docker logs cara-backend --since "$WINDOW" 2>&1 | python3 "$(dirname "$0")/_llm_stats.py" "$WINDOW"
