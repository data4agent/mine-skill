---
name: mine
description: Autonomous mining skill for signed platform work, crawler execution, and submission export through awp-wallet.
bootstrap: ./scripts/bootstrap.sh
windows_bootstrap: ./scripts/bootstrap.ps1
smoke_test: ./scripts/smoke_test.py
requires:
  skills:
    - auto-browser
  bins:
    - npm
    - git
  anyBins:
    - python
    - python3
    - py
  env:
    - PLATFORM_BASE_URL
    - MINER_ID
---

# Mine

Mine is the agent-facing entrypoint for the local mining runtime in this repository.

## Public command surface

Always go through `scripts/run_tool.py`.

```bash
python scripts/run_tool.py first-load
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py start-working
python scripts/run_tool.py check-status
python scripts/run_tool.py list-datasets
python scripts/run_tool.py run-worker 60 0
python scripts/run_tool.py process-task-file <taskType> <taskJsonPath>
python scripts/run_tool.py export-core-submissions <inputPath> <outputPath> <datasetId>
```

## Setup

Bootstrap first.

Unix-like:

```bash
./scripts/bootstrap.sh
```

Windows:

```powershell
./scripts/bootstrap.ps1
```

Bootstrap installs Python dependencies, verifies the host, and installs `awp-wallet` from GitHub if it is missing.

## Wallet flow

Initialize once if needed:

```bash
awp-wallet init
```

Unlock a session:

```bash
awp-wallet unlock --duration 3600
```

Mine uses `awp-wallet` for all request signing. Never store seed phrases or private keys in repo files.

## Environment

Set at least:

```bash
PLATFORM_BASE_URL=http://101.47.73.95
MINER_ID=mine-agent
AWP_WALLET_BIN=awp-wallet
AWP_WALLET_TOKEN=<token from awp-wallet unlock>
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

Important nuance:

- helper commands still require `MINER_ID`
- lower-level platform identity is derived from the wallet signer address

For full details, see [`docs/ENVIRONMENT.md`](./docs/ENVIRONMENT.md).

## Recommended agent workflow

1. Run bootstrap.
2. Initialize or verify the wallet.
3. Unlock the wallet and capture a session token.
4. Run `python scripts/run_tool.py doctor`.
5. Run `python scripts/run_tool.py start-working` for the guided flow, or `python scripts/run_tool.py run-worker 60 0` for the long-running loop.

## Troubleshooting

Use:

```bash
python scripts/run_tool.py doctor
python scripts/run_tool.py diagnose
python scripts/run_tool.py agent-status
```

If `awp-wallet` is missing and bootstrap did not install it, install it from GitHub:

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet
npm install
npm install -g .
```

Do not rely on `npm install -g @aspect/awp-wallet`.

## Reference docs

- [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md)
- [`docs/ENVIRONMENT.md`](./docs/ENVIRONMENT.md)
- [`references/commands-mining.md`](./references/commands-mining.md)
- [`references/api-platform.md`](./references/api-platform.md)
- [`references/protocol-miner.md`](./references/protocol-miner.md)
- [`references/security-model.md`](./references/security-model.md)
- [`references/error-recovery.md`](./references/error-recovery.md)
