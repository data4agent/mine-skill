# Validator Runbook

## Table of Contents

- Roles and Phases
- Join Flow
- Runtime Flow
- Troubleshooting
- Code and Documentation Sources

## Roles and Phases

First identify which identity you currently have:

- `member`: Does not yet have Validator privileges; can only submit applications and query own applications
- `admin`: Can approve Validator applications, trigger evaluation tasks, and query epoch / validator stats
- `validator`: Can heartbeat, ready/unready, write validation results, and claim/report evaluation tasks

Then identify which category your current task falls into:

- Want to join the network
- Want to find out why joining failed
- Already a validator, want to start accepting tasks
- Already received a task, want to complete data review
- An endpoint returned an error, need to determine whether it is a signature, permission, or business precondition issue

## Join Flow

### 1. Establish Signing Context

Use these two endpoints to confirm the current environment:

- `GET /api/public/v1/signature-config`
- `GET /api/iam/v1/me`

For signing requests, prefer reusing:

- `docs/platform_service_web3_client_integration.md`
- `docs/platform_service_web3_request_example.mjs`

Notes:

- All business endpoints use the standard envelope: on success `success=true,data,meta.request_id`; on failure `success=false,error,meta.request_id`
- The client does not need to send `ip_address`; the server observes it from the connection and proxy chain

### 2. Check Whether Stake Meets the Minimum Requirement

External staking RPC:

- Method: `staking.getAgentSubnetStake`
- Documentation: `docs/stake接口-v2.md`

Minimum stake rules in the current protocol:

- Default `min_stake = "1000000000000000000000"` (1000 AWP, wei)
- Code and design sources:
  - `docs/superpowers/specs/2026-04-01-validator-staking-design.md`
  - `apps/platform-service/internal/staking/`

When a user needs to determine whether they can join:

1. Query the current stake for `(agent, subnetId)`
2. Compare the result as a decimal wei string against `min_stake`
3. If the requirement is not met, the platform is expected to return `insufficient_stake`

### 3. Submit Application as a Member

Endpoint:

- `POST /api/iam/v1/validator-applications`
- Permission: `iam.validator.apply`
- Default allowed role: `member`

Request body:

- No body

The platform uses the current signing principal's address as the application address and records the observed IP.

Key fields on success:

- `id`
- `address`
- `status`
- `submitted_at`

Possible outcomes:

- `pending_review`
- `approved`
- `rejected`

### 4. Query Your Own Application

Endpoint:

- `GET /api/iam/v1/validator-applications/me`

Use cases:

- Poll whether the current application has been approved
- Read the `rejection_reason`
- Confirm in an automated workflow whether it is safe to switch to validator runtime mode

### 5. Admin Approval

Only follow this step when the user is explicitly operating as an admin, or when the task objective is "assist the administrator in completing the approval."

Endpoint:

- `POST /api/iam/v1/validator-applications/:id/review`
- Permission: `iam.validator.review`
- Default allowed role: `admin`

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
  "rejection_reason": "stake below requirement"
}
```

When approval is granted, the service re-checks:

- Whether the stake still meets `min_stake`
- Whether the validator capacity allows admission

Therefore, "application submitted successfully" does not guarantee "approval will succeed at review time."

### 6. Understanding Capacity Competition and Protection Period

Validator admission does not only check the minimum stake; it also considers capacity:

- `capacity = ceil(active_miner_count / validator_ratio)`
- If not at full capacity, admission is granted directly
- If at full capacity, the system attempts to replace the validator with the lowest stake who is not in a protection period

Protection period rules:

- When `JoinedEpoch == currentEpoch`, the validator is in a protection period and cannot be replaced

If capacity is full and the current stake is insufficient to replace the lowest replaceable validator, the expected response is:

- `validator_capacity_full`

## Runtime Flow

### 1. heartbeat

Endpoint:

- `POST /api/mining/v1/heartbeat`
- Permission: `mining.heartbeat`
- Validator body:

```json
{
  "client": "validator-cli/1.0"
}
```

Key fields in the response:

- `role = "validator"`
- `validator.validator_id`
- `validator.credit`
- `validator.eligible`
- `validator.credit_tier`
- `validator.min_task_interval_seconds`

Notes:

- This is a unified heartbeat endpoint shared by both miners and validators under one path
- The server routes based on the current role
- If the principal's role is not yet `validator`, do not assume that heartbeat can upgrade the role

### 2. ready / unready

Endpoint:

- `POST /api/mining/v1/validators/ready`
- `POST /api/mining/v1/validators/unready`

Use cases:

- `ready`: Declare that you are available to receive new evaluation tasks
- `unready`: Explicitly exit the ready pool, used for maintenance or temporarily stopping task acceptance

If ready fails, prioritize checking:

- Whether you have been approved as a validator
- Whether recent heartbeats have been normal
- Whether you have been evicted due to stake decrease or other reasons

### 3. Handling Evaluation Tasks

Only admins can create evaluation tasks; validators are only responsible for claim / report.

Claim:

- `POST /api/mining/v1/evaluation-tasks/claim`

Successful response:

- `task_id`
- `assignment_id`
- `validator_id`
- `golden`

Report:

- `POST /api/mining/v1/evaluation-tasks/{taskID}/report`

Request body:

```json
{
  "assignment_id": "assign_001",
  "score": 92
}
```

Notes:

- `assignment_id` must match the one returned by claim
- `validator_id` is not passed in the body; the server uses the current signing principal
- The code does not impose additional restrictions on the score range; if there are no other upstream constraints, use integer scores per the current business examples

### 4. Writing Core Validation Results

This is another primary "data review" path for Validators, existing in parallel with the mining evaluation task flow.

Create:

- `POST /api/core/v1/validation-results`

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

Read:

- `GET /api/core/v1/validation-results`
- `GET /api/core/v1/validation-results/{id}`

Known verdicts:

- `accepted`
- `rejected`

Usage recommendations:

- When retryable writes are needed, always include `idempotency_key`
- When you need to "directly provide a conclusion on a submission," prefer `validation-results`
- When you need to "complete a scoring task assigned to a validator by the mining side," prefer `evaluation-tasks`

## Troubleshooting

### 401 / 403 Basic Troubleshooting

First confirm:

1. Whether `GET /api/public/v1/signature-config` returns the correct domain configuration
2. Whether the `subject` returned by `GET /api/iam/v1/me` matches the expected signer
3. Whether the current `role` satisfies the target endpoint's permission requirements

Common signing protocol error sources:

- `MISSING_HEADERS`
- `INVALID_NONCE`
- `FUTURE_TIMESTAMP`
- `EXPIRED`
- `VALIDITY_TOO_LONG`
- `UNTRUSTED_HOST`
- `INVALID_SIGNATURE`
- `SIGNER_MISMATCH`
- `NONCE_REUSED`

### Common Business Errors

- `validator_application_exists`
  - An application has already been submitted; switch to querying `/api/iam/v1/validator-applications/me`
- `role_suspended`
  - The identity has been suspended; cannot continue applying or operating
- `insufficient_stake`
  - Stake is insufficient; check `requirements.min_stake` in the response
- `validator_capacity_full`
  - Capacity is full; wait for a slot or increase stake
- `validator_not_ready`
  - Not yet in the ready pool, has been evicted, or current state does not allow task acceptance
- `evaluation_task_not_found`
  - `task_id` / `assignment_id` / current validator identity — the three do not match
- `task_claim_forbidden`
  - The current identity is not an allowed operator for this task

### Points to Avoid Misjudging

- `POST /api/mining/v1/heartbeat` does not replace the approval flow
- Do not assume validator privileges before `approved`
- Even after `approved`, eviction can occur if the staking watcher detects a stake decrease
- `GET /api/mining/v1/validators/:id/stats` is currently not a validator self-service endpoint by default; it is an admin endpoint
- `GET /api/mining/v1/ws` is currently a miner endpoint by default, not a validator endpoint

## Code and Documentation Sources

- `docs/stake接口-v2.md`
- `docs/platform_service_web3_client_integration.md`
- `docs/superpowers/specs/2026-04-01-validator-staking-design.md`
- `apps/platform-service/internal/handler/router.go`
- `apps/platform-service/internal/modules/iam/handler/router.go`
- `apps/platform-service/internal/modules/iam/service/service.go`
- `apps/platform-service/internal/modules/mining/handler/router.go`
- `apps/platform-service/internal/modules/mining/service/interfaces.go`
- `apps/platform-service/internal/modules/core/handler/router.go`
- `apps/platform-service/internal/auth/policy_defaults.go`
