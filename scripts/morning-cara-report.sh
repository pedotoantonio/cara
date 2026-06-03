#!/bin/bash
# Morning deep health-check of CARA → report to Telegram.
# Scheduled via cron (see crontab). Reuses the NanoPC alert bot token.
#
# Checks:
#   1. Container health (cara-* up/healthy)
#   2. HTTP health endpoints (frontend 8455, chat/health)
#   3. Full diagnostics suite (GET /admin/diagnostics — db/redis/minio/llm/tts/...)
#   4. Real LLM round-trip (POST /admin/diagnostics/test/llm) — TTFT + tok/s
#   5. Persona scheduler last status (DB)
#   6. Backend error count (last 24h)
#   7. Frigate cameras live (camera_fps>0)
#   8. Disk + swap
#
# Output: single Telegram message to the owner.

set -u

TG_TOKEN="8405867586:AAEeOd2cAxBrX-7tm9GHPumYfMt4_awI3YM"
TG_CHAT="892776592"
BASE="https://192.168.1.23:8455"
ADMIN_EMAIL="pedotoa@gmail.com"
ADMIN_PASS="caracasa2026"
CURL="curl -sk --max-time 30"

ts() { date '+%Y-%m-%d %H:%M'; }
emoji() { case "$1" in ok) echo "✅";; warn) echo "⚠️";; error|fail) echo "❌";; *) echo "•";; esac; }

REPORT="🌅 *CARA — Report mattutino*\n_$(ts)_\n"
ALERTS=0

# --- 1. Containers -----------------------------------------------------------
CONT_TOTAL=$(docker ps -a --format '{{.Names}}' | grep -c '^cara-')
CONT_UP=$(docker ps --filter health=healthy --format '{{.Names}}' | grep -c '^cara-')
CONT_DOWN=$(docker ps -a --format '{{.Names}}\t{{.Status}}' | grep '^cara-' | grep -ivE 'Up' | awk '{print $1}' | tr '\n' ' ')
if [ -z "$CONT_DOWN" ]; then
  REPORT="$REPORT\n✅ *Container*: $CONT_UP/$CONT_TOTAL healthy"
else
  REPORT="$REPORT\n❌ *Container giù*: $CONT_DOWN"
  ALERTS=$((ALERTS+1))
fi

# --- 2. HTTP health ----------------------------------------------------------
H_FRONT=$($CURL -o /dev/null -w '%{http_code}' "$BASE/" 2>/dev/null)
H_CHAT=$($CURL "$BASE/api/v1/chat/health" 2>/dev/null | grep -o '"status":"ok"' | head -1)
if [ "$H_FRONT" = "200" ] && [ -n "$H_CHAT" ]; then
  REPORT="$REPORT\n✅ *HTTP*: frontend $H_FRONT, chat/health ok"
else
  REPORT="$REPORT\n❌ *HTTP*: frontend=$H_FRONT chat=${H_CHAT:-KO}"
  ALERTS=$((ALERTS+1))
fi

# --- login admin -------------------------------------------------------------
TOKEN=$($CURL -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASS\"}" 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  REPORT="$REPORT\n❌ *Login admin FALLITO* — diagnostica saltata"
  ALERTS=$((ALERTS+1))
else
  AUTH="-H \"Authorization: Bearer $TOKEN\""

  # --- 3. Diagnostics suite --------------------------------------------------
  DIAG=$($CURL -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/admin/diagnostics" 2>/dev/null)
  DIAG_LINE=$(echo "$DIAG" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    checks = d.get('checks', [])
    ok = sum(1 for c in checks if c.get('status')=='ok')
    warn = [c['name'] for c in checks if c.get('status')=='warn']
    err = [c['name'] for c in checks if c.get('status') in ('error','fail')]
    out = f'{ok}/{len(checks)} ok'
    if warn: out += ' | warn: '+','.join(warn)
    if err:  out += ' | ERR: '+','.join(err)
    print(('ERR' if err else ('WARN' if warn else 'OK'))+'|'+out)
except Exception as e:
    print('ERR|parse failed: '+str(e)[:60])
" 2>/dev/null)
  DSTAT="${DIAG_LINE%%|*}"; DMSG="${DIAG_LINE#*|}"
  case "$DSTAT" in
    OK)   REPORT="$REPORT\n✅ *Diagnostica*: $DMSG";;
    WARN) REPORT="$REPORT\n⚠️ *Diagnostica*: $DMSG";;
    *)    REPORT="$REPORT\n❌ *Diagnostica*: $DMSG"; ALERTS=$((ALERTS+1));;
  esac

  # --- 4. Real LLM round-trip ------------------------------------------------
  # Longer timeout: the NPU serialises inferences (1 at a time). At 07:00
  # the nightly persona rebuild (03:15) is long done, so the NPU is free,
  # but allow generous headroom in case of Frigate DDR contention.
  LLM=$(curl -sk --max-time 90 -X POST "$BASE/api/v1/admin/diagnostics/test/llm" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"prompt":"Di che colore è il cielo? Rispondi in 3 parole.","max_new_tokens":40}' 2>/dev/null)
  LLM_LINE=$(echo "$LLM" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    txt = (d.get('text') or '').replace(chr(10),' ')[:60]
    if not txt:
        print('ERR|risposta vuota'); raise SystemExit
    print(f\"OK|TTFT {d.get('ttft_s')}s, {d.get('tok_per_s')} tok/s — \\\"{txt}\\\"\")
except SystemExit: pass
except Exception as e:
    print('ERR|'+str(e)[:60])
" 2>/dev/null)
  LSTAT="${LLM_LINE%%|*}"; LMSG="${LLM_LINE#*|}"
  if [ "$LSTAT" = "OK" ]; then
    REPORT="$REPORT\n✅ *LLM (NPU)*: $LMSG"
  else
    REPORT="$REPORT\n❌ *LLM (NPU)*: $LMSG"; ALERTS=$((ALERTS+1))
  fi
fi

# --- 5. Persona scheduler ----------------------------------------------------
PERSONA=$(docker exec cara-postgres psql -U cara -d cara -tAc \
  "SELECT user_id||':'||COALESCE(last_status,'?')||':'||COALESCE(round(confidence)::text,'-')||':'||COALESCE(to_char(last_built_at,'MM-DD HH24:MI'),'mai') FROM persona_profiles ORDER BY user_id;" 2>/dev/null | tr '\n' ' ')
PERSONA_FAIL=$(docker logs --since 24h cara-backend 2>&1 | grep -c "persona.scheduler.user_failed")
if [ "$PERSONA_FAIL" -eq 0 ]; then
  REPORT="$REPORT\n✅ *Persona*: ${PERSONA:-nessun profilo} (0 fail 24h)"
else
  REPORT="$REPORT\n⚠️ *Persona*: $PERSONA_FAIL fail nelle 24h — $PERSONA"
  ALERTS=$((ALERTS+1))
fi

# --- 6. Backend errors 24h ---------------------------------------------------
ERR24=$(docker logs --since 24h cara-backend 2>&1 | grep -iE "\[error|traceback|exception|critical" | grep -ivE "persona.scheduler.user_failed" | grep -c .)
if [ "$ERR24" -eq 0 ]; then
  REPORT="$REPORT\n✅ *Errori backend 24h*: 0"
else
  REPORT="$REPORT\n⚠️ *Errori backend 24h*: $ERR24"
fi

# --- 7. Frigate cameras ------------------------------------------------------
CAM=$(docker exec frigate curl -s --max-time 8 http://127.0.0.1:5000/api/stats 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin); cams = d.get('cameras', {})
    up = [k for k,v in cams.items() if (v.get('camera_fps') or 0) > 0]
    down = [k for k,v in cams.items() if (v.get('camera_fps') or 0) == 0]
    print(f\"{len(up)}/{len(cams)} live\" + (' | giù: '+','.join(down) if down else ''))
except Exception as e:
    print('stats KO')
" 2>/dev/null)
REPORT="$REPORT\n📹 *Frigate*: ${CAM:-N/D}"

# --- 8. Disk + swap ----------------------------------------------------------
DISK=$(df -h / | awk 'NR==2{print $5" ("$4" liberi)"}')
SWAP=$(free -m | awk '/Swap/{print $3"/"$2" MB"}')
REPORT="$REPORT\n💾 *Disco*: $DISK · *Swap*: $SWAP"

# --- verdict -----------------------------------------------------------------
if [ "$ALERTS" -eq 0 ]; then
  REPORT="🟢 *Tutto regolare*\n$REPORT"
else
  REPORT="🔴 *$ALERTS problema/i rilevati*\n$REPORT"
fi

# --- send --------------------------------------------------------------------
curl -s --max-time 20 -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
  -d chat_id="$TG_CHAT" \
  -d parse_mode="Markdown" \
  --data-urlencode text="$(echo -e "$REPORT")" >/dev/null 2>&1

echo "[$(ts)] report inviato (alerts=$ALERTS)"
