# Debugging 401 Unauthorized Errors During Mining -- Transcript (Without Skill)

## Step 1: Understand the project structure

I would start by exploring the codebase to find the authentication and API client code.

```bash
ls /home/ubuntu/code/mine/
```

```bash
find /home/ubuntu/code/mine -name "*.py" | head -40
```

```bash
grep -rl "X-Signer\|X-Signature\|X-Nonce\|401\|unauthorized" /home/ubuntu/code/mine --include="*.py"
```

This reveals the key files:
- `scripts/common.py` -- constants, wallet config resolution, signature config
- `scripts/signer.py` -- EIP-712 signing via awp-wallet CLI
- `scripts/pk_signer.py` -- direct private key EIP-712 signer
- `lib/platform_client.py` -- HTTP client that sends signed requests to the platform

---

## Step 2: Read the authentication code

I would read through the key files to understand the auth flow:

```bash
cat scripts/signer.py
cat scripts/common.py
cat lib/platform_client.py
```

Key findings from reading the code:

1. `PlatformClient._request()` (line 297 of `platform_client.py`) builds EIP-712 signed headers via `self._signer.build_auth_headers()` on every request.
2. On a 401 response, the client checks the error code. If it is `MISSING_HEADERS`, it raises immediately. If it is `UNAUTHORIZED`, `TOKEN_EXPIRED`, or `SESSION_EXPIRED`, it attempts to renew the wallet session once via `self._signer.renew_session()` and retries.
3. `WalletSigner` (in `signer.py`) depends on the `awp-wallet` CLI binary and a session token (`AWP_WALLET_TOKEN`).
4. The session token has a 1-hour lifetime (`WALLET_SESSION_DURATION_SECONDS = 3600`) and a renewal threshold of 5 minutes.
5. `resolve_wallet_config()` in `common.py` loads the token from environment, SecretRef, or persisted state -- and discards it if `AWP_WALLET_TOKEN_EXPIRES_AT` indicates expiry.

---

## Step 3: Check wallet and session health

I would run the environment verification script:

```bash
cd /home/ubuntu/code/mine && python scripts/verify_env.py --json 2>&1
```

This tells me whether `wallet_session_ready` is true or false.

Then check the persisted session state:

```bash
cat output/agent-runs/_worker_state/session.json 2>/dev/null || echo "No persisted session found"
```

Check the current environment:

```bash
echo "AWP_WALLET_TOKEN=${AWP_WALLET_TOKEN:-(not set)}"
echo "AWP_WALLET_TOKEN_EXPIRES_AT=${AWP_WALLET_TOKEN_EXPIRES_AT:-(not set)}"
echo "PLATFORM_BASE_URL=${PLATFORM_BASE_URL:-(not set, defaults to https://api.minework.net)}"
```

Check the awp-wallet binary:

```bash
which awp-wallet 2>/dev/null || echo "awp-wallet not found in PATH"
awp-wallet receive 2>&1 || echo "awp-wallet receive failed"
```

---

## Step 4: Check the signature config from the platform

The platform publishes its expected EIP-712 domain config. I would fetch it to ensure the local config matches:

```
GET https://api.minework.net/api/public/v1/signature-config
```

```bash
curl -s https://api.minework.net/api/public/v1/signature-config | python -m json.tool
```

Then compare the returned `domain_name`, `chain_id`, `verifying_contract`, and `domain_version` against the local defaults:
- `DEFAULT_EIP712_DOMAIN_NAME = "aDATA"`
- `DEFAULT_EIP712_CHAIN_ID = 8453`
- `DEFAULT_EIP712_VERIFYING_CONTRACT = "0x0000000000000000000000000000000000000000"`
- `domain_version = "1"`

Also check the cached signature config:

```bash
cat output/agent-runs/_worker_state/signature_config.json 2>/dev/null || echo "No cached signature config"
```

If the platform has changed any of these values (e.g., updated `chain_id` or `domain_name`) and the local cache is stale, signatures would be invalid and produce 401s.

---

## Step 5: Test the wallet session token directly

Try to unlock a fresh session:

```bash
awp-wallet unlock --duration 3600 2>&1
```

If this succeeds, it returns a `sessionToken`. If it fails with "Invalid or expired session token", the wallet itself needs to be re-initialized.

Then test signing with the fresh token:

```bash
awp-wallet sign-typed-data --token "$AWP_WALLET_TOKEN" --data '{"types":{"EIP712Domain":[{"name":"name","type":"string"}]},"primaryType":"EIP712Domain","domain":{"name":"test"},"message":{}}' 2>&1
```

---

## Step 6: Make a direct authenticated API call to reproduce the 401

I would craft a minimal heartbeat request to reproduce the error:

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts')
sys.path.insert(0, 'lib')
from common import resolve_wallet_config, resolve_platform_base_url
from signer import WalletSigner
from platform_client import PlatformClient

wallet_bin, wallet_token = resolve_wallet_config()
print(f'wallet_bin: {wallet_bin}')
print(f'wallet_token: {wallet_token[:16]}...' if wallet_token else 'wallet_token: EMPTY')

signer = WalletSigner(wallet_bin=wallet_bin, session_token=wallet_token)
print(f'signer address: {signer.get_address()}')

client = PlatformClient(
    base_url=resolve_platform_base_url(),
    token='',
    signer=signer,
)
try:
    result = client.send_unified_heartbeat(client_name='debug-test')
    print(f'Heartbeat OK: {result}')
except Exception as e:
    print(f'Heartbeat FAILED: {e}')
    import traceback
    traceback.print_exc()
"
```

This reproduces the exact error and tells me:
- Whether the wallet token is empty (no session)
- Whether the signer address resolves
- The exact error code/message from the 401 response

---

## Step 7: Identify the root cause

Based on the diagnostic results, the root cause is one of these scenarios:

### Scenario A: Expired wallet session token
The `AWP_WALLET_TOKEN` has expired and auto-renewal failed or was never triggered.

**Fix:**
```bash
awp-wallet unlock --duration 3600
```
Then export the new token:
```bash
export AWP_WALLET_TOKEN="<new_session_token>"
export AWP_WALLET_TOKEN_EXPIRES_AT="$(date -d '+1 hour' +%s)"
```

### Scenario B: No wallet session token at all
The persisted session at `output/agent-runs/_worker_state/session.json` is missing or empty.

**Fix:**
```bash
awp-wallet unlock --duration 3600
```
The `renew_session()` method in `signer.py` automatically persists the token via `persist_wallet_session()`.

### Scenario C: Stale signature config (domain mismatch)
The platform updated its EIP-712 domain parameters but the local cache is stale.

**Fix:**
```bash
rm -f output/agent-runs/_worker_state/signature_config.json
```
Then re-run -- `resolve_signature_config()` will fetch fresh config from the platform.

### Scenario D: Clock skew
The `issuedAt` and `expiresAt` fields in the EIP-712 message use `int(time.time())`. If the system clock is significantly off, the server rejects the signature.

**Check:**
```bash
date -u
curl -s -I https://api.minework.net | grep -i date
```

**Fix:**
```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

### Scenario E: awp-wallet binary missing or broken
The `awp-wallet` binary is not installed or not in PATH.

**Fix:**
Follow the install guidance from the project's `install_guidance.py` module, or ensure the binary is available.

---

## Step 8: Apply the fix and verify

After identifying the specific cause, I would apply the fix. The most common case is an expired session. Here is the full fix sequence:

```bash
# 1. Refresh the wallet session
cd /home/ubuntu/code/mine
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from common import resolve_wallet_config, WALLET_SESSION_DURATION_SECONDS
from signer import WalletSigner

wallet_bin, _ = resolve_wallet_config()
signer = WalletSigner(wallet_bin=wallet_bin, session_token='')
result = signer.renew_session(duration_seconds=WALLET_SESSION_DURATION_SECONDS)
print(f'New session token: {result[\"session_token\"][:16]}...')
print(f'Expires at: {result[\"expires_at\"]}')
"
```

```bash
# 2. Clear stale signature config cache
rm -f output/agent-runs/_worker_state/signature_config.json
```

```bash
# 3. Verify the fix with a heartbeat
python3 -c "
import sys
sys.path.insert(0, 'scripts')
sys.path.insert(0, 'lib')
from common import resolve_wallet_config, resolve_platform_base_url
from signer import WalletSigner
from platform_client import PlatformClient

wallet_bin, wallet_token = resolve_wallet_config()
signer = WalletSigner(wallet_bin=wallet_bin, session_token=wallet_token)
client = PlatformClient(
    base_url=resolve_platform_base_url(),
    token='',
    signer=signer,
)
result = client.send_unified_heartbeat(client_name='debug-test')
print(f'Heartbeat succeeded: {result}')
"
```

---

## Step 9: What I would tell the user

> The 401 errors are caused by [specific root cause identified in Step 7]. Here is what I found:
>
> - [Diagnostic finding 1]
> - [Diagnostic finding 2]
>
> I have applied the fix by [action taken]. The heartbeat test now succeeds, confirming that mining requests are properly authenticated again.
>
> **To prevent this in the future:** The `PlatformClient` already has auto-renewal logic (lines 359-371 in `platform_client.py`) that calls `signer.renew_session()` on 401 responses with `SESSION_EXPIRED` or `TOKEN_EXPIRED` error codes. If the wallet session expired while the miner was not running, the persisted token in `output/agent-runs/_worker_state/session.json` would be stale on next startup. The startup code in `resolve_wallet_config()` discards expired tokens, but only if `AWP_WALLET_TOKEN_EXPIRES_AT` is set. If the expiry timestamp was lost, an expired token could be used.

---

## Summary of the debugging approach

1. **Verify environment** -- check wallet binary, session token, and env vars
2. **Check signature config** -- ensure EIP-712 domain parameters match the platform
3. **Reproduce the error** -- make a direct API call to see the exact 401 response body
4. **Read the error code** -- `MISSING_HEADERS`, `UNAUTHORIZED`, `TOKEN_EXPIRED`, or `SESSION_EXPIRED` each point to different causes
5. **Fix the root cause** -- renew the wallet session, clear stale config cache, or fix clock skew
6. **Verify the fix** -- confirm a heartbeat call succeeds
