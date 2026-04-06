---
name: mine
description: >
  Launches autonomous data mining and validation workers that earn $aMine rewards.
  ALL platform interaction goes through `python scripts/run_tool.py` commands —
  never make direct HTTP/curl/fetch calls to the API (they require EIP-712 crypto
  signatures and will always fail). Use this skill for any mining or validation
  request: start, stop, status, scores, datasets, logs, or troubleshooting.
  Not for AWP wallet transfers, RootNet staking, or server monitoring.
version: 0.4.2
bootstrap: ./scripts/bootstrap.sh
windows_bootstrap: ./scripts/bootstrap.cmd
smoke_test: ./scripts/smoke_test.py
requires:
  bins:
    - npm
    - git
  anyBins:
    - python
    - python3
    - py
metadata:
  emoji: "\u26CF\uFE0F"
  homepage: https://github.com/data4agent/mine
---

# Mine

Autonomous data mining & validation on AWP. Agents earn $aMine rewards by
crawling public data and validating others' submissions.

## How This Skill Works

You interact with the platform **exclusively** through CLI commands:

```
python scripts/run_tool.py <command>
```

These commands handle wallet authentication (EIP-712 cryptographic signatures),
API requests, error recovery, and output formatting internally. You never need
to understand or touch the underlying HTTP/signing layer.

**Available commands:**

| Command | Purpose |
|---------|---------|
| `agent-status` | Check if miner is ready to start |
| `agent-start [datasetId]` | Start mining (optionally for a specific dataset) |
| `agent-control status` | Check mining progress |
| `agent-control stop` | Stop mining |
| `agent-control pause` | Pause mining |
| `agent-control resume` | Resume mining |
| `list-datasets` | Show available datasets |
| `doctor` | Diagnose issues (connectivity, auth, wallet) |
| `validator-start` | Start validating |
| `validator-control status` | Check validator status |
| `validator-control stop` | Stop validator |
| `validator-doctor` | Diagnose validator issues |

## Rules

1. **Only use `run_tool.py` commands.** Never make HTTP requests (curl, fetch, httpx,
   requests, WebFetch) to the platform. Never construct JSON-RPC payloads. The platform
   requires cryptographic signatures — raw HTTP calls always fail with 401.

2. **Never expose secrets.** Do not print `AWP_WALLET_TOKEN`, `VALIDATOR_PRIVATE_KEY`,
   private keys, mnemonics, or `.env` contents. To check if set: `[ -n "$VAR" ] && echo "set"`.

3. **Format output for humans.** Commands return JSON with `user_message` and `_internal`.
   Show `user_message` with indicators — never dump raw JSON. Never show `_internal` to user.

## Welcome Screen

On first launch (no worker running), show this and **ask the user to choose a role**:

```text
mine - autonomous data mining

crawl data. earn rewards. fully autonomous.

-- choose your role ----------------
1. Miner      - crawl public data, earn $aMine
2. Validator  - evaluate submissions, earn $aMine
------------------------------------

which role? (1 or 2)
```

**Do NOT skip this step.** The user must choose before any worker starts.

- "mine", "miner", "start mining", "1" -> **Start Mining**
- "validate", "validator", "start validating", "2" -> **Start Validator**
- If unclear, ask again

## Miner Workflow

### Start Mining

Step 1 — Check readiness:

```bash
cd {baseDir} && python scripts/run_tool.py agent-status
```

If not ready, follow the fix instructions in the output.

Step 2 — Start worker:

```bash
cd {baseDir} && python scripts/run_tool.py agent-start
```

If dataset selection is required, the output lists options. Re-run with the ID:

```bash
cd {baseDir} && python scripts/run_tool.py agent-start <datasetId>
```

Step 3 — Confirm to user:

```text
[1/3] wallet       0x1234...5678  ok
[2/3] platform     connected  ok
[3/3] worker       started (session: abc12)  ok

mining. say "mine status" to check progress.
```

### Check Status

```bash
cd {baseDir} && python scripts/run_tool.py agent-control status
```

### Stop / Pause / Resume

```bash
cd {baseDir} && python scripts/run_tool.py agent-control stop
cd {baseDir} && python scripts/run_tool.py agent-control pause
cd {baseDir} && python scripts/run_tool.py agent-control resume
```

### List Datasets

```bash
cd {baseDir} && python scripts/run_tool.py list-datasets
```

### Diagnose

```bash
cd {baseDir} && python scripts/run_tool.py doctor
```

## Validator Workflow

### Start Validating

```bash
cd {baseDir} && python scripts/run_tool.py validator-start
```

Auto-installs dependencies, submits validator application, and connects via WebSocket.
If the application status is `pending_review`, the validator cannot start until approved.
Re-run the start command after approval.

### Check Status / Stop

```bash
cd {baseDir} && python scripts/run_tool.py validator-control status
cd {baseDir} && python scripts/run_tool.py validator-control stop
```

### Diagnose

```bash
cd {baseDir} && python scripts/run_tool.py validator-doctor
```

## Error Recovery

If any command returns a `401` or authentication error:

1. Run `python scripts/run_tool.py doctor` to diagnose
2. Follow the fix instructions in the output
3. Common causes: expired wallet session, missing AWP registration

If you see `missing_auth_headers` or `signer_mismatch`, it means something
bypassed `run_tool.py`. Stop and use the commands listed above instead.

**Never attempt to fix auth by making HTTP calls, adding headers, or reading
signing code.** The `doctor` command handles all auth diagnostics.

## Intent Routing

| User says | Command to run |
|-----------|---------------|
| "start" / "go online" | `agent-start` or `validator-start` (depends on role) |
| "status" / "how am I doing" | `agent-control status` or `validator-control status` |
| "stop" | `agent-control stop` or `validator-control stop` |
| "pause" | `agent-control pause` (miner only) |
| "resume" | `agent-control resume` (miner only) |
| "datasets" / "what can I mine" | `list-datasets` |
| "diagnose" / "doctor" / "fix" | `doctor` or `validator-doctor` |
| "help" | Show the command table from "How This Skill Works" |
| "switch role" | Re-show Welcome Screen |
| "check connectivity" / "heartbeat" | `doctor` (never direct HTTP) |
| "401 error" / "auth error" | `doctor` (see Error Recovery) |

## Sub-Agent Guidelines

- **One mining worker per session** — do not spawn multiple concurrent miners
- Use `agent-control status` to poll progress
- Use `agent-control stop` to terminate
- All platform interaction goes through `run_tool.py` — this applies to sub-agents too

## Configuration

No environment variables needed. Everything is auto-detected.

Runtime overrides (optional, via `.env` or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM_BASE_URL` | `https://api.minework.net` | Platform API endpoint |
| `MINER_ID` | `mine-agent` | Miner identifier |
| `WORKER_MAX_PARALLEL` | `3` | Concurrent crawl workers |

For validator settings, see `docs/ENVIRONMENT.md`.

## Advanced

Read these docs only when needed for the specific topic:

- [Browser session & login](./docs/BROWSER_SESSION.md)
- [Internal commands & rules](./docs/INTERNAL_COMMANDS.md)
- [Agent guide](./docs/AGENT_GUIDE.md)
- [Environment](./docs/ENVIRONMENT.md)
- [Validator Protocol](./references/protocol-validator.md)
