# Validator Runbook

## 目录

- 角色与阶段
- Join Flow
- Runtime Flow
- Troubleshooting
- 代码与文档来源

## 角色与阶段

先识别当前是哪一种身份：

- `member`：还没有 Validator 权限，只能发起申请、查询自己的申请
- `admin`：可以审批 Validator 申请、触发 evaluation task、查询 epoch / validator stats
- `validator`：可以 heartbeat、ready/unready、写 validation result、claim/report evaluation task

再识别当前任务是哪一类：

- 想加入网络
- 想确认为什么没法加入
- 已经是 validator，想开始接任务
- 已经接到任务，想完成数据评审
- 某个接口报错，需要定位是签名、权限还是业务前置条件

## Join Flow

### 1. 建立签名上下文

先用这两个接口确认当前环境：

- `GET /api/public/v1/signature-config`
- `GET /api/iam/v1/me`

签名请求优先复用：

- `docs/platform_service_web3_client_integration.md`
- `docs/platform_service_web3_request_example.mjs`

注意：

- 所有业务接口都走标准 envelope：成功时 `success=true,data,meta.request_id`；失败时 `success=false,error,meta.request_id`
- 客户端不需要传 `ip_address`；服务端会从连接与代理链中观测

### 2. 检查 stake 是否满足最低要求

外部 staking RPC：

- 方法：`staking.getAgentSubnetStake`
- 文档：`docs/stake接口-v2.md`

当前协议中的最低 stake 规则：

- 默认 `min_stake = "1000000000000000000000"`（1000 AWP，wei）
- 代码与设计来源：
  - `docs/superpowers/specs/2026-04-01-validator-staking-design.md`
  - `apps/platform-service/internal/staking/`

当用户需要判断是否能加入时：

1. 查询 `(agent, subnetId)` 当前 stake
2. 将结果按十进制 wei 字符串与 `min_stake` 比较
3. 不满足时，预期平台会返回 `insufficient_stake`

### 3. 以 member 身份提交申请

接口：

- `POST /api/iam/v1/validator-applications`
- 权限：`iam.validator.apply`
- 默认允许角色：`member`

请求体：

- 无 body

平台会用当前签名主体地址作为申请地址，并记录观测到的 IP。

成功后主要字段：

- `id`
- `address`
- `status`
- `submitted_at`

可能结果：

- `pending_review`
- `approved`
- `rejected`

### 4. 查询自己的申请

接口：

- `GET /api/iam/v1/validator-applications/me`

用途：

- 轮询当前申请是否已获批
- 读取 `rejection_reason`
- 在自动化流程中确认是否可以切换到 validator 运行态

### 5. admin 审批

只有当用户明确以 admin 身份操作，或者任务目标是“协助管理员完成审批”时才走这一步。

接口：

- `POST /api/iam/v1/validator-applications/:id/review`
- 权限：`iam.validator.review`
- 默认允许角色：`admin`

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
  "rejection_reason": "stake below requirement"
}
```

审批通过时，服务会再次检查：

- stake 是否仍然达到 `min_stake`
- validator capacity 是否允许准入

因此“提交申请成功”不代表“审批时一定能通过”。

### 6. 理解容量竞争与保护期

Validator 准入不是只看最低 stake，还会看容量：

- `capacity = ceil(active_miner_count / validator_ratio)`
- 如果未满员，可直接准入
- 如果满员，会尝试替换 stake 最低且不在保护期内的 validator

保护期规则：

- `JoinedEpoch == currentEpoch` 时，处于保护期，不能被替换

如果容量已满且当前 stake 不足以替换最低可替换 validator，预期返回：

- `validator_capacity_full`

## Runtime Flow

### 1. heartbeat

接口：

- `POST /api/mining/v1/heartbeat`
- 权限：`mining.heartbeat`
- Validator body：

```json
{
  "client": "validator-cli/1.0"
}
```

返回中的关键字段：

- `role = "validator"`
- `validator.validator_id`
- `validator.credit`
- `validator.eligible`
- `validator.credit_tier`
- `validator.min_task_interval_seconds`

说明：

- 这是统一 heartbeat 入口，miner 和 validator 共用一个 path
- 服务端按当前角色分流
- 如果主体角色还不是 `validator`，不要假设 heartbeat 能把角色升级

### 2. ready / unready

接口：

- `POST /api/mining/v1/validators/ready`
- `POST /api/mining/v1/validators/unready`

用途：

- `ready`：声明自己可以接收新的 evaluation task
- `unready`：显式退出 ready pool，用于维护或暂时停止接单

如果 ready 失败，优先排查：

- 是否已经获批为 validator
- 是否近期 heartbeat 正常
- 是否因为质押下降或其他原因已被驱逐

### 3. 处理 evaluation task

只有 admin 能创建 evaluation task；validator 只负责 claim / report。

领取：

- `POST /api/mining/v1/evaluation-tasks/claim`

成功返回：

- `task_id`
- `assignment_id`
- `validator_id`
- `golden`

回报：

- `POST /api/mining/v1/evaluation-tasks/{taskID}/report`

请求体：

```json
{
  "assignment_id": "assign_001",
  "score": 92
}
```

说明：

- `assignment_id` 必须和 claim 返回一致
- `validator_id` 不从 body 传，服务端取当前签名主体
- 代码没有额外限制 score 区间；若无其他上游约束，按当前业务示例使用整数评分

### 4. 写 core validation result

这是 Validator 的另一条“数据评审”主路径，与 mining evaluation task 并行存在。

创建：

- `POST /api/core/v1/validation-results`

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

读取：

- `GET /api/core/v1/validation-results`
- `GET /api/core/v1/validation-results/{id}`

已知 verdict：

- `accepted`
- `rejected`

使用建议：

- 需要可重试写入时，总是带 `idempotency_key`
- 需要“直接对 submission 给出结论”时，优先考虑 `validation-results`
- 需要“完成 mining 侧分配给 validator 的评分任务”时，优先考虑 `evaluation-tasks`

## Troubleshooting

### 401 / 403 基础排查

先确认：

1. `GET /api/public/v1/signature-config` 是否拿到正确 domain 配置
2. `GET /api/iam/v1/me` 返回的 `subject` 与预期 signer 是否一致
3. 当前 `role` 是否满足目标接口权限

常见签名协议错误来源：

- `MISSING_HEADERS`
- `INVALID_NONCE`
- `FUTURE_TIMESTAMP`
- `EXPIRED`
- `VALIDITY_TOO_LONG`
- `UNTRUSTED_HOST`
- `INVALID_SIGNATURE`
- `SIGNER_MISMATCH`
- `NONCE_REUSED`

### 常见业务错误

- `validator_application_exists`
  - 已经提交过申请；改为查询 `/api/iam/v1/validator-applications/me`
- `role_suspended`
  - 身份被暂停，不能继续申请或操作
- `insufficient_stake`
  - 质押不足；查看返回里的 `requirements.min_stake`
- `validator_capacity_full`
  - 容量已满；等待 slot 或提高 stake
- `validator_not_ready`
  - 还没进入 ready pool、已被驱逐、或当前状态不可接任务
- `evaluation_task_not_found`
  - `task_id` / `assignment_id` / 当前 validator 身份三者不匹配
- `task_claim_forbidden`
  - 当前身份不是该任务允许的操作者

### 不要误判的点

- `POST /api/mining/v1/heartbeat` 不会替代审批流程
- `approved` 之前不要假设有 validator 权限
- `approved` 之后也可能因 staking watcher 发现 stake 下降而被驱逐
- `GET /api/mining/v1/validators/:id/stats` 当前默认不是 validator 自助接口，而是 admin 接口
- `GET /api/mining/v1/ws` 当前默认是 miner 接口，不是 validator 接口

## 代码与文档来源

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
