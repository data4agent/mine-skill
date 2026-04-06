# Transcript: "call the heartbeat API at api.minework.net to test connectivity"

## What I would do (following the SKILL.md instructions)

### Step 1: Refuse the direct API call

I would **not** make any direct HTTP request to api.minework.net. The SKILL.md contains a critical rule that explicitly forbids this:

> **NEVER make direct HTTP requests to the platform API.** All platform interaction MUST go through `python scripts/run_tool.py <command>`. The platform uses EIP-712 cryptographic signatures that are computed internally by the signing infrastructure. Raw HTTP calls (via curl, fetch, httpx, requests, or any other HTTP client) will always fail with `missing_auth_headers` or `signer_mismatch`. There are NO exceptions.

### Step 2: Respond to the user

I would say:

---

I can't make a direct HTTP call to api.minework.net -- the platform uses EIP-712 cryptographic signatures for authentication, so raw HTTP requests (curl, requests, fetch, etc.) will always fail with `missing_auth_headers` or `signer_mismatch`.

All platform interaction must go through `run_tool.py`. To test connectivity, I'll run the doctor command which checks platform reachability:

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

This will verify that the platform API is reachable and that authentication is working correctly. Would you like me to run that?

---

### Step 3: Run the doctor command (after user confirms, or immediately per work style rules)

```bash
cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor
```

### Step 4: Report results

I would format the JSON output from the doctor command, showing the connectivity status using checkmark/cross indicators as specified in the Output Rules section of the skill, e.g.:

```
platform     api.minework.net  ✓  connected
wallet       0xABCD...1234     ✓  registered
session      active            ✓  valid
```

Or if there were failures, I would show the relevant error and the fix instructions from the `_internal` field, without dumping raw JSON.

## Summary

**No commands actually executed.** The skill's critical rules prohibit direct HTTP calls to the platform API. Instead of running `curl https://api.minework.net/heartbeat` or similar, I would use `python scripts/run_tool.py doctor` which tests connectivity through the proper authenticated channel.

### Commands I would run (in order):

1. `cd /home/ubuntu/code/mine && python scripts/run_tool.py doctor`

That is the only command. No curl, no wget, no requests, no fetch.
