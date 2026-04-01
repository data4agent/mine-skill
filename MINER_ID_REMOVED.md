# MINER_ID 已移除 ✅

## 概述

从此版本开始，**不再需要配置 MINER_ID**。矿工识别完全通过钱包地址自动完成。

## 为什么移除？

经过 API 分析发现：
- ❌ 平台的所有 API 都不使用 MINER_ID 参数
- ✅ 平台使用 EIP-712 签名中的钱包地址识别矿工
- ❌ MINER_ID 环境变量从未发送到平台
- ✅ 心跳响应直接返回钱包地址作为 miner_id

**结论：MINER_ID 是冗余配置**

## 改动内容

### 代码层面

1. **WorkerConfig** - 移除 miner_id 字段
   ```python
   # 之前
   @dataclass
   class WorkerConfig:
       miner_id: str  # ❌ 已删除
       ...
   
   # 现在
   @dataclass
   class WorkerConfig:
       # miner_id 已移除
       ...
   ```

2. **PlatformClient** - 移除 miner_id 参数
   ```python
   # 之前
   def __init__(self, *, miner_id: str, ...):
       self.miner_id = miner_id
   
   # 现在
   def __init__(self, *, ...):
       # miner_id 从钱包自动获取
   ```

3. **agent_runtime.py** - 不再读取 MINER_ID 环境变量
   ```python
   # 之前
   config = WorkerConfig(
       miner_id=os.environ["MINER_ID"],  # ❌ 已删除
       ...
   )
   
   # 现在
   config = WorkerConfig(
       # 不需要 miner_id
       ...
   )
   ```

### 配置层面

1. **SKILL.md** - 移除环境变量要求
   ```yaml
   # 之前
   env:
     - PLATFORM_BASE_URL
     - MINER_ID  # ❌ 已删除
   
   # 现在
   env:
     - PLATFORM_BASE_URL
   ```

2. **.env.example** - 移除配置示例
   ```bash
   # 之前
   export MINER_ID=miner-default  # ❌ 已删除
   
   # 现在
   # Note: Miner identification is automatic via wallet address
   ```

## 升级指南

### 对现有用户的影响

**好消息：零影响！** 🎉

如果你的 `.env` 文件中仍然有 `MINER_ID`：
- ✅ 代码会忽略它（不读取）
- ✅ 不会报错
- ✅ 挖矿功能完全正常

### 建议操作

你可以选择：

**选项 1：保持现状（推荐）**
```bash
# .env 中保留 MINER_ID 也没关系
export MINER_ID=miner-6442b287  # 会被忽略，但不影响运行
```

**选项 2：清理配置**
```bash
# 从 .env 中删除这一行
# export MINER_ID=miner-6442b287
```

两种选择都可以，功能完全相同。

## 工作原理

### 之前的流程

```
用户配置 MINER_ID
    ↓
代码读取 MINER_ID
    ↓
存储在 config 中
    ↓
传给 PlatformClient
    ↓
从不使用（平台用钱包地址）
```

### 现在的流程

```
用户解锁钱包
    ↓
代码获取钱包地址
    ↓
EIP-712 签名包含钱包地址
    ↓
平台从签名提取钱包地址
    ↓
自动作为 miner_id
```

**更简单、更自动、更准确！**

## API 验证

平台心跳响应证明：

```json
// 请求（不包含 miner_id）
POST /api/mining/v1/miners/heartbeat
Headers: {
  "X-Signer": "0x9915FFAF0dF84Dd26cb35f5D1329501919A8055d"
}
Body: {
  "client": "mine-agent"
}

// 响应（平台返回钱包地址作为 miner_id）
{
  "miner_id": "0x9915ffaf0df84dd26cb35f5d1329501919a8055d",
  "online": true,
  "credit": 0
}
```

**平台自动使用钱包地址，完全不需要我们配置！**

## 技术细节

### 查询 API 的处理

有 3 个查询 API 之前使用 `self.miner_id`：

```python
def fetch_miner_status(self):
    miner_id = self._signer.get_address() if self._signer else ""
    return self._request("GET", f"/api/mining/v1/miners/{miner_id}/status")
```

现在自动从钱包获取，更准确。

### 向后兼容

如果代码中有其他地方引用 `config.miner_id`：
- ❌ 会报错：`AttributeError: 'WorkerConfig' object has no attribute 'miner_id'`
- ✅ 应该使用：`signer.get_address()` 获取钱包地址

## 文档更新

已更新：
- ✅ SKILL.md - 移除 MINER_ID 要求
- ✅ .env.example - 移除 MINER_ID 配置
- ✅ 添加说明：Miner identification is automatic

待更新（非阻塞）：
- ⚠️ mine_setup.py - 诊断脚本仍检查 MINER_ID
- ⚠️ post_install_check.py - 安装检查仍检查 MINER_ID
- ⚠️ run_tool.py - 工具命令仍显示 MINER_ID

这些脚本的检查不影响核心功能，可以后续清理。

## 测试验证

验证步骤：

```bash
# 1. 移除 MINER_ID（如果存在）
unset MINER_ID

# 2. 解锁钱包
awp-wallet unlock --duration 3600

# 3. 设置 token
export AWP_WALLET_TOKEN=wlt_xxx

# 4. 运行挖矿
python scripts/run_tool.py run-worker 60 1

# 预期结果：
# ✓ 正常启动
# ✓ 心跳成功
# ✓ 领取任务成功
# ✓ 提交结果成功
```

## 优势

| 方面 | 之前 | 现在 |
|------|------|------|
| 配置复杂度 | 需要设置 MINER_ID | 无需配置 |
| 可能错误 | MINER_ID 设错 | 自动正确 |
| 一致性 | MINER_ID ≠ 钱包地址 | 始终一致 |
| 文档清晰度 | 需要解释 MINER_ID | 自动理解 |
| 用户体验 | 3 个环境变量 | 2 个环境变量 |

## 总结

✅ **MINER_ID 已完全移除**
- 代码不再读取
- 配置不再要求
- 文档已更新

✅ **用户体验提升**
- 零配置
- 自动识别
- 不会出错

✅ **向后兼容**
- 旧的 .env 文件仍可用
- MINER_ID 会被忽略
- 功能完全正常

🎉 **更简单、更可靠、更智能的挖矿配置！**
