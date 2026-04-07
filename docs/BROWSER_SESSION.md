# Browser Session Policy

When mining or crawl tasks need browser work, cookies, or storage state, follow this priority:

1. Reuse an existing session file first
2. If a reusable browser session exists locally, export it quietly without interrupting the user
3. If none, launch the browser and open the platform login page
4. After session is ready, export session and retry the original task automatically
5. Only escalate to the user for CAPTCHA, risk controls, SMS verification, or explicit human confirmation

## PrepareBrowserSession

Single high-level action for all browser/login needs. Do NOT expose low-level `vrd.py` / `agent-browser` command chains to the user.

**Commands:**

```bash
python scripts/run_tool.py browser-session <platform>
python scripts/run_tool.py browser-session-status <platform>
```

**Host behavior:**

1. Call `browser-session <platform>`
2. If response is `ready`, continue the task immediately
3. If response is `awaiting_user_action`, send `public_url` to the user
4. Poll `browser-session-status <platform>`
5. When status becomes `ready`, continue the task; the temporary browser stack should already be stopped

## Automation Boundaries

The agent should automatically:
- Launch browser, open login, wait for session, export session, import cookies, retry crawl

The agent should stop for:
- CAPTCHA, SMS, forced human confirmation, risk pages, or export timeout

The agent should NOT stop just because "a browser is needed" or "cookies are missing".

## Preferred Automation Stack

- Prefer `auto-browser` session bridging
- `agent-browser` is the driver layer for open/wait/export
- Treat browser session as one high-level action, not many commands

Success means a valid session, not merely a loaded page. For LinkedIn, key cookies present is the main success signal.

## Optional Capability

`auto-browser` is for LinkedIn / browser login scenarios that need a visible local browser. It is not a global hard dependency and must not block generic mining init, status checks, or background runs.

If a visible local browser is available, prefer it for login and session export; in remote/VRD scenarios, use the same session export entry points from `auto-browser`.
