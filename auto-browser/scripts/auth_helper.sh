#!/usr/bin/env bash
# AUTH_HELPER - Lightweight login helper
# Usage: bash auth_helper.sh <platform_domain>
# Example: bash auth_helper.sh linkedin.com

set -euo pipefail

PLATFORM_DOMAIN="${1:-}"
if [ -z "$PLATFORM_DOMAIN" ]; then
  echo "Usage: $0 <platform_domain>" >&2
  echo "Example: $0 linkedin.com" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VRD="$SCRIPT_DIR/vrd.py"
STATE="$HOME/.openclaw/vrd-data/state.json"

# Map common platforms to login URLs
get_login_url() {
  case "$1" in
    linkedin.com|www.linkedin.com)
      echo "https://www.linkedin.com/login"
      ;;
    amazon.com|www.amazon.com)
      echo "https://www.amazon.com/ap/signin"
      ;;
    twitter.com|www.twitter.com|x.com|www.x.com)
      echo "https://twitter.com/login"
      ;;
    *)
      echo "https://$1/login"
      ;;
  esac
}

# Step 1: Try silent cookie import
echo "[AUTH] Trying to import existing cookies..." >&2
if agent-browser --cdp 9222 --session vrd cookie-import --domain "$PLATFORM_DOMAIN" 2>/dev/null; then
  echo "[AUTH] Cookie import succeeded" >&2
  exit 0
fi

echo "[AUTH] No cookies available; starting VNC..." >&2

# Step 2: Start VNC if not running
if ! python3 "$VRD" status >/dev/null 2>&1; then
  echo "[AUTH] Starting VNC stack..." >&2
  KASM_BIND=0.0.0.0 python3 "$VRD" start >/tmp/vrd-start.log 2>&1
  sleep 3
fi

# Resolve PUBLIC_URL
PUBLIC_URL=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1])).get('PUBLIC_URL',''))" "$STATE" 2>/dev/null || echo "")
if [ -z "$PUBLIC_URL" ]; then
  echo "[ERROR] Could not get PUBLIC_URL; VNC may not have started correctly" >&2
  exit 1
fi

# Step 3: Open login page
LOGIN_URL=$(get_login_url "$PLATFORM_DOMAIN")
echo "[AUTH] Opening login page: $LOGIN_URL" >&2
agent-browser --cdp 9222 --session vrd open "$LOGIN_URL" >/dev/null 2>&1 || true

# Set guide message
TOKEN=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1])).get('SWITCH_TOKEN',''))" "$STATE" 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then
  curl -s -X POST "http://127.0.0.1:6090/guide?token=$TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"text":"Please login, then click Done below","kind":"action"}' >/dev/null 2>&1 || true
fi

# Print Cloudflare URL for the user
echo "$PUBLIC_URL"

# Step 4: Wait for completion (handled by caller)
# Caller should wait for user "done" or poll /continue/poll

# Success
exit 0
