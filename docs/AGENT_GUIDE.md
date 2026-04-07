# Agent Guide

This guide is the shortest reliable path for an agent to install, verify, and run Mine.

## 1. Host prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- `uv` is optional but preferred for faster virtualenv creation

Quick checks:

```bash
python --version
node --version
git --version
```

## 2. Bootstrap the runtime

Unix-like:

```bash
./scripts/bootstrap.sh
```

Windows:

```powershell
./scripts/bootstrap.ps1
```

What bootstrap does:

- creates or reuses `.venv`
- installs Python requirements
- installs `awp-wallet` from the GitHub repo if it is missing
- refreshes the public signature-config when the platform is reachable and falls back cleanly if it is not
- reports whether the current signature config source is `platform` or `fallback`
- runs host diagnostics, environment verification, smoke tests, and post-install checks

## 3. Wallet session model

The default path is now auto-managed:

- bootstrap ensures `awp-wallet` is available
- Mine restores the last valid local wallet session from worker state when possible
- if the local wallet does not exist yet, Mine attempts `awp-wallet init`
- if the session is missing or expired, Mine attempts `awp-wallet unlock --duration 3600`

Manual wallet commands are still available for recovery:

```bash
awp-wallet init
awp-wallet unlock --duration 3600
```

Mine signs requests through `awp-wallet`. Do not store seed phrases or private keys in repo files.

## 4. Configure the environment

You do not need a `.env` file or manual wallet token export for the normal path. Mine defaults to testnet, a helper-safe `MINER_ID`, and platform-discovered signature settings. Only set overrides when you need something custom:

```bash
PLATFORM_BASE_URL=https://api.minework.net
MINER_ID=mine-agent
AWP_WALLET_BIN=awp-wallet
```

Signature behavior:

- Mine first attempts to refresh from `GET /api/public/v1/signature-config`
- if refresh succeeds, the platform values become the active runtime base and are cached into worker state
- if the platform cannot be reached, it falls back to the built-in aDATA defaults
- `EIP712_*` variables are now manual overrides, not required setup

Registration behavior:

- Mine checks the current wallet against the AWP registration API during startup
- if the wallet is not registered yet, Mine attempts a gasless self-registration automatically
- the gasless path is equivalent to `setRecipient(self)` on AWP
- `doctor` now reports both the signature config origin and the current registration status

Why `MINER_ID` is still listed:

- the lower-level client fetches miner status with the wallet address
- Mine now auto-fills `MINER_ID=mine-agent` for helper-layer compatibility
- only override it if your deployment truly needs a different value

For a fuller variable reference, see [`ENVIRONMENT.md`](./ENVIRONMENT.md).
For validator-specific runtime and protocol details, see [`VALIDATOR.md`](./VALIDATOR.md).

## 5. Verify readiness

Recommended checks:

```bash
python scripts/run_tool.py agent-status
python scripts/run_tool.py first-load
python scripts/run_tool.py doctor
```

Interpretation:

- `doctor` returns structured checks, exact fix commands, the current signature-config origin/status, and wallet registration status
- `agent-status` is the fastest readiness probe for host integrations
- `first-load` renders the guided startup experience

## 6. Start mining

Preferred host flow:

```bash
python scripts/run_tool.py agent-start
```

Then monitor or control it with:

```bash
python scripts/run_tool.py agent-control status
python scripts/run_tool.py agent-control pause
python scripts/run_tool.py agent-control resume
python scripts/run_tool.py agent-control stop
```

The goal is that mining runs in the background while the host agent stays available for user interaction.

Guided start:

```bash
python scripts/run_tool.py start-working
```

This prepares the session, sends heartbeat, fetches datasets, and may ask for dataset selection.

Direct worker loop:

```bash
python scripts/run_tool.py run-worker 60 0
```

- first argument: polling interval in seconds
- second argument: max iterations
- use `0` for a long-running loop

Single-pass run:

```bash
python scripts/run_tool.py run-worker 60 1
```

## 7. Common operator commands

```bash
python scripts/run_tool.py check-status
python scripts/run_tool.py list-datasets
python scripts/run_tool.py pause
python scripts/run_tool.py resume
python scripts/run_tool.py stop
python scripts/run_tool.py diagnose
```

## 8. When setup fails

Prefer this order:

1. Re-run bootstrap.
2. Run `python scripts/run_tool.py doctor`.
3. If wallet session recovery still fails, run `awp-wallet unlock --duration 3600`.
4. Manually install `awp-wallet` from GitHub if bootstrap could not do it.

Manual `awp-wallet` install:

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet
npm install
npm install -g .
awp-wallet --version
```

Do not rely on `npm install -g @aspect/awp-wallet`. This repository currently installs `awp-wallet` from the upstream GitHub source instead.

## 9. Windows LinkedIn auto-login

Windows no longer depends on the Linux VRD stack for LinkedIn login. The crawler now opens a local visible Chrome/Edge window, waits for a valid browser session, and then exports the session back into the crawler flow.

Recommended agent entrypoint:

```powershell
python scripts/run_tool.py browser-session linkedin
python scripts/run_tool.py browser-session-status linkedin
```

`browser-session` reuses an existing browser session when possible. If user handoff is needed, it returns immediately with a temporary Cloudflare link when available; after the user finishes login, poll `browser-session-status` until it reports `ready`. Success also stops the temporary browser stack automatically.

Expected flow:

1. run `crawl --auto-login`
2. a local browser window opens to the LinkedIn login page
3. complete login in that browser window
4. the crawler exports the session and continues automatically

Typical failure causes:

- LinkedIn CAPTCHA or risk challenge
- Chrome/Edge is not installed and pinned browser install failed
- CDP port `9222` is already occupied
- stale browser profile or a dead local control process

## 10. OpenClaw alias mapping

If the host surface wants slash commands, map them to the canonical command layer:

```text
/mine-start  -> python scripts/run_tool.py agent-start
/mine-status -> python scripts/run_tool.py agent-control status
/mine-pause  -> python scripts/run_tool.py agent-control pause
/mine-resume -> python scripts/run_tool.py agent-control resume
/mine-stop   -> python scripts/run_tool.py agent-control stop
```

## 11. Production note

The production platform URL currently requires wallet allow-listing. If you see `401` with `UNTRUSTED_HOST`, the wallet must be approved before mining will work there.

## 12. Validator quick entry

Validator now has a dedicated command group:

```bash
python scripts/run_tool.py validator-status
python scripts/run_tool.py validator-start
python scripts/run_tool.py validator-control status
python scripts/run_tool.py validator-control stop
python scripts/run_tool.py validator-doctor
```

Use [`VALIDATOR.md`](./VALIDATOR.md) as the source of truth for validator behavior, architecture, and troubleshooting.
