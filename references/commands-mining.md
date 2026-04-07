# Mining Commands Reference

All public runtime commands go through `scripts/run_tool.py`.

## Setup and readiness

Host integrations should prefer:

- `agent-status`
- `agent-start`
- `agent-control`

The remaining commands in this file are still valid, but many of them are advanced or local-operator surfaces rather than the primary OpenClaw contract.

### `setup`

```bash
python scripts/run_tool.py setup
```

Runs the JSON-oriented setup wizard in `scripts/mine_setup.py`.

### `setup-status`

```bash
python scripts/run_tool.py setup-status
```

Shows setup progress from the setup wizard state file.

### `setup-fix`

```bash
python scripts/run_tool.py setup-fix
```

Attempts automatic setup remediation.

### `doctor`

```bash
python scripts/run_tool.py doctor
```

Returns structured readiness checks and concrete fix commands.

### `check-env`

```bash
python scripts/run_tool.py check-env
```

Prints the current environment-variable view used by the helper layer.

### `agent-status`

```bash
python scripts/run_tool.py agent-status
```

Returns a compact JSON readiness summary for host integrations.

### `agent-start`

```bash
python scripts/run_tool.py agent-start
python scripts/run_tool.py agent-start datasetA,datasetB
```

Starts mining through the host-facing background session flow. If dataset selection is required, returns a structured prompt telling the host how to retry with dataset ids.

### `agent-control`

```bash
python scripts/run_tool.py agent-control status
python scripts/run_tool.py agent-control pause
python scripts/run_tool.py agent-control resume
python scripts/run_tool.py agent-control stop
```

Queries or controls the current background mining session.

### `browser-session`

```bash
python scripts/run_tool.py browser-session <platform>
python scripts/run_tool.py browser-session <platform> <outputPath>
```

Prepares browser auth state through the runtime auto-browser bridge. The command reuses an existing session if possible; otherwise it launches the temporary browser stack, exposes a temporary Cloudflare handoff URL when needed, exports the final session, and stops the browser stack after success.

### `browser-session-status`

```bash
python scripts/run_tool.py browser-session-status <platform>
```

Polls the current browser-session job. Use this after `browser-session` returns `awaiting_user_action`.

Stable top-level fields for host integrations:

- `status`
- `platform`
- `public_url`
- `login_url`
- `session_path`
- `waiter_pid`
- `waiter_running`
- `cleanup_performed`
- `error`
- `retryable`
- `status_command`

### `diagnose`

```bash
python scripts/run_tool.py diagnose
```

Runs the deeper diagnosis flow, including connectivity and heartbeat checks.

## Guided UX commands

### `first-load`

```bash
python scripts/run_tool.py first-load
```

Renders the welcome and dependency-check experience.

### `check-again`

```bash
python scripts/run_tool.py check-again
```

Alias for `first-load`.

### `start-working`

```bash
python scripts/run_tool.py start-working
python scripts/run_tool.py start-working datasetA,datasetB
```

Prepares a mining session, performs heartbeat, loads datasets, and may ask for dataset selection.

### `check-status`

```bash
python scripts/run_tool.py check-status
```

Human-readable session and epoch summary.

### `status-json`

```bash
python scripts/run_tool.py status-json
```

Machine-readable session status.

### `list-datasets`

```bash
python scripts/run_tool.py list-datasets
```

Lists currently available datasets from the platform.

## Worker loop and task execution

### `run-worker`

```bash
python scripts/run_tool.py run-worker [intervalSeconds] [maxIterations]
```

Examples:

```bash
python scripts/run_tool.py run-worker 60 1
python scripts/run_tool.py run-worker 60 0
```

- default interval: `60`
- default iterations: `1`
- `0` means keep running until stopped

### `run-once`

```bash
python scripts/run_tool.py run-once
```

Runs one worker cycle with the fully initialized worker object.

### `run-loop`

```bash
python scripts/run_tool.py run-loop [intervalSeconds] [maxIterations]
```

Low-level repeated loop runner. Prefer `run-worker` unless you explicitly need this surface.

### `heartbeat`

```bash
python scripts/run_tool.py heartbeat
```

Sends a single heartbeat.

### `process-task-file`

```bash
python scripts/run_tool.py process-task-file <taskType> <taskJsonPath>
```

Processes a local task payload.

### `export-core-submissions`

```bash
python scripts/run_tool.py export-core-submissions <inputPath> <outputPath> <datasetId>
```

Transforms crawler records into submission payloads.

### `agent-run`

```bash
python scripts/run_tool.py agent-run [maxIterations]
```

Agent-oriented JSON event stream wrapper around a simplified loop.

## Session control

### `pause`

```bash
python scripts/run_tool.py pause
```

Pause after the current batch is finished.

### `resume`

```bash
python scripts/run_tool.py resume
```

Resume a paused session.

### `stop`

```bash
python scripts/run_tool.py stop
```

Stop after the current batch and print a session summary.

## Intent router helpers

### `route-intent`

```bash
python scripts/run_tool.py route-intent "<user text>"
```

Routes natural-language input to a runtime action.

### `classify-intent`

```bash
python scripts/run_tool.py classify-intent "<user text>"
```

Returns structured intent classification only.

### `intent-help`

```bash
python scripts/run_tool.py intent-help
```

Prints the supported natural-language command set.
