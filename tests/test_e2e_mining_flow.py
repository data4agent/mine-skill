"""端到端挖矿流程集成测试。

使用 mock 模拟平台 API、爬虫运行器和 WebSocket 客户端，
验证完整的挖矿生命周期：发现 → 爬取 → 提交 → 错误恢复。
"""
from __future__ import annotations

import importlib
import json
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import httpx
import pytest

# 修复 canonicalize 模块冲突：lib/canonicalize.py 缺少 normalize_url，
# 但 scripts/canonicalize.py 有。确保 agent_runtime 能正确导入。
import canonicalize as _canon_mod

if not hasattr(_canon_mod, "normalize_url"):
    # 从 scripts/canonicalize.py 加载 normalize_url 并注入
    _scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
    import importlib.util

    _spec = importlib.util.spec_from_file_location("scripts_canonicalize", f"{_scripts_dir}/canonicalize.py")
    _scripts_canon = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_scripts_canon)  # type: ignore[union-attr]
    _canon_mod.normalize_url = _scripts_canon.normalize_url  # type: ignore[attr-defined]

from agent_runtime import AgentWorker, CrawlerRunner
from run_models import CrawlerRunResult, WorkerConfig, WorkerIterationSummary, WorkItem
from task_sources import WebSocketClaimSource
from ws_client import WSMessage


# ---------------------------------------------------------------------------
# 通用 fixture
# ---------------------------------------------------------------------------


def _make_worker_config(tmp_path: Path) -> WorkerConfig:
    """创建测试用 WorkerConfig。"""
    return WorkerConfig(
        base_url="https://api.test.local",
        token="test-token",
        miner_id="test-miner",
        output_root=tmp_path / "output",
        crawler_root=tmp_path / "crawler",
        python_bin="python3",
        state_root=tmp_path / "state",
        default_backend=None,
        max_parallel=1,
        per_dataset_parallel=False,
        dataset_refresh_seconds=0,  # 不限制 discovery 频率
        discovery_max_pages=5,
        discovery_max_depth=1,
        auth_retry_interval_seconds=60,
    )


def _make_crawler_result(
    tmp_path: Path,
    *,
    records: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    exit_code: int = 0,
) -> CrawlerRunResult:
    """创建测试用 CrawlerRunResult。"""
    output_dir = tmp_path / "run-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return CrawlerRunResult(
        output_dir=output_dir,
        records=records or [],
        errors=errors or [],
        summary={"total": len(records or [])},
        exit_code=exit_code,
        argv=["python3", "-m", "crawler", "run"],
    )


def _make_work_item(
    *,
    item_id: str = "test:item-1",
    source: str = "backend_claim",
    url: str = "https://en.wikipedia.org/wiki/Test",
    dataset_id: str | None = "ds-test",
    platform: str = "wikipedia",
    resource_type: str = "article",
    claim_task_id: str | None = None,
    claim_task_type: str | None = None,
) -> WorkItem:
    """创建测试用 WorkItem。"""
    return WorkItem(
        item_id=item_id,
        source=source,
        url=url,
        dataset_id=dataset_id,
        platform=platform,
        resource_type=resource_type,
        record={"url": url, "platform": platform, "resource_type": resource_type},
        claim_task_id=claim_task_id,
        claim_task_type=claim_task_type,
    )


@pytest.fixture
def tmp_work_dir(tmp_path: Path) -> Path:
    """为每个测试提供独立的临时工作目录。"""
    (tmp_path / "output").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "crawler").mkdir()
    return tmp_path


def _build_mock_client() -> MagicMock:
    """创建通用 mock PlatformClient。"""
    client = MagicMock()
    client.list_datasets.return_value = []
    client.claim_repeat_crawl_task.return_value = None
    client.claim_refresh_task.return_value = None
    client.send_unified_heartbeat.return_value = {"data": {}}
    client.send_miner_heartbeat.return_value = {"data": {}}
    client.submit_core_submissions.return_value = {"success": True, "data": {}}
    client.check_url_occupancy.return_value = {}
    client.check_url_occupancy_public.return_value = {}
    client.report_repeat_crawl_task_result.return_value = {"success": True}
    client.report_refresh_task_result.return_value = {"success": True}
    client.join_miner_ready_pool.return_value = None
    client.fetch_my_miner_stats.return_value = {}
    client.fetch_current_epoch.return_value = {}
    return client


def _build_mock_runner() -> MagicMock:
    """创建通用 mock CrawlerRunner。"""
    runner = MagicMock(spec=CrawlerRunner)
    runner.output_root = Path("/tmp/mock-output")
    return runner


# ---------------------------------------------------------------------------
# Test 1: Discovery → Crawl → Submit
# ---------------------------------------------------------------------------


class TestDiscoveryCrawlSubmitFlow:
    """测试完整的 发现 → 爬取 → 提交 流程。"""

    def test_discovery_crawl_submit(self, tmp_work_dir: Path) -> None:
        """从 dataset 发现 URL → 爬取 → 提交 core submissions。"""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # 配置 list_datasets 返回一个数据集
        mock_client.list_datasets.return_value = [
            {
                "dataset_id": "ds-wiki",
                "source_domains": ["en.wikipedia.org"],
                "epoch_submitted": 10,
                "epoch_target": 80,
            },
        ]

        # 设置 runner.run_item 返回带 records 的结果
        run_result = _make_crawler_result(
            tmp_work_dir,
            records=[{
                "url": "https://en.wikipedia.org/wiki/Test",
                "plain_text": "Test article content",
                "platform": "wikipedia",
                "resource_type": "article",
            }],
        )
        mock_runner.run_item.return_value = run_result

        # 构建 worker 并设置运行状态
        worker = AgentWorker(
            client=mock_client,
            runner=mock_runner,
            config=config,
        )
        # 模拟已选择 dataset 且处于运行状态
        worker.state_store.save_session({
            "mining_state": "running",
            "selected_dataset_ids": ["ds-wiki"],
        })

        # mock 掉 _wikipedia_random_articles 避免网络调用
        with patch("task_sources._wikipedia_random_articles") as mock_wiki:
            mock_wiki.return_value = ["https://en.wikipedia.org/wiki/Test_Article"]
            # mock build_submission_request 避免依赖 crawler 模块
            with patch("agent_runtime.build_submission_request") as mock_build_sub:
                mock_build_sub.return_value = {"records": [{"url": "https://en.wikipedia.org/wiki/Test_Article"}]}
                summary = worker.run_iteration(1)

        # 验证：应有 discovery items
        assert summary["discovery_items"] >= 1
        # runner 应被调用（至少一次）
        assert mock_runner.run_item.called


# ---------------------------------------------------------------------------
# Test 2: Backend Claim → Crawl → Report
# ---------------------------------------------------------------------------


class TestBackendClaimCrawlReportFlow:
    """测试 后台认领 → 爬取 → 上报 流程。"""

    def test_claim_crawl_report(self, tmp_work_dir: Path) -> None:
        """通过 claim_repeat_crawl_task 获取任务 → 爬取 → report_repeat_crawl_task_result。"""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # 配置 claim_repeat_crawl_task 返回任务 payload
        mock_client.claim_repeat_crawl_task.return_value = {
            "id": "rct-100",
            "url": "https://en.wikipedia.org/wiki/Claimed_Page",
            "dataset_id": "ds-wiki",
        }

        run_result = _make_crawler_result(
            tmp_work_dir,
            records=[{
                "url": "https://en.wikipedia.org/wiki/Claimed_Page",
                "plain_text": "Claimed page content here",
                "platform": "wikipedia",
                "resource_type": "article",
            }],
        )
        mock_runner.run_item.return_value = run_result

        worker = AgentWorker(
            client=mock_client,
            runner=mock_runner,
            config=config,
        )
        worker.state_store.save_session({
            "mining_state": "running",
            "selected_dataset_ids": ["ds-wiki"],
        })

        with patch("agent_runtime.build_submission_request") as mock_build_sub:
            mock_build_sub.return_value = {"records": [{"url": "https://en.wikipedia.org/wiki/Claimed_Page"}]}
            summary = worker.run_iteration(1)

        # 验证：应有 claimed_items
        assert summary["claimed_items"] >= 1
        # runner 应被调用
        assert mock_runner.run_item.called
        # report_repeat_crawl_task_result 应被调用
        mock_client.report_repeat_crawl_task_result.assert_called_once()
        call_args = mock_client.report_repeat_crawl_task_result.call_args
        assert call_args[0][0] == "rct-100"  # task_id
        # report payload 应包含 cleaned_data
        report_body = call_args[0][1]
        assert "cleaned_data" in report_body


# ---------------------------------------------------------------------------
# Test 3: WS Push → ACK → Collect WorkItem
# ---------------------------------------------------------------------------


class TestWSPushAckCollectFlow:
    """测试 WebSocket 推送 → ACK → 收集 WorkItem 流程。"""

    def test_ws_push_collect(self) -> None:
        """手动推入消息到 WebSocketClaimSource 队列 → collect() 返回 WorkItem。"""
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False

        ws_source = WebSocketClaimSource(mock_ws_client)

        # 手动推入消息到内部队列（模拟 _receive_loop 行为）
        task_payload = {
            "id": "ws-task-42",
            "url": "https://en.wikipedia.org/wiki/WebSocket_Test",
            "dataset_id": "ds-wiki",
        }
        with ws_source._lock:
            ws_source._queue.append(task_payload)

        # collect 应将 payload 转换为 WorkItem
        items = ws_source.collect()

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, WorkItem)
        assert "ws-task-42" in item.item_id
        assert item.url == "https://en.wikipedia.org/wiki/WebSocket_Test"
        assert item.claim_task_id == "ws-task-42"
        assert item.claim_task_type == "repeat_crawl"
        assert item.source == "backend_claim"

    def test_ws_push_multiple_messages(self) -> None:
        """多个消息应全部被 collect()。"""
        mock_ws_client = MagicMock()
        ws_source = WebSocketClaimSource(mock_ws_client)

        payloads = [
            {"id": f"ws-task-{i}", "url": f"https://en.wikipedia.org/wiki/Page_{i}"}
            for i in range(3)
        ]
        with ws_source._lock:
            ws_source._queue.extend(payloads)

        items = ws_source.collect()
        assert len(items) == 3

        # 队列应被清空
        with ws_source._lock:
            assert len(ws_source._queue) == 0

    def test_ws_collect_invalid_payload_skipped(self) -> None:
        """无效 payload（缺少 url）应被跳过，不影响其他消息。"""
        mock_ws_client = MagicMock()
        ws_source = WebSocketClaimSource(mock_ws_client)

        with ws_source._lock:
            ws_source._queue.append({"id": "no-url-task"})  # 缺少 url
            ws_source._queue.append({
                "id": "good-task",
                "url": "https://en.wikipedia.org/wiki/Good",
            })

        items = ws_source.collect()
        # 第一个应被 skip（SkipClaimedTask），第二个正常
        assert len(items) == 1
        assert "good-task" in items[0].item_id
        # 应有 skip 记录
        assert len(ws_source.last_skips) == 1


# ---------------------------------------------------------------------------
# Test 4: Error Recovery
# ---------------------------------------------------------------------------


class TestErrorRecoveryFlow:
    """测试爬取失败时的错误恢复流程。"""

    def test_runner_exception_recorded_and_item_requeued(self, tmp_work_dir: Path) -> None:
        """runner.run_item 抛异常 → 错误记录在 summary → item 重新入队到 backlog。"""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # 配置 claim 返回一个任务
        mock_client.claim_repeat_crawl_task.return_value = {
            "id": "fail-task-1",
            "url": "https://en.wikipedia.org/wiki/Will_Fail",
            "dataset_id": "ds-test",
        }

        # runner 抛出异常
        mock_runner.run_item.side_effect = RuntimeError("crawler subprocess crashed")

        worker = AgentWorker(
            client=mock_client,
            runner=mock_runner,
            config=config,
        )
        worker.state_store.save_session({
            "mining_state": "running",
            "selected_dataset_ids": ["ds-test"],
        })

        summary = worker.run_iteration(1)

        # 验证：错误应被记录
        assert len(summary["errors"]) >= 1
        error_text = " ".join(summary["errors"])
        assert "crashed" in error_text or "fail-task-1" in error_text

        # item 应被重新入队到 backlog
        backlog = worker.state_store.load_backlog()
        assert len(backlog) >= 1
        requeued = backlog[0]
        assert requeued.resume is True


# ---------------------------------------------------------------------------
# Test 5: Rate Limit Backoff (429)
# ---------------------------------------------------------------------------


class TestRateLimitBackoffFlow:
    """测试 429 Rate Limit 触发 dataset 冷却和重新入队。"""

    def test_429_marks_cooldown_and_requeues(self, tmp_work_dir: Path) -> None:
        """submit_core_submissions returns 429 → dataset cooldown → item re-queued."""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # Use a discovery item (not repeat_crawl, since repeat_crawl skips submission)
        item = _make_work_item(
            item_id="discovery:ds-rate-limited:https://en.wikipedia.org/wiki/Test",
            dataset_id="ds-rate-limited",
        )

        # 创建 crawler result
        result = _make_crawler_result(
            tmp_work_dir,
            records=[{
                "url": "https://en.wikipedia.org/wiki/Test",
                "plain_text": "some content",
                "platform": "wikipedia",
                "resource_type": "article",
            }],
        )

        worker = AgentWorker(
            client=mock_client,
            runner=mock_runner,
            config=config,
        )
        worker.state_store.save_session({
            "mining_state": "running",
            "selected_dataset_ids": ["ds-rate-limited"],
        })

        # 模拟 report 成功，但 submit_core_submissions 返回 429
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "120"}
        mock_request = MagicMock()
        http_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=mock_request,
            response=mock_response,
        )

        summary = WorkerIterationSummary(iteration=1)

        # 直接调用 _handle_result，让 submit 抛 429
        with patch("agent_runtime.build_submission_request") as mock_build_sub, \
             patch("agent_runtime._export_and_submit_core_submissions_for_task") as mock_export:
            mock_export.side_effect = http_error
            worker._handle_result(item, result, summary)

        # 验证：dataset 冷却被标记
        cooldowns = worker.state_store.active_dataset_cooldowns()
        assert "ds-rate-limited" in cooldowns

        # item 应被重新入队
        backlog = worker.state_store.load_backlog()
        assert len(backlog) >= 1
        requeued_item = backlog[0]
        assert requeued_item.resume is True

        # summary 中应有 429 相关错误
        all_text = " ".join(summary.errors + summary.messages)
        assert "429" in all_text or "Rate Limited" in all_text
