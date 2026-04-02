# Environment and Authentication

This document describes the current Mine runtime environment contract as implemented in the codebase.

## Defaulted variables

These values now have safe built-in defaults for the normal OpenClaw path:

| Variable | Required | Notes |
|---|---|---|
| `PLATFORM_BASE_URL` | No | Defaults to the testnet Platform API base URL |
| `MINER_ID` | No | Defaults to `mine-agent` for helper compatibility |

These are required for authenticated mining requests:

| Variable | Required | Notes |
|---|---|---|
| `AWP_WALLET_TOKEN` | Usually yes | Session token from `awp-wallet unlock --duration 3600` |
| `AWP_WALLET_TOKEN_SECRET_REF` | Alternative | SecretRef-based way to supply the wallet token |
| `AWP_WALLET_BIN` | No | Defaults to `awp-wallet` |

## Known-good platform values

The code defaults are still generic:

- `EIP712_DOMAIN_NAME=Platform Service`
- `EIP712_CHAIN_ID=1`
- `EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000`

For the currently documented aDATA platform, the recommended values are:

```bash
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

If those values are missing, Mine falls back to the generic defaults above.

## Known platform base URLs

Test environment:

```bash
PLATFORM_BASE_URL=http://101.47.73.95
```

Production environment:

```bash
PLATFORM_BASE_URL=https://sd76fip34meovmfu5ftlg.apigateway-ap-southeast-1.volceapi.com
```

Production note:

- production access may return `401` with `UNTRUSTED_HOST`
- that means the wallet address is not yet allow-listed for production

## Optional runtime variables

| Variable | Default | Purpose |
|---|---|---|
| `SOCIAL_CRAWLER_ROOT` | repo root | Override runtime root discovery |
| `CRAWLER_OUTPUT_ROOT` | `output/agent-runs` | Run artifact root |
| `WORKER_STATE_ROOT` | `<output>/_worker_state` | Persistent worker session state |
| `PYTHON_BIN` | `python` | Python executable for spawned crawler work |
| `WORKER_MAX_PARALLEL` | `3` | Parallel work limit |
| `WORKER_PER_DATASET_PARALLEL` | `1` | Per-dataset concurrency toggle |
| `DATASET_REFRESH_SECONDS` | `900` | Dataset refresh interval |
| `DISCOVERY_MAX_PAGES` | `25` | Discovery page cap |
| `DISCOVERY_MAX_DEPTH` | `1` | Discovery depth cap |
| `AUTH_RETRY_INTERVAL_SECONDS` | `300` | Rate-limit and auth retry interval |
| `PLATFORM_TOKEN` | empty | Optional bearer token added alongside wallet signatures |
| `MINE_CONFIG_PATH` | `~/.mine/mine.json` or legacy config | Config root used for secret resolution |
| `OPENCLAW_CONFIG_PATH` | fallback | Alternate config path for secret resolution |

## SecretRef support

If you do not want to inject `AWP_WALLET_TOKEN` directly, Mine can resolve it from `AWP_WALLET_TOKEN_SECRET_REF`.

Supported SecretRef sources:

- `env`
- `file`
- `exec`

The provider configuration is loaded from `MINE_CONFIG_PATH` or, if absent, `OPENCLAW_CONFIG_PATH`.

## `MINER_ID` reality check

The current codebase has two layers with different behavior:

- helper scripts and readiness flows still carry a `MINER_ID` field
- low-level API status, settlement, and reward calls derive the miner key from the wallet signer address

Until those layers are unified, Mine auto-fills a stable helper value. You do not need to configure `MINER_ID` manually unless your environment depends on a custom one.

## Recommended `.env` template

```bash
PLATFORM_BASE_URL=http://101.47.73.95
MINER_ID=mine-agent
AWP_WALLET_BIN=awp-wallet
AWP_WALLET_TOKEN=
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

## Verification commands

```bash
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py diagnose
python scripts/verify_env.py --profile minimal --json
```
