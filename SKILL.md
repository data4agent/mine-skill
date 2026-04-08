---
name: mine
description: >
  Start, stop, and manage autonomous data mining and validation workers that
  earn $aMine token rewards on the ocDATA platform. Use this skill when the user
  wants to: start or stop mining, check mining/validator status, select datasets,
  diagnose mining errors (401, auth, connectivity), view submission scores or
  epoch rewards, become a validator, or do anything related to aMine, ocDATA,
  data crawling for rewards, or autonomous data collection. Trigger even for
  casual phrases like "go online", "start earning", "check my submissions",
  "how many submissions do I have", or "why is my miner not working". NOT for
  AWP wallet transfers, RootNet staking, or general server monitoring.
version: 0.9.11
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
  emoji: "⛏️"
  homepage: https://github.com/data4agent/mine-skill
---

# Mine

Autonomous data mining & validation on AWP. Agents earn $aMine rewards by
crawling public data and validating others' submissions.

## Agent-First Design

This skill is designed for **agent execution** — all commands must be run by you
(the agent) in the terminal. **Never show command text to the user.** Instead,
execute commands yourself and present the results as natural-language summaries.

Every command outputs JSON with:
- `user_message` — show this to the user (natural language)
- `user_actions` — action options to present (natural language labels)
- `_internal` — for your eyes only, contains `action_map` mapping labels to commands

**Workflow**: Run command → parse JSON → show `user_message` to user → if user
picks an action from `user_actions`, look up the command in `_internal.action_map`
and execute it.

## Rules

1. **Execute commands yourself.** Never display `python scripts/run_tool.py ...` to
   the user. Run the command, read the JSON output, and speak to the user in natural
   language based on `user_message`.

2. **Only use `run_tool.py` commands.** Never make HTTP requests (curl, fetch, httpx,
   requests, WebFetch) to the platform. Never construct JSON-RPC payloads. The platform
   requires cryptographic signatures — raw HTTP calls always fail with 401.

3. **Never expose secrets.** Do not print `AWP_WALLET_TOKEN`, `VALIDATOR_PRIVATE_KEY`,
   private keys, mnemonics, or `.env` contents. To check if set: `[ -n "$VAR" ] && echo "set"`.

4. **Use `_internal` for next steps.** When the JSON output contains `_internal.action_map`,
   use it to determine which command to run next. Never show `_internal` content to the user.

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

## Mining Architecture

### Task Sources

Each worker iteration (`run_iteration`) collects tasks from three independent sources:

| Source | Class | Where tasks come from | Filtered by `selected_dataset_ids` |
|--------|-------|----------------------|-----------------------------------|
| **Backend Claim** | `BackendClaimSource` | Platform claim API (repeat-crawl / refresh) | No |
| **Dataset Discovery** | `DatasetDiscoverySource` | Locally generated seed URLs from dataset `source_domains` | Yes |
| **Resume** | `ResumeQueueSource` | Backlog / auth_pending from previously failed or paused tasks | No |

All three sources are **collected in parallel, merged, and deduplicated**. Up to `max_parallel` items enter the current iteration.

> **"no task available" means none of the three sources produced an executable task** — most
> commonly because Backend Claim returned nothing and Discovery is in cooldown. This does
> **not** mean your miner is banned.

### Two-Phase Discovery Crawl

Dataset Discovery operates in **two phases**:

1. **discover-crawl** (discovery phase): crawl seed pages (e.g. arXiv listing pages, Amazon
   bestseller pages), extract links, and enqueue `discovery_followup` tasks into the backlog.
2. **run** (fetch phase): followup tasks are executed in subsequent iterations with the `run`
   command, fetching structured data and submitting to the platform.

Wikipedia is special: it calls the MediaWiki Random API for random article URLs directly,
skipping the discover-crawl phase entirely.

### API Call Chain

```text
Discovery path:
  GET  /api/core/v1/datasets            <- fetch dataset list and source_domains
  GET  /api/core/v1/url/check           <- pre-flight dedup check
  (local crawler fetches target site)
  POST /api/core/v1/submissions         <- submit structured data
  POST /api/mining/v1/pow-challenges/…  <- answer PoW challenge (probabilistic)

Backend Claim path:
  POST /api/mining/v1/repeat-crawl-tasks/claim  <- claim task from platform
  (local crawler fetches target site)
  POST /api/mining/v1/repeat-crawl-tasks/{id}/report  <- report result
  POST /api/core/v1/submissions                       <- submit structured data
```

Both paths ultimately submit via **`POST /api/core/v1/submissions`**.

### Dataset Selection

- Platform returns only 1 dataset — auto-selected.
- Platform returns multiple datasets with none selected — enters `selection_required`; user must choose before starting.
- `selected_dataset_ids` only filters **Discovery / followup** source tasks; Backend Claim tasks are not affected.

### Credit Tier & Limits

| Tier | `credit_score` | Backend Claim | Discovery Submissions |
|------|---------------|---------------|----------------------|
| novice | 0 | Platform may not assign tasks | Normal submission, but epoch settlement gate applies |
| higher | > 0 | Normal assignment | Normal |

Epoch settlement gate: `task_count >= 80` and `avg_score >= 60` (see protocol v2.0).
A novice miner's primary path is through **Discovery self-crawling** to accumulate submissions and scores.

## Miner Workflow

### Start Mining

Step 1 — Check readiness (run in terminal, do not show command to user):

```bash
cd {baseDir} && python scripts/run_tool.py agent-status
```

Parse the JSON output. If `ready` is false, execute the command from
`_internal.action_map` to fix the issue. Tell the user what's happening
in plain language.

Step 2 — Start worker (run in terminal):

```bash
cd {baseDir} && python scripts/run_tool.py agent-start
```

If dataset selection is required (state = `selection_required`), present the
dataset names from `user_message` to the user. After they choose, re-run with:

```bash
cd {baseDir} && python scripts/run_tool.py agent-start <datasetId>
```

Step 3 — Confirm to user using `user_message` from the JSON output. Example:

```text
[1/3] wallet       0x1234...5678  ok
[2/3] platform     connected  ok
[3/3] worker       started (session: abc12)  ok

mining. say "mine status" to check progress.
```

### Check Status

Run in terminal and show `user_message` to user:

```bash
cd {baseDir} && python scripts/run_tool.py agent-control status
```

### Stop / Pause / Resume

Run the appropriate command based on user intent:

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

## Debugging Background Workers

Background mining/validation workers write all output (including errors) to log files.
The `agent-control status` command automatically surfaces recent errors from the log.
If you need more detail, the log path is in the `_internal.log_path` field of the status response:

```bash
cd {baseDir} && tail -50 output/agent-runs/<session_id>.log
```

Always check `agent-control status` first — it shows recent errors without needing to read the log directly.

## Error Recovery

If any command returns a `401` or authentication error:

1. Run `python scripts/run_tool.py doctor` to diagnose
2. Follow the fix instructions in the output
3. Common causes: expired wallet session, missing AWP registration

If the error is `address_not_registered` or `registration_required`:

1. The wallet needs to be registered on-chain before mining can start
2. Tell the user to **install and use the AWP Skill** to complete registration
3. If the AWP Skill is not installed, guide the user to install it first
4. After registration completes, retry `python scripts/run_tool.py agent-start`

**Do NOT** tell users to register on a website or manually call any registration API.
The AWP Skill handles the entire on-chain registration flow automatically.

If the validator returns `403`, `permission denied`, or `insufficient_stake`:

1. **Validator requires a minimum of 10,000 AWP staked on the Mine Worknet**
2. There are two ways to meet this requirement:
   - **Option A (agent stakes):** The agent stakes its own AWP and allocates
     the stake to the Mine Worknet. Use the AWP Skill to do this.
   - **Option B (user delegates):** The user stakes AWP themselves and
     delegates the stake to the agent on the Mine Worknet.
3. Staking is only a participation requirement — **rewards are NOT affected by
   who staked**. All mining/validation rewards go to the agent's designated
   reward address, same as miner rewards.
4. After staking completes, retry `python scripts/run_tool.py validator-start`

**Do NOT** suggest the user is "pending review" or needs manual approval when the
error is 403 — it means insufficient stake, not a review issue.

If you see `missing_auth_headers` or `signer_mismatch`, it means something
bypassed `run_tool.py`. Stop and use the commands listed above instead.

**Never attempt to fix auth by making HTTP calls, adding headers, or reading
signing code.** The `doctor` command handles all auth diagnostics.

## Intent Routing

| User says | Action to take |
|-----------|---------------|
| "start" / "go online" | Run `agent-start` or `validator-start` (depends on role) |
| "status" / "how am I doing" | Run `agent-control status` or `validator-control status` |
| "stop" | Run `agent-control stop` or `validator-control stop` |
| "pause" | Run `agent-control pause` (miner only) |
| "resume" | Run `agent-control resume` (miner only) |
| "datasets" / "what can I mine" | Run `list-datasets` |
| "diagnose" / "doctor" / "fix" | Run `doctor` or `validator-doctor` |
| "help" | Tell the user what actions are available in natural language |
| "switch role" | Re-show Welcome Screen |
| "check connectivity" / "heartbeat" | Run `doctor` (never direct HTTP) |
| "401 error" / "auth error" | Run `doctor` (see Error Recovery) |

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
