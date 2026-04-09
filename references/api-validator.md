# Validator API Map

## Table of Contents

- Signature & Response Conventions
- Roles & Permissions
- Network Onboarding Endpoints
- Validator Runtime Endpoints
- Data Review Endpoints
- External Staking Endpoints

## Signature & Response Conventions

Signature baseline:

- Public config: `GET /api/public/v1/signature-config`
- Integration guide: `docs/platform_service_web3_client_integration.md`
- Example script: `docs/platform_service_web3_request_example.mjs`

Minimum required headers:

- `X-Signer`
- `X-Signature`
- `X-Nonce`
- `X-Issued-At`
- `X-Expires-At`

Recommended additional headers:

- `X-Chain-Id`
- `X-Signed-Headers`
- `Content-Type`
- `X-Request-ID`

Platform response envelope:

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "req-local-001"
  }
}
```

Error envelope:

```json
{
  "success": false,
  "error": {
    "code": "validator_capacity_full",
    "message": "validator capacity is full"
  },
  "meta": {
    "request_id": "req-local-001"
  }
}
```

## Roles & Permissions

| Action | Path | Permission | Role |
|---|---|---|---|
| Query current identity | `/api/iam/v1/me` | `iam.me.read` | `member+` |
| Submit validator application | `/api/iam/v1/validator-applications` | `iam.validator.apply` | `member` |
| Query my application | `/api/iam/v1/validator-applications/me` | `iam.validator.apply` | `member` |
| Review validator application | `/api/iam/v1/validator-applications/:id/review` | `iam.validator.review` | `admin` |
| Unified heartbeat | `/api/mining/v1/heartbeat` | `mining.heartbeat` | `member` / `miner` / `validator` |
| Validator ready | `/api/mining/v1/validators/ready` | `mining.validator.ready` | `validator` |
| Validator unready | `/api/mining/v1/validators/unready` | `mining.validator.unready` | `validator` |
| Claim evaluation task | `/api/mining/v1/evaluation-tasks/claim` | `mining.evaluation.claim` | `validator` |
| Report evaluation task | `/api/mining/v1/evaluation-tasks/:id/report` | `mining.evaluation.report` | `validator` |
| List validation results | `/api/core/v1/validation-results` | `core.validation_results.read` | `validator` |
| Get validation result | `/api/core/v1/validation-results/:id` | `core.validation_results.read` | `validator` |
| Create validation result | `/api/core/v1/validation-results` | `core.validation_results.create` | `validator` |

Endpoints currently not under validator self-service permissions:

- `/api/mining/v1/evaluation-tasks` task creation: `admin`
- `/api/mining/v1/validators/:id/stats`: `admin`
- `/api/mining/v1/ws`: default `miner`

## Network Onboarding Endpoints

### `POST /api/iam/v1/validator-applications`

- Body: none
- Address source: current signing principal
- Observed IP: written by server

Success data main fields:

```json
{
  "id": "app_001",
  "address": "0xabc...",
  "status": "pending_review",
  "submitted_at": "2026-04-02T12:00:00Z"
}
```

Common failures:

- `validator_application_exists`
- `role_suspended`
- `insufficient_stake`
- `validator_capacity_full`

### `GET /api/iam/v1/validator-applications/me`

Success data main fields:

- `id`
- `address`
- `status`
- `submitted_at`
- `reviewed_at`
- `reviewed_by`
- `rejection_reason`

### `POST /api/iam/v1/validator-applications/:id/review`

Request body:

```json
{
  "decision": "approve",
  "rejection_reason": ""
}
```

Or:

```json
{
  "decision": "reject",
  "rejection_reason": "manual rejection reason"
}
```

## Validator Runtime Endpoints

### `POST /api/mining/v1/heartbeat`

Request body:

```json
{
  "client": "validator-cli/1.0"
}
```

Validator success data example:

```json
{
  "role": "validator",
  "validator": {
    "validator_id": "0xabc...",
    "credit": 65,
    "eligible": true,
    "credit_tier": "good",
    "min_task_interval_seconds": 30
  }
}
```

### `POST /api/mining/v1/validators/ready`

Success data:

```json
{
  "validator_id": "0xabc...",
  "status": "ready"
}
```

### `POST /api/mining/v1/validators/unready`

Success data:

```json
{
  "validator_id": "0xabc...",
  "status": "unready"
}
```

### `POST /api/mining/v1/evaluation-tasks/claim`

Success data:

```json
{
  "task_id": "eval_001",
  "assignment_id": "asg_001",
  "validator_id": "0xabc...",
  "golden": false
}
```

### `POST /api/mining/v1/evaluation-tasks/{id}/report`

Request body:

```json
{
  "assignment_id": "asg_001",
  "score": 92
}
```

Common failures:

- `evaluation_task_not_found`
- `validator_not_ready`
- `task_claim_forbidden`

## Data Review Endpoints

### `POST /api/core/v1/validation-results`

Request body:

```json
{
  "submission_id": "sub_123",
  "verdict": "accepted",
  "score": 95,
  "comment": "Structured result is complete",
  "idempotency_key": "ivr-001"
}
```

Known `verdict` values:

- `accepted`
- `rejected`

### `GET /api/core/v1/validation-results`

Supported query parameters:

- `page`
- `page_size`
- `sort`
- `order`

### `GET /api/core/v1/validation-results/{id}`

Returns a single validation result detail.

## External Staking Endpoints

### RPC: `staking.getAgentSubnetStake`

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "staking.getAgentSubnetStake",
  "params": {
    "agent": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
    "subnetId": "155921803519041537"
  },
  "id": 1
}
```

Success response:

```json
{
  "jsonrpc": "2.0",
  "result": {
    "amount": "5000000000000000000000"
  },
  "id": 1
}
```

### WSS: `watchAllocations`

Subscribe:

```json
{
  "watchAllocations": [
    { "subnetId": "155921803519041537" }
  ]
}
```

Notes:

- The platform's internal watcher uses this to detect stake changes and evict validators with insufficient stake
- This is not the primary entry point for validators to perform business actions on the platform
