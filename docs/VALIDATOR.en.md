# Validator functionality

This document describes the validator feature in the current `mine` project: responsibilities, how to run it, CLI entry points, core modules, environment variables, and troubleshooting. It reflects **the current canonical code**; material from historical “extracted” directories has been folded into this doc and `references/`.

> Chinese version: [VALIDATOR.md](VALIDATOR.md)

## 1. Overview

The validator receives evaluation tasks from the platform, assesses the quality of structured data submitted by miners, and sends results back to the platform.

The current implementation has two main flows:

- **Runtime flow**: A background process starts the validator, connects over WebSocket, keeps heartbeats, receives tasks, and reports results
- **Evaluation flow**: Two-phase evaluation of each submission
  - Phase 1: Consistency check
  - Phase 2: Quality scoring

## 2. CLI entry points

All supported entry points live in `scripts/run_tool.py`:

```bash
python scripts/run_tool.py validator-status
python scripts/run_tool.py validator-start
python scripts/run_tool.py validator-control status
python scripts/run_tool.py validator-control stop
python scripts/run_tool.py validator-doctor
```

Notes:

- `validator-status`: Whether the validator is running
- `validator-start`: Start the background validator process
- `validator-control status`: Background process status
- `validator-control stop`: Stop the background process
- `validator-doctor`: Diagnose key configuration and runtime state

Internal command:

```bash
python scripts/run_tool.py run-validator-worker <session_id>
```

This is normally invoked by the background process manager; do not run it manually unless you know what you are doing.

## 3. Runtime flow

The main validator flow is:

1. Start the background process
2. Create `WalletSigner`, `PlatformClient`, `ValidatorWSClient`, `EvaluationEngine`
3. Connect WebSocket
4. Join the validator ready pool
5. Send heartbeats periodically
6. Receive `evaluation_task`
7. Send `ack_eval` first
8. Fetch task details and submission payload
9. Run two-phase evaluation
10. Report scores or write `validation-results`
11. Wait according to credit tier, then re-enter the ready pool

## 4. Evaluation logic

Core evaluation logic is in `scripts/evaluation_engine.py`.

### 4.1 Phase 1: Consistency check

Inputs:

- `cleaned_data`
- `structured_data`

Goals:

- Decide whether the miner’s structured output matches the cleaned source text
- If there is obvious fabrication, mismatch, or severe distortion, mark as `rejected`

Outputs:

- `consistent = false`
- `score = 0`
- `reason = <rejection reason>`

### 4.2 Phase 2: Quality scoring

Runs only if the consistency check passes.

Dimensions:

- Completeness
- Accuracy
- Type correctness
- Sufficiency of information

`EvaluationEngine` currently returns:

- `verdict`
- `consistent`
- `score`
- `reason`

## 5. Core modules

### `scripts/openclaw_llm.py`

Wraps OpenClaw CLI calls and extracts JSON from LLM text output.

### `scripts/evaluation_engine.py`

Implements two-phase evaluation and produces `EvaluationResult`.

### `scripts/ws_client.py`

Handles:

- WebSocket connection
- Receiving platform messages
- Sending `ack_eval`
- Reconnecting after disconnects

### `scripts/validator_runtime.py`

Main validator runtime, orchestrating:

- WebSocket main loop
- Heartbeat loop
- Fetching task details
- Calling the evaluation engine
- Calling platform APIs to report results

### `scripts/validator_worker.py`

Background process manager:

- Start validator background process
- Stop background process
- Query background process status

### `scripts/worker_state.py`

Persists validator session, background process metadata, and state files.

### `lib/platform_client.py`

Validator-related APIs, including:

- `get_me`
- `submit_validator_application`
- `get_my_validator_application`
- `join_ready_pool`
- `leave_ready_pool`
- `get_evaluation_task`
- `report_evaluation`
- `create_validation_result`
- `list_validation_results`
- `get_validation_result`

## 6. Environment variables

Main validator-related variables:

| Variable | Default | Description |
| --- | --- | --- |
| `PLATFORM_BASE_URL` | `https://api.minework.net` | Platform API base URL |
| `VALIDATOR_ID` | `validator-agent` | Validator identifier |
| `VALIDATOR_OUTPUT_ROOT` | `output/validator-runs` | Validator output directory |
| `EVAL_TIMEOUT_SECONDS` | `120` | Per-evaluation timeout (seconds) |
| `AWP_WALLET_BIN` | `awp-wallet` | Wallet executable |

Credit-tier wait intervals in the current code:

| credit tier | Interval (seconds) |
| --- | --- |
| `novice` | `120` |
| `good` | `30` |
| `excellent` | `10` |

WebSocket URL is derived in `scripts/common.py` by `resolve_ws_url()`:

- `http://...` → `ws://.../api/mining/v1/ws`
- `https://...` → `wss://.../api/mining/v1/ws`

## 7. State and output directories

Defaults:

- Output root: `output/validator-runs`
- State directory: `output/validator-runs/_worker_state`

Typical state files:

- Session state
- Background PID / `session_id`
- Runtime snapshots

## 8. Relationship to the miner

The validator reuses miner infrastructure:

- Same `run_tool.py`
- Same `common.py`
- Same `PlatformClient`
- Same wallet signing stack

Responsibilities differ:

- **Miner**: crawl, extract, submit data
- **Validator**: review miner submissions

## 9. Reference docs

Protocol and API details:

- `references/api-validator.md`
- `references/protocol-validator.md`

Integration plan and design:

- `docs/superpowers/plans/2026-04-03-validator-integration.zh.md`
- `docs/superpowers/plans/2026-04-03-validator-integration.md`
- `docs/superpowers/specs/2026-04-03-validator-integration-design.md`

## 10. Troubleshooting order

Suggested order:

1. `python scripts/run_tool.py validator-status`
2. `python scripts/run_tool.py validator-doctor`
3. Verify wallet session is valid
4. Check `PLATFORM_BASE_URL` and `resolve_ws_url()` output
5. Check whether the platform allows the current address as a validator
6. Check permissions and error codes in `references/api-validator.md`

## 11. Historical extracted directories

The repo previously contained two extracted directories:

- `validator-skill-extracted`
- `validator-skill-1-extracted`

Useful content from them now lives in:

- Code: `scripts/*`, `lib/platform_client.py`
- Docs: `docs/VALIDATOR.md` (and this English file)
- References: `references/api-validator.md`, `references/protocol-validator.md`

Treat these canonical locations as the source of truth; do not rely on the old extracted trees.
