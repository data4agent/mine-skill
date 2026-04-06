# Transcript: Debugging 401 Unauthorized Errors When Mining

## User Message
"I'm getting 401 unauthorized errors when mining, debug and fix it"

---

## Agent Actions

### Step 1: Identify the role context

The user mentions "mining", so the role is **Miner**. The user is reporting an error, which maps to a **Diagnose** intent per the skill's "Decide What To Do" table. Additionally, the skill has a dedicated **Error Recovery** section for 401 errors.

I would say to the user:

> Got it — you're hitting 401 unauthorized errors while mining. Let me run the doctor to diagnose the issue.

### Step 2: Run the doctor (per Error Recovery section)

The SKILL.md "Error Recovery" section states:

> If a `run_tool.py` command returns a `401` or authentication error:
> 1. Run `python scripts/run_tool.py doctor` to diagnose

Command:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

I would inspect the JSON output, extract `user_message` and `_internal` fields. Per the Output Rules, I would show `user_message` formatted with indicators — never dump raw JSON. The `_internal` field is for agent execution only — never shown to user.

### Step 3: Interpret doctor output and follow fix instructions

The doctor output will contain fix instructions. Per the skill:

> 2. The doctor output contains fix instructions — follow them
> 3. Common causes: expired wallet session, missing AWP registration

**Scenario A: Expired wallet session**

If the doctor output indicates an expired wallet session, the `_internal` field would contain a fix command. I would run whatever fix command is indicated. For example:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

This checks readiness and may trigger wallet session renewal. Based on recent commit history (`refactor: update wallet session duration and renewal threshold` and `feat: implement auto-renewal for expired wallet sessions`), the fix likely involves re-establishing the wallet session.

I would say to the user:

> ! Your wallet session has expired. Refreshing it now...

Then run whatever remediation command the doctor's `_internal` field specifies — for example:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

**Scenario B: Missing AWP registration**

If the doctor says the wallet is not registered on AWP, I would follow the fix instructions from `_internal`. This might involve running a registration command:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

And following whatever registration steps the output prescribes.

**Key constraint (from CRITICAL RULES):** I would **NEVER** attempt to fix auth by making direct HTTP calls, adding headers, using curl/fetch/httpx/requests, or constructing JSON-RPC payloads. All interaction goes through `run_tool.py`.

### Step 4: Verify the fix

After following the doctor's fix instructions, I would re-run the doctor to confirm the issue is resolved:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

Then check agent status to confirm readiness:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status
```

I would present the results to the user using the formatted output style:

> ```
> [1/3] wallet       0x1234...5678 ✓
> [2/3] platform     connected ✓
> [3/3] auth         valid ✓
> ```
>
> The 401 errors were caused by an expired wallet session. It's been refreshed and you're good to go. Say "start" to resume mining, or "status" to check your current state.

### Step 5: Restart mining if appropriate

If the user wants to resume, I would start the worker again:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start
```

---

## What I Would NOT Do

Per the CRITICAL RULES in the skill:

1. **Would NOT** make direct HTTP requests to debug or fix the auth (no curl, no requests, no fetch).
2. **Would NOT** construct JSON-RPC payloads or manually add authentication headers.
3. **Would NOT** print or display `AWP_WALLET_TOKEN`, `VALIDATOR_PRIVATE_KEY`, private keys, mnemonics, or `.env` contents. To check if a variable is set, I would only use: `[ -n "$AWP_WALLET_TOKEN" ] && echo "set"`.
4. **Would NOT** show raw JSON output to the user. Only the `user_message` field gets shown, formatted with indicators.
5. **Would NOT** show `_internal` data to the user — it is for agent execution only.

---

## Summary of Exact Command Sequence

1. `cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor`
2. Follow the fix command(s) from the doctor's `_internal` output (e.g., session refresh, re-registration)
3. `cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor` (verify fix)
4. `cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-status` (confirm readiness)
5. `cd /home/ubuntu/code/mine && python scripts/run_tool.py agent-start` (resume mining, if user requests)
