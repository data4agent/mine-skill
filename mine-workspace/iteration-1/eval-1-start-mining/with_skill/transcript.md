# Transcript: "start mining"

## User says: "start mining"

---

### Step 1: Show Welcome Screen

Since no worker is currently running, I display the welcome screen and ask the user to choose a role:

```text
⛏️  mine · autonomous data mining

crawl data. earn rewards. fully autonomous.

── choose your role ─────────────
1. Miner      → crawl public data, earn $aMine
2. Validator  → evaluate submissions, earn $aMine
──────────────────────────────────

which role? (1 or 2)
```

### Step 2: Interpret User Intent

The user said "start mining". Per the skill: *If the user says "mine", "miner", "start mining", "1" -> proceed to Start Mining.* The intent is clear -- the user wants to be a **Miner** and start mining. No need to wait for a separate reply; the role is already indicated by the task.

Proceeding to **Start Mining**.

---

### Step 3: Check Readiness (Start Mining - Step 1)

Run the readiness check:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

**What I do with the output:**

- The command returns JSON with `user_message`, `user_actions`, and `_internal`.
- I show the `user_message` to the user, formatted with check/cross indicators -- never raw JSON.
- If not ready, the output contains fix instructions. I follow them before proceeding.
- If ready, I proceed to Step 4.

**If not ready (example):** The output might say the wallet session is expired. I would follow the fix instructions from the output (e.g., run `python scripts/run_tool.py doctor` to diagnose and then follow the remediation steps). I would NOT make direct HTTP calls to fix auth.

**Assuming readiness check passes**, I proceed.

---

### Step 4: Start Worker (Start Mining - Step 2)

**Preferred approach** -- spawn a non-blocking sub-agent:

```javascript
sessions_spawn({
  task: "cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start",
  label: "mine-worker",
  runTimeoutSeconds: 3600
})
```

**Fallback** -- if `sessions_spawn` is not available, run directly:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start
```

**What I do with the output:**

- If the output indicates a dataset selection is required and lists available datasets, I re-run with the chosen dataset ID:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start <datasetId>
```

- If the worker starts successfully, I proceed to Step 5.

---

### Step 5: Confirm Running (Start Mining - Step 3)

I display the confirmation to the user, using actual values from the command output:

```text
[1/3] wallet       0x1234...5678 ✓
[2/3] platform     connected ✓
[3/3] worker       started (session: abc12) ✓

mining. say "mine status" to check progress.
```

---

## Summary of All Commands (in order)

1. `cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status`
2. `cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start` (or with `<datasetId>` if dataset selection is required)

## Key Rules Followed

- All platform interaction goes through `python scripts/run_tool.py <command>` -- no direct HTTP requests.
- No JSON-RPC payloads constructed manually.
- No secrets printed or displayed (wallet tokens, private keys, env contents).
- Output from commands is shown via `user_message` with indicators, never as raw JSON.
- `_internal` fields are never shown to the user.
- Only one mining worker spawned per session.
