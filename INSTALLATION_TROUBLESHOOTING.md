# 安装问题排查

## 问题：Skill 安装后 awp-wallet 未安装

### 症状

安装 mine skill 后，运行时报错：
```
ERROR: awp-wallet not found
```

或者：
```
Agent identity — not available
Fix: Install awp-wallet: npm install -g @aspect/awp-wallet
```

### 原因

可能的原因：
1. **Node.js 未安装** - awp-wallet 需要 Node.js 20+
2. **npm 权限问题** - 无法全局安装 npm 包
3. **网络问题** - npm registry 无法访问
4. **Bootstrap 脚本跳过了** - 如果通过其他方式安装
5. **PATH 问题** - awp-wallet 已安装但不在 PATH 中

### 解决方案

## 方法 1: 自动修复（推荐）⭐

运行修复脚本，它会自动检测并修复问题：

```bash
cd mine
python scripts/fix_installation.py
```

或者直接运行检查脚本：

```bash
python scripts/post_install_check.py
```

这会：
- ✓ 检查所有依赖（Python, Node.js, npm, awp-wallet）
- ✓ 自动安装缺失的组件
- ✓ 设置默认环境变量
- ✓ 验证安装成功

输出示例：
```
================================================================================
Mine Skill - Post-Install Check
================================================================================

✓ Python version: Python 3.12
✓ Node.js: Node.js v20.10.0
✓ npm: npm 10.2.3
⚠ awp-wallet: awp-wallet not found

================================================================================
Attempting Auto-Fix
================================================================================

→ Installing awp-wallet...
  ✓ awp-wallet installed successfully

================================================================================
✓ All checks passed!
================================================================================
```

## 方法 2: 重新运行 Bootstrap

```bash
# Windows
.\scripts\bootstrap.ps1

# Linux/Mac
bash scripts/bootstrap.sh
```

Bootstrap 脚本包含完整的安装流程。

## 方法 3: 手动安装步骤

### 步骤 1: 确认 Node.js 已安装

```bash
node --version
npm --version
```

如果未安装，从 https://nodejs.org 下载安装。

**推荐版本**: Node.js 20 LTS 或更高

### 步骤 2: 安装 awp-wallet

```bash
npm install -g @aspect/awp-wallet
```

### 步骤 3: 验证安装

```bash
awp-wallet --version
```

应该输出：
```
@aspect/awp-wallet/1.x.x
```

### 步骤 4: 初始化钱包

```bash
awp-wallet init
```

按提示设置密码。

### 步骤 5: 解锁钱包

```bash
awp-wallet unlock --duration 3600
```

复制输出的 `sessionToken`。

### 步骤 6: 设置环境变量

```bash
export AWP_WALLET_TOKEN=wlt_xxx  # 从上一步复制
```

## 常见问题

### Q1: npm install 报权限错误 (EACCES)

**Windows:**
```powershell
# 以管理员身份运行 PowerShell
npm install -g @aspect/awp-wallet
```

**Linux/Mac:**
```bash
# 不要用 sudo！使用 nvm 代替
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
npm install -g @aspect/awp-wallet
```

### Q2: npm registry 网络超时

使用国内镜像：

```bash
npm config set registry https://registry.npmmirror.com
npm install -g @aspect/awp-wallet
```

### Q3: awp-wallet 安装成功但找不到命令

**检查安装位置:**

```bash
npm list -g @aspect/awp-wallet
```

**查找可执行文件:**

```bash
# Windows
where awp-wallet

# Linux/Mac
which awp-wallet
```

**手动设置 PATH:**

Windows:
```powershell
$env:AWP_WALLET_BIN = "C:\Users\<用户名>\AppData\Roaming\npm\awp-wallet.cmd"
```

Linux/Mac:
```bash
export AWP_WALLET_BIN="$(npm root -g)/../bin/awp-wallet"
```

### Q4: Node.js 版本太低

```bash
# 检查版本
node --version  # 需要 >= v20.0.0

# 升级 Node.js

# Windows: 从 https://nodejs.org 下载最新版本

# macOS:
brew upgrade node

# Linux (使用 nvm):
nvm install 20
nvm use 20
nvm alias default 20
```

### Q5: Python 虚拟环境未创建

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements-core.txt

# Linux/Mac
source .venv/bin/activate
pip install -r requirements-core.txt
```

## 诊断命令

### 完整诊断

```bash
python scripts/run_tool.py doctor
```

返回 JSON 格式的详细诊断信息：

```json
{
  "status": "error",
  "checks": [
    {"name": "python", "ok": true, "message": "Python 3.12"},
    {"name": "awp-wallet", "ok": false, "message": "Not found"}
  ],
  "fix_commands": [
    "npm install -g @aspect/awp-wallet"
  ]
}
```

### Agent 状态

```bash
python scripts/run_tool.py agent-status
```

超简洁输出，适合 AI agent 解析：

```json
{
  "ready": false,
  "state": "missing_wallet",
  "message": "awp-wallet not installed",
  "next_action": "Install awp-wallet",
  "next_command": "npm install -g @aspect/awp-wallet"
}
```

## 验证安装完整性

运行完整检查：

```bash
python scripts/post_install_check.py
```

应该看到：

```
================================================================================
✓ All checks passed!
================================================================================

Next steps:
  1. Initialize wallet: awp-wallet init
  2. Unlock wallet:    awp-wallet unlock --duration 3600
  3. Start mining:     python scripts/run_tool.py run-worker 60 1
```

## 仍然无法解决？

### 收集诊断信息

```bash
# 系统信息
python --version
node --version
npm --version

# 检查 PATH
echo $PATH  # Linux/Mac
echo $env:PATH  # Windows

# npm 配置
npm config list

# 已安装的全局包
npm list -g --depth=0

# awp-wallet 查找
npm list -g @aspect/awp-wallet
which awp-wallet  # Linux/Mac
where awp-wallet  # Windows
```

### 提交 Issue

访问: https://github.com/your-repo/mine/issues

包含以上诊断信息和：
- 操作系统版本
- 安装步骤
- 完整错误信息
- `post_install_check.py` 输出

## 快速参考

| 问题 | 解决命令 |
|------|---------|
| 检查并修复 | `python scripts/fix_installation.py` |
| 重新安装 | `bash scripts/bootstrap.sh` |
| 诊断 | `python scripts/run_tool.py doctor` |
| 手动安装钱包 | `npm install -g @aspect/awp-wallet` |
| 初始化钱包 | `awp-wallet init` |
| 解锁钱包 | `awp-wallet unlock --duration 3600` |

## 预防措施

在安装 mine skill 之前，确保：

1. ✓ Node.js 20+ 已安装
2. ✓ Python 3.11+ 已安装
3. ✓ npm 可以全局安装包（权限正确）
4. ✓ 网络连接正常（可访问 npm registry）

完整安装流程：

```bash
# 1. 检查前置条件
node --version  # >= v20.0.0
python --version  # >= 3.11

# 2. 安装 mine skill
openclaw install mine

# 3. 验证安装
cd ~/.openclaw/extensions/mine
python scripts/post_install_check.py

# 4. 初始化
awp-wallet init
awp-wallet unlock --duration 3600

# 5. 开始挖矿
python scripts/run_tool.py run-worker 60 1
```

## 相关文档

- [AWP_WALLET_AUTO_INSTALL.md](docs/AWP_WALLET_AUTO_INSTALL.md) - awp-wallet 自动安装说明
- [EIP712_CONFIGURATION.md](docs/EIP712_CONFIGURATION.md) - EIP-712 签名配置
- [SKILL.md](SKILL.md) - Skill 使用文档
