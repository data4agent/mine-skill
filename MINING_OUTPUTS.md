# 挖矿输出说明

## 输出目录结构

挖矿过程会在 `output/` 目录下生成各种文件：

```
output/
├── _run_once/                    # 单次运行摘要
│   └── iteration-{N}.json       # 每次迭代的汇总信息
├── _worker_state/                # Worker 状态
│   ├── discovered_urls.jsonl    # 发现的 URL 队列
│   ├── active_tasks.json        # 活跃任务列表
│   └── datasets_snapshot.json   # 数据集快照
└── {source}/                     # 按来源分类的任务输出
    └── {item_id}/                # 每个任务的输出目录
        ├── task-input.jsonl     # 任务输入数据
        ├── records.jsonl        # 爬取记录
        ├── errors.jsonl         # 错误日志
        ├── summary.json         # 任务摘要
        ├── task/
        │   └── item.json        # 任务详情
        ├── crawler/
        │   └── result.json      # 爬虫结果
        ├── occupancy/
        │   └── response.json    # URL 占用检查
        ├── preflight/
        │   ├── response.json    # 预检响应
        │   ├── rejection.json   # 拒绝原因（如果被拒绝）
        │   └── challenge.json   # PoW 挑战
        └── _runtime/
            └── mine-model-config.json  # 模型配置
```

## 核心输出文件

### 1. 任务级别输出

#### task-input.jsonl
任务的输入数据（JSONL 格式，每行一个 JSON 对象）

```jsonl
{"url": "https://example.com", "metadata": {...}}
{"url": "https://example.org", "metadata": {...}}
```

#### records.jsonl
爬取的数据记录

```jsonl
{"title": "Example", "content": "...", "url": "https://example.com", "timestamp": "2026-04-01T12:00:00Z"}
{"title": "Another", "content": "...", "url": "https://example.org", "timestamp": "2026-04-01T12:01:00Z"}
```

**字段说明:**
- `url`: 爬取的 URL
- `title`: 页面标题
- `content`: 提取的内容
- `metadata`: 元数据（作者、发布时间等）
- `timestamp`: 爬取时间戳

#### errors.jsonl
爬取过程中的错误

```jsonl
{"url": "https://fail.com", "error": "Connection timeout", "timestamp": "2026-04-01T12:00:00Z"}
```

#### summary.json
任务执行摘要

```json
{
  "item_id": "repeat-crawl-123",
  "source": "repeat-crawl-tasks",
  "status": "completed",
  "records_count": 50,
  "errors_count": 2,
  "start_time": "2026-04-01T12:00:00Z",
  "end_time": "2026-04-01T12:05:00Z",
  "duration_seconds": 300,
  "crawler_exit_code": 0
}
```

### 2. 子任务输出

#### task/item.json
完整的任务信息

```json
{
  "item_id": "repeat-crawl-123",
  "source": "repeat-crawl-tasks",
  "payload": {
    "task_id": "abc-123",
    "dataset_id": "ds-456",
    "urls": ["https://example.com"]
  },
  "output_dir": "/path/to/output/repeat-crawl-tasks/repeat-crawl-123"
}
```

#### crawler/result.json
爬虫执行结果

```json
{
  "exit_code": 0,
  "stdout": "Crawled 50 pages successfully",
  "stderr": "",
  "output_dir": "/path/to/output",
  "records": 50,
  "errors": 2,
  "summary": {
    "urls_processed": 50,
    "urls_failed": 2,
    "total_size_bytes": 1048576
  }
}
```

#### occupancy/response.json
URL 占用检查结果

```json
{
  "occupied": false,
  "url": "https://example.com",
  "dataset_id": "ds-456",
  "checked_at": "2026-04-01T12:00:00Z"
}
```

如果 URL 已被占用：
```json
{
  "occupied": true,
  "url": "https://example.com",
  "dataset_id": "ds-456",
  "occupied_by": {
    "submission_id": "sub-789",
    "miner_id": "0x1234...",
    "created_at": "2026-03-30T10:00:00Z"
  }
}
```

#### preflight/response.json
提交前预检结果

```json
{
  "allowed": true,
  "dataset_id": "ds-456",
  "epoch_id": "epoch-202604",
  "submission_limit": 100,
  "submissions_used": 45,
  "submissions_remaining": 55,
  "pow_challenge": {
    "challenge_id": "pow-123",
    "difficulty": 4,
    "prefix": "0000"
  }
}
```

#### preflight/rejection.json
预检拒绝原因（如果被拒绝）

```json
{
  "allowed": false,
  "reason": "quota_exceeded",
  "message": "Submission limit reached for this epoch",
  "retry_after": "2026-04-02T00:00:00Z"
}
```

#### preflight/challenge.json
PoW 挑战信息

```json
{
  "challenge_id": "pow-123",
  "difficulty": 4,
  "prefix": "0000",
  "nonce": 54321,
  "answer": "00001a2b3c4d5e6f",
  "solved_at": "2026-04-01T12:01:00Z"
}
```

### 3. Worker 状态文件

#### _worker_state/discovered_urls.jsonl
发现的待爬取 URL 队列

```jsonl
{"url": "https://example.com/page1", "discovered_at": "2026-04-01T12:00:00Z", "depth": 1}
{"url": "https://example.com/page2", "discovered_at": "2026-04-01T12:01:00Z", "depth": 2}
```

#### _worker_state/active_tasks.json
当前活跃的任务列表

```json
{
  "tasks": [
    {
      "item_id": "repeat-crawl-123",
      "status": "processing",
      "started_at": "2026-04-01T12:00:00Z"
    }
  ],
  "updated_at": "2026-04-01T12:05:00Z"
}
```

#### _worker_state/datasets_snapshot.json
数据集信息快照

```json
{
  "datasets": [
    {
      "dataset_id": "ds-456",
      "name": "Web Articles",
      "description": "General web articles",
      "epoch_id": "epoch-202604",
      "submission_limit": 100
    }
  ],
  "fetched_at": "2026-04-01T12:00:00Z"
}
```

### 4. 运行摘要

#### _run_once/iteration-{N}.json
每次迭代的汇总

```json
{
  "iteration": 1,
  "timestamp": "2026-04-01T12:00:00Z",
  "heartbeat_sent": true,
  "claimed_items": 3,
  "processed_items": 3,
  "submitted_items": 2,
  "skipped_items": 1,
  "discovered_followups": 15,
  "messages": [
    "processed repeat-crawl-123 in /output/repeat-crawl-tasks/repeat-crawl-123",
    "exported core submissions to /output/submissions/sub-456.json"
  ],
  "duration_seconds": 300
}
```

## 提交文件

### submissions/{submission_id}.json
提交到平台的数据

```json
{
  "submission_id": "sub-456",
  "dataset_id": "ds-456",
  "epoch_id": "epoch-202604",
  "miner_id": "0x1234...",
  "records": [
    {
      "url": "https://example.com",
      "title": "Example",
      "content": "...",
      "metadata": {...}
    }
  ],
  "record_count": 50,
  "pow_answer": "00001a2b3c4d5e6f",
  "submitted_at": "2026-04-01T12:05:00Z"
}
```

## 日志文件

### stdout/stderr
标准输出和错误输出会包含：

```
[2026-04-01 12:00:00] Starting mining iteration 1
[2026-04-01 12:00:01] Sending heartbeat...
[2026-04-01 12:00:02] ✓ Heartbeat successful
[2026-04-01 12:00:03] Claiming tasks...
[2026-04-01 12:00:04] ✓ Claimed 3 tasks
[2026-04-01 12:00:05] Processing task repeat-crawl-123...
[2026-04-01 12:05:00] ✓ Task completed: 50 records, 2 errors
[2026-04-01 12:05:01] Submitting results...
[2026-04-01 12:05:05] ✓ Submission successful: sub-456
```

## 输出配置

### 环境变量

```bash
# 输出根目录
export CRAWLER_OUTPUT_ROOT=/path/to/output

# Worker 状态目录
export WORKER_STATE_ROOT=/path/to/state

# 保留历史记录数量
export MAX_OUTPUT_HISTORY=100
```

### 默认路径

```bash
# 默认输出目录
output/agent-runs/

# 默认状态目录
output/agent-runs/_worker_state/
```

## 输出大小估算

单个任务的输出大小取决于爬取的数据量：

| 项目 | 大小 |
|------|------|
| 小型任务 (10 URLs) | ~500 KB |
| 中型任务 (50 URLs) | ~2 MB |
| 大型任务 (200 URLs) | ~10 MB |
| 每天挖矿 (50 任务) | ~100-500 MB |
| 每周挖矿 | ~700 MB - 3.5 GB |

**建议:**
- 定期清理旧的输出文件
- 保留最近 7-30 天的数据
- 重要数据归档到其他位置

## 清理输出

### 手动清理

```bash
# 清理所有输出
rm -rf output/

# 清理旧的输出（保留最近 7 天）
find output/ -type f -mtime +7 -delete

# 清理特定来源
rm -rf output/repeat-crawl-tasks/

# 清理错误日志
find output/ -name "errors.jsonl" -delete
```

### 自动清理

在 `~/.bashrc` 或 crontab 中添加：

```bash
# 每天凌晨 3 点清理 30 天前的输出
0 3 * * * find /path/to/mine/output -type f -mtime +30 -delete
```

## 输出分析

### 统计挖矿成果

```bash
# 统计总记录数
find output/ -name "records.jsonl" -exec wc -l {} + | awk '{sum+=$1} END {print sum}'

# 统计总任务数
find output/ -name "summary.json" | wc -l

# 统计成功率
success=$(find output/ -name "summary.json" -exec grep -l '"status": "completed"' {} + | wc -l)
total=$(find output/ -name "summary.json" | wc -l)
echo "Success rate: $((success * 100 / total))%"

# 统计总输出大小
du -sh output/
```

### 查找错误

```bash
# 查找所有错误
find output/ -name "errors.jsonl" -exec cat {} +

# 统计错误类型
find output/ -name "errors.jsonl" -exec jq -r '.error' {} + | sort | uniq -c | sort -rn

# 查找失败的任务
find output/ -name "summary.json" -exec grep -l '"status": "failed"' {} +
```

## 导出数据

### 导出所有记录

```bash
# 合并所有记录到一个文件
find output/ -name "records.jsonl" -exec cat {} + > all_records.jsonl

# 转换为 CSV
jq -r '[.url, .title, .timestamp] | @csv' all_records.jsonl > records.csv
```

### 导出统计报告

```python
import json
from pathlib import Path

# 读取所有 summary.json
summaries = []
for summary_file in Path("output").rglob("summary.json"):
    summaries.append(json.loads(summary_file.read_text()))

# 统计
total_tasks = len(summaries)
total_records = sum(s.get("records_count", 0) for s in summaries)
total_errors = sum(s.get("errors_count", 0) for s in summaries)

print(f"Total tasks: {total_tasks}")
print(f"Total records: {total_records}")
print(f"Total errors: {total_errors}")
print(f"Success rate: {(total_tasks - total_errors) / total_tasks * 100:.2f}%")
```

## 重要提示

1. **输出目录会持续增长** - 定期清理避免磁盘满
2. **敏感数据** - records.jsonl 可能包含敏感信息，注意权限
3. **备份重要数据** - 提交成功前保留输出文件
4. **日志轮转** - 考虑使用日志管理工具
5. **监控磁盘空间** - 设置告警避免空间不足

## 相关文档

- [SKILL.md](SKILL.md) - 快速参考
- [README.md](README.md) - 项目说明
- [DEPENDENCIES.md](DEPENDENCIES.md) - 依赖说明
