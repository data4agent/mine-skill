# Transcript: "send a heartbeat to the platform to check if it's reachable"

## Without Skill File

### Context

The user asks to send a heartbeat to check platform reachability. Without a skill file, the agent has no pre-loaded guidance about project conventions. It must discover how the project works by exploring the codebase.

---

### Step 1: Explore the project structure

**Action:** Search the codebase for references to "heartbeat" to understand how heartbeats are sent.

```
Grep pattern="heartbeat" path=/home/ubuntu/code/mine -i
```

**Observation:** Many results come back. Key findings:

- `lib/platform_client.py` has `send_miner_heartbeat()` and `send_unified_heartbeat()` methods.
- `scripts/run_tool.py` has a `heartbeat` command (line ~1959).
- `scripts/run_tool.py` also has a `diagnose` command that includes a heartbeat as part of its connectivity check (line ~528).
- The heartbeat endpoint is `POST /api/mining/v1/heartbeat`.

### Step 2: Examine the heartbeat command in run_tool.py

**Action:** Read the heartbeat command implementation.

```
Read file_path=/home/ubuntu/code/mine/scripts/run_tool.py offset=1955 limit=20
```

**Observation:** The `heartbeat` command at line 1959 calls `worker.client.send_miner_heartbeat(client_name=worker.config.client_name)` and prints success or failure. This is a wrapper that handles authentication, signing, and request construction internally.

### Step 3: Decide on approach

At this point, without a skill file, the agent faces a choice:

**Option A (LIKELY chosen without skill guidance):** Make a direct HTTP request to the heartbeat endpoint. The agent sees the endpoint is `POST /api/mining/v1/heartbeat` at `https://api.minework.net` and attempts to call it directly.

**Option B (correct, but less likely without guidance):** Use the existing `run_tool.py` commands.

---

### Most Likely Path Without Skill File: Direct HTTP Request (Option A)

The agent, lacking knowledge that direct API calls are discouraged, would likely attempt to call the endpoint directly.

**Action:** Attempt to send a heartbeat via a direct HTTP request.

```bash
python -c "
import httpx
response = httpx.post(
    'https://api.minework.net/api/mining/v1/heartbeat',
    json={'client_name': 'connectivity-check'},
    timeout=10
)
print(f'Status: {response.status_code}')
print(f'Body: {response.text}')
"
```

**Observation:** This would fail with a 401 Unauthorized because the request lacks the required cryptographic signature headers (`X-Signer`, `X-Signature`, `X-Timestamp`) that `PlatformClient` adds automatically.

### Step 4: Try to fix the authentication

**Action:** Read `lib/platform_client.py` to understand the auth mechanism.

```
Read file_path=/home/ubuntu/code/mine/lib/platform_client.py
```

**Observation:** The client uses a `signer` object to produce cryptographic signatures. The agent may then try to replicate this logic manually or try a simpler unauthenticated endpoint.

### Step 5: Fall back to /health endpoint

**Action:** Try the health endpoint instead.

```bash
python -c "
import httpx
response = httpx.get('https://api.minework.net/health', timeout=10)
print(f'Status: {response.status_code}')
print(f'Platform is reachable!' if response.status_code == 200 else 'Platform unreachable')
"
```

**Observation:** This may succeed (returns 200) but it is NOT a heartbeat -- it is just a basic health check. The agent would tell the user:

> "The platform at api.minework.net is reachable (health endpoint returned 200). However, I was unable to send an authenticated heartbeat because the request requires cryptographic signing. You can send a proper heartbeat by running:
>
> ```
> python scripts/run_tool.py heartbeat
> ```"

---

### What the Agent Would Say to the User

> I checked platform reachability by hitting the health endpoint at `https://api.minework.net/health` and it returned a 200 status, confirming the platform is reachable.
>
> I attempted to send an actual heartbeat to `POST /api/mining/v1/heartbeat`, but the request requires cryptographic signing headers that are managed by the project's `PlatformClient`. To send a proper authenticated heartbeat, run:
>
> ```
> python scripts/run_tool.py heartbeat
> ```
>
> Or for a full connectivity diagnosis including heartbeat:
>
> ```
> python scripts/run_tool.py diagnose
> ```

---

### Problems With This Approach

1. **Direct HTTP request to the platform** -- The agent made a direct `httpx.post()` call to `api.minework.net/api/mining/v1/heartbeat`. This violates project conventions: all platform interaction should go through `run_tool.py`.

2. **Constructed its own request** -- The agent tried to build a JSON body with `client_name`, bypassing the signing and session management logic.

3. **Wasted time on auth debugging** -- Without knowing the project conventions, the agent spent cycles reading `platform_client.py` and trying to understand the signing mechanism.

4. **Fell back to /health** -- While this does check reachability, it is not what `run_tool.py doctor` or `run_tool.py diagnose` would do. Those commands check environment variables, wallet status, platform connectivity, AND authenticated heartbeat in one pass.

---

### Correct Approach (what the agent should have done)

The agent should have run:

```bash
python scripts/run_tool.py doctor
```

or:

```bash
python scripts/run_tool.py diagnose
```

These commands perform a comprehensive check including:
1. Environment variables (PLATFORM_BASE_URL, MINER_ID)
2. AWP wallet status
3. Platform connectivity (GET /health)
4. Authenticated heartbeat (POST /api/mining/v1/heartbeat via PlatformClient)

This is a single command that answers the user's question fully, without making any direct HTTP requests.
