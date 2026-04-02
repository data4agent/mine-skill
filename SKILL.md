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
---

# Mine

Agent-facing entrypoint for the local mining runtime.

## Commands (6 canonical)

```bash
python scripts/run_tool.py agent-status              # Check readiness
python scripts/run_tool.py agent-start               # Start background mining
python scripts/run_tool.py agent-control status      # Check mining status
python scripts/run_tool.py agent-control pause       # Pause mining
python scripts/run_tool.py agent-control resume      # Resume mining
python scripts/run_tool.py agent-control stop        # Stop mining
python scripts/run_tool.py doctor                    # Diagnose issues
```

All other commands are internal/deprecated.

## Readiness States

`agent-status` and `doctor` return a unified readiness contract:

| State | can_diagnose | can_start | can_mine | Meaning |
|-------|--------------|-----------|----------|---------|
| `ready` | true | true | true | Fully operational |
| `registration_required` | true | true | false | Can start, will auto-register |
| `auth_required` | true | false | false | Wallet session missing/expired |
| `agent_not_initialized` | false | false | false | awp-wallet not found |
| `degraded` | true | true | false | Partial functionality |

**Warnings** may include: `wallet session expired`, `wallet session expires in Ns`, `using fallback signature config`.

## Setup

```bash
./scripts/bootstrap.sh      # Unix
./scripts/bootstrap.ps1     # Windows
```

Bootstrap installs dependencies, `awp-wallet`, and establishes wallet session.

## Workflow

1. `./scripts/bootstrap.sh`
2. `python scripts/run_tool.py agent-status`
3. `python scripts/run_tool.py agent-start`
4. `python scripts/run_tool.py agent-control status`

## Environment (defaults work)

```bash
PLATFORM_BASE_URL=http://101.47.73.95   # testnet default
MINER_ID=mine-agent                      # default
AWP_WALLET_BIN=awp-wallet               # auto-detected
```

EIP-712 signature config is auto-fetched from platform; falls back to built-in defaults if unreachable.

## Troubleshooting

```bash
python scripts/run_tool.py doctor
awp-wallet unlock --duration 3600
```

## Reference

- [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md)
- [`docs/ENVIRONMENT.md`](./docs/ENVIRONMENT.md)
