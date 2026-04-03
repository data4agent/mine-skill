# Validator API Map

## 目录

- 签名与响应约定
- 角色与权限
- 加网相关接口
- Validator 运行态接口
- 数据评审接口
- 外部 staking 接口

## 签名与响应约定

签名基线：

- 公共配置：`GET /api/public/v1/signature-config`
- 联调说明：`docs/platform_service_web3_client_integration.md`
- 示例脚本：`docs/platform_service_web3_request_example.mjs`

最少请求头：

- `X-Signer`
- `X-Signature`
- `X-Nonce`
- `X-Issued-At`
- `X-Expires-At`

建议同时发送：

- `X-Chain-Id`
- `X-Signed-Headers`
- `Content-Type`
- `X-Request-ID`

平台响应 envelope：

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "req-local-001"
  }
}
```

错误 envelope：

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

## 角色与权限

| 动作 | 路径 | 权限 | 角色 |
|---|---|---|---|
| 查询当前身份 | `/api/iam/v1/me` | `iam.me.read` | `member+` |
| 提交 validator 申请 | `/api/iam/v1/validator-applications` | `iam.validator.apply` | `member` |
| 查询我的申请 | `/api/iam/v1/validator-applications/me` | `iam.validator.apply` | `member` |
| 审批 validator 申请 | `/api/iam/v1/validator-applications/:id/review` | `iam.validator.review` | `admin` |
| 统一 heartbeat | `/api/mining/v1/heartbeat` | `mining.heartbeat` | `member` / `miner` / `validator` |
| validator ready | `/api/mining/v1/validators/ready` | `mining.validator.ready` | `validator` |
| validator unready | `/api/mining/v1/validators/unready` | `mining.validator.unready` | `validator` |
| claim evaluation task | `/api/mining/v1/evaluation-tasks/claim` | `mining.evaluation.claim` | `validator` |
| report evaluation task | `/api/mining/v1/evaluation-tasks/:id/report` | `mining.evaluation.report` | `validator` |
| list validation results | `/api/core/v1/validation-results` | `core.validation_results.read` | `validator` |
| get validation result | `/api/core/v1/validation-results/:id` | `core.validation_results.read` | `validator` |
| create validation result | `/api/core/v1/validation-results` | `core.validation_results.create` | `validator` |

当前默认不属于 validator 自助权限的接口：

- `/api/mining/v1/evaluation-tasks` 创建任务：`admin`
- `/api/mining/v1/validators/:id/stats`：`admin`
- `/api/mining/v1/ws`：默认 `miner`

## 加网相关接口

### `POST /api/iam/v1/validator-applications`

- body：无
- 地址来源：当前签名主体
- 观测 IP：服务端写入

成功 data 主要字段：

```json
{
  "id": "app_001",
  "address": "0xabc...",
  "status": "pending_review",
  "submitted_at": "2026-04-02T12:00:00Z"
}
```

常见失败：

- `validator_application_exists`
- `role_suspended`
- `insufficient_stake`
- `validator_capacity_full`

### `GET /api/iam/v1/validator-applications/me`

成功 data 主要字段：

- `id`
- `address`
- `status`
- `submitted_at`
- `reviewed_at`
- `reviewed_by`
- `rejection_reason`

### `POST /api/iam/v1/validator-applications/:id/review`

请求体：

```json
{
  "decision": "approve",
  "rejection_reason": ""
}
```

或：

```json
{
  "decision": "reject",
  "rejection_reason": "manual rejection reason"
}
```

## Validator 运行态接口

### `POST /api/mining/v1/heartbeat`

请求体：

```json
{
  "client": "validator-cli/1.0"
}
```

Validator 成功 data 示例：

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

成功 data：

```json
{
  "validator_id": "0xabc...",
  "status": "ready"
}
```

### `POST /api/mining/v1/validators/unready`

成功 data：

```json
{
  "validator_id": "0xabc...",
  "status": "unready"
}
```

### `POST /api/mining/v1/evaluation-tasks/claim`

成功 data：

```json
{
  "task_id": "eval_001",
  "assignment_id": "asg_001",
  "validator_id": "0xabc...",
  "golden": false
}
```

### `POST /api/mining/v1/evaluation-tasks/{id}/report`

请求体：

```json
{
  "assignment_id": "asg_001",
  "score": 92
}
```

常见失败：

- `evaluation_task_not_found`
- `validator_not_ready`
- `task_claim_forbidden`

## 数据评审接口

### `POST /api/core/v1/validation-results`

请求体：

```json
{
  "submission_id": "sub_123",
  "verdict": "accepted",
  "score": 95,
  "comment": "结构化结果完整",
  "idempotency_key": "ivr-001"
}
```

已知 `verdict`：

- `accepted`
- `rejected`

### `GET /api/core/v1/validation-results`

支持查询参数：

- `page`
- `page_size`
- `sort`
- `order`

### `GET /api/core/v1/validation-results/{id}`

返回单条 validation result 详情。

## 外部 staking 接口

### RPC：`staking.getAgentSubnetStake`

请求：

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

成功返回：

```json
{
  "jsonrpc": "2.0",
  "result": {
    "amount": "5000000000000000000000"
  },
  "id": 1
}
```

### WSS：`watchAllocations`

订阅：

```json
{
  "watchAllocations": [
    { "subnetId": "155921803519041537" }
  ]
}
```

说明：

- 平台内部 watcher 用它感知 stake 变化并驱逐质押不足的 validator
- 这不是 validator 在平台侧执行业务动作的主入口
