# Miner Session Protocol

Mine persists worker state so that mining can resume cleanly after restarts.

## State file location

Default session path:

```text
output/agent-runs/_worker_state/session.json
```

Override with:

```text
WORKER_STATE_ROOT
```

## Persisted state

Common persisted fields include:

| Field | Description |
|---|---|
| `mining_state` | Lifecycle state such as `idle`, `running`, `paused`, or `stopped` |
| `selected_dataset_ids` | Datasets chosen for the current session |
| `active_datasets` | Latest dataset list from the platform |
| `credit_score` / `credit_tier` | Latest miner credit information |
| `epoch_id`, `epoch_submitted`, `epoch_target` | Current epoch tracking |
| `last_heartbeat_at` | Latest successful heartbeat time |
| `token_expires_at` | Wallet session expiry tracking |
| `session_totals` | Aggregate submitted, processed, and failed counts |
| `last_summary` / `last_iteration` | Latest run summaries |
| `last_control_action` | Last pause, resume, or stop command |
| `stop_reason` | Why the session ended |

Transient in-memory fields such as active PoW challenges are not guaranteed to survive restart.

## Update triggers

| Event | Typical updates |
|---|---|
| Start session | dataset selection, lifecycle state, lock acquisition |
| Heartbeat success | credit data, epoch info, registration state |
| Token renewal | wallet token expiry timestamps |
| Batch completion | summaries, counters, last activity |
| Pause / resume / stop | lifecycle state and control metadata |

## Persistence behavior

- writes are designed to be crash-safe through temporary-file replacement
- worker state is periodically flushed during long-running sessions
- a lock file is used to prevent multiple active workers from clobbering the same state

## Operator implications

- `pause` and `stop` are cooperative, not instant-kill operations
- `resume` expects the previous state directory to still exist
- deleting `output/agent-runs/_worker_state` resets the persisted session model
