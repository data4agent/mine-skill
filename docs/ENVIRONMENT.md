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
| `AWP_WALLET_TOKEN` | Usually no | Optional explicit override; Mine now prefers auto-managed local wallet sessions |
| `AWP_WALLET_TOKEN_SECRET_REF` | Alternative | SecretRef-based way to supply the wallet token when the host manages secrets |
| `AWP_WALLET_BIN` | No | Defaults to `awp-wallet` |

## Validator variables

These variables are used by the validator runtime:

| Variable | Required | Notes |
| --- | --- | --- |
| `VALIDATOR_ID` | No | Defaults to `validator-agent` |
| `VALIDATOR_OUTPUT_ROOT` | No | Defaults to `output/validator-runs` |
| `EVAL_TIMEOUT_SECONDS` | No | Defaults to `120` seconds |

Validator also reuses:

- `PLATFORM_BASE_URL`
- `AWP_WALLET_BIN`
- the same signature auto-discovery flow as the miner runtime

For validator commands, runtime flow, and module layout, see [`VALIDATOR.md`](./VALIDATOR.md).

## Signature config discovery

Mine now discovers signature settings automatically:

1. try `GET /api/public/v1/signature-config`
2. if the fetch succeeds, persist the resolved config under worker state and use it as the active base
3. if the platform is unavailable, fall back to the built-in aDATA defaults
4. if explicit `EIP712_*` environment overrides are present, apply them last as manual overrides

The current built-in fallback values are:

```bash
EIP712_DOMAIN_NAME=aDATA
EIP712_CHAIN_ID=8453
EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

The cached platform response is stored under:

```bash
<WORKER_STATE_ROOT>/signature_config.json
```

Only override `EIP712_*` manually if you are targeting a different environment or need an emergency compatibility override.

`doctor`, `mine_setup`, and post-install checks now expose the effective signature config origin as `platform` or `fallback`, so the host can see whether runtime values came from the platform or the built-in defaults.

## AWP registration discovery and auto-registration

Mine also checks whether the current wallet is already registered on AWP:

1. resolve the current wallet address through `awp-wallet receive`
2. query `GET {AWP_API_URL}/address/{address}/check`
3. if the wallet is unregistered and a wallet session is available, submit a gasless self-registration through `POST {AWP_API_URL}/relay/set-recipient`
4. poll registration status until confirmed or timeout

The default AWP API base URL is:

```bash
AWP_API_URL=https://api.awp.sh/api
```

You can override `AWP_API_URL` if your environment uses a different AWP deployment.

The effective registration state is now surfaced by `doctor`, `mine_setup`, and post-install checks as values such as:

- `registered`
- `auto_registered`
- `registration_pending`
- `wallet_session_unavailable`
- `status_check_failed`

## Known platform base URLs

```bash
PLATFORM_BASE_URL=https://api.minework.net
```

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
| `SIGNATURE_CONFIG_PATH` | `/api/public/v1/signature-config` | Public endpoint path used for signature auto-discovery |

## SecretRef support

If you do not want to rely on the auto-managed local wallet session, Mine can resolve the token from `AWP_WALLET_TOKEN_SECRET_REF`.

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
PLATFORM_BASE_URL=https://api.minework.net
MINER_ID=mine-agent
AWP_WALLET_BIN=awp-wallet
```

## Verification commands

```bash
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py diagnose
python scripts/verify_env.py --profile minimal --json
```
