# Internal Commands & Rules

Detailed reference for agent internals. See [SKILL.md](../SKILL.md) for the quick-start version.

## Full Command Mapping

| Action | Internal command |
| ------ | --------------- |
| Initialize | `python scripts/run_tool.py init` |
| CheckReadiness | `python scripts/run_tool.py agent-status` |
| StartMining | `python scripts/run_tool.py agent-start` |
| CheckStatus | `python scripts/run_tool.py agent-control status` |
| PauseMining | `python scripts/run_tool.py agent-control pause` |
| ResumeMining | `python scripts/run_tool.py agent-control resume` |
| StopMining | `python scripts/run_tool.py agent-control stop` |
| Diagnose | `python scripts/run_tool.py doctor` |
| PrepareBrowserSession | `python scripts/run_tool.py browser-session <platform>` then poll `browser-session-status <platform>` |
| ListDatasets | `python scripts/run_tool.py list-datasets` |
| CrawlURL | `python -m crawler run --input <input.jsonl> --output <output_dir>` (add `--auto-login` for auth-gated platforms) |
| EnrichRecords | `python -m crawler enrich --input <records.jsonl> --output <output_dir> --model-config <config.json>` or `python -m crawler fill-enrichment --records <records.jsonl> --responses <responses.json>` |
| ValidateSchema | `python scripts/schema_tools.py validate` |
| ExportSubmissions | `python scripts/run_tool.py export-core-submissions <input> <output> <datasetId>` or `python -m crawler export-submissions --input <records.jsonl> --output <out.json> --dataset-id <id>` |

Lower-level entry points (rarely needed directly):

- `process-task-file` — process a single task JSON (used by StartMining internally)
- `run-worker` — run one mining iteration
- `agent-run` — agent-driven single run
- `first-load` — initial platform data load

## Readiness States

`CheckReadiness` and `Diagnose` share these semantics:

| State | can_diagnose | can_start | can_mine | Meaning |
| ----- | ------------ | --------- | -------- | ------- |
| `ready` | true | true | true | Fully usable |
| `registration_required` | true | true | false | Can start; registration runs on start |
| `auth_required` | true | false | false | Wallet session missing or expired |
| `agent_not_initialized` | false | false | false | awp-wallet or runtime not ready |
| `degraded` | true | true | false | Partially usable |

Common warnings:

- `wallet session expired`
- `wallet session expires in Ns`
- `using fallback signature config`

## Behavior Rules

1. Prefer the background session path; do not call low-level `run-worker` first
2. Prefer returning "current state + next action" instead of a list of commands
3. When runtime returns `selection_required`, interpret it as "user must choose a dataset"; do not invent a choice
4. When runtime returns `auth_required` or `401`, prefer `Diagnose` or `Initialize`
5. `StopMining` has side effects; confirm if the user's intent is unclear
6. Browser or LinkedIn auto-login applies only in those scenarios — not a global prerequisite
7. For browser login, cookies, or storage state export, prefer `PrepareBrowserSession`
8. `CrawlURL` runs fetch → extract → enrich → schema(1) flatten as a single pipeline; do not run stages manually unless debugging
9. Enrichment groups may return `pending_agent` when no LLM is configured; use `EnrichRecords` with a model config to complete them
10. `ValidateSchema` is a dry check with no side effects; safe to run anytime

## Data Pipeline Flow

When the user wants to crawl a specific URL or process a task file:

1. Run `CrawlURL` with the target URL or task file
2. Pipeline automatically: fetch → extract → enrich → output records aligned to schema(1)
3. If enrichment groups remain `pending_agent` (no LLM configured), run `EnrichRecords` with model config
4. Run `ValidateSchema` to verify field coverage against schema(1) contracts
5. Run `ExportSubmissions` to convert records into platform submission format

The data pipeline does not require `StartMining`; it runs independently.

## Environment

Defaults work out of the box:

```bash
PLATFORM_BASE_URL=https://api.minework.net
MINER_ID=mine-agent                      # default
AWP_WALLET_BIN=awp-wallet               # auto-detected
```

EIP-712 signature config is auto-fetched from platform; falls back to built-in defaults if unreachable.
