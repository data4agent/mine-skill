# Frontend Skill Development Guide

> **Version**: 2.0 (2026-04-06)  
> **Base URL**: `http://<host>:8080`  
> **Framework**: Gin (Go)

This document serves as a comprehensive reference for developing frontend applications that interact with the ocDATA Data Mining Platform. It covers authentication, all API endpoints, request/response schemas, WebSocket integration, credit systems, and error handling.

---

## Table of Contents

1. [Authentication (EIP-712)](#1-authentication-eip-712)
2. [Response Envelope](#2-response-envelope)
3. [Roles & Permissions](#3-roles--permissions)
4. [Health & Monitoring](#4-health--monitoring)
5. [Public API](#5-public-api)
6. [IAM Module](#6-iam-module)
7. [Core Module](#7-core-module)
8. [Mining Module](#8-mining-module)
9. [WebSocket Realtime Channel](#9-websocket-realtime-channel)
10. [Credit System](#10-credit-system)
11. [Quality Assurance Workflow](#11-quality-assurance-workflow)
12. [Epoch & Settlement](#12-epoch--settlement)
13. [Timing Parameters](#13-timing-parameters)
14. [Error Handling](#14-error-handling)
15. [Miner Frontend Workflow](#15-miner-frontend-workflow)
16. [Validator Frontend Workflow](#16-validator-frontend-workflow)
17. [Admin Frontend Workflow](#17-admin-frontend-workflow)

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

**Legacy format** (UUID nonce or RFC3339 timestamps — `UseLegacyType = true`):

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

**Zero Hash**: `0x0000000000000000000000000000000000000000000000000000000000000000` (64 zero nibbles). Used for ALL empty fields — do NOT use `keccak256("")`.

**Body Hash**:
- Empty body or `nil` → **zero hash**
- `application/json` with valid JSON → canonicalize body per RFC 8785, then `keccak256(canonicalized_bytes)`
- If JSON canonicalization fails → `keccak256(raw_body_bytes)`
- Other content types → `keccak256(raw_body_bytes)`

**Query Hash**:
- No query parameters → **zero hash**
- Sort query parameter keys alphabetically
- For each key, sort its values alphabetically
- URL-encode both key and value with `url.QueryEscape`
- Join as `key1=val1&key1=val2&key2=val3`
- Hash: `keccak256(joined_string)`

**Headers Hash**:
- No signed headers (or `X-Signed-Headers` not set) → **zero hash**
- `X-Signed-Headers` is parsed by splitting on `,`, lowercasing, and **sorting alphabetically**
- For each signed header: join multiple values with `,`, trim and collapse internal whitespace to single space
- Format each as `lowercasekey:normalizedvalue`
- Sort all lines alphabetically
- Join with `\n` (newline)
- Hash: `keccak256(joined_string)`
- If `X-Signed-Headers` lists headers but none are present in the request → **zero hash**

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

### 2.1 Success Response

```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "request_id": "uuid-string"
  }
}
```

### 2.2 Error Response

```json
{
  "success": false,
  "error": {
    "code": "error_code",
    "category": "category",
    "message": "Human-readable description",
    "retryable": false,
    "recoverable": true,
    "recovery_strategy": "fix_request",
    "hint": "optional hint",
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
    "docs_key": "optional_docs_reference",
    "retry_at": "RFC3339 timestamp",
    "retry_after_seconds": 60
  },
  "meta": {
    "request_id": "uuid-string"
  }
}
```

### 2.3 Error Categories

| Category | Description |
|----------|-------------|
| `validation` | Request validation failure |
| `authentication` | Auth header/signature issues |
| `permission` | Role/permission restrictions |
| `state_conflict` | State transition violations |
| `rate_limit` | Rate limiting |
| `dependency` | Service dependency issues |
| `not_found` | Resource not found |
| `internal` | Server errors |

### 2.4 Recovery Strategies

| Strategy | Description |
|----------|-------------|
| `fix_request` | Fix request parameters and retry |
| `retry_same_request` | Retry the same request later |
| `change_precondition` | Change a precondition (e.g. stake more) |
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
- **`AllowedRoles`**: Only the exact listed roles are permitted — **admin does NOT inherit**. For example, `allowed: miner` means only miners can call the endpoint; admin will get 403.

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

Non-admin users must have their address registered on-chain before accessing protected APIs. Unregistered addresses receive a `403 address_not_registered` error. Once the identity has a role set locally (miner/validator), the RPC registration check is skipped for performance.

---

## 4. Health & Monitoring

All health endpoints are **public** (no authentication required).

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| `GET` | `/health` | Liveness probe | `{"status": "ok"}` |
| `GET` | `/healthz` | Legacy liveness (deprecated) | `{"status": "ok"}` |
| `GET` | `/ready` | Readiness probe (Core + Mining) | `{"status": "ready"}` |
| `GET` | `/readyz` | Legacy readiness (deprecated) | `{"status": "ready"}` |
| `GET` | `/metrics` | Prometheus metrics (OpenMetrics) | Prometheus text format |

---

## 5. Public API

**Base Path**: `/api/public/v1`  
**Authentication**: None

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/signature-config` | Get EIP-712 signature configuration |

See [Section 1.1](#11-signature-configuration) for response details.

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
    "submitted_at": "2026-04-06T10:00:00Z",
    "reviewed_at": "2026-04-06T10:00:00Z",
    "reviewed_by": "auto"
  }
}
```

**Notes:**
- Applications are **auto-approved** if the applicant meets staking requirements (>= 10000 AWP) and validator capacity is available.
- Allowlisted addresses bypass stake checks (`reviewed_by: "allowlist"`).
- If capacity is full, the applicant can replace a lower-staked validator.

**Error Responses:**

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
    "submitted_at": "2026-04-06T10:00:00Z",
    "reviewed_at": "2026-04-06T10:00:00Z",
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
    "message": "validator application not found"
  }
}
```

**Important**: This endpoint returns HTTP 200 even for not-found errors. Frontend must check `success` field, not HTTP status code.

### 6.4 Review Validator Application (Admin)

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
      "schema": { ... },
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

**Note on optional fields**: `updated_at`, `reviewed_at`, `rejection_reason`, `refresh_interval` use `omitempty` — they are **absent from the JSON** (not empty strings) when unset. Frontend code should check for field existence, not empty string.

#### Get Dataset (Public)

```
GET /api/core/v1/datasets/:id
```

**Authentication**: Not required

#### Create Dataset (Admin)

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

#### Review Dataset (Admin)

```
POST /api/core/v1/datasets/:id/review
```

**Permission**: `core.datasets.review`

**Request:**
```json
{
  "decision": "approve",
  "rejection_reason": ""
}
```

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
pending_review → active (approve)
pending_review → rejected (reject)
active ↔ paused
active → archived
paused → archived
```

**`/datasets/:id/status` Request:**
```json
{ "status": "active" }
```

**`/datasets/:id/reject` Request (optional body):**
```json
{ "reason": "Insufficient data quality criteria" }
```

### 7.2 Submissions

#### Submit Data Entries

```
POST /api/core/v1/submissions
```

**Permission**: `core.submissions.create` (allowed: `miner` only)

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
      "crawl_timestamp": "2026-04-06T10:00:00Z"
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
| `entries[].crawl_timestamp` | string | Yes | Crawl timestamp (RFC 3339, e.g. `"2026-03-28T10:00:00Z"`) |

**Response (201 Created or 200 if challenge required):**
```json
{
  "success": true,
  "data": {
    "admission_status": "accepted",
    "challenge": null,
    "accepted": [
      {
        "id": "sub-uuid",
        "dataset_id": "ds_posts",
        "miner_id": "0x1234...",
        "epoch_id": "2026-04-06",
        "original_url": "https://x.com/user/status/12345",
        "normalized_url": "https://x.com/user/status/12345",
        "dedup_hash": "abc123...",
        "high_risk": false,
        "cleaned_data": "This is the post content...",
        "structured_data": { "post_id": "12345", "content": "...", "author": "user" },
        "crawl_timestamp": "2026-04-06T10:00:00Z",
        "status": "pending",
        "refresh_of_submission_id": "",
        "created_at": "2026-04-06T10:00:00Z"
      }
    ],
    "rejected": [
      {
        "url": "https://x.com/user/status/99999",
        "reason": "dedup_hash_conflict"
      }
    ]
  }
}
```

**Admission Status Values:**
- `"accepted"` — All valid entries were accepted (HTTP 201)
- `"challenge_required"` — PoW challenge triggered (HTTP 200); entries are held pending challenge completion

**Note**: `challenge` and `rejected` use `omitempty` — they are **absent from JSON** when null/empty, not `null` or `[]`.

**Per-Entry Rejection Reasons:**
- `url_pattern_mismatch` — URL doesn't match dataset patterns
- `duplicate` — Duplicate entry within same batch
- `dedup_hash_in_cooldown` — Dedup hash in cooldown period
- `url_already_occupied` — URL already occupied
- `malformed` — Entry validation failed
- `dataset_not_active` — Dataset is not active
- `internal_error` — Server error

#### PoW Challenge Response (when `admission_status` = `"challenge_required"`)

The `challenge` field contains:
```json
{
  "id": "challenge-uuid",
  "miner_id": "0x1234...",
  "epoch_id": "2026-04-06",
  "dataset_id": "ds_posts",
  "schema_key": "posts",
  "question_id": "posts-understanding-v1",
  "question_version": 1,
  "question_type": "content_understanding",
  "prompt": "Question text...",
  "validation_meta": { "schema_fields": "post_id,content,author" },
  "created_at": "2026-04-06T10:00:00Z",
  "expires_at": "2026-04-06T10:05:00Z"
}
```

#### List Submissions

```
GET /api/core/v1/submissions
```

**Permission**: `core.submissions.read` (allowed: `miner` only)  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Response item (SubmissionQueryResponse):**
```json
{
  "id": "sub-uuid",
  "dataset_id": "ds_posts",
  "miner_id": "0x1234...",
  "epoch_id": "2026-04-06",
  "dedup_hash": "abc123...",
  "high_risk": false,
  "crawl_timestamp": "2026-04-06T10:00:00Z",
  "status": "confirmed",
  "refresh_of_submission_id": "",
  "created_at": "2026-04-06T10:00:00Z",
  "updated_at": "2026-04-06T12:00:00Z"
}
```

#### Get Submission

```
GET /api/core/v1/submissions/:id
```

**Permission**: `core.submissions.read`

### 7.3 Deduplication

#### Check Dedup Hash

```
GET /api/core/v1/dedup/check?dataset_id=ds_posts&dedup_hash=abc123
```

**Permission**: `core.dedup.check` (allowed: `miner` only)

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

#### List Dedup Occupancies

```
GET /api/core/v1/dedup-occupancies
```

**Permission**: `core.dedup_occupancies.read`  
**Query Parameters**: `page`, `page_size`, `sort`, `order`

**Response item:**
```json
{
  "dataset_id": "ds_posts",
  "dedup_hash": "abc123...",
  "submission_id": "sub-uuid",
  "submission_status": "confirmed",
  "occupied": true,
  "updated_at": "2026-04-06T10:00:00Z"
}
```

#### Get Dedup Occupancy

```
GET /api/core/v1/dedup-occupancies/:datasetId/:dedupHash
```

**Permission**: `core.dedup_occupancies.read`

#### Check Dedup Occupancy by Structured Data

```
POST /api/core/v1/dedup-occupancies/check
```

**Permission**: `core.dedup_occupancies.read`

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

### 7.4 Validation Results

#### Create Validation Result

```
POST /api/core/v1/validation-results
```

**Permission**: `core.validation_results.create`

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

| Field | Type | Values |
|-------|------|--------|
| `verdict` | string | `"accepted"` or `"rejected"` |
| `score` | int | 0-100 |
| `idempotency_key` | string | Unique key to prevent duplicates |

#### List Validation Results

```
GET /api/core/v1/validation-results
```

**Permission**: `core.validation_results.read`

#### Get Validation Result

```
GET /api/core/v1/validation-results/:id
```

**Permission**: `core.validation_results.read`

### 7.5 Epochs

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
  "epoch_id": "2026-04-06",
  "status": "completed",
  "summary": {
    "total": 1000,
    "confirmed": 950,
    "rejected": 50
  },
  "window_start_at": "2026-04-06T00:00:00Z",
  "window_end_at": "2026-04-07T00:00:00Z",
  "settlement_started_at": "2026-04-07T00:00:05Z",
  "settlement_completed_at": "2026-04-07T00:01:00Z",
  "created_at": "2026-04-06T00:00:00Z",
  "updated_at": "2026-04-07T00:01:00Z"
}
```

**Epoch Status Values**: `open`, `settling`, `completed`, `failed`

#### Get Epoch (Public)

```
GET /api/core/v1/epochs/:epochID
```

#### Settle Epoch (Admin)

```
POST /api/core/v1/epochs/:epochID/settle
```

**Permission**: `core.epochs.settle` (min role: `admin`)

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

**Note**: `updated_at` is omitted from the response when the config has never been updated (newly created configs).

#### Get Protocol Config

```
GET /api/core/v1/protocol-configs/:key
GET /api/core/v1/protocol-configs/:key?scope=ds_posts
```

#### Set Protocol Config

```
PUT /api/core/v1/protocol-configs
```

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

**Permission**: `core.protocol_configs.write`

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

---

## 8. Mining Module

**Base Path**: `/api/mining/v1`

### 8.1 Heartbeat

```
POST /api/mining/v1/heartbeat
```

**Permission**: `mining.heartbeat` (min role: `member`)

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
      "last_heartbeat_at": "2026-04-06T10:00:00Z",
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

### 8.2 Ready Pool Management

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

**Permission**: `mining.validator.ready` / `mining.validator.unready` (allowed: `validator` only)

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

### 8.3 Online Miners/Validators

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
  "last_heartbeat_at": "2026-04-06T10:00:00Z",
  "online": true,
  "credit": 65
}
```

#### List Online Validators

```
GET /api/mining/v1/validators/online
```

**Permission**: `mining.validators.online.read` (min role: `admin`)

**Response item:**
```json
{
  "validator_id": "0x5678...",
  "client": "validator-cli/1.0",
  "last_heartbeat_at": "2026-04-06T10:00:00Z",
  "online": true,
  "credit": 85,
  "eligible": true,
  "ready": true
}
```

### 8.4 Proof-of-Work (PoW)

#### Answer PoW Challenge

```
POST /api/mining/v1/pow-challenges/:id/answer
```

**Permission**: `mining.pow.answer` (allowed: `miner` only)

**Request:**
```json
{
  "answer": "accepted"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "challenge_id": "challenge-uuid",
    "miner_id": "0x1234...",
    "passed": true,
    "answered_at": "2026-04-06T10:01:00Z"
  }
}
```

**Notes:**
- PoW challenge is triggered during submission based on `pow_probability` from heartbeat
- Challenge TTL: **5 minutes**
- After passing the challenge, the held submission entries are automatically processed

### 8.5 Refresh Tasks

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/refresh-tasks` | `mining.refresh.create` | Create refresh task |
| `POST` | `/refresh-tasks/claim` | `mining.refresh.claim` | Claim a task |
| `POST` | `/refresh-tasks/:id/report` | `mining.refresh.report` | Report result |
| `GET` | `/refresh-tasks` | `mining.refresh.list` | List tasks |
| `GET` | `/refresh-tasks/:id` | `mining.refresh.list` | Get task |

**Create Request:**
```json
{
  "epoch_id": "2026-04-06",
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
    "epoch_id": "2026-04-06",
    "dataset_id": "ds_posts",
    "url": "https://x.com/user/status/12345",
    "assigned_miner_id": "0x1234...",
    "status": "completed",
    "submission_id": "sub-uuid"
  }
}
```

### 8.6 Repeat Crawl Tasks

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/repeat-crawl-tasks` | `mining.repeat.create` | Create task (deprecated) |
| `POST` | `/repeat-crawl-tasks/claim` | `mining.repeat.claim` | Claim a task |
| `POST` | `/repeat-crawl-tasks/:id/report` | `mining.repeat.report` | Report result |
| `POST` | `/repeat-crawl-tasks/:id/reject` | `mining.repeat.reject` | Reject task (no penalty) |
| `POST` | `/repeat-crawl-tasks/:id/reassign` | `mining.repeat.reassign` | Reassign task (admin) |
| `GET` | `/repeat-crawl-tasks` | `mining.repeat.list` | List tasks |
| `GET` | `/repeat-crawl-tasks/:id` | `mining.repeat.list` | Get task |

**Claim Response:**
```json
{
  "success": true,
  "data": {
    "id": "task-uuid",
    "epoch_id": "2026-04-06",
    "submission_id": "sub-uuid",
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

#### Core-Derived Repeat Task

```
POST /api/mining/v1/core-submissions/:id/repeat-crawl-tasks
```

**Permission**: `mining.core_submission.repeat`

**Request:**
```json
{
  "epoch_id": "2026-04-06"
}
```

### 8.7 Evaluation Tasks

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/evaluation-tasks` | `mining.evaluation.create` | Create task (deprecated) |
| `POST` | `/evaluation-tasks/claim` | `mining.evaluation.claim` | Claim task |
| `POST` | `/evaluation-tasks/:id/report` | `mining.evaluation.report` | Report result |
| `GET` | `/evaluation-tasks` | `mining.evaluation.list` | List tasks |
| `GET` | `/evaluation-tasks/:id` | `mining.evaluation.list` | Get task |

#### Claim Evaluation Task

```
POST /api/mining/v1/evaluation-tasks/claim
```

**Permission**: `mining.evaluation.claim` (allowed: `validator` only)

**Response:**
```json
{
  "success": true,
  "data": {
    "task_id": "eval-task-uuid",
    "assignment_id": "assign-uuid",
    "validator_id": "0x5678...",
    "golden": false,
    "cleaned_data": "Original miner submission content (M0)...",
    "repeat_cleaned_data": "Re-crawled content (M1) for comparison...",
    "structured_data": {
      "post_id": "12345",
      "content": "Original content...",
      "author": "user"
    },
    "schema_fields": ["author", "content", "post_id"]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Evaluation task ID |
| `assignment_id` | string | Assignment ID (use in report) |
| `validator_id` | string | Validator address |
| `golden` | bool | Whether this is a golden (benchmark) task |
| `cleaned_data` | string | Original miner submission (M0) |
| `repeat_cleaned_data` | string | Re-crawled data (M1) for comparison; empty if Step 1 |
| `structured_data` | object | Original structured data |
| `schema_fields` | string[] | Schema field names (sorted) |

#### Report Evaluation Task

```
POST /api/mining/v1/evaluation-tasks/:id/report
```

**Permission**: `mining.evaluation.report` (allowed: `validator` only)

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
- `"match"` — The original data (M0) matches the re-crawled data (M1); the submission is authentic
- `"mismatch"` — The data does not match; possible fraud or significant deviation

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "eval-task-uuid",
    "epoch_id": "2026-04-06",
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

**Permission**: `mining.core_submission.evaluation`

**Request:**
```json
{
  "epoch_id": "2026-04-06",
  "golden_score": 88
}
```

### 8.8 Epoch Snapshots & Settlement

#### Get Epoch Snapshot (Public)

```
GET /api/mining/v1/epochs/:id/snapshot
```

**Authentication**: Not required

**Response:**
```json
{
  "success": true,
  "data": {
    "epoch_id": "2026-04-06",
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

#### Get Epoch Settlement Results (Public)

```
GET /api/mining/v1/epochs/:id/settlement-results
```

**Response:**
```json
{
  "success": true,
  "data": {
    "epoch_id": "2026-04-06",
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

### 8.9 Participant Stats

#### Get Miner Stats

```
GET /api/mining/v1/miners/:id/stats
```

**Permission**: `mining.miners.stats.read`

**Response:**
```json
{
  "success": true,
  "data": {
    "miner_id": "0x1234...",
    "ip_address": "203.0.113.10",
    "client": "miner-cli/1.0",
    "last_heartbeat_at": "2026-04-06T10:00:00Z",
    "credit": 65,
    "ready_pool_opt_in": true,
    "consecutive_fail": 0,
    "timeout_history": [false, false, true, false, false],
    "evicted_until_epoch": ""
  }
}
```

#### Get Validator Stats

```
GET /api/mining/v1/validators/:id/stats
```

**Permission**: `mining.validators.stats.read`

**Response:**
```json
{
  "success": true,
  "data": {
    "validator_id": "0x5678...",
    "ip_address": "203.0.113.20",
    "client": "validator-cli/1.0",
    "last_heartbeat_at": "2026-04-06T10:00:00Z",
    "last_task_completed_at": "2026-04-06T09:55:00Z",
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

---

## 9. WebSocket Realtime Channel

### 9.1 Connection

```
GET /api/mining/v1/ws
```

**Permission**: `mining.ws` (min role: `member`)  
**Protocol**: WebSocket upgrade with EIP-712 auth headers on the HTTP upgrade request

### 9.2 Server → Client Messages

**Repeat Crawl Task Push:**
```json
{
  "type": "repeat_crawl_task",
  "data": {
    "id": "task-uuid",
    "epoch_id": "2026-04-06",
    "submission_id": "sub-uuid",
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
    "golden": false,
    "cleaned_data": "M0 content...",
    "repeat_cleaned_data": "M1 content...",
    "structured_data": { ... },
    "schema_fields": ["field1", "field2"]
  }
}
```

### 9.3 Client → Server Messages

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

## 10. Credit System

### 10.1 Credit Tiers

Both miners and validators use a 0-100 credit score system.

| Score Range | Tier | Description |
|-------------|------|-------------|
| 80-100 | `excellent` | Highest trust level |
| 60-79 | `good` | Standard trusted participant |
| 40-59 | `normal` | Moderate trust |
| 20-39 | `restricted` | Under observation |
| 0-19 | `novice` | New or penalized participant |

### 10.2 Miner Credit Effects

| Tier | Sampling Rate | Epoch Submit Limit | PoW Probability |
|------|--------------|-------------------|-----------------|
| `excellent` (80+) | Base rate (0.30) | 1,000,000 | 1% |
| `good` (60-79) | Base rate (0.30) | 10,000 | 5% |
| `normal` (40-59) | 1.5x base (max 1.0) | 2,000 | 20% |
| `restricted` (20-39) | 2.0x base (max 1.0) | 500 | 50% |
| `novice` (0-19) | 1.0 (100%) | 100 | 100% |

### 10.3 Validator Credit Effects

| Tier | Min Task Interval | Min Eval Count | Golden Task Probability |
|------|-------------------|----------------|------------------------|
| `excellent` (80+) | 10 seconds | 10 | 5% |
| `good` (60-79) | 30 seconds | 10 | 10% |
| `normal` (40-59) | 2 minutes | 10 | 20% |
| `restricted` (20-39) | 5 minutes | 10 | 30% |
| `novice` (0-19) | 10 minutes | 3 | 40% |

### 10.4 Credit Adjustment (Per Epoch)

**Miners:**
- Qualified: +5 (cap at 100)
- Not qualified: -15 (floor at 0), consecutive_fail + 1
- 3+ consecutive failures: credit reset to 0

**Validators:**
- Accuracy >= 60%: +5 (cap at 100), consecutive_flag reset to 0
- Accuracy < 60%: -15, consecutive_flag + 1
- Accuracy < 20%: credit reset to 0

### 10.5 Validator Eviction Rules

| Rule | Window | Threshold | Penalty |
|------|--------|-----------|---------|
| **Idle** | 3-of-10 | 3 idle epochs in last 10 | Evict 1 epoch, -15 credit |
| **Flag** | 4-of-10 | 4 flagged (accuracy < 60%) in last 10 | Evict 1 epoch, -15 credit |
| **Timeout** | 4-of-10 | 4 timeouts in last 10 | Evict 1 epoch |
| **Unclaimed** | 3 consecutive | 3 consecutive unclaimed tasks | 1-hour cooldown |

---

## 11. Quality Assurance Workflow

### 11.1 Pipeline Overview

```
Miner submits data (M0)
    → Sampling decision (credit-based rate)
    → If sampled:
        Phase A: Repeat Crawl (Step 1)
            → Different miner re-crawls same URL → produces M1
            → Evaluation Task created
        Phase B: Evaluation
            → Validator compares M0 vs M1
            → Reports "match" (authentic) or "mismatch" (suspicious)
            → If match: score applied, submission confirmed/rejected
            → If mismatch: Step 2 triggered
        Phase A: Repeat Crawl (Step 2, if mismatch)
            → Third miner re-crawls → produces M2
            → New Evaluation Task created
        Phase B: Final Evaluation
            → Validator compares M0 vs M2
            → Final determination
```

### 11.2 Evaluation Modes

| Mode | Validators | Trigger |
|------|-----------|---------|
| `single` | 1 validator | Default for Step 1 evaluations |
| `peer_review` | Up to 5 validators | Triggered when consensus is needed |

### 11.3 Match/Mismatch Consensus (Peer Review)

When multiple validators evaluate the same task:
- **Match consensus**: >= 3/5 validators agree on "match" → submission scored
- **Mismatch consensus**: >= 3/5 validators agree on "mismatch" → Step 2 triggered or fraud confirmed
- **No consensus**: All validators reported but no majority → scored using available data

### 11.4 Scoring Scenarios

**Scenario 1** (Step 1 Match): M0 scored with validator's score. M0 repeat score = 5.

**Scenario 2** (Step 1 Mismatch → Step 2 Match): M0 confirmed authentic. M0 repeat score = 5, M1 repeat score = 0.

**Scenario 3** (Step 1 Mismatch → Step 2 Mismatch): M0 confirmed fraudulent (score = 0). M0 repeat score = 0, M1 repeat score = 5.

### 11.5 Reward Weight

Effective task count for reward calculation:
```
effectiveTaskCount = mineCount + repeatCount * 0.8
```

Repeat tasks count at 80% weight compared to original mining tasks.

---

## 12. Epoch & Settlement

### 12.1 Epoch Lifecycle

- **Duration**: 1 UTC natural day (00:00 - 00:00 UTC)
- **Epoch ID format**: `"YYYY-MM-DD"` (e.g. `"2026-04-06"`)
- **Auto-settlement**: Triggered at UTC 00:00 daily
- **Manual settlement**: Admin can trigger via `POST /api/core/v1/epochs/:epochID/settle`

### 12.2 Settlement Formula

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
- Miner: `task_count >= 80` (configurable via `PLATFORM_SERVICE_MINER_MIN_TASK_COUNT`) and `avg_score >= 60` (configurable via `PLATFORM_SERVICE_MINER_MIN_AVG_SCORE`)
- Validator: `eval_count >= 10` required; accuracy < 20% → disqualified (`severe_misbehavior`); accuracy 20-60% → qualified but penalized

### 12.3 Validator Penalties

| Penalty | Trigger | Credit Effect | Additional |
|---------|---------|--------------|------------|
| `severe_misbehavior` | accuracy < 20% | Disqualified, reset to 0 | Excluded from reward pool entirely (no slash/redistribution) |
| `misbehavior` | accuracy 20-60% | -15, flag++ | Reward slashed and redistributed |
| `low_quality` | — | -15 | None |
| `idle` | eval_count < 10 | -15 | None |

---

## 13. Timing Parameters

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

---

## 14. Error Handling

### 14.1 HTTP Status Codes

| Code | Usage |
|------|-------|
| 200 | Success (GET, challenge_required submission) |
| 201 | Created (POST with accepted entries) |
| 400 | Bad request / validation error |
| 401 | Authentication failed |
| 403 | Forbidden / insufficient permissions |
| 404 | Resource not found |
| 409 | State conflict |
| 422 | Validation error (semantic) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service not ready / persistence required |

### 14.2 Common Error Codes

| Code | Category | Description |
|------|----------|-------------|
| `unauthorized` | authentication | Missing/invalid auth |
| `missing_auth_headers` | authentication | Required headers missing |
| `invalid_signature` | authentication | Signature verification failed |
| `request_expired` | authentication | Timestamp outside validity window |
| `nonce_reused` | authentication | Nonce already used |
| `forbidden` | permission | Insufficient role |
| `role_suspended` | permission | Identity suspended |
| `address_not_registered` | permission | Address not registered on-chain |
| `insufficient_stake` | permission | Stake below minimum |
| `invalid_request` | validation | Malformed request |
| `invalid_review_decision` | validation | Invalid decision value |
| `dataset_inactive` | state_conflict | Dataset not active |
| `dedup_hash_conflict` | state_conflict | Dedup hash already occupied |
| `dedup_hash_in_cooldown` | rate_limit | Hash in cooldown period |
| `validator_application_exists` | state_conflict | Application already exists |
| `validator_application_reviewed` | state_conflict | Already reviewed |
| `validator_capacity_full` | state_conflict | No validator slots |
| `validator_not_ready` | dependency | Validator not in ready pool |
| `evaluation_task_not_found` | not_found | Task not found |
| `repeat_task_not_found` | not_found | Task not found |
| `challenge_not_found` | not_found | PoW challenge not found |
| `quality_workflow_not_found` | not_found | Workflow not found |
| `validator_capacity_all_protected` | state_conflict | All validators in protection period |
| `persistence_unavailable` | dependency | Database persistence required (503) |
| `service_not_ready` | dependency | Service dependencies not ready (503) |

---

## 15. Miner Frontend Workflow

### 15.1 Main Loop

```
1. Heartbeat (every 60s)
   POST /api/mining/v1/heartbeat
   → Returns credit, credit_tier, epoch_submit_limit, pow_probability

2. Get Active Datasets
   GET /api/core/v1/datasets (filter status="active" client-side)

3. Pre-check Deduplication (optional)
   GET /api/core/v1/dedup/check?dataset_id=...&dedup_hash=...

4. Submit Data
   POST /api/core/v1/submissions
   → If admission_status="challenge_required":
       POST /api/mining/v1/pow-challenges/:id/answer
       → On pass: submission auto-resumes

5. Join Ready Pool
   POST /api/mining/v1/miners/ready

6. Handle Repeat Crawl Tasks
   Option A (polling): POST /api/mining/v1/repeat-crawl-tasks/claim
   Option B (WebSocket): Connect to /api/mining/v1/ws
     → Receive {"type":"repeat_crawl_task", ...}
     → Send {"ack":"task-id"} within 30s
     → Re-crawl the URL
     → POST /api/mining/v1/repeat-crawl-tasks/:id/report

7. Leave Ready Pool (optional)
   POST /api/mining/v1/miners/unready
```

### 15.2 Key Display Fields

| Field | Source | Display |
|-------|--------|---------|
| Credit score | heartbeat → `credit` | Progress bar 0-100 |
| Credit tier | heartbeat → `credit_tier` | Badge (novice/restricted/normal/good/excellent) |
| Submit limit | heartbeat → `epoch_submit_limit` | Remaining quota |
| PoW probability | heartbeat → `pow_probability` | Percentage |
| Online status | heartbeat → `online` | Green/red indicator |

---

## 16. Validator Frontend Workflow

### 16.1 Main Loop

```
1. Apply as Validator (one-time)
   POST /api/iam/v1/validator-applications
   → Auto-approved if stake >= 10000 AWP

2. Check Application Status
   GET /api/iam/v1/validator-applications/me

3. Heartbeat (every 60s)
   POST /api/mining/v1/heartbeat
   → Returns credit, eligible, credit_tier, min_task_interval_seconds

4. Join Ready Pool
   POST /api/mining/v1/validators/ready

5. Claim & Complete Evaluation Tasks
   Option A (polling): POST /api/mining/v1/evaluation-tasks/claim
   Option B (WebSocket): Connect to /api/mining/v1/ws
     → Receive {"type":"evaluation_task", ...}
     → Send {"ack_eval":"assignment-id"} within 30s
     → Compare cleaned_data (M0) vs repeat_cleaned_data (M1)
     → Determine match/mismatch
     → Score structured_data quality against schema_fields
     → POST /api/mining/v1/evaluation-tasks/:id/report
       { "assignment_id": "...", "result": "match", "score": 85 }

6. Respect min_task_interval_seconds between claims

7. Leave Ready Pool (optional)
   POST /api/mining/v1/validators/unready
```

### 16.2 Evaluation Logic

When evaluating a claimed task:

1. **Compare M0 vs M1**: Check if `cleaned_data` (original submission) and `repeat_cleaned_data` (re-crawled data) represent the same content
2. **Determine result**: `"match"` if authentic, `"mismatch"` if data appears fabricated or significantly different
3. **Score quality**: Rate the structured_data quality (0-100) based on completeness, accuracy, and adherence to schema_fields
4. **Golden tasks**: When `golden=true`, the system knows the expected score; your accuracy contributes to your reputation

### 16.3 Key Display Fields

| Field | Source | Display |
|-------|--------|---------|
| Credit score | heartbeat → `credit` | Progress bar 0-100 |
| Credit tier | heartbeat → `credit_tier` | Badge |
| Eligible | heartbeat → `eligible` | Can receive tasks |
| Min interval | heartbeat → `min_task_interval_seconds` | Seconds between tasks |
| Stake amount | stats → `stake_amount` | AWP staked |
| Accuracy | settlement → `accuracy` | Performance metric |

---

## 17. Admin Frontend Workflow

### 17.1 Dataset Management

```
1. Create Dataset
   POST /api/core/v1/datasets

2. Review Dataset
   POST /api/core/v1/datasets/:id/review

3. Lifecycle Management
   POST /api/core/v1/datasets/:id/activate
   POST /api/core/v1/datasets/:id/pause
   POST /api/core/v1/datasets/:id/archive
   POST /api/core/v1/datasets/:id/reject
```

### 17.2 Protocol Configuration

```
GET  /api/core/v1/protocol-configs           # List all configs
PUT  /api/core/v1/protocol-configs           # Set config
DELETE /api/core/v1/protocol-configs/:key    # Delete config
```

### 17.3 Epoch Settlement

```
GET  /api/core/v1/epochs                     # List epochs
POST /api/core/v1/epochs/:epochID/settle     # Manual settlement
GET  /api/mining/v1/epochs/:id/snapshot      # View snapshot
GET  /api/mining/v1/epochs/:id/settlement-results  # View results
```

### 17.4 Participant Monitoring

```
GET /api/mining/v1/miners/online             # Online miners
GET /api/mining/v1/validators/online         # Online validators
GET /api/mining/v1/miners/:id/stats          # Miner details
GET /api/mining/v1/validators/:id/stats      # Validator details
```

### 17.5 Validator Application Review

```
POST /api/iam/v1/validator-applications/:id/review
```

### 17.6 Task Management

```
GET  /api/mining/v1/repeat-crawl-tasks       # List repeat tasks
POST /api/mining/v1/repeat-crawl-tasks/:id/reassign  # Reassign task
GET  /api/mining/v1/evaluation-tasks         # List evaluation tasks
GET  /api/mining/v1/refresh-tasks            # List refresh tasks
```

---

## Appendix A: Permission Matrix

| Permission Key | Access | Endpoints |
|---------------|--------|-----------|
| `iam.me.read` | min: member | `GET /api/iam/v1/me` |
| `iam.validator.apply` | min: member | `POST /api/iam/v1/validator-applications`, `GET .../me` |
| `iam.validator.review` | min: admin | `POST /api/iam/v1/validator-applications/:id/review` |
| `core.datasets.create` | min: member | `POST /api/core/v1/datasets` |
| `core.datasets.review` | min: admin | `POST .../datasets/:id/review` |
| `core.datasets.status` | min: admin | `POST .../datasets/:id/status` |
| `core.datasets.activate` | min: admin | `POST .../datasets/:id/activate` |
| `core.datasets.pause` | min: admin | `POST .../datasets/:id/pause` |
| `core.datasets.archive` | min: admin | `POST .../datasets/:id/archive` |
| `core.datasets.reject` | min: admin | `POST .../datasets/:id/reject` |
| `core.submissions.read` | allowed: miner, admin | `GET .../submissions`, `GET .../submissions/:id` |
| `core.submissions.create` | allowed: miner | `POST .../submissions` |
| `core.dedup.check` | allowed: miner | `GET .../dedup/check` |
| `core.dedup_occupancies.read` | allowed: miner | `GET/POST .../dedup-occupancies/...` |
| `core.validation_results.read` | allowed: validator | `GET .../validation-results/...` |
| `core.validation_results.create` | allowed: validator | `POST .../validation-results` |
| `core.epochs.read` | min: admin | `GET .../epochs` (protected), `GET .../epochs/:id` |
| `core.epochs.settle` | min: admin | `POST .../epochs/:epochID/settle` |
| `core.protocol_configs.read` | min: admin | `GET .../protocol-configs/...` |
| `core.protocol_configs.write` | min: admin | `PUT/DELETE .../protocol-configs/...` |
| `mining.heartbeat` | allowed: member, miner, validator | `POST /api/mining/v1/heartbeat` |
| `mining.miners.online.read` | **public** (no auth) | `GET .../miners/online` |
| `mining.miner.ready` | allowed: miner | `POST .../miners/ready` |
| `mining.miner.unready` | allowed: miner | `POST .../miners/unready` |
| `mining.pow.answer` | allowed: miner | `POST .../pow-challenges/:id/answer` |
| `mining.refresh.create` | min: admin | `POST .../refresh-tasks` |
| `mining.refresh.claim` | allowed: miner | `POST .../refresh-tasks/claim` |
| `mining.refresh.report` | allowed: miner | `POST .../refresh-tasks/:id/report` |
| `mining.refresh.list` | min: admin | `GET .../refresh-tasks/...` |
| `mining.repeat.create` | min: admin | `POST .../repeat-crawl-tasks` |
| `mining.repeat.claim` | allowed: miner | `POST .../repeat-crawl-tasks/claim` |
| `mining.repeat.report` | allowed: miner | `POST .../repeat-crawl-tasks/:id/report` |
| `mining.repeat.reject` | allowed: miner | `POST .../repeat-crawl-tasks/:id/reject` |
| `mining.repeat.reassign` | min: admin | `POST .../repeat-crawl-tasks/:id/reassign` |
| `mining.repeat.list` | min: admin | `GET .../repeat-crawl-tasks/...` |
| `mining.validator.ready` | allowed: validator | `POST .../validators/ready` |
| `mining.validator.unready` | allowed: validator | `POST .../validators/unready` |
| `mining.validators.online.read` | min: admin | `GET .../validators/online` |
| `mining.evaluation.create` | min: admin | `POST .../evaluation-tasks` |
| `mining.evaluation.claim` | allowed: validator | `POST .../evaluation-tasks/claim` |
| `mining.evaluation.report` | allowed: validator | `POST .../evaluation-tasks/:id/report` |
| `mining.evaluation.list` | min: admin | `GET .../evaluation-tasks/...` |
| `mining.core_submission.repeat` | min: admin | `POST .../core-submissions/:id/repeat-crawl-tasks` |
| `mining.core_submission.evaluation` | min: admin | `POST .../core-submissions/:id/evaluation-tasks` |
| `mining.epoch.snapshot.read` | **public** (no auth) | `GET .../epochs/:id/snapshot` |
| `mining.epoch.settlement.read` | **public** (no auth) | `GET .../epochs/:id/settlement-results` |
| `mining.miners.stats.read` | min: admin | `GET .../miners/:id/stats` |
| `mining.validators.stats.read` | min: admin | `GET .../validators/:id/stats` |
| `mining.ws` | min: member | `GET .../ws` |

**Notes**:
- Public endpoints (marked **public** above) are registered without authentication middleware — the policy store entry exists but is not enforced.
- `allowed:` permissions use **exact role matching** — admin does NOT inherit. Only the listed roles can access.
- `min:` permissions use **role hierarchy** — admin inherits all lower roles.

---

## Appendix B: Dedup Hash Computation

The dedup hash is computed as:
```
SHA256(field1_value | field2_value | ... | fieldN_value)
```

Where fields are taken from the dataset's `dedup_fields` array in order, separated by `|`, using values from `structured_data`.
