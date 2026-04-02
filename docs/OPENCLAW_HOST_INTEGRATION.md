# OpenClaw Host Integration

This document defines the recommended Mine host contract for OpenClaw and similar chat-first agent hosts.

## Canonical commands

```bash
python scripts/run_tool.py agent-status
python scripts/run_tool.py agent-start
python scripts/run_tool.py agent-control status
python scripts/run_tool.py agent-control pause
python scripts/run_tool.py agent-control resume
python scripts/run_tool.py agent-control stop
```

## Expected host flow

1. Install the skill repository and run bootstrap.
2. Call `agent-status`.
3. If `ready=false`, execute `next_command`.
4. If `ready=true`, call `agent-start`.
5. Keep the conversation interactive while mining continues in the background.
6. Use `agent-control status|pause|resume|stop` for follow-up actions.

## Alias mapping

Slash aliases are optional presentation affordances and should map to the canonical commands:

```text
/mine-start  -> python scripts/run_tool.py agent-start
/mine-status -> python scripts/run_tool.py agent-control status
/mine-pause  -> python scripts/run_tool.py agent-control pause
/mine-resume -> python scripts/run_tool.py agent-control resume
/mine-stop   -> python scripts/run_tool.py agent-control stop
```

## Output contract

Host-facing commands should prefer compact JSON with:

- `state`
- `message`
- `next_action`
- `next_command`
- `ready`
- `actions`
- `background_session` when relevant

Human-readable views such as `first-load` and `check-status` are still useful for operator-facing surfaces, but they are not the primary integration contract.
