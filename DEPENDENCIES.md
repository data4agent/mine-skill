# Mine Skill 依赖说明

## 依赖总览

### Python 依赖（核心）

**requirements-core.txt** (12 个包)

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| pydantic | ≥2.8.0 | 数据验证和模型 |
| httpx | ≥0.27.0 | HTTP 客户端 |
| typer | ≥0.12.3 | CLI 框架 |
| rich | ≥13.7.1 | 终端美化输出 |
| crawl4ai | ≥0.4.0,<1.0 | AI 爬虫框架 |
| beautifulsoup4 | ≥4.12.3 | HTML 解析 |
| lxml | ≥5.3.0 | XML/HTML 处理 |
| markdownify | ≥0.13.1 | HTML 转 Markdown |
| PyMuPDF | ≥1.26.0 | PDF 处理 |
| pymupdf4llm | ≥0.0.27 | PDF LLM 提取 |
| pycryptodome | ≥3.20.0 | 加密库 |

### Python 依赖（浏览器）

**requirements-browser.txt** (3 个包)

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| playwright | ≥1.52.0 | 浏览器自动化 |
| camoufox | ≥0.4.11 | 隐身浏览器 |

### Python 依赖（开发）

**requirements-dev.txt** (2 个包)

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| pytest | ≥8.4.1 | 测试框架 |

### Node.js 依赖

**awp-wallet**

| 包名 | 安装方式 | 用途 |
|------|----------|------|
| @aspect/awp-wallet | npm install -g | EVM 钱包 CLI (EIP-712 签名) |

## 实际安装大小

### Python 虚拟环境

```
.venv/  ≈ 870 MB
```

包含：
- Python 解释器副本
- 所有 Python 依赖包
- 依赖的依赖（传递依赖）

### awp-wallet

```
@aspect/awp-wallet  ≈ 150-200 MB
```

包含：
- Node.js 包和依赖
- EVM 钱包功能
- 加密库

## 总计

**完整安装（full profile）:**
```
Python 依赖:  870 MB
awp-wallet:   ~180 MB
----------------------------
总计:         ~1050 MB (约 1 GB)
```

**最小安装（core profile）:**
```
Python core:  ~400 MB
awp-wallet:   ~180 MB
----------------------------
总计:         ~580 MB
```

## 安装时间估算

基于普通网络连接：

| 步骤 | 时间 |
|------|------|
| 下载 Python 依赖 | 2-5 分钟 |
| 安装 Python 依赖 | 1-3 分钟 |
| 下载 awp-wallet | 30-60 秒 |
| 安装 awp-wallet | 10-30 秒 |
| **总计** | **4-10 分钟** |

## 依赖说明

### 核心依赖

**crawl4ai** - AI 驱动的网页爬虫框架
- 提供智能内容提取
- 支持多种爬取策略
- 集成 LLM 处理

**PyMuPDF / pymupdf4llm** - PDF 处理
- 读取 PDF 文档
- 提取文本和图片
- LLM 友好的格式化

**pycryptodome** - 加密库
- 数据加密/解密
- 哈希计算
- 签名验证

**httpx** - 现代 HTTP 客户端
- 异步 HTTP 请求
- HTTP/2 支持
- 连接池管理

### 浏览器依赖

**playwright** - 浏览器自动化
- 支持 Chromium/Firefox/WebKit
- 页面截图和录制
- 网络拦截和修改

**camoufox** - 反检测浏览器
- 绕过反爬虫机制
- 指纹随机化
- 高匿名性

### 工具依赖

**awp-wallet** - EVM 钱包 CLI
- 钱包管理（创建、导入、导出）
- EIP-712 签名
- 多链支持

## 优化建议

### 减少安装大小

1. **只安装核心依赖**
   ```bash
   INSTALL_PROFILE=core bash scripts/bootstrap.sh
   ```
   节省 ~470 MB

2. **跳过浏览器依赖**
   ```bash
   # 只安装 requirements-core.txt
   pip install -r requirements-core.txt
   ```
   节省 ~300 MB

3. **使用 uv 代替 pip**
   ```bash
   uv pip install -r requirements-core.txt
   ```
   更快的安装速度

### 加速安装

1. **使用国内镜像**
   ```bash
   # Python
   pip install -r requirements-core.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   
   # npm
   npm config set registry https://registry.npmmirror.com
   ```

2. **使用 uv**
   ```bash
   # uv 比 pip 快 10-100 倍
   pip install uv
   uv pip install -r requirements-core.txt
   ```

3. **并行安装**
   ```bash
   # Python 依赖和 awp-wallet 同时安装
   pip install -r requirements-core.txt &
   npm install -g @aspect/awp-wallet &
   wait
   ```

## 磁盘空间要求

| 场景 | 所需空间 |
|------|----------|
| 最小安装 | 600 MB |
| 标准安装 | 1.1 GB |
| 开发安装 | 1.2 GB |
| + 缓存和临时文件 | + 200-500 MB |
| **推荐预留** | **2 GB** |

## 卸载

完全卸载 mine skill：

```bash
# 1. 删除虚拟环境
rm -rf .venv

# 2. 卸载 awp-wallet
npm uninstall -g @aspect/awp-wallet

# 3. 清理缓存
pip cache purge
npm cache clean --force

# 释放空间: ~1.2 GB
```

## 依赖更新

查看过期依赖：

```bash
# Python
pip list --outdated

# npm
npm outdated -g @aspect/awp-wallet
```

更新依赖：

```bash
# Python
pip install --upgrade -r requirements-core.txt

# npm
npm update -g @aspect/awp-wallet
```

## 常见问题

### Q: 为什么虚拟环境这么大？

A: 包含了很多传递依赖。主要占空间的包：
- playwright: ~150 MB (浏览器二进制)
- crawl4ai: ~100 MB (AI 模型)
- PyMuPDF: ~50 MB (PDF 库)
- 其他传递依赖: ~570 MB

### Q: 可以共享虚拟环境吗？

A: 不推荐。每个项目应该有独立的虚拟环境，避免依赖冲突。

### Q: awp-wallet 可以本地安装吗？

A: 可以，但全局安装更方便：
```bash
# 本地安装（不推荐）
npm install @aspect/awp-wallet

# 使用
npx awp-wallet ...
```

全局安装后可以直接使用 `awp-wallet` 命令。
