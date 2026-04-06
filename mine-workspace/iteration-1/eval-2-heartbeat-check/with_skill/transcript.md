# Transcript: "send a heartbeat to the platform to check if it's reachable"

## Step 1: Interpret the user's intent using the skill

The user wants to check if the platform is reachable. Looking at the SKILL.md decision table, this maps closest to **"diagnose" / "doctor"** since the user is asking about platform connectivity. However, no role has been chosen yet.

But wait -- the skill says: **"On first launch (no worker running), print the Welcome Screen and ask the user to choose a role."** The user has not chosen a role. However, the request is not about starting mining or validating -- it is a diagnostic/connectivity check. The skill's "Decide What To Do" section requires a role to be chosen first.

Since the user's request is essentially a diagnostic action (checking platform reachability), and the skill requires a role choice first, I would present the welcome screen. But the heartbeat command exists in `run_tool.py` and the `doctor` command checks platform reachability directly.

Given the user just wants a quick reachability check, and "doctor" is available under both roles, I will first ask for a role, then run the doctor command which includes platform reachability checks.

**However**, re-reading the skill more carefully: the `doctor` command is the closest match. Both miner and validator roles have a "diagnose" / "doctor" intent. The most direct approach per the skill rules is:

## What I would say to the user:

```
⛏️  mine · autonomous data mining

crawl data. earn rewards. fully autonomous.

── choose your role ─────────────
1. Miner      → crawl public data, earn $aMine
2. Validator  → evaluate submissions, earn $aMine
──────────────────────────────────

which role? (1 or 2)
```

## Step 2: User responds (assumed: "1" for Miner, since we need a role to proceed)

Assuming the user picks a role (e.g., "1" for Miner), I proceed.

## Step 3: Run readiness check per the skill

The skill says when the role is Miner, run the readiness check first:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

Then, for user intent "diagnose" / "doctor", the action is **Diagnose**.

## Step 4: Run the doctor command

The user's intent ("send a heartbeat to check if the platform is reachable") maps to the **Diagnose** action in the skill's intent table. The doctor command performs platform connectivity checks (hitting the `/health` endpoint) and an authenticated heartbeat test.

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

## Step 5: Present the results

The `doctor` command output includes:

- Section 3: **Platform Connectivity** -- hits `{PLATFORM_BASE_URL}/health` and reports whether the platform is reachable.
- Section 4: **Authentication Test (Heartbeat)** -- sends an authenticated heartbeat via `send_miner_heartbeat()` and reports success or failure.

Per the skill's **Output Rules**, I would format the JSON output using indicators, showing only the `user_message` field and never dumping raw JSON or exposing `_internal` data.

Example output I would show:

```
── diagnostics ──────────────────
platform    https://api.minework.net ✓ reachable
heartbeat   authenticated ✓
──────────────────────────────────

platform is reachable and responding to heartbeats.
```

Or, if the platform were unreachable:

```
── diagnostics ──────────────────
platform    https://api.minework.net ✗ cannot connect
──────────────────────────────────

! platform is not reachable. check your network connection
  and verify PLATFORM_BASE_URL is correct.
```

## Commands that would be run (in order):

1. `cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status`
2. `cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor`

## Key decisions:

- **Did NOT use `curl`, `httpx`, or any direct HTTP request** to check the platform. The skill's CRITICAL RULES forbid all direct HTTP calls to the platform API.
- **Did NOT run the `heartbeat` command directly**, because `heartbeat` is listed as a legacy/internal command in `run_tool.py` and requires a fully configured worker with authentication. The `doctor` command is the proper diagnostic tool that checks both basic reachability (unauthenticated `/health`) and authenticated heartbeat in a single pass.
- **Asked the user to choose a role first**, as required by the skill's Welcome Screen rule ("Do NOT skip this step").
- **Formatted output with indicators** (checkmarks/crosses) per the Output Rules, never showing raw JSON.
