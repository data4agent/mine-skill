# ocDATA Platform Service — Skill Development Guide

This document provides everything an LLM agent (Claude Code, Codex, etc.) needs to build a Skill that correctly interacts with the ocDATA Platform Service.

> **Version**: Based on latest main (2026-04-05)  
> **Base URL**: `http://<host>:8080`

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Response Envelope](#2-response-envelope)
3. [Roles & Permissions](#3-roles--permissions)
4. [Miner Skill Workflow](#4-miner-skill-workflow)
5. [Validator Skill Workflow](#5-validator-skill-workflow)
6. [WebSocket Realtime Channel](#6-websocket-realtime-channel)
7. [Dataset Management](#7-dataset-management)
8. [Submission API](#8-submission-api)
9. [Deduplication API](#9-deduplication-api)
10. [Repeat Crawl API](#10-repeat-crawl-api)
11. [Evaluation API](#11-evaluation-api)
12. [Epoch & Settlement API](#12-epoch--settlement-api)
13. [Protocol Configuration API](#13-protocol-configuration-api)
14. [Validator Application API](#14-validator-application-api)
15. [Credit System](#15-credit-system)
16. [Timing Parameters](#16-timing-parameters)
17. [Error Handling](#17-error-handling)
18. [Miner Skill Reference Implementation](#18-miner-skill-reference-implementation)
19. [Validator Skill Reference Implementation](#19-validator-skill-reference-implementation)

---

## 1. Authentication

All authenticated endpoints use **EIP-712 typed-data signatures** via HTTP headers.

### Required Headers

```
X-Signer: 0x<ethereum_address>
X-Signature: 0x<eip712_signature>
X-Nonce: <unique_string>
X-Issued-At: <RFC3339_timestamp>
X-Expires-At: <RFC3339_timestamp>
```

### Constraints

| Parameter | Value |
|-----------|-------|
| Max signature validity | 300 seconds |
| Clock skew tolerance | 30 seconds |
| Max request body | 8 MB |

### Retrieve Signing Configuration

```
GET /api/public/v1/signature-config

Response:
{
  "domain_name": "aDATA",
  "domain_version": "1",
  "chain_id": 97
}
```

Use these values to construct the EIP-712 domain separator for signing.

---

## 2. Response Envelope

### Success Response

```json
{
  "code": 200,
  "message": "success",
  "data": { /* endpoint-specific payload */ },
  "meta": {
    "request_id": "uuid-string",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

### Error Response

```json
{
  "code": "error_code_string",
  "category": "validation|permission|not_found|state_conflict|rate_limit|internal",
  "message": "Human-readable description",
  "retryable": false,
  "recoverable": true,
  "recovery_strategy": "fix_request|retry_same_request|change_precondition|stop",
  "field_errors": [
    {"field": "entries[0].url", "reason": "required", "message": "URL is required"}
  ],
  "recovery_actions": [
    {"action": "retry", "label": "Retry after fixing input", "blocking": false}
  ]
}
```

---

## 3. Roles & Permissions

| Role | Description | How to Obtain |
|------|-------------|---------------|
| `unbound` | Default role | Created on first heartbeat |
| `miner` | Data submitter | Auto-promoted on first heartbeat |
| `validator` | Data evaluator | Submit application → admin approval (or allowlist auto-approve) |
| `admin` | Full access | Pre-configured via `PLATFORM_SERVICE_BOOTSTRAP_ADMIN_ADDRESSES` env var |

Each API endpoint requires a specific permission. Permissions are mapped to minimum required roles. A higher role inherits all lower role permissions (admin > validator > miner > unbound).

---

## 4. Miner Skill Workflow

The Miner Skill performs a continuous loop: heartbeat → crawl → submit → handle PoW → respond to repeat crawl tasks.

### Step 1: Heartbeat (every 60 seconds)

```
POST /api/mining/v1/heartbeat
Auth: Required (EIP-712)

Request Body:
{
  "client": "miner-skill/1.0"
}

Response (200):
{
  "role": "miner",
  "miner": {
    "miner_id": "0xabc...",
    "ip_address": "203.0.113.10",
    "client": "miner-skill/1.0",
    "last_heartbeat_at": "2026-04-01T12:00:00Z",
    "online": true,
    "credit": 45,
    "credit_tier": "normal",
    "epoch_submit_limit": 2000,
    "pow_probability": 0.20
  }
}
```

**Key response fields:**
- `credit`: Current credit score (0-100). Determines submission limits, PoW probability, and sampling rate.
- `credit_tier`: Human-readable tier name. One of: `novice`, `restricted`, `normal`, `good`, `excellent`.
- `epoch_submit_limit`: Maximum submissions allowed in the current epoch for this credit tier.
- `pow_probability`: Probability (0.0-1.0) that the next submission will trigger a PoW challenge.

### Step 2: Query Active Datasets

```
GET /api/core/v1/datasets

Response (200):
[
  {
    "dataset_id": "ds_posts",
    "name": "X Posts",
    "status": "active",
    "source_domains": ["x.com", "twitter.com"],
    "schema": {
      "post_id": {"type": "string", "required": true},
      "content": {"type": "string", "required": true},
      "author": {"type": "string", "required": true},
      "likes": {"type": "integer", "required": false}
    },
    "dedup_fields": ["post_id"],
    "url_patterns": ["(x|twitter)\\.com/.+/status/(\\d+)"],
    "refresh_interval": null,
    "total_entries": 5000
  }
]
```

**Before submitting data, the Skill MUST verify:**
1. `status` is `"active"` — submissions to non-active datasets are rejected.
2. `structured_data` contains ALL fields where `required: true` in `schema`.
3. URL matches at least one regex in `url_patterns` (if configured). The regex is applied to the `host+path` portion only (query string and fragment are excluded).
4. The `dedup_fields` values are unique — no existing pending/confirmed submission has the same content.

### Step 3: Pre-check Deduplication (optional but recommended)

```
GET /api/core/v1/dedup/check?dataset_id=ds_posts&dedup_hash=a665a...
Auth: Required (miner role)

Response (200):
{
  "dataset_id": "ds_posts",
  "dedup_hash": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
  "exists": true
}
```

If `exists` is `true`, do NOT submit this entry — it will be rejected with reason `"duplicate"`.

**Dedup hash computation:**
```
dedup_hash = SHA256( json_marshal(field1_value) + "|" + json_marshal(field2_value) + ... )
```
where fields are taken from `dedup_fields` in array order.

Alternatively, use the server-side check which computes the hash for you:

```
POST /api/core/v1/dedup-occupancies/check
Auth: Required

Request Body:
{
  "dataset_id": "ds_posts",
  "structured_data": {"post_id": "123", "content": "hello", "author": "alice"}
}

Response (200):
{
  "dataset_id": "ds_posts",
  "dedup_hash": "a665a...",
  "occupied": true,
  "submission_status": "pending"
}
```

### Step 4: Submit Data

```
POST /api/core/v1/submissions
Auth: Required (miner role)

Request Body:
{
  "dataset_id": "ds_posts",
  "entries": [
    {
      "url": "https://x.com/user/status/123?s=20",
      "cleaned_data": "The raw text content of the post after cleaning HTML, scripts, etc.",
      "structured_data": {
        "post_id": "123",
        "content": "Hello world",
        "author": "alice"
      },
      "crawl_timestamp": "2026-04-01T10:00:00Z"
    },
    {
      "url": "https://x.com/user/status/456",
      "cleaned_data": "Another post content",
      "structured_data": {
        "post_id": "456",
        "content": "Second post",
        "author": "bob"
      },
      "crawl_timestamp": "2026-04-01T10:05:00Z"
    }
  ]
}

Response (201):
{
  "admission_status": "accepted",
  "accepted": [
    {
      "id": "sub_abc123",
      "dataset_id": "ds_posts",
      "miner_id": "0xabc...",
      "epoch_id": "2026-04-01",
      "original_url": "https://x.com/user/status/123?s=20",
      "normalized_url": "x.com/user/status/123",
      "dedup_hash": "a665a...",
      "high_risk": false,
      "status": "pending",
      "created_at": "2026-04-01T10:00:05Z"
    }
  ],
  "rejected": [
    {
      "url": "https://x.com/user/status/456",
      "reason": "duplicate"
    }
  ]
}
```

**Entry-level processing:** Each entry is validated independently. If one entry fails, others may still succeed. The response contains both `accepted` and `rejected` arrays.

**Rejection reasons:**

| Reason | Description | Skill Action |
|--------|-------------|-------------|
| `url_pattern_mismatch` | URL does not match any dataset `url_patterns` regex | Fix URL or skip this entry |
| `duplicate` | `dedup_hash` already exists for this dataset | Skip — content already submitted |
| `dedup_hash_in_cooldown` | Content was previously rejected and is in 1-epoch cooldown | Wait for cooldown to expire |
| `url_already_occupied` | The normalized URL slot is already taken | Skip — URL already submitted |
| `malformed` | Entry structure is invalid (missing fields, wrong types) | Fix structured_data to match schema |
| `dataset_not_active` | Dataset is not in "active" status | Submit to a different dataset |
| `internal_error` | Server error — retryable | Retry after backoff |

### Step 5: Handle PoW Challenge (if triggered)

If `admission_status` is `"challenge_required"`, the response includes a `challenge` object:

```json
{
  "admission_status": "challenge_required",
  "challenge": {
    "id": "pow_abc123",
    "prompt": "Given this schema, extract the author field from: ...",
    "question_type": "structured_extract",
    "expires_at": "2026-04-01T10:05:00Z"
  },
  "accepted": [],
  "rejected": []
}
```

Answer the challenge:

```
POST /api/mining/v1/pow-challenges/pow_abc123/answer
Auth: Required

Request Body:
{
  "answer": "alice"
}

Response (200):
{
  "challenge_id": "pow_abc123",
  "passed": true,
  "answered_at": "2026-04-01T10:00:30Z"
}
```

If `passed` is `true`, retry the original submission. The PoW grant is consumed automatically.

### Step 6: Join Miner Ready Pool

To receive repeat crawl tasks, the miner must join the ready pool:

```
POST /api/mining/v1/miners/ready
Auth: Required

Response (200):
{
  "miner_id": "0xabc...",
  "status": "ready"
}
```

To leave the ready pool:
```
POST /api/mining/v1/miners/unready
```

### Step 7: Claim & Complete Repeat Crawl Tasks

**HTTP polling mode:**

```
POST /api/mining/v1/repeat-crawl-tasks/claim
Auth: Required

Response (200):
{
  "id": "rpt_xyz789",
  "epoch_id": "2026-04-01",
  "submission_id": "sub_abc123",
  "step": 1,
  "assigned_miner_id": "0xabc...",
  "status": "claimed",
  "phase_a_result": "pending",
  "miner_score": 0
}
```

If no task is available, the endpoint returns a 404/409 error.

**After crawling and cleaning the URL:**

```
POST /api/mining/v1/repeat-crawl-tasks/rpt_xyz789/report
Auth: Required

Request Body:
{
  "cleaned_data": "The re-crawled and cleaned text content"
}

Response (200):
{
  "id": "rpt_xyz789",
  "status": "completed",
  "phase_a_result": "passed",
  "miner_score": 82
}
```

**Rejecting a task** (if the miner is not suitable for this URL/dataset):

```
POST /api/mining/v1/repeat-crawl-tasks/rpt_xyz789/reject
Auth: Required

Response (200):
{
  "id": "rpt_xyz789",
  "status": "pending_claim",
  "assigned_miner_id": ""
}
```

Rejecting does not incur any penalty. The task is reassigned to another miner.

---

## 5. Validator Skill Workflow

The Validator Skill performs: apply → heartbeat → join ready pool → claim evaluation tasks → submit scores.

### Step 1: Apply as Validator

```
POST /api/iam/v1/validator-applications
Auth: Required

Response (201):
{
  "id": "app_abc123",
  "address": "0xdef...",
  "status": "pending_review",
  "submitted_at": "2026-04-01T08:00:00Z"
}
```

**Prerequisites:**
- Must have staked ≥ 1,000 AWP on the subnet (verified via RPC at application time)
- If on the validator allowlist, the application is auto-approved

**Possible statuses:** `pending_review` → `approved` (by admin review) or `rejected`

### Step 2: Heartbeat (every 60 seconds)

```
POST /api/mining/v1/heartbeat
Auth: Required

Request Body:
{
  "client": "validator-skill/1.0"
}

Response (200):
{
  "role": "validator",
  "validator": {
    "validator_id": "0xdef...",
    "credit": 65,
    "eligible": true,
    "credit_tier": "good",
    "min_task_interval_seconds": 30
  }
}
```

**Key response fields:**
- `eligible`: Whether the validator can join the ready pool. `false` if evicted or suspended.
- `min_task_interval_seconds`: Minimum seconds to wait between completing one task and joining the ready pool for the next.

### Step 3: Join Ready Pool

```
POST /api/mining/v1/validators/ready
Auth: Required

Response (200):
{
  "validator_id": "0xdef...",
  "status": "ready"
}
```

**Join conditions (all must be true):**
- `eligible` is `true`
- No outstanding uncompleted task assignments
- Time since last task completion ≥ `min_task_interval_seconds`
- Not in eviction period
- Not in unclaimed cooldown period (1 hour after 3 consecutive unclaimed tasks)

**Possible errors:**
- `409 validator_not_ready`: One or more conditions not met. Wait and retry.

### Step 4: Claim Evaluation Task

```
POST /api/mining/v1/evaluation-tasks/claim
Auth: Required

Response (200):
{
  "task_id": "evt_abc123",
  "assignment_id": "asg_xyz789",
  "validator_id": "0xdef...",
  "golden": false
}
```

**Important:** The `golden` field indicates whether this is a test task with a known correct answer. The validator should NOT change behavior based on this field — evaluate normally. Golden tasks are used to measure validator accuracy.

If no task is available, the endpoint returns a 404/409 error.

### Step 5: Submit Evaluation Score

```
POST /api/mining/v1/evaluation-tasks/evt_abc123/report
Auth: Required

Request Body:
{
  "assignment_id": "asg_xyz789",
  "score": 85
}

Response (200):
{
  "id": "evt_abc123",
  "status": "completed",
  "miner_score": 85
}
```

**Scoring guidelines (0-100 composite score):**

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Field completeness | 30% | Are all required schema fields present and non-empty? |
| Value accuracy | 40% | Do structured_data values accurately reflect the cleaned_data content? |
| Type correctness | 15% | Do field values match their schema-defined types? |
| Information sufficiency | 15% | Is there obvious information in cleaned_data that is missing from structured_data? |

### Step 6: Leave Ready Pool (optional)

```
POST /api/mining/v1/validators/unready
Auth: Required
```

---

## 6. WebSocket Realtime Channel

Instead of polling with HTTP claim endpoints, Skills can use WebSocket for instant task notifications.

### Connection

```
GET /api/mining/v1/ws
Auth: Required (EIP-712 headers on the HTTP upgrade request)
Protocol: WebSocket
```

The server identifies the client from the authenticated principal's address. No `address` query parameter is needed.

### Server → Client Messages

**Repeat Crawl Task Assignment (for Miners):**
```json
{
  "type": "repeat_crawl_task",
  "data": {
    "id": "rpt_xyz789",
    "epoch_id": "2026-04-01",
    "submission_id": "sub_abc123",
    "step": 1,
    "assigned_miner_id": "0xabc...",
    "status": "pending_claim",
    "phase_a_result": "pending"
  }
}
```

**Evaluation Task Assignment (for Validators):**
```json
{
  "type": "evaluation_task",
  "data": {
    "task_id": "evt_abc123",
    "assignment_id": "asg_xyz789",
    "submission_id": "sub_abc123",
    "mode": "single"
  }
}
```

### Client → Server Messages

**ACK Repeat Crawl (confirms receipt, starts 5-minute lease):**
```json
{"ack": "rpt_xyz789"}
```

**ACK Evaluation (confirms receipt, starts 10-minute lease):**
```json
{"ack_eval": "asg_xyz789"}
```

**Reject Repeat Crawl (declines task, no penalty):**
```json
{"reject": "rpt_xyz789"}
```

### Timeout Behavior

| Scenario | Timeout | Consequence |
|----------|---------|-------------|
| No ACK after push | 30 seconds | Task reassigned to another participant. No penalty. |
| ACK'd but no report (Miner) | 5 minutes | Task recycled + timeout recorded (4-of-10 → eviction) |
| ACK'd but no report (Validator) | 10 minutes | Task recycled + score=0 recorded + timeout (3-of-10 → eviction) |
| 3 consecutive unclaimed (Validator) | — | Removed from ready pool + 1 hour cooldown |

---

## 7. Dataset Management

### List Datasets (Public)

```
GET /api/core/v1/datasets
Query: page=1, page_size=20, sort=created_at, order=desc

Response: Array of Dataset objects
```

### Get Dataset (Public)

```
GET /api/core/v1/datasets/{dataset_id}
```

### Create Dataset (Admin)

```
POST /api/core/v1/datasets
Auth: Required (core.datasets.create permission)

Request Body:
{
  "name": "X Posts",
  "creation_fee": "50",
  "source_domains": ["x.com", "twitter.com"],
  "schema": {
    "post_id": {"type": "string", "required": true},
    "content": {"type": "string", "required": true},
    "author": {"type": "string", "required": true}
  },
  "dedup_fields": ["post_id"],
  "url_patterns": ["(x|twitter)\\.com/.+/status/(\\d+)"],
  "refresh_interval": null
}
```

**Validation rules:**
- `schema` must have ≥ 3 fields with `required: true`
- Every field in `dedup_fields` must exist in `schema` and be `required: true`
- Every entry in `url_patterns` must be a valid Go regex (compiled with `regexp.Compile`)
- `dedup_fields` becomes **immutable** once the dataset reaches `active` status

### Dataset Status Transitions

```
POST /api/core/v1/datasets/{id}/activate   — pending_review/paused → active
POST /api/core/v1/datasets/{id}/pause      — active → paused
POST /api/core/v1/datasets/{id}/archive    — active/paused → archived
POST /api/core/v1/datasets/{id}/reject     — pending_review → rejected
POST /api/core/v1/datasets/{id}/review     — pending_review → approved/rejected
```

**State machine:**
```
Created → pending_review → active ←→ paused
                         ↓              ↓
                      rejected       archived
```

---

## 8. Submission API

### Submit Entries

See [Step 4 in Miner Workflow](#step-4-submit-data) for complete request/response format.

**Important behaviors:**
- Each entry is processed **independently**. If one fails, others can still succeed.
- The `normalized_url` is computed by the server using `url_patterns` regex extraction. The matched portion of the URL becomes the normalized form (stripping query strings, fragments, etc.).
- Submissions with `high_risk: true` will undergo 100% quality evaluation (instead of the normal 30% sampling rate).

### List Submissions

```
GET /api/core/v1/submissions
Auth: Required (core.submissions.read)
Query: page, page_size, sort, order, dataset_id, submission_id
```

### Get Submission

```
GET /api/core/v1/submissions/{id}
Auth: Required (core.submissions.read)
```

---

## 9. Deduplication API

### Check by Hash

```
GET /api/core/v1/dedup/check?dataset_id=ds_posts&dedup_hash=a665a...
Auth: Required (core.dedup.check, miner role)

Response:
{
  "dataset_id": "ds_posts",
  "dedup_hash": "a665a...",
  "exists": true
}
```

### Check by Structured Data

```
POST /api/core/v1/dedup-occupancies/check
Auth: Required (core.dedup_occupancies.read)

Request:
{
  "dataset_id": "ds_posts",
  "structured_data": {"post_id": "123", "content": "hello", "author": "alice"}
}

Response:
{
  "dataset_id": "ds_posts",
  "dedup_hash": "a665a...",
  "occupied": true,
  "submission_status": "pending"
}
```

The server computes the `dedup_hash` from the dataset's `dedup_fields` and the provided `structured_data`.

### List Dedup Occupancies

```
GET /api/core/v1/dedup-occupancies
Auth: Required (core.dedup_occupancies.read)
Query: page, page_size
```

---

## 10. Repeat Crawl API

### Create (Admin/System)

```
POST /api/mining/v1/repeat-crawl-tasks
Auth: Required (mining.repeat.create)

Request:
{
  "submission_id": "sub_abc123",
  "epoch_id": "2026-04-01"
}
```

### Create from Core Submission (Admin)

```
POST /api/mining/v1/core-submissions/{submission_id}/repeat-crawl-tasks
Auth: Required (mining.core_submission.repeat)

Request:
{
  "epoch_id": "2026-04-01"
}
```

### Claim

```
POST /api/mining/v1/repeat-crawl-tasks/claim
Auth: Required (mining.repeat.claim)
```

Returns the next pending repeat crawl task assigned to the authenticated miner.

### Report

```
POST /api/mining/v1/repeat-crawl-tasks/{id}/report
Auth: Required (mining.repeat.report)

Request:
{
  "cleaned_data": "Re-crawled text content"
}
```

### Reject

```
POST /api/mining/v1/repeat-crawl-tasks/{id}/reject
Auth: Required (mining.repeat.reject)
```

### Reassign (Admin)

```
POST /api/mining/v1/repeat-crawl-tasks/{id}/reassign
Auth: Required (mining.repeat.reassign)

Request:
{
  "assigned_miner_id": "0xnew_miner"
}
```

### List

```
GET /api/mining/v1/repeat-crawl-tasks
Auth: Required (mining.repeat.list)
```

### Get

```
GET /api/mining/v1/repeat-crawl-tasks/{id}
Auth: Required (mining.repeat.list)
```

---

## 11. Evaluation API

### Create from Core Submission (Admin)

```
POST /api/mining/v1/core-submissions/{submission_id}/evaluation-tasks
Auth: Required (mining.core_submission.evaluation)

Request:
{
  "epoch_id": "2026-04-01",
  "golden_score": 85
}
```

The `golden_score` field is optional. When set, a percentage of assignments (based on validator credit) will be marked as golden tasks using this expected score.

### Claim

```
POST /api/mining/v1/evaluation-tasks/claim
Auth: Required (mining.evaluation.claim)

Response:
{
  "task_id": "evt_abc123",
  "assignment_id": "asg_xyz789",
  "validator_id": "0xdef...",
  "golden": false
}
```

### Report

```
POST /api/mining/v1/evaluation-tasks/{id}/report
Auth: Required (mining.evaluation.report)

Request:
{
  "assignment_id": "asg_xyz789",
  "score": 85
}
```

**Score range:** 0-100 integer. See [scoring guidelines](#step-5-submit-evaluation-score) for dimension weights.

### List

```
GET /api/mining/v1/evaluation-tasks
Auth: Required (mining.evaluation.list)
```

### Get

```
GET /api/mining/v1/evaluation-tasks/{id}
Auth: Required (mining.evaluation.list)
```

---

## 12. Epoch & Settlement API

### List Epochs (Public)

```
GET /api/core/v1/epochs
Query: page, page_size, sort, order

Response:
[
  {
    "id": "epoch_20260401",
    "epoch_id": "2026-04-01",
    "status": "settled",
    "summary": {"total": 500, "confirmed": 450, "rejected": 50},
    "window_start_at": "2026-04-01T00:00:00Z",
    "window_end_at": "2026-04-02T00:00:00Z"
  }
]
```

**Epoch statuses:** `open` → `settling` → `settled` (or `failed` on error)

### Get Epoch Snapshot (Public)

Real-time aggregated stats for the current or past epoch:

```
GET /api/mining/v1/epochs/2026-04-01/snapshot

Response:
{
  "epoch_id": "2026-04-01",
  "miners": {
    "0xabc...": {"task_count": 95, "avg_score": 78.5}
  },
  "validators": {
    "0xdef...": {"eval_count": 120, "accuracy": 85.2, "peer_review_accuracy": 82.0, "consecutive_idle": 0}
  }
}
```

### Get Settlement Results (Public)

Final settlement data after epoch closure:

```
GET /api/mining/v1/epochs/2026-04-01/settlement-results

Response:
{
  "epoch_id": "2026-04-01",
  "miners": [
    {
      "miner_id": "0xabc...",
      "task_count": 95,
      "avg_score": 78.5,
      "qualified": true,
      "weight": 585056.25,
      "reward_amount": 45.2,
      "confirmed_submission_count": 95,
      "rejected_submission_count": 0
    }
  ],
  "validators": [
    {
      "validator_id": "0xdef...",
      "eval_count": 120,
      "accuracy": 85.2,
      "qualified": true,
      "weight": 871084.8,
      "reward_amount": 38.7,
      "slashed_amount": 0,
      "redistributed_amount": 2.1,
      "penalty_reason": ""
    }
  ]
}
```

### Trigger Settlement (Admin)

```
POST /api/core/v1/epochs/2026-04-01/settle
Auth: Required (core.epochs.settle)
```

Settlement normally runs automatically at UTC 00:00. This endpoint allows manual triggering.

---

## 13. Protocol Configuration API

### List Configs (Admin)

```
GET /api/core/v1/protocol-configs
Auth: Required (core.protocol_configs.read)
Query: key (optional filter)

Response:
[
  {"key": "sampling_rate", "scope": "", "value": "0.30", "description": "Base sampling rate"},
  {"key": "epoch_emission", "scope": "", "value": "10000", "description": "ocDATA per epoch"},
  {"key": "miner_reward_share", "scope": "", "value": "0.41"},
  {"key": "validator_reward_share", "scope": "", "value": "0.41"},
  {"key": "owner_reward_share", "scope": "", "value": "0.18"},
  {"key": "validator_ratio", "scope": "", "value": "5"},
  {"key": "min_stake", "scope": "", "value": "1000000000000000000000"},
  {"key": "emission_weight", "scope": "ds_posts", "value": "200"}
]
```

### Get Config (Admin)

```
GET /api/core/v1/protocol-configs/sampling_rate?scope=
Auth: Required
```

### Set Config (Admin)

```
PUT /api/core/v1/protocol-configs
Auth: Required (core.protocol_configs.write)

Request:
{
  "key": "emission_weight",
  "scope": "ds_posts",
  "value": "200",
  "description": "Posts dataset reward weight"
}
```

**scope:** Empty string `""` for global configs. Dataset ID for per-dataset configs (e.g., `emission_weight`).

### Delete Config (Admin)

```
DELETE /api/core/v1/protocol-configs/emission_weight?scope=ds_posts
Auth: Required (core.protocol_configs.write)
```

### Default Protocol Parameters

| Key | Default | Description |
|-----|---------|-------------|
| `sampling_rate` | `0.30` | 30% of submissions enter quality evaluation |
| `epoch_emission` | `10000` | Total ocDATA minted per epoch |
| `miner_reward_share` | `0.41` | 41% of emission to miners |
| `validator_reward_share` | `0.41` | 41% of emission to validators |
| `owner_reward_share` | `0.18` | 18% of emission to subnet owner |
| `validator_ratio` | `5` | 1 validator per 5 active miners |
| `min_stake` | `1000000000000000000000` | 1000 AWP in wei |
| `emission_weight` | `100` (per dataset) | Controls miner reward pool distribution |

---

## 14. Validator Application API

### Submit Application

```
POST /api/iam/v1/validator-applications
Auth: Required (iam.validator.apply)

Response (201):
{
  "id": "app_abc123",
  "address": "0xdef...",
  "status": "pending_review",
  "submitted_at": "2026-04-01T08:00:00Z"
}
```

### Get My Application

```
GET /api/iam/v1/validator-applications/me
Auth: Required
```

### Review Application (Admin)

```
POST /api/iam/v1/validator-applications/app_abc123/review
Auth: Required (iam.validator.review)

Request:
{
  "decision": "approve",
  "rejection_reason": ""
}
```

---

## 15. Credit System

### Miner Credit Tiers

| Tier | Score | Submit Limit/Epoch | PoW Probability | Sampling Rate |
|------|-------|-------------------|-----------------|---------------|
| novice | 0-19 | 100 | 100% | 100% |
| restricted | 20-39 | 500 | 50% | 60% |
| normal | 40-59 | 2,000 | 20% | 45% |
| good | 60-79 | 10,000 | 5% | 30% |
| excellent | 80-100 | 1,000,000 | 1% | 30% |

### Validator Credit Tiers

| Tier | Score | Task Interval | Golden Task % | Min Evals/Epoch |
|------|-------|--------------|---------------|-----------------|
| novice | 0-19 | ≥ 10 min | 40% | 3 |
| restricted | 20-39 | ≥ 5 min | 30% | 10 |
| normal | 40-59 | ≥ 2 min | 20% | 10 |
| good | 60-79 | ≥ 30 sec | 10% | 10 |
| excellent | 80-100 | ≥ 10 sec | 5% | 10 |

### Credit Adjustment (Per Epoch)

| Outcome | Credit Change |
|---------|--------------|
| Qualified (miner: task≥80 & avg≥60; validator: accuracy≥60 & evals≥min) | +5 (cap 100) |
| Unqualified | -15 (floor 0) |
| 3 consecutive unqualified epochs | Reset to 0 |

### Validator Accuracy Penalties

| Accuracy Range | Reward | Credit | Flag |
|---------------|--------|--------|------|
| ≥ 60% | Normal | +5, flag=0 | Reset |
| 40-60% | Normal | -15, flag++ | Increment |
| 20-40% | **Confiscated** (100%) | -15, flag++ | Increment |
| < 20% | Confiscated + **30-day eviction** | Reset to 0 | N/A |
| flag ≥ 5 consecutive | — | Reset to 0 | **7-day eviction** |

---

## 16. Timing Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Heartbeat interval | 60s | How often the Skill should send heartbeat |
| Heartbeat TTL | 120s | Offline after this period without heartbeat |
| Repeat Crawl lease | 5 min | Time to complete after claiming |
| Evaluation lease | 10 min | Time to complete after claiming |
| Claim deadline | 30s | Time to ACK/claim after task assignment |
| Unclaimed cooldown | 1 hour | Blocked from ready pool after 3 consecutive unclaimed |
| Epoch duration | 24 hours | UTC 00:00 to UTC 00:00 |
| Cooldown (rejected data) | 1 Epoch | Cannot re-submit same dedup_hash |
| High-risk period | 3 Epochs | 100% evaluation for previously-rejected content |
| PoW challenge TTL | 5 min | Time to answer PoW challenge |

---

## 17. Error Handling

### HTTP Status Code Guide

| Code | Meaning | Skill Action |
|------|---------|-------------|
| 200/201 | Success | Process response normally |
| 400 | Bad request | Fix request body/params, do not retry unchanged |
| 401 | Auth failed | Re-sign with fresh timestamp |
| 403 | Forbidden | Wrong role or insufficient permission — cannot recover |
| 404 | Not found | Resource doesn't exist — skip |
| 409 | Conflict | State conflict (duplicate, wrong status, capacity full) — read error code |
| 422 | Validation failed | Fix input based on `field_errors` |
| 429 | Rate limited | Wait for `retry_at` timestamp, then retry |
| 500 | Server error | Retry with exponential backoff |
| 503 | Not ready | Service starting up — retry after delay |

### Common Error Codes

| Code | HTTP | Description |
|------|------|-------------|
| `dataset_inactive` | 409 | Dataset not in active status |
| `dedup_hash_conflict` | 409 | Content already exists |
| `dedup_hash_in_cooldown` | 409 | Content in post-rejection cooldown |
| `url_pattern_mismatch` | 422 | URL doesn't match dataset patterns |
| `url_already_occupied` | 409 | Normalized URL slot taken |
| `insufficient_stake` | 403 | Validator stake below minimum |
| `validator_capacity_full` | 409 | No room for new validators |
| `validator_not_ready` | 409 | Cannot join ready pool (conditions not met) |
| `evaluation_task_not_found` | 404 | No pending task for this validator |
| `repeat_task_not_found` | 404 | No pending task for this miner |
| `pow_challenge_not_found` | 404 | Challenge expired or already answered |

---

## 18. Miner Skill Reference Implementation

```python
import time
import requests
from eth_account import Account

BASE_URL = "http://coordinator:8080"
PRIVATE_KEY = "0x..."
ADDRESS = Account.from_key(PRIVATE_KEY).address

def sign_headers():
    """Generate EIP-712 auth headers"""
    now = datetime.utcnow()
    return {
        "X-Signer": ADDRESS,
        "X-Signature": sign_eip712(PRIVATE_KEY, now),
        "X-Nonce": str(uuid4()),
        "X-Issued-At": now.isoformat() + "Z",
        "X-Expires-At": (now + timedelta(minutes=5)).isoformat() + "Z"
    }

def main_loop():
    while True:
        # 1. Heartbeat
        hb = requests.post(f"{BASE_URL}/api/mining/v1/heartbeat",
            json={"client": "miner-skill/1.0"},
            headers=sign_headers()
        ).json()
        credit = hb["data"]["miner"]["credit"]
        limit = hb["data"]["miner"]["epoch_submit_limit"]

        # 2. Get active datasets
        datasets = requests.get(f"{BASE_URL}/api/core/v1/datasets").json()["data"]
        active = [d for d in datasets if d["status"] == "active"]

        # 3. Crawl & submit for each dataset
        for dataset in active:
            entries = crawl_dataset(dataset)

            # Pre-check dedup
            clean_entries = []
            for entry in entries:
                check = requests.get(
                    f"{BASE_URL}/api/core/v1/dedup/check",
                    params={"dataset_id": dataset["dataset_id"], "dedup_hash": compute_hash(entry, dataset["dedup_fields"])},
                    headers=sign_headers()
                ).json()
                if not check["data"]["exists"]:
                    clean_entries.append(entry)

            if clean_entries:
                result = requests.post(f"{BASE_URL}/api/core/v1/submissions",
                    json={"dataset_id": dataset["dataset_id"], "entries": clean_entries},
                    headers=sign_headers()
                ).json()

                # Handle PoW challenge
                if result["data"]["admission_status"] == "challenge_required":
                    challenge = result["data"]["challenge"]
                    answer = solve_pow(challenge["prompt"])
                    requests.post(
                        f"{BASE_URL}/api/mining/v1/pow-challenges/{challenge['id']}/answer",
                        json={"answer": answer},
                        headers=sign_headers()
                    )
                    # Retry submission after passing PoW
                    requests.post(f"{BASE_URL}/api/core/v1/submissions",
                        json={"dataset_id": dataset["dataset_id"], "entries": clean_entries},
                        headers=sign_headers()
                    )

        # 4. Join ready pool for repeat crawl tasks
        requests.post(f"{BASE_URL}/api/mining/v1/miners/ready", headers=sign_headers())

        # 5. Check for repeat crawl tasks
        try:
            task = requests.post(f"{BASE_URL}/api/mining/v1/repeat-crawl-tasks/claim",
                headers=sign_headers()
            ).json()
            if task.get("data"):
                cleaned = crawl_url(task["data"]["url"])
                requests.post(
                    f"{BASE_URL}/api/mining/v1/repeat-crawl-tasks/{task['data']['id']}/report",
                    json={"cleaned_data": cleaned},
                    headers=sign_headers()
                )
        except:
            pass  # No tasks available

        time.sleep(60)
```

---

## 19. Validator Skill Reference Implementation

```python
import time

def validator_loop():
    while True:
        # 1. Heartbeat
        hb = requests.post(f"{BASE_URL}/api/mining/v1/heartbeat",
            json={"client": "validator-skill/1.0"},
            headers=sign_headers()
        ).json()
        interval = hb["data"]["validator"]["min_task_interval_seconds"]
        eligible = hb["data"]["validator"]["eligible"]

        if not eligible:
            time.sleep(60)
            continue

        # 2. Join ready pool
        try:
            requests.post(f"{BASE_URL}/api/mining/v1/validators/ready", headers=sign_headers())
        except:
            time.sleep(interval)
            continue

        # 3. Claim evaluation task
        try:
            assignment = requests.post(f"{BASE_URL}/api/mining/v1/evaluation-tasks/claim",
                headers=sign_headers()
            ).json()["data"]

            # 4. Evaluate the submission
            # The cleaned_data and structured_data are available from the task context
            score = evaluate_quality(
                cleaned_data=assignment.get("cleaned_data", ""),
                structured_data=assignment.get("structured_data", {}),
                schema=get_dataset_schema(assignment.get("dataset_id"))
            )

            # 5. Submit score
            requests.post(
                f"{BASE_URL}/api/mining/v1/evaluation-tasks/{assignment['task_id']}/report",
                json={
                    "assignment_id": assignment["assignment_id"],
                    "score": score
                },
                headers=sign_headers()
            )
        except:
            pass  # No tasks available

        time.sleep(max(interval, 10))

def evaluate_quality(cleaned_data, structured_data, schema):
    """Score structured_data quality against cleaned_data reference.

    Dimensions:
    - Field completeness (30%): All required fields present?
    - Value accuracy (40%): Values match cleaned_data content?
    - Type correctness (15%): Values match schema types?
    - Information sufficiency (15%): No obvious missing data?
    """
    score = 0
    # ... implement evaluation logic ...
    return min(max(score, 0), 100)
```
