---
name: mine
description: Autonomous mining skill for Data Mining WorkNet. Handles crawling, enrichment, and submission signing through awp-wallet.
bootstrap: ./scripts/bootstrap.sh
windows_bootstrap: ./scripts/bootstrap.ps1
smoke_test: ./scripts/smoke_test.py
requires:
  skills:
    - browse
    - auto-browser
  bins:
    - python3
    - npm
  anyBins:
    - python
    - py
  env:
    - PLATFORM_BASE_URL
---

# Mine

Autonomous mining skill for Data Mining WorkNet.

## Quick Start

```bash
# 1. Install (auto-installs all dependencies including awp-wallet)
openclaw install mine

# 2. Initialize wallet
awp-wallet init

# 3. Unlock wallet
awp-wallet unlock --duration 3600

# 4. Start mining
python scripts/run_tool.py run-worker 60 1
```

## Installation Problems?

### awp-wallet Not Found

**CRITICAL**: `npm install -g @aspect/awp-wallet` does NOT work (404 error). The package is not published to npm registry.

**Correct installation method for ANY server:**

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet && bash install.sh
awp-wallet --version  # Verify installation
```

### Other Dependency Issues

If other dependencies are missing:

```bash
python scripts/fix_installation.py
```

See [INSTALLATION_TROUBLESHOOTING.md](./INSTALLATION_TROUBLESHOOTING.md) for details.

## Common Commands

| Command | Description |
|---------|-------------|
| `python scripts/run_tool.py setup` | One-shot setup wizard |
| `python scripts/run_tool.py doctor` | Diagnose issues |
| `python scripts/run_tool.py agent-status` | Check readiness |
| `python scripts/run_tool.py run-worker 60 1` | Start mining |
| `python scripts/fix_installation.py` | Fix incomplete installation |

## Agent Integration

**For AI Agents**: See [docs/AGENT_QUICK_START.md](./docs/AGENT_QUICK_START.md) for complete step-by-step setup guide.

### Quick Checklist

1. Install awp-wallet from GitHub (NOT npm - will 404)
2. Create `.env` with platform config
3. Unlock wallet and get token
4. Export env vars and start mining

### Status Check

```bash
python scripts/run_tool.py agent-status  # Returns JSON with next_action
```

## Environment Variables

Required:

```bash
export PLATFORM_BASE_URL=http://101.47.73.95

# EIP-712 Signature (CRITICAL!)
export EIP712_DOMAIN_NAME=aDATA
export EIP712_CHAIN_ID=8453
export EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

**Note**: Miner identification is automatic via your wallet address. No MINER_ID needed!

See [WORKING_CONFIG.md](./WORKING_CONFIG.md) for working configuration.

## Security

The agent uses its own wallet for signing requests. Wallet management is automatic — you don't need to configure or unlock anything during mining (session tokens auto-renew).

## Documentation

- **[docs/AGENT_QUICK_START.md](./docs/AGENT_QUICK_START.md)** - **AI Agent step-by-step setup guide**
- [INSTALLATION_TROUBLESHOOTING.md](./INSTALLATION_TROUBLESHOOTING.md) - Installation issues
- [WORKING_CONFIG.md](./WORKING_CONFIG.md) - Verified working configuration
- [docs/EIP712_CONFIGURATION.md](./docs/EIP712_CONFIGURATION.md) - EIP-712 signature setup
- [docs/PLATFORM_REGISTRATION.md](./docs/PLATFORM_REGISTRATION.md) - Platform registration
- [docs/AWP_WALLET_AUTO_INSTALL.md](./docs/AWP_WALLET_AUTO_INSTALL.md) - awp-wallet auto-install

## Status Indicators

```bash
✓ Agent identity — ready              # Wallet unlocked and ready
⚠ Agent identity — session expired    # Run: awp-wallet unlock --duration 3600
✗ Agent identity — not available      # Run: python scripts/fix_installation.py
```

## Troubleshooting

### Problem: awp-wallet not found

```bash
python scripts/fix_installation.py
```

### Problem: 401 Unauthorized

- Check EIP-712 configuration (see [WORKING_CONFIG.md](./WORKING_CONFIG.md))
- Verify wallet is unlocked: `awp-wallet status --token $AWP_WALLET_TOKEN`

### Problem: Environment variables not set

```bash
python scripts/run_tool.py doctor
# Follow fix_commands in output
```

## Mining Workflow

```text
1. Check Status
   ↓
2. Claim Task
   ↓
3. Run Crawler
   ↓
4. Submit Results
   ↓
5. Report Completion
   ↓
   (Loop back to 1)
```

The `run-worker` command handles this entire loop automatically.

## For More Details

Run any command to see detailed help and options.
