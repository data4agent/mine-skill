# Frontend Skill Development Guide

> **Version**: 3.0 (2026-04-09)  
> **Base URL**: `http://<host>:8080`  
> **Framework**: Gin (Go)

This document serves as a comprehensive reference for developing frontend applications and LLM-driven skills that interact with the ocDATA Data Mining Platform API. It covers authentication, all API endpoints, request/response schemas, state machines, WebSocket integration, credit systems, and error handling.

An LLM reading only this document should be able to correctly call every endpoint.

---

## Table of Contents

1. [Authentication (EIP-712)](#1-authentication-eip-712)
2. [Response Envelope](#2-response-envelope)
3. [Roles & Permissions](#3-roles--permissions)
4. [State Machines](#4-state-machines)
5. [Public API (no auth)](#5-public-api-no-auth)
6. [IAM Module](#6-iam-module)
7. [Core Module](#7-core-module)
8. [Mining Module](#8-mining-module)
9. [WebSocket Realtime Channel](#9-websocket-realtime-channel)
10. [Error Reference Table](#10-error-reference-table)
11. [Miner Workflow](#11-miner-workflow)
12. [Validator Workflow](#12-validator-workflow)
13. [Admin Workflow](#13-admin-workflow)
14. [Timing Parameters](#14-timing-parameters)

---

## 1. Authentication (EIP-712)

All protected endpoints require EIP-712 typed-data signatures via HTTP headers.

### 1.1 Signature Configuration

Retrieve the runtime signature parameters before signing:

```
GET /api/public/v1/signature-config
```

**Response:**
```json
{
  "success": true,
  "data": {
    "scheme": "eip712-http-request",
    "primary_type": "APIRequest",
    "domain": {
      "name": "aDATA",
      "version": "1",
      "chain_id": 8453,
      "verifying_contract": "0xAB41eE5C44D4568aD802D104A6dAB1Fe09C590D1"
    },
    "required_headers": ["X-Signer", "X-Signature", "X-Nonce", "X-Issued-At", "X-Expires-At"],
    "optional_headers": ["X-Chain-Id", "X-Signed-Headers", "Content-Type"],
    "message_fields": ["method", "host", "path", "queryHash", "headersHash", "bodyHash", "nonce", "issuedAt", "expiresAt"],
    "max_validity_secs": 300,
    "clock_skew_secs": 30,
    "canonical_formats": {
      "nonce": "decimal-string",
      "issued_at": "unix-seconds",
      "expires_at": "unix-seconds"
    },
    "compatible_formats": {
      "nonce": ["decimal-string", "uuid"],
      "issued_at": ["unix-seconds", "rfc3339"],
      "expires_at": ["unix-seconds", "rfc3339"]
    }
  },
  "meta": { "request_id": "..." }
}
```

### 1.2 Required Request Headers

| Header | Description |
|--------|-------------|
| `X-Signer` | Ethereum address (EIP-712 signer) |
| `X-Signature` | EIP-712 signature hex string |
| `X-Nonce` | Unique nonce. Supported formats: **decimal-string** (canonical, e.g. `"1748293847"`) or **UUID** (e.g. `"550e8400-e29b-41d4-a716-446655440000"`). Decimal strings are normalized via `big.Int`; UUIDs are normalized via `uuid.Parse`. Leading zeros in decimal cause `SIGNER_MISMATCH` |
| `X-Issued-At` | Request issued timestamp. Supported formats: **Unix seconds** (canonical, e.g. `"1712400000"`) or **RFC 3339** (e.g. `"2026-04-06T12:00:00Z"`). RFC 3339 is converted to Unix seconds internally |
| `X-Expires-At` | Request expiration timestamp. Same formats as `X-Issued-At` |

### 1.3 Optional Headers

| Header | Description |
|--------|-------------|
| `X-Chain-Id` | Blockchain chain ID |
| `X-Signed-Headers` | Comma-separated list of additional signed headers |
| `Content-Type` | MIME type (e.g. `application/json`) |

**Note**: `X-Request-ID` is NOT a signed header. It was removed because Envoy API Gateway overwrites it on forwarded requests, which breaks `headersHash` verification.

### 1.4 EIP-712 Typed Data Structure

**Canonical format** (decimal-string nonce + unix-seconds timestamps):

```
EIP712Domain:
  name        (string)
  version     (string)
  chainId     (uint256)
  verifyingContract (address)

APIRequest:
  method      (string)    # HTTP method (GET, POST, etc.)
  host        (string)    # Request host
  path        (string)    # Request path
  queryHash   (bytes32)   # keccak256(sorted query string) or zero hash (0x000...000)
  headersHash (bytes32)   # keccak256(signed headers) or zero hash (0x000...000)
  bodyHash    (bytes32)   # keccak256(body) or zero hash (0x000...000)
  nonce       (uint256)   # Decimal-string nonce (normalized via big.Int)
  issuedAt    (uint256)   # Unix timestamp (seconds)
  expiresAt   (uint256)   # Unix timestamp (seconds)
```

**Legacy format** (UUID nonce or RFC3339 timestamps -- `UseLegacyType = true`):

When any of nonce/issuedAt/expiresAt uses a non-canonical format (UUID or RFC3339), the server tries BOTH type variants for signer recovery:

```
APIRequest (legacy):
  method      (string)
  host        (string)
  path        (string)
  queryHash   (bytes32)
  headersHash (bytes32)
  bodyHash    (bytes32)
  nonce       (string)    # Raw nonce string as-is (UUID or decimal)
  issuedAt    (string)    # Raw timestamp string as-is (RFC3339 or unix-seconds)
  expiresAt   (string)    # Raw timestamp string as-is
```

The server tries canonical (uint256) first, then legacy (string) types. Clients using UUID nonce or RFC3339 timestamps should sign with the **legacy** type definition (all three fields as `string`).

**Zero Hash**: `0x0000000000000000000000000000000000000000000000000000000000000000` (64 zero nibbles). Used for ALL empty fields -- do NOT use `keccak256("")`.

**Body Hash**:
- Empty body or `nil` -> **zero hash**
- `application/json` with valid JSON -> canonicalize body per RFC 8785 (JCS), then `keccak256(canonicalized_bytes)`
- If JSON canonicalization fails -> `keccak256(raw_body_bytes)`
- Other content types -> `keccak256(raw_body_bytes)`

**RFC 8785 (JCS) canonicalization rules** -- the server uses `github.com/cyberphone/json-canonicalization`:
- Sort object keys lexicographically (by Unicode code point)
- Use compact separators: no whitespace (equivalent to Python `separators=(',', ':')`)
- **Non-ASCII characters (e.g. Chinese, emoji) are kept as raw UTF-8 bytes, NOT escaped to `\uXXXX`**
- Only ASCII control characters (`< U+0020`) are `\u`-escaped
- Standard JSON escapes: `\\`, `\"`, `\b`, `\f`, `\n`, `\r`, `\t`
- Numbers: ES6 formatting (no trailing zeros, no positive exponent sign)

**IMPORTANT for Python clients**: Use `json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False)`. Do NOT use `ensure_ascii=True` -- the server outputs non-ASCII as raw UTF-8. ASCII-escaping produces different bytes -> different keccak256 -> `SIGNER_MISMATCH`.

```
Input:  {"name": "测试", "value": 42}
Output: {"name":"测试","value":42}    <- raw UTF-8, NOT \u6d4b\u8bd5
```

**Query Hash**:
- No query parameters -> **zero hash**
- Sort query parameter keys alphabetically
- For each key, sort its values alphabetically
- URL-encode both key and value with `url.QueryEscape`
- Join as `key1=val1&key1=val2&key2=val3`
- Hash: `keccak256(joined_string)`

**Headers Hash**:
- No signed headers (or `X-Signed-Headers` not set) -> **zero hash**
- `X-Signed-Headers` is parsed by splitting on `,`, lowercasing, and **sorting alphabetically**
- For each signed header: join multiple values with `,`, trim and collapse internal whitespace to single space
- Format each as `lowercasekey:normalizedvalue`
- Sort all lines alphabetically
- Join with `\n` (newline)
- Hash: `keccak256(joined_string)`
- If `X-Signed-Headers` lists headers but none are present in the request -> **zero hash**

**Nonce**: Two formats supported:
- **decimal-string** (canonical): parsed as `big.Int`, re-serialized with `.String()`. No leading zeros.
- **UUID**: parsed via `uuid.Parse`, re-serialized as canonical UUID string (lowercase, with hyphens).
When a UUID nonce is used, the server sets `UseLegacyType = true` which changes the EIP-712 `nonce` field type from `uint256` to `string`.

**Signature v-value**: The signature recovery ID (v) can be either 0/1 or 27/28. The server adjusts `v -= 27` if `v >= 27`.

### 1.5 Signature Validity

- Maximum validity window: **300 seconds** (5 minutes)
- Clock skew tolerance: **30 seconds**
- Maximum request body size: **8 MB**
- Nonces must not be reused

### 1.6 Authentication Error Codes

| Code | Description |
|------|-------------|
| `MISSING_HEADERS` | Required auth headers missing |
| `INVALID_NONCE` | Nonce is not a valid decimal integer or UUID |
| `INVALID_ISSUED_AT` | Invalid issued-at timestamp (must be Unix seconds integer or RFC 3339 string) |
| `INVALID_EXPIRES_AT` | Invalid expires-at timestamp (must be Unix seconds integer or RFC 3339 string) |
| `INVALID_CHAIN_ID` | Invalid chain ID in X-Chain-Id header |
| `FUTURE_TIMESTAMP` | Issued-at is in the future beyond clock skew |
| `EXPIRED` | Request has expired |
| `VALIDITY_TOO_LONG` | Validity window exceeds max |
| `UNTRUSTED_HOST` | Host not in trusted hosts list |
| `NONCE_REUSED` | Nonce was already used |
| `UNSUPPORTED_SIGNED_HEADERS` | Signed headers not in allowed list |
| `REQUEST_BODY_TOO_LARGE` | Request body exceeds 8 MB limit |
| `INVALID_SIGNATURE` | Signature verification failed |
| `SIGNER_MISMATCH` | Recovered signer does not match X-Signer |

---

## 2. Response Envelope

All API responses use a consistent envelope format.

### 2.1 SuccessEnvelope

```json
{
  "success": true,
  "data": { "<varies by endpoint>" },
  "meta": {
    "request_id": "uuid-string"
  }
}
```

TypeScript equivalent:
```typescript
interface SuccessEnvelope<T> {
  success: true;
  data: T;
  meta: { request_id: string };
}
```

### 2.2 ErrorEnvelope

```json
{
  "success": false,
  "error": {
    "code": "string",
    "category": "string",
    "message": "string",
    "retryable": false,
    "recoverable": true,
    "recovery_strategy": "string",
    "hint": "string",
    "field_errors": [
      {
        "field": "field_name",
        "reason": "required",
        "message": "field is required",
        "allowed_values": ["val1", "val2"]
      }
    ],
    "resource": {
      "type": "resource_type",
      "current_state": "state"
    },
    "requirements": {
      "min_stake": "10000000000000000000000"
    },
    "recovery_actions": [
      {
        "action": "fix_request",
        "label": "Fix request",
        "requires_authorization": false,
        "recommended_actor": "current_identity",
        "blocking": true
      }
    ],
    "docs_key": "string",
    "retry_at": "RFC3339 timestamp",
    "retry_after_seconds": 60,
    "details": { "key": "value" }
  },
  "meta": {
    "request_id": "uuid-string"
  }
}
```

### 2.3 ErrorBody Fields (complete)

| Field | Type | Always present | Description |
|-------|------|----------------|-------------|
| `code` | string | Yes | Machine-readable error code |
| `category` | string | Yes | Error category (see below) |
| `message` | string | Yes | Human-readable description |
| `retryable` | bool | Yes | Whether retrying the same request may succeed |
| `recoverable` | bool | Yes | Whether the caller can fix the issue |
| `recovery_strategy` | string | No (omitempty) | How to recover (see below) |
| `hint` | string | No (omitempty) | LLM-friendly hint on what to do next |
| `field_errors` | FieldError[] | No (omitempty) | Per-field validation errors |
| `resource` | object | No (omitempty) | Resource info (type, current_state) |
| `requirements` | object | No (omitempty) | Requirements not met (e.g. min_stake) |
| `recovery_actions` | RecoveryAction[] | No (omitempty) | Suggested recovery actions |
| `docs_key` | string | No (omitempty) | Documentation reference |
| `retry_at` | string | No (omitempty) | Earliest retry time (RFC 3339) |
| `retry_after_seconds` | int | No (omitempty) | Seconds to wait before retry |
| `details` | map | No (omitempty) | Additional details |

### 2.4 NextActionHint

When an endpoint response includes a `next_action` field, it tells the LLM caller what to do next:

```json
{
  "action": "answer_pow_challenge",
  "method": "POST",
  "path": "/api/mining/v1/pow-challenges/<id>/answer",
  "description": "Answer the PoW challenge to unlock submission"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | Machine-readable action name |
| `method` | string | HTTP method to use |
| `path` | string | Full API path to call |
| `description` | string | Human-readable description of what the next step does |

### 2.5 Error Categories

| Category | Description |
|----------|-------------|
| `validation` | Request validation failure |
| `authentication` | Auth header/signature issues |
| `permission` | Role/permission restrictions |
| `precondition` | Preconditions not met (e.g. address not registered) |
| `state_conflict` | State transition violations |
| `rate_limit` | Rate limiting |
| `dependency` | Service dependency issues |
| `not_found` | Resource not found |
| `internal` | Server errors |

### 2.6 Recovery Strategies

| Strategy | Description |
|----------|-------------|
| `fix_request` | Fix request parameters and retry |
| `retry_same_request` | Retry the same request later |
| `wait_and_retry` | Wait for a cooldown period then retry |
| `wait_next_epoch` | Wait until the next epoch |
| `change_precondition` | Change a precondition (e.g. stake more) |
| `register_address` | Register address on-chain first |
| `switch_identity` | Use a different identity |
| `request_human_help` | Requires manual intervention |
| `stop` | Cannot be recovered |

---

## 3. Roles & Permissions

### 3.1 Role Hierarchy

```
admin (rank 3) > validator (rank 2) > miner (rank 1) > member (rank 0)
```

**Two permission models are used:**
- **`MinRole`**: Higher roles inherit lower role permissions (e.g. `min: admin` means admin only; `min: member` means all roles).
- **`AllowedRoles`**: Only the exact listed roles are permitted -- **admin does NOT inherit**. For example, `allowed: miner` means only miners can call the endpoint; admin will get 403.

See Appendix A for which model each permission uses.

### 3.2 Role Assignment

| Role | How to Obtain |
|------|---------------|
| `member` | Default role after authentication with registered address |
| `miner` | Auto-promoted from `member` on first heartbeat call |
| `validator` | Submit validator application (auto-approved if stake >= 10000 AWP and capacity available) |
| `admin` | Pre-configured via environment variable or identity store |

### 3.3 Identity States

| Status | Description |
|--------|-------------|
| `active` | Normal operation |
| `suspended` | Temporarily disabled (returns 403) |
| `revoked` | Permanently disabled (returns 403) |

### 3.4 Address Registration

Non-admin users must have their address registered on-chain before accessing protected APIs. Unregistered addresses receive a `428 address_not_registered` error with registration guidance (Base chainId=8453, registration URL). Once the identity has a role set locally (miner/validator), the RPC registration check is skipped for performance.

**428 Response:**
```json
{
  "success": false,
  "error": {
    "code": "address_not_registered",
    "category": "precondition",
    "message": "address is not registered on-chain; please register on Base (chainId=8453) at https://api.awp.sh/v2 first, then retry",
    "retryable": true,
    "recoverable": true,
    "recovery_strategy": "register_address",
    "hint": "Visit https://api.awp.sh/v2 to register your address on Base (chainId=8453). After registration is confirmed on-chain, retry the request.",
    "requirements": {
      "chain_id": 8453,
      "chain_name": "Base",
      "registration_url": "https://api.awp.sh/v2"
    }
  }
}
```

---

## 4. State Machines

This section documents the key state machines in the platform. Understanding these is critical for LLM callers that need to drive multi-step workflows.

### 4.1 PoW State Machine (Miner Submission Gate)

Each miner has a `submission_state` that controls whether they can submit data. The state transitions probabilistically after each successful submission based on the miner's credit score.

```
                    PoW passed
    +----------+  ------------->  +----------+
    | checking |                  | opening  |
    +----------+  <-------------  +----------+
                    dice roll          |
                    (probability       | submit entries
                     based on credit)  | (accepted)
                                       v
                                  transition back
                                  based on pow_probability
```

**States:**

| State | `can_submit` | Description |
|-------|-------------|-------------|
| `opening` | `true` | Miner can submit entries freely |
| `checking` | `false` | Miner must answer a PoW challenge before submitting |

**Transition rules:**
- `checking -> opening`: Miner answers the PoW challenge correctly
- `opening -> checking`: After a successful submission, the system rolls dice with probability = `pow_probability` (from heartbeat). If triggered, state transitions to `checking`.
- `opening -> opening`: If dice roll does not trigger, state stays `opening`.

**PoW probability by credit tier:**

| Tier | Credit Range | `pow_probability` |
|------|-------------|-------------------|
| `excellent` | 80-100 | 0.01 (1%) |
| `good` | 60-79 | 0.05 (5%) |
| `normal` | 40-59 | 0.20 (20%) |
| `restricted` | 20-39 | 0.50 (50%) |
| `novice` | 0-19 | 1.00 (100%) |

**PoW challenge mechanism:** The challenge is a dynamic SHA256 hash computation. The server generates a random nonce (UUID), computes `SHA256(nonce)`, and asks the miner to return the first 8 hex characters of the hash.

- **Prompt**: `Compute SHA256("<nonce>") and return the first 8 hex characters.`
- **Expected answer**: `hex.EncodeToString(sha256.Sum256([]byte(nonce))[:4])` -- i.e., the first 4 bytes of the SHA256 hash, encoded as 8 hex characters.
- **Challenge TTL**: 5 minutes

### 4.2 Submission Lifecycle

```
    +----------+       validation       +-----------+
    | pending  | --------------------> | confirmed |
    +----------+                        +-----------+
         |
         | validation (negative)
         v
    +----------+
    | rejected |
    +----------+
```

**States:**

| State | Description |
|-------|-------------|
| `pending` | Submitted, awaiting validation |
| `confirmed` | Passed quality validation |
| `rejected` | Failed validation or determined fraudulent |

**Deduplication enforcement:** Dedup is enforced via a partial unique index on the submissions table (`WHERE status != 'rejected'`). There is no separate `dedup_occupancies` table. The dedup-occupancies endpoints query submissions directly.

### 4.3 Quality Workflow Lifecycle

Each sampled submission spawns a quality workflow that progresses through repeat crawl and evaluation phases.

```
                          repeat task
    +----------+  created   +-----------------+  miner claims   +---------------------+
    | accepted | --------> | repeat_pending  | ------------->  | repeat_in_progress  |
    +----------+            +-----------------+                 +---------------------+
                                                                        |
                                                    miner reports       |
                                                                        v
                                                            +----------------------+
                                                            | evaluation_pending   |
                                                            +----------------------+
                                                                        |
                                                    validator claims    |
                                                                        v
                                                            +------------------------+
                                                            | evaluation_in_progress |
                                                            +------------------------+
                                                              /                   \
                                          evaluation          evaluation
                                          completes           fails/timeout
                                              |                      |
                                              v                      v
                                          +--------+           +---------+
                                          | closed |           | invalid |
                                          +--------+           +---------+
```

**States:**

| State | Description |
|-------|-------------|
| `accepted` | Submission sampled; workflow created |
| `repeat_pending` | Repeat crawl task created, awaiting miner claim |
| `repeat_in_progress` | A miner is re-crawling the URL |
| `evaluation_pending` | Repeat data received; evaluation task created |
| `evaluation_in_progress` | A validator is evaluating the data |
| `closed` | Evaluation completed successfully |
| `invalid` | Workflow failed (timeout, error, etc.) |

**QualityWorkflowRecord fields:**

| Field | Type | Description |
|-------|------|-------------|
| `submission_id` | string | The submission being evaluated |
| `schema_fields` | string[] | Sorted schema field names |
| `status` | string | Current workflow status |
| `repeat_task_id` | string | Associated repeat crawl task ID |
| `evaluation_id` | string | Associated evaluation task ID |
| `created_at` | datetime | Workflow creation time |
| `updated_at` | datetime | Last update time |

### 4.4 Evaluation Task Lifecycle

```
    +-----------------+     claim      +------------------+     report     +------------+
    | pending_reports | ------------> | in_progress      | ------------>  | completed  |
    +-----------------+               +------------------+                +------------+
                                              |
                                              | timeout/error
                                              v
                                        +---------+
                                        | expired |
                                        +---------+
```

**Evaluation modes:**

| Mode | Validators | Trigger |
|------|-----------|---------|
| `single` | 1 validator | Default for Step 1 evaluations |
| `peer_review` | Up to 5 validators | Triggered when consensus is needed |

---

## 5. Public API (no auth)

**Base Path**: `/api/public/v1`  
**Authentication**: None required

### 5.1 Signature Config

```
GET /api/public/v1/signature-config
```

See [Section 1.1](#11-signature-configuration) for full response.

### 5.2 Protocol Info

```
GET /api/public/v1/protocol-info
```

**Response:**
```json
{
  "success": true,
  "data": {
    "min_stake": "10000000000000000000000",
    "min_stake_formatted": "10000 AWP",
    "chain_id": 8453,
    "chain_name": "Base",
    "registration_url": "https://api.awp.sh/v2"
  }
}
```

### 5.3 Network Stats

```
GET /api/public/v1/stats
```

**Response:**
```json
{
  "success": true,
  "data": {
    "online_miners": 42,
    "online_validators": 8,
    "current_epoch": "2026-04-09"
  }
}
```

### 5.4 Health Endpoints

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| `GET` | `/health` | Liveness probe | `{"status": "ok"}` |
| `GET` | `/healthz` | Legacy liveness (deprecated) | `{"status": "ok"}` |
| `GET` | `/ready` | Readiness probe (Core + Mining) | `{"status": "ready"}` |
| `GET` | `/readyz` | Legacy readiness (deprecated) | `{"status": "ready"}` |
| `GET` | `/metrics` | Prometheus metrics (OpenMetrics) | Prometheus text format |

**Error codes:** `service_not_ready` (503) when dependencies are not ready.

---

## 6. IAM Module

**Base Path**: `/api/iam/v1`  
**Authentication**: All endpoints require EIP-712 signature

### 6.1 Get Current Identity

```
GET /api/iam/v1/me
```

**Permission**: `iam.me.read` (min role: `member`)

**Response:**
```json
{
  "success": true,
  "data": {
    "subject": "0x1234...abcd",
    "role": "miner",
    "issuer": ""
  }
}
```

### 6.2 Submit Validator Application

```
POST /api/iam/v1/validator-applications
```

**Permission**: `iam.validator.apply` (min role: `member`)  
**Request Body**: None required (address taken from authentication)

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "app-uuid",
    "address": "0x1234...abcd",
    "status": "approved",
    "submitted_at": "2026-04-09T10:00:00Z",
    "reviewed_at": "2026-04-09T10:00:00Z",
    "reviewed_by": "auto"
  }
}
```

**Notes:**
- Applications are **auto-approved** if the applicant meets staking requirements (>= 10000 AWP) and validator capacity is available.
- Allowlisted addresses bypass stake checks (`reviewed_by: "allowlist"`).
- If capacity is full, the applicant can replace a lower-staked validator.

**Error codes:**

| HTTP | Code | Description |
|------|------|-------------|
| 409 | `validator_application_exists` | Application already exists |
| 403 | `insufficient_stake` | Stake below minimum (includes `requirements.min_stake`) |
| 409 | `validator_capacity_full` | No capacity and cannot replace any validator |
| 403 | `role_suspended` | Identity is suspended |

### 6.3 Get My Validator Application

```
GET /api/iam/v1/validator-applications/me
```

**Permission**: `iam.validator.apply` (min role: `member`)

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "app-uuid",
    "address": "0x1234...abcd",
    "status": "approved",
    "submitted_at": "2026-04-09T10:00:00Z",
    "reviewed_at": "2026-04-09T10:00:00Z",
    "reviewed_by": "auto"
  }
}
```

**When no application exists (HTTP 200 with `success: false`):**
```json
{
  "success": false,
  "error": {
    "code": "validator_application_not_found",
    "category": "not_found",
    "message": "validator application not found",
    "retryable": false,
    "recoverable": false,
    "recovery_strategy": "stop"
  }
}
```

**Important**: This endpoint returns HTTP 200 even for not-found errors. Frontend must check `success` field, not HTTP status code.

### 6.4 List Validator Applications (Admin)

```
GET /api/iam/v1/validator-applications
```

**Permission**: `iam.validator.list` (min role: `admin`)  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "app-uuid",
      "address": "0x1234...abcd",
      "status": "approved",
      "submitted_at": "2026-04-09T10:00:00Z",
      "reviewed_at": "2026-04-09T10:00:00Z",
      "reviewed_by": "auto"
    }
  ]
}
```

### 6.5 Review Validator Application (Admin)

```
POST /api/iam/v1/validator-applications/:id/review
```

**Permission**: `iam.validator.review` (min role: `admin`)

**Request:**
```json
{
  "decision": "approve",
  "rejection_reason": ""
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `decision` | string | Yes | `"approve"` or `"reject"` |
| `rejection_reason` | string | No | Reason for rejection |

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "app-uuid",
    "address": "0x1234...abcd",
    "status": "approved",
    "submitted_at": "...",
    "reviewed_at": "...",
    "reviewed_by": "0xadmin..."
  }
}
```

**Error codes:** `validator_application_reviewed` (409), `invalid_review_decision` (400)

---

## 7. Core Module

**Base Path**: `/api/core/v1`

### 7.1 Datasets

#### List Datasets (Public)

```
GET /api/core/v1/datasets
```

**Authentication**: Not required  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "dataset_id": "ds_posts",
      "name": "Twitter Posts",
      "creator": "0x1234...",
      "creation_fee": "100",
      "status": "active",
      "source_domains": ["twitter.com", "x.com"],
      "schema": { "post_id": {"type":"string","required":true}, "content": {"type":"string","required":true} },
      "dedup_fields": ["post_id"],
      "url_patterns": ["https?://x\\.com/.+/status/\\d+"],
      "refresh_interval": "24h",
      "created_at": "2026-04-01T00:00:00Z",
      "reviewed_at": "2026-04-01T01:00:00Z",
      "reviewed_by": "0xadmin...",
      "total_entries": 1500
    }
  ]
}
```

**Note on optional fields**: `updated_at`, `reviewed_at`, `rejection_reason`, `refresh_interval` use `omitempty` -- they are **absent from the JSON** (not empty strings) when unset. Frontend code should check for field existence, not empty string.

#### Get Dataset (Public)

```
GET /api/core/v1/datasets/:id
```

**Authentication**: Not required  
**Response**: Same shape as a single item in the list above.  
**Error codes:** `dataset_not_found` (404)

#### Create Dataset

```
POST /api/core/v1/datasets
```

**Permission**: `core.datasets.create` (min role: `member`)

**Request:**
```json
{
  "name": "Twitter Posts",
  "creation_fee": "100",
  "source_domains": ["twitter.com", "x.com"],
  "schema": {
    "post_id": { "type": "string", "required": true },
    "content": { "type": "string", "required": true },
    "author": { "type": "string", "required": true },
    "timestamp": { "type": "datetime" }
  },
  "dedup_fields": ["post_id"],
  "url_patterns": ["https?://x\\.com/.+/status/\\d+"],
  "refresh_interval": "24h"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Dataset name |
| `creation_fee` | string | No | Fee for creation |
| `source_domains` | string[] | No | Allowed source domains |
| `schema` | object | Yes | Arbitrary valid JSON; at least 3 fields recommended |
| `dedup_fields` | string[] | Yes | Fields used for dedup hash |
| `url_patterns` | string[] | No | Go-compatible regex patterns |
| `refresh_interval` | string | No | Refresh interval (e.g. "24h") |

**Error codes:** `invalid_request` (400)

#### Review Dataset (Admin)

```
POST /api/core/v1/datasets/:id/review
```

**Permission**: `core.datasets.review` (min role: `admin`)

**Request:**
```json
{
  "decision": "approve",
  "rejection_reason": ""
}
```

**Error codes:** `dataset_not_found` (404), `invalid_review_decision` (400)

#### Dataset Status Management (Admin)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/datasets/:id/status` | `core.datasets.status` | Set arbitrary status |
| `POST` | `/datasets/:id/activate` | `core.datasets.activate` | Activate dataset |
| `POST` | `/datasets/:id/pause` | `core.datasets.pause` | Pause dataset |
| `POST` | `/datasets/:id/archive` | `core.datasets.archive` | Archive dataset |
| `POST` | `/datasets/:id/reject` | `core.datasets.reject` | Reject dataset |

**Status Transitions:**
```
pending_review -> active (approve)
pending_review -> rejected (reject)
active <-> paused
active -> archived
paused -> archived
```

**`/datasets/:id/status` Request:**
```json
{ "status": "active" }
```

**`/datasets/:id/reject` Request (optional body):**
```json
{ "reason": "Insufficient data quality criteria" }
```

**Error codes:** `dataset_not_found` (404), `dataset_not_active` (409)

### 7.2 Epochs

#### List Epochs (Public)

```
GET /api/core/v1/epochs
```

**Authentication**: Not required  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Response item:**
```json
{
  "id": "epoch-uuid",
  "epoch_id": "2026-04-09",
  "status": "completed",
  "summary": {
    "total": 1000,
    "confirmed": 950,
    "rejected": 50
  },
  "window_start_at": "2026-04-09T00:00:00Z",
  "window_end_at": "2026-04-10T00:00:00Z",
  "settlement_started_at": "2026-04-10T00:00:05Z",
  "settlement_completed_at": "2026-04-10T00:01:00Z",
  "created_at": "2026-04-09T00:00:00Z",
  "updated_at": "2026-04-10T00:01:00Z"
}
```

**Epoch Status Values**: `open`, `settling`, `completed`, `failed`

#### Get Epoch (Public)

```
GET /api/core/v1/epochs/:epochID
```

**Authentication**: Not required

#### Current Epoch Shortcut (Public)

```
GET /api/core/v1/epochs/current
```

**Authentication**: Not required  
Returns the current epoch without needing to list all epochs.

#### Settle Epoch (Admin)

```
POST /api/core/v1/epochs/:epochID/settle
```

**Permission**: `core.epochs.settle` (min role: `admin`)

### 7.3 Dataset Stats (Public)

```
GET /api/core/v1/datasets/:id/stats
```

**Authentication**: Not required  
Returns submission statistics for a specific dataset.

### 7.4 Deduplication

#### Check Dedup Hash (Public)

```
GET /api/core/v1/dedup/check?dataset_id=ds_posts&dedup_hash=abc123
```

**Authentication**: Not required

**Response:**
```json
{
  "success": true,
  "data": {
    "dataset_id": "ds_posts",
    "dedup_hash": "abc123",
    "exists": true
  }
}
```

#### List Dedup Occupancies (Public)

```
GET /api/core/v1/dedup-occupancies
```

**Authentication**: Not required  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Note:** The `dedup_occupancies` table has been removed. This endpoint queries the `submissions` table directly using the partial unique index (`WHERE status != 'rejected'`).

**Response item:**
```json
{
  "dataset_id": "ds_posts",
  "dedup_hash": "abc123...",
  "submission_id": "sub-uuid",
  "submission_status": "confirmed",
  "occupied": true,
  "updated_at": "2026-04-09T10:00:00Z"
}
```

#### Get Dedup Occupancy (Public)

```
GET /api/core/v1/dedup-occupancies/:datasetId/:dedupHash
```

**Authentication**: Not required

#### Check Dedup Occupancy by Structured Data (Public)

```
POST /api/core/v1/dedup-occupancies/check
```

**Authentication**: Not required

**Request:**
```json
{
  "dataset_id": "ds_posts",
  "structured_data": {
    "post_id": "12345"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "dataset_id": "ds_posts",
    "dedup_hash": "computed-hash",
    "occupied": true,
    "submission_status": "confirmed"
  }
}
```

### 7.5 URL Occupancy Check (Public)

```
GET /api/core/v1/url/check?dataset_id=ds_posts&url=https://x.com/user/status/12345
```

**Authentication**: Not required  
Checks whether a URL is already occupied for a given dataset.

### 7.6 Protocol Configuration (Admin)

#### List Protocol Configs

```
GET /api/core/v1/protocol-configs
GET /api/core/v1/protocol-configs?key=sampling_rate
```

**Permission**: `core.protocol_configs.read` (min role: `admin`)

**Response item:**
```json
{
  "key": "sampling_rate",
  "scope": "",
  "value": "0.30",
  "description": "Submission sampling rate",
  "updated_at": "2026-04-01T00:00:00Z"
}
```

**Note**: `updated_at` is omitted from the response when the config has never been updated.

#### Get Protocol Config

```
GET /api/core/v1/protocol-configs/:key
GET /api/core/v1/protocol-configs/:key?scope=ds_posts
```

#### Set Protocol Config

```
PUT /api/core/v1/protocol-configs
```

**Permission**: `core.protocol_configs.write` (min role: `admin`)

**Request:**
```json
{
  "key": "sampling_rate",
  "scope": "",
  "value": "0.30",
  "description": "Submission sampling rate"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | Yes | Config key |
| `scope` | string | No | `""` for global, dataset ID for per-dataset |
| `value` | string | Yes | Config value (parsed by consumers) |
| `description` | string | No | Human-readable description |

#### Delete Protocol Config

```
DELETE /api/core/v1/protocol-configs/:key
DELETE /api/core/v1/protocol-configs/:key?scope=ds_posts
```

**Permission**: `core.protocol_configs.write` (min role: `admin`)

#### Default Protocol Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `sampling_rate` | `"0.30"` | Submission sampling rate (30%) |
| `epoch_emission` | `"10000"` | Total ocDATA emitted per epoch |
| `validator_ratio` | `"5"` | Miner:Validator capacity ratio |
| `miner_reward_share` | `"0.41"` | Miner reward pool share |
| `validator_reward_share` | `"0.41"` | Validator reward pool share |
| `owner_reward_share` | `"0.18"` | Owner reward pool share |
| `min_stake` | `"10000000000000000000000"` | Min validator stake (10000 AWP in wei) |
| `emission_weight` | Per-dataset | Reward weight per dataset |

### 7.7 Submissions (Core-forwarded, DEPRECATED)

> **DEPRECATED**: These endpoints are backward-compatibility shims that forward to the Mining service. New integrations should use the Mining module endpoints at `/api/mining/v1/submissions` (see Section 8.4) instead. These forwarding routes will be removed in a future release.

Submission endpoints under `/api/core/v1` forward to the Mining service. They behave identically to the Mining module endpoints but use the Core path prefix.

#### Submit Data Entries

```
POST /api/core/v1/submissions
```

**Permission**: `mining.submission.create` (allowed: `miner` only via core forwarding)

**Request:**
```json
{
  "dataset_id": "ds_posts",
  "entries": [
    {
      "url": "https://x.com/user/status/12345",
      "cleaned_data": "This is the post content...",
      "structured_data": {
        "post_id": "12345",
        "content": "This is the post content...",
        "author": "user"
      },
      "crawl_timestamp": "2026-04-09T10:00:00Z"
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_id` | string | Yes | Target dataset ID |
| `entries` | array | Yes | Submission entries |
| `entries[].url` | string | Yes | Source URL |
| `entries[].cleaned_data` | string | Yes | Cleaned text content |
| `entries[].structured_data` | object | Yes | Structured fields matching dataset schema |
| `entries[].crawl_timestamp` | string | Yes | Crawl timestamp (RFC 3339, e.g. `"2026-04-09T10:00:00Z"`) |

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| `admission_status` | string | `"accepted"` or `"challenge_required"` |
| `accepted` | array | Accepted submissions |
| `rejected` | array | Rejected entries with reasons |
| `challenge_required` | bool | Legacy boolean (mining path only, omitted on core path). Use `admission_status` instead. |
| `challenge` | object | PoW challenge (when `admission_status` = `"challenge_required"`) |
| `next_action` | object | Next step hint (when challenge required) |

**Response (201 Created -- `admission_status` = `"accepted"`):**
```json
{
  "success": true,
  "data": {
    "admission_status": "accepted",
    "accepted": [
      {
        "id": "sub-uuid",
        "dataset_id": "ds_posts",
        "miner_id": "0x1234...",
        "epoch_id": "2026-04-09",
        "original_url": "https://x.com/user/status/12345",
        "normalized_url": "https://x.com/user/status/12345",
        "dedup_hash": "abc123...",
        "high_risk": false,
        "cleaned_data": "This is the post content...",
        "structured_data": { "post_id": "12345", "content": "...", "author": "user" },
        "crawl_timestamp": "2026-04-09T10:00:00Z",
        "status": "pending",
        "refresh_of_submission_id": "",
        "created_at": "2026-04-09T10:00:00Z"
      }
    ],
    "rejected": [
      {
        "url": "https://x.com/user/status/99999",
        "reason": "duplicate"
      }
    ]
  }
}
```

**Response (428 Precondition Required -- `admission_status` = `"challenge_required"`):**
```json
{
  "success": true,
  "data": {
    "admission_status": "challenge_required",
    "accepted": [],
    "challenge": {
      "id": "pow_abc123",
      "miner_id": "0x1234...",
      "epoch_id": "2026-04-09",
      "dataset_id": "ds_posts",
      "schema_key": "posts",
      "question_id": "hashcash-v1",
      "question_version": 1,
      "question_type": "hash_challenge",
      "prompt": "Compute SHA256(\"f47ac10b-58cc-4372-a567-0e02b2c3d479\") and return the first 8 hex characters.",
      "validation_meta": { "nonce": "f47ac10b-58cc-4372-a567-0e02b2c3d479" },
      "created_at": "2026-04-09T10:00:00Z",
      "expires_at": "2026-04-09T10:05:00Z"
    },
    "next_action": {
      "action": "answer_pow_challenge",
      "method": "POST",
      "path": "/api/mining/v1/pow-challenges/pow_abc123/answer",
      "description": "Answer the PoW challenge to unlock submission"
    }
  }
}
```

**SubmissionResponse fields (15 fields):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Submission ID |
| `dataset_id` | string | Dataset ID |
| `miner_id` | string | Miner address |
| `epoch_id` | string | Epoch date |
| `original_url` | string | Original URL as submitted |
| `normalized_url` | string | Normalized URL |
| `dedup_hash` | string | Dedup hash (omitempty) |
| `high_risk` | bool | High-risk flag (omitempty) |
| `cleaned_data` | string | Cleaned text content (omitempty) |
| `structured_data` | object | Structured data (omitempty) |
| `crawl_timestamp` | datetime | Crawl timestamp |
| `status` | string | `"pending"`, `"confirmed"`, or `"rejected"` |
| `refresh_of_submission_id` | string | If this is a refresh, the original submission ID (omitempty) |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp (omitempty, null if never updated) |

**Admission Status Values:**
- `"accepted"` -- All valid entries were accepted (HTTP 201)
- `"challenge_required"` -- PoW challenge triggered (HTTP 428); entries are held pending challenge completion

**Per-Entry Rejection Reasons:**
- `url_pattern_mismatch` -- URL doesn't match dataset patterns
- `duplicate` -- Duplicate entry within same batch
- `dedup_hash_in_cooldown` -- Dedup hash in cooldown period
- `url_already_occupied` -- URL already occupied
- `malformed` -- Entry validation failed
- `submission_too_frequent` -- Submission interval too short
- `dataset_not_active` -- Dataset is not active
- `internal_error` -- Server error

**Error codes:** `invalid_request` (400), `dataset_not_found` (404), `dataset_not_active` (409), `miner_not_found` (404), `miner_offline` (409), `submission_too_frequent` (429), `rate_limit_exceeded` (429), `persistence_unavailable` (503)

#### List Submissions

```
GET /api/core/v1/submissions
```

**Permission**: `mining.submission.read` (allowed: `miner`, `validator`)  
**Query Parameters**: `page` (default 1), `page_size` (default 50, max 200)

**Note**: Non-admin callers automatically see only their own submissions (the server filters by the caller's miner_id).

#### Get Submission

```
GET /api/core/v1/submissions/:id
```

**Permission**: `mining.submission.read`

**Note**: Non-admin callers can only view their own submissions. Attempting to view another miner's submission returns `403 forbidden`.

### 7.8 Validation Results (Core-forwarded, DEPRECATED)

> **DEPRECATED**: These endpoints are backward-compatibility shims that forward to the Mining service. New integrations should use the Mining module endpoints at `/api/mining/v1/validation-results` (see Section 8.5) instead. These forwarding routes will be removed in a future release.

#### Create Validation Result

```
POST /api/core/v1/validation-results
```

**Permission**: `mining.validation_result.create` (allowed: `validator` only)

**Request:**
```json
{
  "submission_id": "sub-uuid",
  "verdict": "accepted",
  "score": 85,
  "comment": "Data quality is good",
  "idempotency_key": "unique-key"
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `submission_id` | string | Yes | Target submission |
| `verdict` | string | Yes | `"accepted"` or `"rejected"` |
| `score` | int | Yes | 0-100 |
| `comment` | string | No | Human-readable comment |
| `idempotency_key` | string | No | Unique key to prevent duplicates |

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "vr-uuid",
    "submission_id": "sub-uuid",
    "validator_id": "0x5678...",
    "verdict": "accepted",
    "score": 85,
    "comment": "Data quality is good",
    "idempotency_key": "unique-key",
    "created_at": "2026-04-09T10:00:00Z"
  }
}
```

**Error codes:** `invalid_validation_result` (400), `submission_not_found` (404), `duplicate_submission` (409)

#### List Validation Results

```
GET /api/core/v1/validation-results?submission_id=sub-uuid
```

**Permission**: `mining.validation_result.read` (allowed: `miner`, `validator`, `admin`)

**Required query parameter**: `submission_id`

**Note**: Results are auto-filtered by role:
- **Miner**: must own the referenced submission
- **Validator**: sees only their own evaluations
- **Admin**: sees all results

#### Get Validation Result

```
GET /api/core/v1/validation-results/:id
```

**Permission**: `mining.validation_result.read`

**Note**: Ownership is enforced per role:
- **Validator**: can view their own evaluations
- **Miner**: can view results for their own submissions
- **Admin**: can view all results

**Error codes:** `validation_result_not_found` (404), `forbidden` (403)

---

## 8. Mining Module

**Base Path**: `/api/mining/v1`

### 8.1 Heartbeat

```
POST /api/mining/v1/heartbeat
```

**Permission**: `mining.heartbeat` (allowed: `member`, `miner`, `validator`)

**Request:**
```json
{
  "client": "miner-cli/1.0"
}
```

**Response (Miner):**
```json
{
  "success": true,
  "data": {
    "role": "miner",
    "miner": {
      "miner_id": "0x1234...",
      "ip_address": "203.0.113.10",
      "client": "miner-cli/1.0",
      "last_heartbeat_at": "2026-04-09T10:00:00Z",
      "online": true,
      "credit": 65,
      "credit_tier": "good",
      "epoch_submit_limit": 10000,
      "pow_probability": 0.05
    }
  }
}
```

**Response (Validator):**
```json
{
  "success": true,
  "data": {
    "role": "validator",
    "validator": {
      "validator_id": "0x5678...",
      "credit": 85,
      "eligible": true,
      "credit_tier": "excellent",
      "min_task_interval_seconds": 10
    }
  }
}
```

**Notes:**
- `member` role is auto-promoted to `miner` on first heartbeat call
- The response type depends on the caller's role (`miner` or `validator`)
- Heartbeat should be called every **60 seconds**; TTL is **120 seconds** (offline if no heartbeat within this window)
- After a successful submission (not heartbeat), the system probabilistically transitions the miner's submission state (see Section 4.1)

**Error codes:** `identity_binding_failed` (500)

### 8.2 PoW Challenge Flow

This is the complete PoW challenge flow with actual JSON examples. The PoW uses dynamic SHA256 challenges (NOT a static question bank).

#### Step 1: Send Heartbeat

```
POST /api/mining/v1/heartbeat
Content-Type: application/json

{ "client": "miner-cli/1.0" }
```

**Response:**
```json
{
  "success": true,
  "data": {
    "role": "miner",
    "miner": {
      "miner_id": "0xABCD1234...",
      "ip_address": "203.0.113.10",
      "client": "miner-cli/1.0",
      "last_heartbeat_at": "2026-04-09T10:00:00Z",
      "online": true,
      "credit": 65,
      "credit_tier": "good",
      "epoch_submit_limit": 10000,
      "pow_probability": 0.05
    }
  }
}
```

#### Step 2: Submit Entries (triggers challenge)

```
POST /api/mining/v1/submissions
Content-Type: application/json

{
  "dataset_id": "ds_posts",
  "entries": [
    {
      "url": "https://x.com/alice/status/123456",
      "cleaned_data": "Hello world from Alice",
      "structured_data": { "post_id": "123456", "content": "Hello world from Alice", "author": "alice" },
      "crawl_timestamp": "2026-04-09T10:00:00Z"
    }
  ]
}
```

**Response (428 -- challenge required because miner is in `checking` state):**
```json
{
  "success": true,
  "data": {
    "admission_status": "challenge_required",
    "accepted": [],
    "challenge": {
      "id": "pow_e8b5c7a2-4f3d-4e1a-9b2c-8d7e6f5a4b3c",
      "miner_id": "0xABCD1234...",
      "epoch_id": "2026-04-09",
      "dataset_id": "ds_posts",
      "schema_key": "posts",
      "question_id": "hashcash-v1",
      "question_version": 1,
      "question_type": "hash_challenge",
      "prompt": "Compute SHA256(\"f47ac10b-58cc-4372-a567-0e02b2c3d479\") and return the first 8 hex characters.",
      "validation_meta": { "nonce": "f47ac10b-58cc-4372-a567-0e02b2c3d479" },
      "created_at": "2026-04-09T10:00:05Z",
      "expires_at": "2026-04-09T10:05:05Z"
    },
    "next_action": {
      "action": "answer_pow_challenge",
      "method": "POST",
      "path": "/api/mining/v1/pow-challenges/pow_e8b5c7a2-4f3d-4e1a-9b2c-8d7e6f5a4b3c/answer",
      "description": "Answer the PoW challenge to unlock submission"
    }
  },
  "meta": { "request_id": "req-uuid-1" }
}
```

#### Step 3: Answer the Challenge

To compute the answer:
```python
import hashlib
nonce = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
h = hashlib.sha256(nonce.encode()).digest()
answer = h[:4].hex()  # first 4 bytes = 8 hex characters
# answer = "a1b2c3d4" (example)
```

```
POST /api/mining/v1/pow-challenges/pow_e8b5c7a2-4f3d-4e1a-9b2c-8d7e6f5a4b3c/answer
Content-Type: application/json

{ "answer": "a1b2c3d4" }
```

**Response (passed):**
```json
{
  "success": true,
  "data": {
    "challenge_id": "pow_e8b5c7a2-4f3d-4e1a-9b2c-8d7e6f5a4b3c",
    "miner_id": "0xABCD1234...",
    "passed": true,
    "answered_at": "2026-04-09T10:00:10Z",
    "next_action": {
      "action": "retry_submission",
      "method": "POST",
      "path": "/api/mining/v1/submissions",
      "description": "Resubmit the original entries now that PoW is passed"
    }
  },
  "meta": { "request_id": "req-uuid-2" }
}
```

**Response (failed -- wrong answer or expired):**
```json
{
  "success": true,
  "data": {
    "challenge_id": "pow_e8b5c7a2-...",
    "miner_id": "0xABCD1234...",
    "passed": false,
    "answered_at": "2026-04-09T10:00:10Z"
  }
}
```

Note: When `passed` is `false`, there is no `next_action`. The miner must get a new challenge via the submission gate or by retrying submission.

**Error codes:** `challenge_not_found` (404)

#### Step 4: Resubmit (now in `opening` state)

```
POST /api/mining/v1/submissions
Content-Type: application/json

{
  "dataset_id": "ds_posts",
  "entries": [
    {
      "url": "https://x.com/alice/status/123456",
      "cleaned_data": "Hello world from Alice",
      "structured_data": { "post_id": "123456", "content": "Hello world from Alice", "author": "alice" },
      "crawl_timestamp": "2026-04-09T10:00:00Z"
    }
  ]
}
```

**Response (201 -- accepted):**
```json
{
  "success": true,
  "data": {
    "admission_status": "accepted",
    "accepted": [
      {
        "id": "sub_7f8a9b0c...",
        "dataset_id": "ds_posts",
        "miner_id": "0xABCD1234...",
        "epoch_id": "2026-04-09",
        "original_url": "https://x.com/alice/status/123456",
        "normalized_url": "x.com/alice/status/123456",
        "dedup_hash": "e3b0c44298...",
        "high_risk": false,
        "cleaned_data": "Hello world from Alice",
        "structured_data": { "post_id": "123456", "content": "Hello world from Alice", "author": "alice" },
        "crawl_timestamp": "2026-04-09T10:00:00Z",
        "status": "pending",
        "created_at": "2026-04-09T10:00:15Z"
      }
    ]
  },
  "meta": { "request_id": "req-uuid-3" }
}
```

### 8.3 Submission Gate

Check the miner's current submission gate state without attempting a submission.

```
GET /api/mining/v1/miners/me/submission-gate
```

**Permission**: `mining.miner.submission_gate` (allowed: `miner`, `validator`)

**Response (opening state -- can submit):**
```json
{
  "success": true,
  "data": {
    "state": "opening",
    "can_submit": true
  }
}
```

**Response (checking state -- PoW required):**
```json
{
  "success": true,
  "data": {
    "state": "checking",
    "can_submit": false,
    "challenge": {
      "id": "pow_abc123...",
      "miner_id": "0x1234...",
      "epoch_id": "2026-04-09",
      "dataset_id": "",
      "schema_key": "generic",
      "question_id": "hashcash-v1",
      "question_version": 1,
      "question_type": "hash_challenge",
      "prompt": "Compute SHA256(\"<nonce>\") and return the first 8 hex characters.",
      "validation_meta": { "nonce": "<nonce>" },
      "created_at": "2026-04-09T10:00:00Z",
      "expires_at": "2026-04-09T10:05:00Z"
    },
    "next_action": {
      "action": "answer_pow_challenge",
      "method": "POST",
      "path": "/api/mining/v1/pow-challenges/pow_abc123.../answer",
      "description": "Answer the PoW challenge to unlock submission"
    }
  }
}
```

**Error codes:** `miner_not_found` (404), `miner_offline` (409)

### 8.4 Submissions (Mining path)

The Mining module has its own submission endpoints that are functionally equivalent to the Core-forwarded ones.

#### Submit Data Entries

```
POST /api/mining/v1/submissions
```

**Permission**: `mining.submission.create` (allowed: `miner`, `validator`)

This is the **primary submission endpoint**. Request and response format is documented in Section 7.7 (which describes the deprecated Core-forwarded equivalent). The mining path includes a legacy `challenge_required` boolean field alongside `admission_status`.

#### List Submissions

```
GET /api/mining/v1/submissions
```

**Permission**: `mining.submission.read` (allowed: `miner`, `validator`)

#### Get Submission

```
GET /api/mining/v1/submissions/:id
```

**Permission**: `mining.submission.read`

### 8.5 Validation Results (Mining path)

#### Create Validation Result

```
POST /api/mining/v1/validation-results
```

**Permission**: `mining.validation_result.create` (allowed: `validator`)

This is the **primary validation result endpoint**. Request and response format is documented in Section 7.8 (which describes the deprecated Core-forwarded equivalent).

#### List Validation Results

```
GET /api/mining/v1/validation-results?submission_id=sub-uuid
```

**Permission**: `mining.validation_result.read` (allowed: `miner`, `validator`)

#### Get Validation Result

```
GET /api/mining/v1/validation-results/:id
```

**Permission**: `mining.validation_result.read`

### 8.6 Ready Pool Management

#### Miner Ready Pool

```
POST /api/mining/v1/miners/ready      # Join ready pool
POST /api/mining/v1/miners/unready    # Leave ready pool
```

**Permission**: `mining.miner.ready` / `mining.miner.unready` (allowed: `miner` only)

**Response:**
```json
{
  "success": true,
  "data": {
    "miner_id": "0x1234...",
    "status": "ready"
  }
}
```

#### Validator Ready Pool

```
POST /api/mining/v1/validators/ready      # Join ready pool
POST /api/mining/v1/validators/unready    # Leave ready pool
```

**Permission**: `mining.validator.ready` / `mining.validator.unready` (allowed: `miner`, `validator`)

**Response:**
```json
{
  "success": true,
  "data": {
    "validator_id": "0x5678...",
    "status": "ready"
  }
}
```

### 8.7 Refresh Tasks

| Method | Path | Permission | Auth |
|--------|------|-----------|------|
| `POST` | `/refresh-tasks` | `mining.refresh.create` | admin |
| `POST` | `/refresh-tasks/claim` | `mining.refresh.claim` | miner |
| `POST` | `/refresh-tasks/:id/report` | `mining.refresh.report` | miner |
| `GET` | `/refresh-tasks` | `mining.refresh.list` | admin |
| `GET` | `/refresh-tasks/:id` | `mining.refresh.list` | admin |

**Create Request:**
```json
{
  "epoch_id": "2026-04-09",
  "dataset_id": "ds_posts",
  "url": "https://x.com/user/status/12345",
  "historical_miner_ids": ["0xold1..."],
  "excluded_ips": ["1.2.3.4"]
}
```

**Report Request:**
```json
{
  "cleaned_data": "Re-crawled content..."
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "task-uuid",
    "epoch_id": "2026-04-09",
    "dataset_id": "ds_posts",
    "url": "https://x.com/user/status/12345",
    "assigned_miner_id": "0x1234...",
    "status": "completed",
    "submission_id": "sub-uuid"
  }
}
```

### 8.8 Repeat Crawl Tasks

| Method | Path | Permission | Auth |
|--------|------|-----------|------|
| `POST` | `/repeat-crawl-tasks` | `mining.repeat.create` | admin |
| `POST` | `/repeat-crawl-tasks/claim` | `mining.repeat.claim` | miner |
| `POST` | `/repeat-crawl-tasks/:id/report` | `mining.repeat.report` | miner |
| `POST` | `/repeat-crawl-tasks/:id/reject` | `mining.repeat.reject` | miner |
| `POST` | `/repeat-crawl-tasks/:id/reassign` | `mining.repeat.reassign` | admin |
| `GET` | `/repeat-crawl-tasks` | `mining.repeat.list` | admin |
| `GET` | `/repeat-crawl-tasks/:id` | `mining.repeat.list` | admin |

**Claim Response:**
```json
{
  "success": true,
  "data": {
    "id": "task-uuid",
    "epoch_id": "2026-04-09",
    "submission_id": "sub-uuid",
    "dataset_id": "ds_posts",
    "url": "https://x.com/user/status/12345",
    "step": 1,
    "assigned_miner_id": "0x1234...",
    "status": "in_progress",
    "phase_a_result": "pending",
    "step_two_task_id": "",
    "miner_score": 0
  }
}
```

**Report Request:**
```json
{
  "cleaned_data": "Re-crawled content for comparison..."
}
```

**Reject Request:** No body required.

**Reassign Request (Admin):**
```json
{
  "assigned_miner_id": "0xnewminer..."
}
```

**Error codes:** `repeat_task_not_found` (404)

#### Core-Derived Repeat Task

```
POST /api/mining/v1/core-submissions/:id/repeat-crawl-tasks
```

**Permission**: `mining.core_submission.repeat` (min role: `admin`)

**Request:**
```json
{
  "epoch_id": "2026-04-09"
}
```

### 8.9 Evaluation Tasks

| Method | Path | Permission | Auth |
|--------|------|-----------|------|
| `POST` | `/evaluation-tasks` | `mining.evaluation.create` | admin |
| `POST` | `/evaluation-tasks/claim` | `mining.evaluation.claim` | miner, validator |
| `POST` | `/evaluation-tasks/:id/report` | `mining.evaluation.report` | miner, validator |
| `GET` | `/evaluation-tasks` | `mining.evaluation.list` | admin |
| `GET` | `/evaluation-tasks/:id` | `mining.evaluation.list` | admin |

#### Claim Evaluation Task

```
POST /api/mining/v1/evaluation-tasks/claim
```

**Permission**: `mining.evaluation.claim` (allowed: `miner`, `validator`)

**Response:**
```json
{
  "success": true,
  "data": {
    "task_id": "eval-task-uuid",
    "assignment_id": "assign-uuid",
    "validator_id": "0x5678...",
    "dataset_id": "ds_posts",
    "cleaned_data": "Original miner submission content (M0)...",
    "repeat_cleaned_data": "Re-crawled content (M1) for comparison...",
    "structured_data": {
      "post_id": "12345",
      "content": "Original content...",
      "author": "user"
    },
    "schema_fields": ["author", "content", "post_id"],
    "dataset_schema": {
      "post_id": { "type": "string", "required": true },
      "content": { "type": "string", "required": true },
      "author": { "type": "string", "required": true }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Evaluation task ID |
| `assignment_id` | string | Assignment ID (use in report) |
| `validator_id` | string | Validator address |
| `dataset_id` | string | Dataset ID |
| `cleaned_data` | string | Original miner submission (M0) |
| `repeat_cleaned_data` | string | Re-crawled data (M1) for comparison; empty if Step 1 |
| `structured_data` | object | Original structured data |
| `schema_fields` | string[] | Schema field names (sorted) |
| `dataset_schema` | object | Full dataset schema definition |

**Error codes:** `evaluation_task_not_found` (404), `validator_not_ready` (409)

#### Report Evaluation Task

```
POST /api/mining/v1/evaluation-tasks/:id/report
```

**Permission**: `mining.evaluation.report` (allowed: `miner`, `validator`)

**Request:**
```json
{
  "assignment_id": "assign-uuid",
  "result": "match",
  "score": 92
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `assignment_id` | string | Yes | Assignment ID from claim |
| `result` | string | No | `"match"` or `"mismatch"` |
| `score` | int | Yes | Quality score 0-100 |

**Result Values:**
- `"match"` -- The original data (M0) matches the re-crawled data (M1); the submission is authentic
- `"mismatch"` -- The data does not match; possible fraud or significant deviation

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "eval-task-uuid",
    "epoch_id": "2026-04-09",
    "submission_id": "sub-uuid",
    "miner_id": "0x1234...",
    "mode": "single",
    "status": "completed",
    "miner_score": 92
  }
}
```

#### Core-Derived Evaluation Task

```
POST /api/mining/v1/core-submissions/:id/evaluation-tasks
```

**Permission**: `mining.core_submission.evaluation` (min role: `admin`)

**Request:**
```json
{
  "epoch_id": "2026-04-09",
  "golden_score": 88
}
```

### 8.10 Golden Tasks (Admin)

Golden tasks are benchmark evaluation tasks with known expected scores. They are used to calibrate validator accuracy. Validators cannot distinguish golden tasks from regular evaluation tasks.

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/golden-tasks` | `mining.golden_task.manage` | Create golden task |
| `GET` | `/golden-tasks` | `mining.golden_task.manage` | List all golden tasks |
| `PUT` | `/golden-tasks/:id` | `mining.golden_task.manage` | Update golden task |
| `DELETE` | `/golden-tasks/:id` | `mining.golden_task.manage` | Delete golden task |

All require **admin** role.

#### Create Golden Task

```
POST /api/mining/v1/golden-tasks
```

**Request:**
```json
{
  "dataset_id": "ds_posts",
  "url": "https://x.com/alice/status/12345",
  "cleaned_data": "Known good content...",
  "structured_data": {
    "post_id": "12345",
    "content": "Known good content...",
    "author": "alice"
  },
  "expected_score": 90,
  "source": "manual",
  "source_submission_id": ""
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_id` | string | Yes | Dataset ID |
| `url` | string | Yes | Source URL |
| `cleaned_data` | string | Yes | Known-good cleaned data |
| `structured_data` | object | No | Known-good structured data |
| `expected_score` | int | Yes | Expected quality score (0-100) |
| `source` | string | No | `"manual"` (default) or `"auto_mined"` |
| `source_submission_id` | string | No | Original submission ID if auto-mined |

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "golden-uuid",
    "dataset_id": "ds_posts",
    "url": "https://x.com/alice/status/12345",
    "cleaned_data": "Known good content...",
    "structured_data": { ... },
    "expected_score": 90,
    "source": "manual",
    "source_submission_id": "",
    "enabled": true,
    "used_count": 0,
    "created_at": "2026-04-09T10:00:00Z",
    "updated_at": "0001-01-01T00:00:00Z"
  }
}
```

#### Update Golden Task

```
PUT /api/mining/v1/golden-tasks/:id
```

**Request:**
```json
{
  "id": "golden-uuid",
  "enabled": false,
  "expected_score": 85
}
```

#### Delete Golden Task

```
DELETE /api/mining/v1/golden-tasks/:id
```

**Error codes:** `golden_task_not_found` (equivalent -- returns not found), `persistence_unavailable` (503)

### 8.11 Self-Service Stats

#### Get My Miner Stats

```
GET /api/mining/v1/miners/me/stats
```

**Permission**: `mining.miner.stats.self` (allowed: `miner` only)

**Response:**
```json
{
  "success": true,
  "data": {
    "miner_id": "0x1234...",
    "ip_address": "203.0.113.10",
    "client": "miner-cli/1.0",
    "last_heartbeat_at": "2026-04-09T10:00:00Z",
    "credit": 65,
    "ready_pool_opt_in": true,
    "consecutive_fail": 0,
    "timeout_history": [false, false, true, false, false],
    "evicted_until_epoch": ""
  }
}
```

#### Get My Validator Stats

```
GET /api/mining/v1/validators/me/stats
```

**Permission**: `mining.validator.stats.self` (allowed: `validator` only)

**Response:**
```json
{
  "success": true,
  "data": {
    "validator_id": "0x5678...",
    "ip_address": "203.0.113.20",
    "client": "validator-cli/1.0",
    "last_heartbeat_at": "2026-04-09T10:00:00Z",
    "last_task_completed_at": "2026-04-09T09:55:00Z",
    "credit": 85,
    "eligible": true,
    "ready_pool_opt_in": true,
    "consecutive_fail": 0,
    "consecutive_flag": 0,
    "idle_history": [false, false, false, false, false],
    "flag_history": [false, false, false, false, false],
    "timeout_history": [false, false, false, false, false],
    "evicted_until_epoch": "",
    "consecutive_unclaimed": 0,
    "unclaimed_cooldown_until": "0001-01-01T00:00:00Z",
    "stake_amount": "15000000000000000000000",
    "joined_epoch": "2026-04-01"
  }
}
```

#### Get My Submissions (Miner)

```
GET /api/mining/v1/miners/me/submissions
```

**Permission**: `mining.miner.submissions.self` (allowed: `miner` only)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "sub-uuid",
      "dataset_id": "ds_posts",
      "miner_id": "0x1234...",
      "epoch_id": "2026-04-09",
      "status": "confirmed"
    }
  ]
}
```

### 8.12 Public Read Endpoints

#### List All Miners (Public)

```
GET /api/mining/v1/miners
```

**Authentication**: Not required

**Response item:**
```json
{
  "miner_id": "0x1234...",
  "credit": 65,
  "credit_tier": "good",
  "online": true,
  "client": "miner-cli/1.0",
  "last_heartbeat_at": "2026-04-09T10:00:00Z"
}
```

#### Get Miner Profile (Public)

```
GET /api/mining/v1/profiles/miners/:address
```

**Authentication**: Not required

**Response:**
```json
{
  "success": true,
  "data": {
    "miner_id": "0x1234...",
    "credit": 65,
    "credit_tier": "good",
    "online": true,
    "client": "miner-cli/1.0",
    "last_heartbeat_at": "2026-04-09T10:00:00Z"
  }
}
```

#### Get Miner Epoch History (Public)

```
GET /api/mining/v1/profiles/miners/:address/epochs
```

**Authentication**: Not required  
Returns the last 100 epochs for the given miner.

**Response item:**
```json
{
  "epoch_id": "2026-04-09",
  "task_count": 50,
  "avg_score": 78.5,
  "qualified": true,
  "weight": 0.15,
  "reward_amount": 615.0
}
```

#### Get Validator Epoch History (Public)

```
GET /api/mining/v1/profiles/validators/:address/epochs
```

**Authentication**: Not required

#### Get Address Profile (Public)

```
GET /api/mining/v1/profiles/:address
```

**Authentication**: Not required  
Returns combined miner + validator profile for an address, including lifetime stats and current epoch stats.

**Response:**
```json
{
  "success": true,
  "data": {
    "address": "0x1234...",
    "miner": {
      "miner_id": "0x1234...",
      "credit": 65,
      "credit_tier": "good",
      "online": true
    },
    "validator": null,
    "miner_summary": {
      "total_epochs": 30,
      "total_tasks": 1500,
      "total_rewards": 45000.0,
      "avg_score": 82.5
    },
    "validator_summary": null,
    "current_epoch": {
      "epoch_id": "2026-04-09",
      "miner": {
        "task_count": 50,
        "pending_submission_count": 5,
        "repeat_task_count": 3,
        "sampled_score_count": 8,
        "avg_score": 85.0
      },
      "validator": {
        "eval_count": 0,
        "golden_count": 0,
        "peer_count": 0,
        "accuracy": 0,
        "peer_review_accuracy": 0
      }
    }
  }
}
```

#### List Online Miners (Public)

```
GET /api/mining/v1/miners/online
```

**Authentication**: Not required

**Response item:**
```json
{
  "miner_id": "0x1234...",
  "client": "miner-cli/1.0",
  "last_heartbeat_at": "2026-04-09T10:00:00Z",
  "online": true,
  "credit": 65
}
```

#### List Online Validators (Public)

```
GET /api/mining/v1/validators/online
```

**Authentication**: Not required

**Response item:**
```json
{
  "validator_id": "0x5678...",
  "client": "validator-cli/1.0",
  "last_heartbeat_at": "2026-04-09T10:00:00Z",
  "online": true,
  "credit": 85,
  "eligible": true,
  "ready": true
}
```

#### Epoch Snapshot (Public)

```
GET /api/mining/v1/epochs/:id/snapshot
```

**Authentication**: Not required

**Response:**
```json
{
  "success": true,
  "data": {
    "epoch_id": "2026-04-09",
    "miners": {
      "0x1234...": {
        "task_count": 50,
        "avg_score": 78.5
      }
    },
    "validators": {
      "0x5678...": {
        "eval_count": 20,
        "accuracy": 92.3,
        "peer_review_accuracy": 88.5,
        "consecutive_idle": 0
      }
    }
  }
}
```

#### Epoch Settlement Results (Public)

```
GET /api/mining/v1/epochs/:id/settlement-results
```

**Authentication**: Not required

**Response:**
```json
{
  "success": true,
  "data": {
    "epoch_id": "2026-04-09",
    "miners": [
      {
        "miner_id": "0x1234...",
        "task_count": 50,
        "avg_score": 78.5,
        "qualified": true,
        "weight": 0.15,
        "reward_amount": 615.0,
        "confirmed_submission_count": 48,
        "rejected_submission_count": 2
      }
    ],
    "validators": [
      {
        "validator_id": "0x5678...",
        "eval_count": 20,
        "accuracy": 92.3,
        "peer_review_accuracy": 88.5,
        "consecutive_idle": 0,
        "qualified": true,
        "weight": 0.25,
        "reward_amount": 1025.0,
        "slashed_amount": 0,
        "redistributed_amount": 0,
        "penalty_reason": ""
      }
    ]
  }
}
```

### 8.13 Admin Stats

#### Get Miner Stats (Admin)

```
GET /api/mining/v1/miners/:id/stats
```

**Permission**: `mining.miners.stats.read` (min role: `admin`)

Same response shape as `GET /miners/me/stats` (Section 8.11).

#### Get Validator Stats (Admin)

```
GET /api/mining/v1/validators/:id/stats
```

**Permission**: `mining.validators.stats.read` (min role: `admin`)

Same response shape as `GET /validators/me/stats` (Section 8.11).

---

## 9. WebSocket Realtime Channel

### 9.1 Connection

```
GET /api/mining/v1/ws
```

**Permission**: `mining.ws` (min role: `member`)  
**Protocol**: WebSocket upgrade with EIP-712 auth headers on the HTTP upgrade request

### 9.2 Server -> Client Messages

**Repeat Crawl Task Push:**
```json
{
  "type": "repeat_crawl_task",
  "data": {
    "id": "task-uuid",
    "epoch_id": "2026-04-09",
    "submission_id": "sub-uuid",
    "dataset_id": "ds_posts",
    "url": "https://x.com/user/status/12345",
    "step": 1,
    "assigned_miner_id": "0x1234...",
    "status": "pending",
    "phase_a_result": "pending",
    "step_two_task_id": "",
    "miner_score": 0
  }
}
```

**Evaluation Task Push:**
```json
{
  "type": "evaluation_task",
  "data": {
    "task_id": "eval-task-uuid",
    "assignment_id": "assign-uuid",
    "validator_id": "0x5678...",
    "dataset_id": "ds_posts",
    "cleaned_data": "M0 content...",
    "repeat_cleaned_data": "M1 content...",
    "structured_data": { ... },
    "schema_fields": ["field1", "field2"],
    "dataset_schema": { ... }
  }
}
```

### 9.3 Client -> Server Messages

**Acknowledge Repeat Crawl Task:**
```json
{ "ack": "task-uuid" }
```

**Acknowledge Evaluation Task:**
```json
{ "ack_eval": "assignment-uuid" }
```

**Reject Repeat Crawl Task:**
```json
{ "reject": "task-uuid" }
```

### 9.4 Timing

- Send buffer: **64 messages** per client
- ACK deadline: **30 seconds** (task returned to pool if not acknowledged)
- Repeat crawl lease: **5 minutes** after claiming
- Evaluation lease: **10 minutes** after claiming
- If 3 consecutive tasks go unclaimed: **1-hour cooldown** from ready pool

---

## 10. Error Reference Table

Complete table of all error codes returned by the platform.

| Error Code | HTTP | Category | Retryable | Recoverable | Recovery Strategy | Hint |
|-----------|------|----------|-----------|-------------|-------------------|------|
| `unauthorized` | 401 | authentication | false | false | stop | Check auth headers |
| `missing_auth_headers` | 401 | authentication | false | true | fix_request | Include all required EIP-712 headers |
| `invalid_signature` | 401 | authentication | false | true | fix_request | Verify signature computation |
| `signer_mismatch` | 401 | authentication | false | true | fix_request | Recovered signer != X-Signer |
| `request_expired` | 401 | authentication | false | true | fix_request | Regenerate with fresh timestamps |
| `nonce_reused` | 401 | authentication | false | true | fix_request | Use a unique nonce |
| `forbidden` | 403 | permission | false | false | switch_identity | Insufficient role |
| `role_suspended` | 403 | permission | false | false | request_human_help | Identity is suspended |
| `ownership_required` | 403 | permission | false | false | stop | Caller does not own the resource |
| `insufficient_stake` | 428 | precondition | false | true | increase_stake | Stake below minimum (mining path returns 428, IAM path returns 403) |
| `address_not_registered` | 428 | precondition | true | true | register_address | Register on Base (chainId=8453) |
| `invalid_request` | 400 | validation | false | true | fix_request | Malformed request body |
| `invalid_review_decision` | 400 | validation | false | true | fix_request | Decision must be "approve" or "reject" |
| `invalid_validation_result` | 400 | validation | false | true | fix_request | Invalid validation result input |
| `url_pattern_mismatch` | 400 | validation | false | true | fix_request | URL does not match dataset patterns |
| `malformed_submission` | 400 | validation | false | true | fix_request | Check required fields |
| `dataset_not_found` | 404 | not_found | false | false | stop | Verify dataset_id |
| `submission_not_found` | 404 | not_found | false | false | stop | Verify submission ID |
| `validation_result_not_found` | 404 | not_found | false | false | stop | Verify validation result ID |
| `miner_not_found` | 404 | not_found | false | false | stop | Send heartbeat first |
| `evaluation_task_not_found` | 404 | not_found | false | false | stop | Task not found |
| `repeat_task_not_found` | 404 | not_found | false | false | stop | Task not found |
| `challenge_not_found` | 404 | not_found | false | false | stop | PoW challenge not found |
| `quality_workflow_not_found` | 404 | not_found | false | false | stop | Workflow not found |
| `dataset_not_active` | 409 | state_conflict | false | false | stop | Dataset is paused or archived |
| `duplicate_submission` | 409 | state_conflict | false | false | stop | Dedup hash already occupied |
| `dedup_hash_in_cooldown` | 409 | state_conflict | true | true | wait_and_retry | Retry after cooldown expires |
| `miner_offline` | 409 | dependency | true | true | retry_same_request | Send heartbeat first (mining handler uses `dependency` category) |
| `validator_application_exists` | 409 | state_conflict | false | false | stop | Already applied |
| `validator_application_reviewed` | 409 | state_conflict | false | false | stop | Already reviewed |
| `validator_capacity_full` | 409 | state_conflict | false | false | stop | No validator slots available |
| `validator_capacity_all_protected` | 409 | state_conflict | false | false | stop | All validators in protection period |
| `validator_not_ready` | 409 | dependency | true | true | retry_same_request | Join ready pool first |
| `submission_too_frequent` | 429 | rate_limit | true | true | retry_same_request | Wait before submitting again |
| `submission_rate_limited` | 429 | rate_limit | false | false | wait_next_epoch | Epoch quota exhausted (mining path) |
| `rate_limit_exceeded` | 429 | rate_limit | false | false | wait_next_epoch | Epoch quota exhausted (core forwarding path) |
| `persistence_unavailable` | 503 | dependency | true | true | retry_same_request | Database not available |
| `service_not_ready` | 503 | dependency | true | true | retry_same_request | Service dependencies not ready |
| `registration_backend_unavailable` | 503 | dependency | true | true | retry_same_request | On-chain check backend down |
| `identity_store_unavailable` | 503 | dependency | true | true | retry_same_request | Identity store unavailable |
| `nonce_store_unavailable` | 503 | dependency | true | true | retry_same_request | Nonce store unavailable |
| `internal_error` | 500 | internal | false | false | request_human_help | Check server logs with request_id |
| `identity_binding_failed` | 500 | internal | false | false | request_human_help | Failed to bind miner role |

---

## 11. Miner Workflow

Step-by-step guide for an LLM operating as a miner.

### 11.1 Initialization

```
1. GET /api/public/v1/signature-config
   -> Obtain EIP-712 domain params for signing

2. POST /api/mining/v1/heartbeat  { "client": "miner-cli/1.0" }
   -> Auto-promoted from member to miner
   -> Note: credit, credit_tier, epoch_submit_limit, pow_probability

3. GET /api/core/v1/datasets  (filter status="active" client-side)
   -> Get list of active datasets with schema and url_patterns
```

### 11.2 Main Loop (repeat every 60s)

```
4. POST /api/mining/v1/heartbeat  { "client": "miner-cli/1.0" }
   -> Refresh online status and credit info
   -> Note pow_probability for current credit tier

5. (Optional) Check submission gate:
   GET /api/mining/v1/miners/me/submission-gate
   -> If state="checking", answer the PoW challenge first
   -> If state="opening", proceed to submit

6. (Optional) Pre-check dedup:
   GET /api/core/v1/dedup/check?dataset_id=...&dedup_hash=...
   -> Skip if already occupied

7. Submit Data:
   POST /api/mining/v1/submissions
   -> If admission_status="accepted" (HTTP 201): done
   -> If admission_status="challenge_required" (HTTP 428):
      a. Extract challenge.id from response
      b. Compute SHA256(nonce) -> take first 8 hex chars
      c. POST /api/mining/v1/pow-challenges/<id>/answer
         { "answer": "<8_hex_chars>" }
      d. If passed=true, follow next_action to resubmit
      e. If passed=false, get new challenge via submission gate

8. Join Ready Pool:
   POST /api/mining/v1/miners/ready

9. Handle Repeat Crawl Tasks:
   Option A (polling): POST /api/mining/v1/repeat-crawl-tasks/claim
   Option B (WebSocket): Connect to /api/mining/v1/ws
     -> Receive {"type":"repeat_crawl_task", ...}
     -> Send {"ack":"task-id"} within 30 seconds
     -> Re-crawl the URL
     -> POST /api/mining/v1/repeat-crawl-tasks/:id/report
        { "cleaned_data": "re-crawled content" }

10. View Own Stats:
    GET /api/mining/v1/miners/me/stats
    GET /api/mining/v1/miners/me/submissions
```

### 11.3 Submission Rate Limit

Submissions are rate-limited per miner. The minimum interval is `max(avg_interval/5, 30s)` where `avg_interval = elapsed_epoch_time / pending_submission_count`. If exceeded, returns 429 `submission_too_frequent`.

### 11.4 Key Display Fields

| Field | Source | Display |
|-------|--------|---------|
| Credit score | heartbeat -> `credit` | Progress bar 0-100 |
| Credit tier | heartbeat -> `credit_tier` | Badge (novice/restricted/normal/good/excellent) |
| Submit limit | heartbeat -> `epoch_submit_limit` | Remaining quota |
| PoW probability | heartbeat -> `pow_probability` | Percentage |
| Online status | heartbeat -> `online` | Green/red indicator |

---

## 12. Validator Workflow

Step-by-step guide for an LLM operating as a validator.

### 12.1 Initialization

```
1. GET /api/public/v1/protocol-info
   -> Check min_stake requirement (10000 AWP)

2. POST /api/iam/v1/validator-applications
   -> Apply as validator (auto-approved if stake >= 10000 AWP)

3. GET /api/iam/v1/validator-applications/me
   -> Check application status (approved/pending/rejected)
```

### 12.2 Main Loop (repeat every 60s)

```
4. POST /api/mining/v1/heartbeat  { "client": "validator-cli/1.0" }
   -> Returns: credit, eligible, credit_tier, min_task_interval_seconds

5. POST /api/mining/v1/validators/ready
   -> Join ready pool to receive evaluation tasks

6. Claim & Complete Evaluation Tasks:
   Option A (polling): POST /api/mining/v1/evaluation-tasks/claim
   Option B (WebSocket): Connect to /api/mining/v1/ws
     -> Receive {"type":"evaluation_task", ...}
     -> Send {"ack_eval":"assignment-id"} within 30 seconds
     -> Compare cleaned_data (M0) vs repeat_cleaned_data (M1)
     -> Determine match/mismatch
     -> Score structured_data quality against schema_fields
     -> POST /api/mining/v1/evaluation-tasks/:id/report
        { "assignment_id": "...", "result": "match", "score": 85 }

7. Respect min_task_interval_seconds between claims

8. View Own Stats:
   GET /api/mining/v1/validators/me/stats
```

### 12.3 Evaluation Logic

When evaluating a claimed task:

1. **Compare M0 vs M1**: Check if `cleaned_data` (original submission) and `repeat_cleaned_data` (re-crawled data) represent the same content
2. **Determine result**: `"match"` if authentic, `"mismatch"` if data appears fabricated or significantly different
3. **Score quality**: Rate the structured_data quality (0-100) based on completeness, accuracy, and adherence to schema_fields
4. **Golden tasks**: Some tasks are golden (benchmark) tasks where the system knows the expected score; your accuracy contributes to your reputation. Golden status is not exposed in the claim response

### 12.4 Key Display Fields

| Field | Source | Display |
|-------|--------|---------|
| Credit score | heartbeat -> `credit` | Progress bar 0-100 |
| Credit tier | heartbeat -> `credit_tier` | Badge |
| Eligible | heartbeat -> `eligible` | Can receive tasks |
| Min interval | heartbeat -> `min_task_interval_seconds` | Seconds between tasks |
| Stake amount | stats -> `stake_amount` | AWP staked |
| Accuracy | settlement -> `accuracy` | Performance metric |

---

## 13. Admin Workflow

### 13.1 Dataset Management

```
1. Create Dataset:
   POST /api/core/v1/datasets

2. Review Dataset:
   POST /api/core/v1/datasets/:id/review

3. Lifecycle Management:
   POST /api/core/v1/datasets/:id/activate
   POST /api/core/v1/datasets/:id/pause
   POST /api/core/v1/datasets/:id/archive
   POST /api/core/v1/datasets/:id/reject
```

### 13.2 Protocol Configuration

```
GET  /api/core/v1/protocol-configs           # List all configs
PUT  /api/core/v1/protocol-configs           # Set config
DELETE /api/core/v1/protocol-configs/:key    # Delete config
```

### 13.3 Epoch Settlement

```
GET  /api/core/v1/epochs                     # List epochs
GET  /api/core/v1/epochs/current             # Current epoch
POST /api/core/v1/epochs/:epochID/settle     # Manual settlement
GET  /api/mining/v1/epochs/:id/snapshot      # View snapshot
GET  /api/mining/v1/epochs/:id/settlement-results  # View results
```

### 13.4 Participant Monitoring

```
GET /api/mining/v1/miners                    # All miners (public)
GET /api/mining/v1/miners/online             # Online miners
GET /api/mining/v1/validators/online         # Online validators
GET /api/mining/v1/miners/:id/stats          # Miner details (admin)
GET /api/mining/v1/validators/:id/stats      # Validator details (admin)
```

### 13.5 Validator Application Management

```
GET  /api/iam/v1/validator-applications           # List all applications
POST /api/iam/v1/validator-applications/:id/review # Review application
```

### 13.6 Task Management

```
GET  /api/mining/v1/repeat-crawl-tasks       # List repeat tasks
POST /api/mining/v1/repeat-crawl-tasks/:id/reassign  # Reassign task
GET  /api/mining/v1/evaluation-tasks         # List evaluation tasks
GET  /api/mining/v1/refresh-tasks            # List refresh tasks
```

### 13.7 Golden Task Management

```
POST   /api/mining/v1/golden-tasks           # Create golden task
GET    /api/mining/v1/golden-tasks           # List golden tasks
PUT    /api/mining/v1/golden-tasks/:id       # Update golden task
DELETE /api/mining/v1/golden-tasks/:id       # Delete golden task
```

---

## 14. Timing Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Heartbeat interval | 60 seconds | How often to call heartbeat |
| Heartbeat TTL | 120 seconds | Offline if no heartbeat within this |
| Repeat crawl lease | 5 minutes | Time to complete repeat task |
| Evaluation lease | 10 minutes | Time to complete evaluation |
| Claim deadline | 30 seconds | ACK WebSocket task push |
| Unclaimed cooldown | 1 hour | After 3 consecutive unclaimed |
| PoW challenge TTL | 5 minutes | Time to answer challenge |
| Epoch duration | 24 hours | UTC 00:00 - 00:00 |
| Cooldown (rejected data) | 1 epoch | Dedup hash blocked |
| High-risk period | 3 epochs | 100% sampling rate |
| Consistency threshold | 75 | Score threshold for consistency |
| Dynamic threshold | 50 | Lower threshold for dynamic evaluation |
| Max golden tasks per epoch | 10 | System-wide cap per epoch |
| Signature max validity | 300 seconds | Max EIP-712 signature window |
| Clock skew tolerance | 30 seconds | Server-side clock skew allowance |
| Max request body | 8 MB | Maximum request body size |

---

## Appendix A: Permission Matrix

| Permission Key | Access | Endpoints |
|---------------|--------|-----------|
| `iam.me.read` | min: member | `GET /api/iam/v1/me` |
| `iam.validator.apply` | min: member | `POST /api/iam/v1/validator-applications`, `GET .../me` |
| `iam.validator.review` | min: admin | `POST /api/iam/v1/validator-applications/:id/review` |
| `iam.validator.list` | min: admin | `GET /api/iam/v1/validator-applications` |
| `core.datasets.create` | min: member | `POST /api/core/v1/datasets` |
| `core.datasets.review` | min: admin | `POST .../datasets/:id/review` |
| `core.datasets.status` | min: admin | `POST .../datasets/:id/status` |
| `core.datasets.activate` | min: admin | `POST .../datasets/:id/activate` |
| `core.datasets.pause` | min: admin | `POST .../datasets/:id/pause` |
| `core.datasets.archive` | min: admin | `POST .../datasets/:id/archive` |
| `core.datasets.reject` | min: admin | `POST .../datasets/:id/reject` |
| `mining.submission.read` | allowed: miner, admin | `GET .../submissions`, `GET .../submissions/:id` (core forwarding uses mining permissions) |
| `mining.submission.create` | allowed: miner | `POST .../submissions` (core forwarding uses mining permissions) |
| `core.url_occupancies.read` | allowed: miner | `GET .../url-occupancies/...` |
| `mining.validation_result.read` | allowed: miner, validator, admin | `GET .../validation-results/...` |
| `mining.validation_result.create` | allowed: validator | `POST .../validation-results` |
| `core.epochs.read` | min: admin | `GET .../epochs` (protected), `GET .../epochs/:id` |
| `core.epochs.settle` | min: admin | `POST .../epochs/:epochID/settle` |
| `core.protocol_configs.read` | min: admin | `GET .../protocol-configs/...` |
| `core.protocol_configs.write` | min: admin | `PUT/DELETE .../protocol-configs/...` |
| `mining.heartbeat` | allowed: member, miner, validator | `POST /api/mining/v1/heartbeat` |
| `mining.miner.ready` | allowed: miner | `POST .../miners/ready` |
| `mining.miner.unready` | allowed: miner | `POST .../miners/unready` |
| `mining.pow.answer` | allowed: miner | `POST .../pow-challenges/:id/answer` |
| `mining.miner.submission_gate` | allowed: miner, validator | `GET .../miners/me/submission-gate` |
| `mining.submission.create` | allowed: miner, validator | `POST .../submissions` |
| `mining.submission.read` | allowed: miner, validator | `GET .../submissions`, `GET .../submissions/:id` |
| `mining.validation_result.create` | allowed: validator | `POST .../validation-results` |
| `mining.validation_result.read` | allowed: miner, validator | `GET .../validation-results/...` |
| `mining.refresh.create` | min: admin | `POST .../refresh-tasks` |
| `mining.refresh.list` | min: admin | `GET .../refresh-tasks/...` |
| `mining.refresh.claim` | allowed: miner | `POST .../refresh-tasks/claim` |
| `mining.refresh.report` | allowed: miner | `POST .../refresh-tasks/:id/report` |
| `mining.repeat.create` | min: admin | `POST .../repeat-crawl-tasks` |
| `mining.repeat.list` | min: admin | `GET .../repeat-crawl-tasks/...` |
| `mining.repeat.claim` | allowed: miner | `POST .../repeat-crawl-tasks/claim` |
| `mining.repeat.report` | allowed: miner | `POST .../repeat-crawl-tasks/:id/report` |
| `mining.repeat.reject` | allowed: miner | `POST .../repeat-crawl-tasks/:id/reject` |
| `mining.repeat.reassign` | min: admin | `POST .../repeat-crawl-tasks/:id/reassign` |
| `mining.validator.ready` | allowed: miner, validator | `POST .../validators/ready` |
| `mining.validator.unready` | allowed: miner, validator | `POST .../validators/unready` |
| `mining.evaluation.create` | min: admin | `POST .../evaluation-tasks` |
| `mining.evaluation.list` | min: admin | `GET .../evaluation-tasks/...` |
| `mining.evaluation.claim` | allowed: miner, validator | `POST .../evaluation-tasks/claim` |
| `mining.evaluation.report` | allowed: miner, validator | `POST .../evaluation-tasks/:id/report` |
| `mining.core_submission.repeat` | min: admin | `POST .../core-submissions/:id/repeat-crawl-tasks` |
| `mining.core_submission.evaluation` | min: admin | `POST .../core-submissions/:id/evaluation-tasks` |
| `mining.epoch.snapshot.read` | min: admin | `GET .../epochs/:id/snapshot` (policy exists but endpoint is public) |
| `mining.epoch.settlement.read` | min: admin | `GET .../epochs/:id/settlement-results` (policy exists but endpoint is public) |
| `mining.miners.stats.read` | min: admin | `GET .../miners/:id/stats` |
| `mining.validators.stats.read` | min: admin | `GET .../validators/:id/stats` |
| `mining.miner.stats.self` | allowed: miner | `GET .../miners/me/stats` |
| `mining.validator.stats.self` | allowed: validator | `GET .../validators/me/stats` |
| `mining.miner.submissions.self` | allowed: miner | `GET .../miners/me/submissions` |
| `mining.golden_task.manage` | min: admin | `POST/GET/PUT/DELETE .../golden-tasks/...` |
| `mining.ws` | min: member | `GET .../ws` |

**Public endpoints (no authentication required):**

| Endpoint | Description |
|----------|-------------|
| `GET /api/public/v1/signature-config` | EIP-712 signature configuration |
| `GET /api/public/v1/protocol-info` | Protocol info (min_stake, chain, registration URL) |
| `GET /api/public/v1/stats` | Network overview (online miners/validators, current epoch) |
| `GET /api/core/v1/datasets` | List datasets |
| `GET /api/core/v1/datasets/:id` | Get dataset |
| `GET /api/core/v1/datasets/:id/stats` | Dataset submission stats |
| `GET /api/core/v1/epochs` | List epochs |
| `GET /api/core/v1/epochs/current` | Current epoch shortcut |
| `GET /api/core/v1/epochs/:epochID` | Get epoch |
| `GET /api/core/v1/dedup/check` | Check dedup hash |
| `GET /api/core/v1/url/check` | URL occupancy check |
| `GET /api/core/v1/dedup-occupancies` | List dedup occupancies |
| `GET /api/core/v1/dedup-occupancies/:datasetId/:dedupHash` | Get dedup occupancy |
| `POST /api/core/v1/dedup-occupancies/check` | Check dedup occupancy by structured data |
| `GET /api/mining/v1/miners` | List all miners |
| `GET /api/mining/v1/miners/online` | List online miners |
| `GET /api/mining/v1/validators/online` | List online validators |
| `GET /api/mining/v1/profiles/miners/:address` | Get miner public profile |
| `GET /api/mining/v1/profiles/miners/:address/epochs` | Miner epoch history (last 100) |
| `GET /api/mining/v1/profiles/validators/:address/epochs` | Validator epoch history |
| `GET /api/mining/v1/profiles/:address` | Combined address profile |
| `GET /api/mining/v1/epochs/:id/snapshot` | Epoch snapshot |
| `GET /api/mining/v1/epochs/:id/settlement-results` | Epoch settlement results |

**Notes**:
- `allowed:` permissions use **exact role matching** -- admin does NOT inherit. Only the listed roles can access.
- `min:` permissions use **role hierarchy** -- admin inherits all lower roles.
- Ownership enforcement: `submissions/:id` and `validation-results/:id` return `403 forbidden` for non-admin callers viewing resources they do not own.
- Internal errors use safe generic messages; details are in server logs only (use `request_id` to correlate).

---

## Appendix B: Dedup Hash Computation

The dedup hash is computed as:
```
SHA256(field1_value | field2_value | ... | fieldN_value)
```

Where fields are taken from the dataset's `dedup_fields` array in order, separated by `|`, using values from `structured_data`.

---

## Appendix C: Credit System

### C.1 Credit Tiers

Both miners and validators use a 0-100 credit score system.

| Score Range | Tier | Description |
|-------------|------|-------------|
| 80-100 | `excellent` | Highest trust level |
| 60-79 | `good` | Standard trusted participant |
| 40-59 | `normal` | Moderate trust |
| 20-39 | `restricted` | Under observation |
| 0-19 | `novice` | New or penalized participant |

### C.2 Miner Credit Effects

| Tier | Sampling Rate | Epoch Submit Limit | PoW Probability |
|------|--------------|-------------------|-----------------|
| `excellent` (80+) | Base rate (0.30) | 1,000,000 | 1% |
| `good` (60-79) | Base rate (0.30) | 10,000 | 5% |
| `normal` (40-59) | 1.5x base (max 1.0) | 2,000 | 20% |
| `restricted` (20-39) | 2.0x base (max 1.0) | 500 | 50% |
| `novice` (0-19) | 1.0 (100%) | 100 | 100% |

### C.3 Validator Credit Effects

| Tier | Min Task Interval | Min Eval Count | Golden Task Probability |
|------|-------------------|----------------|------------------------|
| `excellent` (80+) | 10 seconds | 10 | 5% |
| `good` (60-79) | 30 seconds | 10 | 10% |
| `normal` (40-59) | 2 minutes | 10 | 20% |
| `restricted` (20-39) | 5 minutes | 10 | 30% |
| `novice` (0-19) | 10 minutes | 3 | 40% |

### C.4 Credit Adjustment (Per Epoch)

**Miners:**
- Qualified: +5 (cap at 100)
- Not qualified: -15 (floor at 0), consecutive_fail + 1
- 3+ consecutive failures: credit reset to 0

**Validators:**
- Accuracy >= 60%: +5 (cap at 100), consecutive_flag reset to 0
- Accuracy < 60%: -15, consecutive_flag + 1
- Accuracy < 20%: credit reset to 0

### C.5 Validator Eviction Rules

| Rule | Window | Threshold | Penalty |
|------|--------|-----------|---------|
| **Idle** | 3-of-10 | 3 idle epochs in last 10 | Evict 1 epoch, -15 credit |
| **Flag** | 4-of-10 | 4 flagged (accuracy < 60%) in last 10 | Evict 1 epoch, -15 credit |
| **Timeout** | 4-of-10 | 4 timeouts in last 10 | Evict 1 epoch |
| **Unclaimed** | 3 consecutive | 3 consecutive unclaimed tasks | 1-hour cooldown |

---

## Appendix D: Epoch & Settlement

### D.1 Epoch Lifecycle

- **Duration**: 1 UTC natural day (00:00 - 00:00 UTC)
- **Epoch ID format**: `"YYYY-MM-DD"` (e.g. `"2026-04-09"`)
- **Auto-settlement**: Triggered at UTC 00:00 daily
- **Manual settlement**: Admin can trigger via `POST /api/core/v1/epochs/:epochID/settle`

### D.2 Settlement Formula

**Miner Reward**:
```
effectiveTaskCount = mineCount + repeatCount * 0.8
weight = avgScore * avgScore * effectiveTaskCount
rewardAmount = epochEmission * minerRewardShare * (weight / totalMinerWeight)
```

**Validator Reward**:
```
weight = accuracy * accuracy * evalCount
rewardAmount = epochEmission * validatorRewardShare * (weight / totalValidatorWeight)
```

**Qualification Requirements**:
- Miner: `task_count >= 80` (configurable) and `avg_score >= 60` (configurable)
- Validator: `eval_count >= 10` required; accuracy < 20% -> disqualified; accuracy 20-60% -> qualified but penalized

### D.3 Validator Penalties

| Penalty | Trigger | Credit Effect | Additional |
|---------|---------|--------------|------------|
| `severe_misbehavior` | accuracy < 20% | Disqualified, reset to 0 | Excluded from reward pool |
| `misbehavior` | accuracy 20-60% | -15, flag++ | Reward slashed and redistributed |
| `low_quality` | -- | -15 | None |
| `idle` | eval_count < 10 | -15 | None |

---

## Appendix E: Quality Assurance Pipeline

### E.1 Pipeline Overview

```
Miner submits data (M0)
    -> Sampling decision (credit-based rate)
    -> If sampled:
        Phase A: Repeat Crawl (Step 1)
            -> Different miner re-crawls same URL -> produces M1
            -> Evaluation Task created
        Phase B: Evaluation
            -> Validator compares M0 vs M1
            -> Reports "match" (authentic) or "mismatch" (suspicious)
            -> If match: score applied, submission confirmed/rejected
            -> If mismatch: Step 2 triggered
        Phase A: Repeat Crawl (Step 2, if mismatch)
            -> Third miner re-crawls -> produces M2
            -> New Evaluation Task created
        Phase B: Final Evaluation
            -> Validator compares M0 vs M2
            -> Final determination
```

### E.2 Match/Mismatch Consensus (Peer Review)

When multiple validators evaluate the same task:
- **Match consensus**: >= 3/5 validators agree on "match" -> submission scored
- **Mismatch consensus**: >= 3/5 validators agree on "mismatch" -> Step 2 triggered or fraud confirmed
- **No consensus**: All validators reported but no majority -> scored using available data

### E.3 Scoring Scenarios

**Scenario 1** (Step 1 Match): M0 scored with validator's score. M0 repeat score = 5.

**Scenario 2** (Step 1 Mismatch -> Step 2 Match): M0 confirmed authentic. M0 repeat score = 5, M1 repeat score = 0.

**Scenario 3** (Step 1 Mismatch -> Step 2 Mismatch): M0 confirmed fraudulent (score = 0). M0 repeat score = 0, M1 repeat score = 5.

### E.4 Reward Weight

Effective task count for reward calculation:
```
effectiveTaskCount = mineCount + repeatCount * 0.8
```

Repeat tasks count at 80% weight compared to original mining tasks.
