---
name: mine
description: Agent-first mining skill for signed platform work, data crawling, structured extraction, LLM enrichment, schema(1) field alignment, and submission export through awp-wallet.
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
---

# Mine

## First Load

On first invocation, output this welcome before anything else:

```
Welcome to Mine — the autonomous data mining service

Mine crawls public data, structures it, and submits to AWP for $aMine rewards.
Fully autonomous — no human in the loop.

  start working  — begin mining
  check status   — credit score, epoch, earnings
  list datasets  — see available datasets
```

Then run `python scripts/run_tool.py agent-status` and show the result.

## Output Rules

All commands return JSON with `user_message`, `user_actions`, and `_internal`.
- Show `user_message` formatted with ✓/✗/! indicators — never dump raw JSON
- `_internal` is for agent execution only — **never show to user**
- On errors, show the fix command from `_internal`, not the raw error
- See `mine-ux-preview.html` for full visual reference of expected UX

## Quick Start

1. **Install** — run the bootstrap script in the `mine/` directory:
   - Windows: `.\scripts\bootstrap.cmd`
   - Unix: `./scripts/bootstrap.sh`
2. **Check readiness**: `python scripts/run_tool.py agent-status`
3. **Start mining** — use `sessions_spawn` to run mining in a background sub-agent:

```
sessions_spawn({
  task: "cd mine && python scripts/run_tool.py agent-start",
  label: "mine-worker",
  runTimeoutSeconds: 3600
})
```

This keeps the user conversation free. The sub-agent announces results back when done.

If `sessions_spawn` is unavailable, fall back to direct execution:
`python scripts/run_tool.py agent-start`

That is the entire setup. Do NOT read source code or clone external repos.

## Actions

### Mining

| Action | Command |
| ------ | ------- |
| Initialize | `python scripts/run_tool.py init` |
| Check readiness | `python scripts/run_tool.py agent-status` |
| Start mining | `python scripts/run_tool.py agent-start` |
| Check status | `python scripts/run_tool.py agent-control status` |
| Pause | `python scripts/run_tool.py agent-control pause` |
| Resume | `python scripts/run_tool.py agent-control resume` |
| Stop | `python scripts/run_tool.py agent-control stop` |
| Diagnose | `python scripts/run_tool.py doctor` |
| List datasets | `python scripts/run_tool.py list-datasets` |
| Crawl URL | `python -m crawler run --input <input.jsonl> --output <output_dir>` |
| Enrich records | `python -m crawler enrich --input <records.jsonl> --output <output_dir>` |
| Validate schema | `python scripts/schema_tools.py validate` |
| Export submissions | `python scripts/run_tool.py export-core-submissions <input> <output> <datasetId>` |

### Validator

| Action | Command |
| ------ | ------- |
| Initialize validator | `python scripts/run_tool.py validator-init` |
| Start validating | `python scripts/run_tool.py validator-start` |
| Check validator status | `python scripts/run_tool.py validator-control status` |
| Pause validator | `python scripts/run_tool.py validator-control pause` |
| Resume validator | `python scripts/run_tool.py validator-control resume` |
| Stop validator | `python scripts/run_tool.py validator-control stop` |
| Diagnose validator | `python scripts/run_tool.py validator-doctor` |

## Flow

### Mining Flow

1. Run **Check readiness** first
2. If not initialized → run **Initialize** → then check again
3. When ready → **Start mining** via `sessions_spawn` (preferred) or direct command
4. Control with **Check status** / **Pause** / **Resume** / **Stop**
5. Sub-agent announces progress back to the main conversation automatically

### Validator Flow

1. Run **Initialize validator** — auto-configures wallet, applies as validator
2. Run **Start validating** — connects via WebSocket, receives evaluation tasks
3. Monitor with **Check validator status** / **Pause** / **Resume** / **Stop**

The validator connects to the platform via WebSocket, receives evaluation tasks, scores miner submissions using 4-dimension LLM analysis (field completeness, value accuracy, type correctness, information sufficiency), and reports scores back.

Use `/subagents list` to see active mining sub-agents, `/subagents kill <id>` to stop one.

## Sub-Agent Pattern

| Scenario | Method |
| -------- | ------ |
| OpenClaw host | `sessions_spawn` — non-blocking, result announced back |
| Cursor / other hosts | `python scripts/run_tool.py agent-start` — forks background process via `subprocess.Popen` |

Sub-agent guidelines:
- **One mining worker per session** — do not spawn multiple concurrent miners
- Use `runTimeoutSeconds` to set a hard cap (recommended: 3600)
- Use `agent-control status` to poll progress from the main conversation
- Use `agent-control stop` or `/subagents kill <id>` to terminate

## Validator Environment (defaults work)

```bash
VALIDATOR_ID=validator-agent            # default
EVAL_LLM_MODEL=                         # LLM model for evaluation (auto-detected)
EVAL_LLM_TEMPERATURE=0.0               # evaluation temperature
EVAL_TIMEOUT_SECONDS=480                # single evaluation timeout (8 min)
```

Shared settings (`PLATFORM_BASE_URL`, `AWP_WALLET_BIN`, EIP-712 config) are inherited from the mining configuration.

## Reference

Read these docs only when needed for the specific topic:

- [Browser session & login](./docs/BROWSER_SESSION.md) — cookie import, auto-login, PrepareBrowserSession
- [Internal commands & rules](./docs/INTERNAL_COMMANDS.md) — full command mapping, readiness states, behavior rules
- [Agent guide](./docs/AGENT_GUIDE.md) — detailed operational guide
- [Environment](./docs/ENVIRONMENT.md) — environment variables and config
- [OpenClaw integration](./docs/OPENCLAW_HOST_INTEGRATION.md) — host contract for OpenClaw
- [Validator API](./references/api-validator.md) — validator API endpoints
- [Validator Protocol](./references/protocol-validator.md) — WebSocket protocol and evaluation flow
