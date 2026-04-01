# Mine Skill - AI Agent Quick Start

> **For AI Agents**: This is a step-by-step guide to install and run the mine skill on ANY server.

## Prerequisites Check

```bash
node --version   # Required: >= 20.0.0
python --version # Required: >= 3.11
git --version    # Required for awp-wallet installation
```

## Complete Installation Flow

### 1. Install awp-wallet (CRITICAL STEP)

**DO NOT USE**: `npm install -g @aspect/awp-wallet` ❌ (This will fail with 404)

**CORRECT METHOD** ✅:

```bash
# Clone and install from GitHub
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet
bash install.sh
cd ..

# Verify installation
awp-wallet --version
```

**Installation options**:
```bash
# Quick install with auto-setup
bash install.sh

# Install without creating wallet (manual setup later)
bash install.sh --no-init

# Import existing wallet
bash install.sh --mnemonic "your twelve word phrase"

# Multi-agent setup
bash install.sh --agent-id "miner-001"
```

### 2. Configure Environment

Create `.env` file in mine directory:

```bash
cd mine  # Ensure you're in the mine directory

cat > .env << 'EOF'
# Platform Service
PLATFORM_BASE_URL=http://101.47.73.95
MINER_ID=miner-default

# AWP Wallet
AWP_WALLET_BIN=awp-wallet
AWP_WALLET_TOKEN=

# EIP-712 Signature Domain Parameters
# CRITICAL: These must match the platform's configuration
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
EOF
```

### 3. Initialize Wallet (if needed)

```bash
# Check if wallet exists
awp-wallet status

# If wallet doesn't exist, initialize it
awp-wallet init
# Follow prompts to set password
```

### 4. Unlock Wallet and Get Token

```bash
# Unlock for 1 hour
awp-wallet unlock --duration 3600

# Output example:
# {"sessionToken":"wlt_776ff7679004ce44e2617c63a10b4f6d","expires":"2026-04-01T17:05:31.163Z"}

# Copy the sessionToken value
```

### 5. Update .env with Token

```bash
# Method 1: Using sed (Linux/Mac/Git Bash)
TOKEN="wlt_776ff7679004ce44e2617c63a10b4f6d"  # Replace with your token
sed -i "s/AWP_WALLET_TOKEN=.*/AWP_WALLET_TOKEN=$TOKEN/" .env

# Method 2: Manual edit
# Open .env and replace AWP_WALLET_TOKEN= with AWP_WALLET_TOKEN=wlt_xxxxx
```

### 6. Start Mining

```bash
# Export environment variables
export $(cat .env | grep -v '^#' | xargs)
export PYTHONPATH=.

# Start mining (infinite loop)
python scripts/run_tool.py run-worker 60 0

# Or run limited iterations for testing
python scripts/run_tool.py run-worker 60 10  # 10 iterations
```

## Common Issues and Solutions

### Issue: "ModuleNotFoundError: No module named 'lib.canonicalize'"

**Solution**: Set PYTHONPATH

```bash
export PYTHONPATH=.
python scripts/run_tool.py run-worker 60 1
```

### Issue: "KeyError: 'PLATFORM_BASE_URL'"

**Solution**: Export environment variables from .env

```bash
export $(cat .env | grep -v '^#' | xargs)
python scripts/run_tool.py run-worker 60 1
```

### Issue: "awp-wallet not found"

**Solution**: Install from GitHub (see Step 1 above)

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet && bash install.sh
```

### Issue: Wallet session expired

**Solution**: Unlock wallet again

```bash
awp-wallet unlock --duration 3600
# Update .env with new token
```

## One-Command Mining Start (After Setup)

After initial setup is complete, use this to start mining:

```bash
cd mine && \
export $(cat .env | grep -v '^#' | xargs) && \
export PYTHONPATH=. && \
python scripts/run_tool.py run-worker 60 0
```

## Monitoring Mining Status

```bash
# Check agent status
python scripts/run_tool.py agent-status

# Check wallet status
awp-wallet status

# View mining logs (if running in background)
tail -f output/worker.log
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PLATFORM_BASE_URL` | Yes | - | Platform API endpoint |
| `MINER_ID` | Yes | miner-default | Unique miner identifier |
| `AWP_WALLET_TOKEN` | Yes | - | Session token from unlock |
| `AWP_WALLET_BIN` | No | awp-wallet | Path to awp-wallet binary |
| `EIP712_DOMAIN_NAME` | Yes | aDATA | EIP-712 domain name |
| `EIP712_CHAIN_ID` | Yes | 8453 | EIP-712 chain ID (Base) |
| `EIP712_VERIFYING_CONTRACT` | Yes | 0x0...0 | Contract address |
| `PYTHONPATH` | Yes (runtime) | . | Python module path |

## Mining Command Parameters

```bash
python scripts/run_tool.py run-worker <INTERVAL> <ITERATIONS>
```

- `INTERVAL`: Seconds to wait between iterations (e.g., 60)
- `ITERATIONS`: Number of iterations to run (0 = infinite)

Examples:
```bash
# Infinite mining
python scripts/run_tool.py run-worker 60 0

# 10 iterations for testing
python scripts/run_tool.py run-worker 60 10

# Fast polling (30 seconds)
python scripts/run_tool.py run-worker 30 0
```

## Decision Tree for AI Agents

```
START
  |
  ├─ awp-wallet installed?
  |    NO → Install from GitHub (Step 1)
  |    YES ↓
  |
  ├─ .env file exists?
  |    NO → Create .env file (Step 2)
  |    YES ↓
  |
  ├─ Wallet initialized?
  |    NO → Run: awp-wallet init (Step 3)
  |    YES ↓
  |
  ├─ Wallet unlocked?
  |    NO → Run: awp-wallet unlock --duration 3600 (Step 4)
  |    YES ↓
  |
  ├─ AWP_WALLET_TOKEN in .env?
  |    NO → Update .env with token (Step 5)
  |    YES ↓
  |
  └─ START MINING (Step 6)
       export $(cat .env | grep -v '^#' | xargs)
       export PYTHONPATH=.
       python scripts/run_tool.py run-worker 60 0
```

## Automated Setup Script

If you need to automate the entire setup:

```bash
#!/bin/bash
# auto_setup.sh - Automated mine skill setup

set -e

# 1. Install awp-wallet
if ! command -v awp-wallet &> /dev/null; then
    echo "Installing awp-wallet..."
    git clone https://github.com/awp-core/awp-wallet.git /tmp/awp-wallet
    cd /tmp/awp-wallet && bash install.sh --no-init
    cd -
fi

# 2. Create .env
cat > .env << 'EOF'
PLATFORM_BASE_URL=http://101.47.73.95
MINER_ID=miner-default
AWP_WALLET_BIN=awp-wallet
AWP_WALLET_TOKEN=
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
EOF

# 3. Initialize wallet
awp-wallet init

# 4. Unlock wallet and extract token
TOKEN=$(awp-wallet unlock --duration 3600 | python3 -c "import sys, json; print(json.load(sys.stdin)['sessionToken'])")

# 5. Update .env with token
sed -i "s/AWP_WALLET_TOKEN=.*/AWP_WALLET_TOKEN=$TOKEN/" .env

# 6. Start mining
export $(cat .env | grep -v '^#' | xargs)
export PYTHONPATH=.
python scripts/run_tool.py run-worker 60 0
```

## Troubleshooting Commands

```bash
# Diagnose issues
python scripts/run_tool.py doctor

# Check agent readiness
python scripts/run_tool.py agent-status

# Fix installation issues
python scripts/fix_installation.py

# Verify wallet
awp-wallet status

# Test environment
python scripts/verify_env.py --profile full
```

## Related Documentation

- [SKILL.md](../SKILL.md) - Main skill documentation
- [INSTALLATION_TROUBLESHOOTING.md](../INSTALLATION_TROUBLESHOOTING.md) - Detailed troubleshooting
- [WORKING_CONFIG.md](../WORKING_CONFIG.md) - Verified working configuration
- [EIP712_CONFIGURATION.md](./EIP712_CONFIGURATION.md) - EIP-712 signature setup
