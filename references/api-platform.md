# Platform API Reference

Mine talks to the platform through signed HTTP requests built by `lib/platform_client.py` and `scripts/signer.py`.

## Base URL

Configured through `PLATFORM_BASE_URL`.

Known values in current project docs:

- test: `http://101.47.73.95`
- production: `https://sd76fip34meovmfu5ftlg.apigateway-ap-southeast-1.volceapi.com`

## Authentication model

When a wallet signer is available, requests include:

| Header | Purpose |
|---|---|
| `Content-Type` | Request body type |
| `X-Request-ID` | Request correlation ID |
| `X-Signer` | Wallet address from `awp-wallet receive` |
| `X-Signature` | EIP-712 signature |
| `X-Nonce` | Per-request nonce |
| `X-Issued-At` | Signature issue timestamp |
| `X-Expires-At` | Signature expiry timestamp |
| `X-Chain-Id` | EIP-712 chain ID |
| `X-Signed-Headers` | Currently `content-type,x-request-id` |
| `Authorization` | Optional bearer token from `PLATFORM_TOKEN` |

The signature domain is configurable:

- code defaults: `Platform Service`, chain ID `1`, zero-address verifying contract
- recommended for the known aDATA platform: `aDATA`, chain ID `8453`, zero-address verifying contract

## Endpoint summary

### Heartbeat

```text
POST /api/mining/v1/heartbeat
POST /api/mining/v1/miners/heartbeat
```

Used to confirm registration state, credit score, and epoch status.

### Dataset listing

```text
GET /api/core/v1/datasets
GET /api/core/v1/datasets/{datasetId}
```

### Task claim and report

```text
POST /api/mining/v1/repeat-crawl-tasks/claim
POST /api/mining/v1/refresh-tasks/claim
POST /api/mining/v1/repeat-crawl-tasks/{taskId}/report
POST /api/mining/v1/refresh-tasks/{taskId}/report
```

### Occupancy and submission

```text
GET /api/core/v1/url-occupancies/check?dataset_id={id}&url={encodedUrl}
POST /api/core/v1/submissions
GET /api/core/v1/submissions/{submissionId}
```

### Preflight and PoW

```text
POST /api/mining/v1/miners/preflight
POST /api/mining/v1/pow-challenges/{challengeId}/answer
```

### Wallet-derived miner status

These calls use the signer wallet address, not the `MINER_ID` environment variable:

```text
GET /api/mining/v1/miners/{walletAddress}/status
GET /api/mining/v1/miners/{walletAddress}/settlement
GET /api/mining/v1/miners/{walletAddress}/reward-summary
```

## Runtime behavior by status code

| Status | Meaning | Runtime behavior |
|---|---|---|
| `401` + `MISSING_HEADERS` | Signed headers missing | Fail fast with setup guidance |
| `401` + `UNAUTHORIZED` / `TOKEN_EXPIRED` / `SESSION_EXPIRED` | Wallet session expired | Renew wallet session once, then retry |
| `401` + `UNTRUSTED_HOST` | Wallet not allowed on current host/platform | Surface to operator; no auto-fix |
| `403` | Access denied | Surface and stop the affected action |
| `404` on occupancy | Endpoint absent | Graceful fallback to empty occupancy |
| `404` on miner status / settlement / reward summary | Endpoint absent | Return empty dict |
| `404` on claim | No task available | Return `None` |
| `409` | Duplicate submission | Skip item |
| `429` | Rate limited | Cool down the dataset and retry later |
| `500+` or timeout | Transient platform issue | Retry with backoff up to three times |

## Implementation pointers

- signer: `scripts/signer.py`
- client: `lib/platform_client.py`
- worker construction: `scripts/agent_runtime.py`
