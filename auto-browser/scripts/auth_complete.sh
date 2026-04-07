#!/usr/bin/env bash
# AUTH_COMPLETE - Finish the login flow
# Usage: bash auth_complete.sh [--wait-user | --timeout SECONDS]
# Example: bash auth_complete.sh --wait-user  (caller runs after user says "done")
# Example: bash auth_complete.sh --timeout 300 (poll for 300 seconds)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HOME/.openclaw/vrd-data/state.json"

MODE="${1:-timeout}"
TIMEOUT="${2:-300}"
if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] TIMEOUT must be a number" >&2
  exit 1
fi

TOKEN=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1])).get('SWITCH_TOKEN',''))" "$STATE" 2>/dev/null || echo "")

if [ "$MODE" = "--wait-user" ]; then
  # Caller invokes this after the user says "done"
  echo "[AUTH] User finished login" >&2
elif [ "$MODE" = "--timeout" ]; then
  # Polling mode
  echo "[AUTH] Waiting for login (timeout ${TIMEOUT}s)..." >&2
  if [ -n "$TOKEN" ]; then
    curl -s "http://127.0.0.1:6090/continue/poll?token=$TOKEN&after=0&timeout=$TIMEOUT" >/dev/null 2>&1 || true
  else
    sleep "$TIMEOUT"
  fi
else
  echo "Usage: $0 [--wait-user | --timeout SECONDS]" >&2
  exit 1
fi

# Clear guide message
if [ -n "$TOKEN" ]; then
  curl -s -X DELETE "http://127.0.0.1:6090/guide?token=$TOKEN" >/dev/null 2>&1 || true
fi

# Capture cookie snapshot
echo "[AUTH] Capturing login state..." >&2
agent-browser --cdp 9222 --session vrd snapshot >/dev/null 2>&1 || true

echo "[AUTH] Login complete" >&2
exit 0
