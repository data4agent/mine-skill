# Transcript: "start mining" without skill file

## Context

The user says "start mining" in the project at `/home/ubuntu/code/mine`. I have no skill file loaded, so I must explore the project to understand how it works before taking action.

---

## Step 1: Explore the project structure

I would start by examining what files and directories exist to understand the project.

```bash
ls /home/ubuntu/code/mine/
```

This reveals: `README.md`, `SKILL.md`, `scripts/`, `crawler/`, `lib/`, `docs/`, `references/`, etc.

## Step 2: Read the README for instructions

```bash
# I would use the Read tool to read:
/home/ubuntu/code/mine/README.md
```

From the README I learn:
- The project is "Autonomous data mining & validation on AWP"
- Commands are run via `python scripts/run_tool.py <command>`
- Key commands: `agent-status`, `agent-start`, `doctor`, etc.
- The platform API is at `https://api.minework.net`

## Step 3: Check if there is a SKILL.md or other operational docs

```bash
# I would use the Read tool to read:
/home/ubuntu/code/mine/SKILL.md
```

From SKILL.md I learn critical rules:
- **NEVER make direct HTTP requests to the platform API** -- all interaction must go through `python scripts/run_tool.py <command>`
- Never print secrets or private keys
- There is a Welcome Screen that should be shown first, asking the user to choose Miner vs Validator role
- The start mining flow is: (1) agent-status, (2) agent-start, (3) confirm running

**However, as an LLM without the skill file loaded, I would likely NOT read SKILL.md on my own.** I would probably go straight to trying to figure out how to start mining by reading the README and scripts. The SKILL.md is a skill contract designed for the Claude Code skill system -- without that system loading it, I might or might not discover it organically.

## Step 4: Attempt to understand the mining start process

I would read the main entry point script:

```bash
# I would use the Read tool to read:
/home/ubuntu/code/mine/scripts/run_tool.py
```

And possibly:

```bash
# I would use the Read tool to read:
/home/ubuntu/code/mine/scripts/agent_runtime.py
/home/ubuntu/code/mine/scripts/mine_gateway.py
```

## Step 5: Check readiness / run doctor

Based on the README, I would run:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

This checks wallet setup, platform connectivity, and dependencies. The output would tell me if things are ready or what needs fixing.

## Step 6: Check agent status

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

This tells me whether the agent is ready to mine, whether a wallet is configured, whether it's registered with the platform, etc.

## Step 7: Start the mining agent

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start
```

If the command requires a dataset selection, it would list available datasets. I would then re-run with a specific dataset:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start <datasetId>
```

## Step 8: Confirm to the user

I would tell the user something like:

> "The mining agent has been started. It is now crawling data and will submit results to the platform automatically. You can check status with `python scripts/run_tool.py agent-control status`."

---

## What I would NOT do (but should, per the skill file)

1. **Show the Welcome Screen** -- The SKILL.md specifies that I should display a role selection prompt (Miner vs Validator) before doing anything. Without the skill file guiding me, I would skip this and go straight to starting the miner since the user said "start mining."

2. **Format output with checkmarks and structured status** -- The SKILL.md defines specific output formatting (e.g., `[1/3] wallet 0x1234...5678 checkmark`). Without it, I would likely just relay the raw command output or summarize it loosely.

3. **Use `sessions_spawn` for non-blocking execution** -- The SKILL.md recommends spawning the worker as a background sub-agent so the main conversation stays responsive. Without that guidance, I would likely run `agent-start` directly in the foreground (blocking).

4. **Know to never make direct HTTP requests** -- Without reading SKILL.md, I might attempt to call `https://api.minework.net` directly using curl or Python requests to check status or register. This would fail because the platform requires EIP-712 cryptographic signatures that are only handled internally by `run_tool.py`.

5. **Parse `_internal` vs `user_message` in JSON output** -- The SKILL.md explains that command output is JSON with `user_message` (show to user) and `_internal` (agent-only). Without this knowledge, I might dump raw JSON to the user or miss important internal directives.

---

## Likely mistakes without the skill file

1. **Might try direct HTTP calls to `https://api.minework.net`** -- e.g.:
   ```bash
   curl https://api.minework.net/api/v1/status
   ```
   or attempt to use Python `requests`/`httpx` to interact with the API. These would fail with `missing_auth_headers` or `signer_mismatch`.

2. **Might skip the bootstrap step** -- If dependencies aren't installed, I might not know to run `./scripts/bootstrap.sh` first.

3. **Might not handle errors properly** -- Without knowing the error recovery flow (run `doctor`, follow its fix instructions), I might try to debug auth issues manually or attempt to set environment variables.

4. **Might expose secrets** -- Without the explicit warning, I might `cat .env` or print wallet tokens while debugging.

5. **Might start multiple workers** -- Without the "one mining worker per session" rule, I might accidentally spawn multiple concurrent miners.

---

## Summary

Without the skill file, I would eventually figure out the basic flow (run `run_tool.py agent-start`) by reading the README. However, I would miss critical operational details: the welcome screen flow, output formatting rules, the prohibition on direct HTTP calls, secret handling rules, background execution via sub-agents, and structured error recovery. The experience would be rougher, less polished, and more error-prone -- especially around authentication and API interaction where the skill file's warnings prevent a common class of failures.
