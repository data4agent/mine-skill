"""End-to-end mining flow integration tests.

Uses mocks to simulate Platform API, crawler runner, and WebSocket client,
verifying the complete mining lifecycle: discovery -> crawl -> submit -> error recovery.
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

# Fix canonicalize module conflict: lib/canonicalize.py lacks normalize_url,
# but scripts/canonicalize.py has it. Ensure agent_runtime imports correctly.
import canonicalize as _canon_mod

if not hasattr(_canon_mod, "normalize_url"):
    # Load normalize_url from scripts/canonicalize.py and inject it
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
# Common fixtures
# ---------------------------------------------------------------------------


def _make_worker_config(tmp_path: Path) -> WorkerConfig:
    """Create a WorkerConfig for testing."""
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
        dataset_refresh_seconds=0,  # no throttle on discovery frequency
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
    """Create a CrawlerRunResult for testing."""
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
    """Create a WorkItem for testing."""
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
    """Provide an isolated temporary working directory for each test."""
    (tmp_path / "output").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "crawler").mkdir()
    return tmp_path


def _build_mock_client() -> MagicMock:
    """Create a common mock PlatformClient."""
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
    """Create a common mock CrawlerRunner."""
    runner = MagicMock(spec=CrawlerRunner)
    runner.output_root = Path("/tmp/mock-output")
    return runner


# ---------------------------------------------------------------------------
# Test 1: Discovery → Crawl → Submit
# ---------------------------------------------------------------------------


class TestDiscoveryCrawlSubmitFlow:
    """Test the complete discovery -> crawl -> submit flow."""

    def test_discovery_crawl_submit(self, tmp_work_dir: Path) -> None:
        """Discover URLs from dataset -> crawl -> submit core submissions."""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # Configure list_datasets to return one dataset
        mock_client.list_datasets.return_value = [
            {
                "dataset_id": "ds-wiki",
                "source_domains": ["en.wikipedia.org"],
                "epoch_submitted": 10,
                "epoch_target": 80,
            },
        ]

        # Set runner.run_item to return a result with records
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

        # Build worker and set running state
        worker = AgentWorker(
            client=mock_client,
            runner=mock_runner,
            config=config,
        )
        # Simulate selected dataset and running state
        worker.state_store.save_session({
            "mining_state": "running",
            "selected_dataset_ids": ["ds-wiki"],
        })

        # Mock _wikipedia_random_articles to avoid network calls
        with patch("task_sources._wikipedia_random_articles") as mock_wiki:
            mock_wiki.return_value = ["https://en.wikipedia.org/wiki/Test_Article"]
            # Mock build_submission_request to avoid dependency on crawler module
            with patch("agent_runtime.build_submission_request") as mock_build_sub:
                mock_build_sub.return_value = {"records": [{"url": "https://en.wikipedia.org/wiki/Test_Article"}]}
                summary = worker.run_iteration(1)

        # Verify: should have discovery items
        assert summary["discovery_items"] >= 1
        # runner should be called (at least once)
        assert mock_runner.run_item.called


# ---------------------------------------------------------------------------
# Test 2: Backend Claim → Crawl → Report
# ---------------------------------------------------------------------------


class TestBackendClaimCrawlReportFlow:
    """Test the backend claim -> crawl -> report flow."""

    def test_claim_crawl_report(self, tmp_work_dir: Path) -> None:
        """Obtain task via claim_repeat_crawl_task -> crawl -> report_repeat_crawl_task_result."""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # Configure claim_repeat_crawl_task to return a task payload
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

        # Verify: should have claimed_items
        assert summary["claimed_items"] >= 1
        # runner should be called
        assert mock_runner.run_item.called
        # report_repeat_crawl_task_result should be called
        mock_client.report_repeat_crawl_task_result.assert_called_once()
        call_args = mock_client.report_repeat_crawl_task_result.call_args
        assert call_args[0][0] == "rct-100"  # task_id
        # report payload should contain cleaned_data
        report_body = call_args[0][1]
        assert "cleaned_data" in report_body


# ---------------------------------------------------------------------------
# Test 3: WS Push → ACK → Collect WorkItem
# ---------------------------------------------------------------------------


class TestWSPushAckCollectFlow:
    """Test WebSocket push -> ACK -> collect WorkItem flow."""

    def test_ws_push_collect(self) -> None:
        """Manually push messages into WebSocketClaimSource queue -> collect() returns WorkItem."""
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False

        ws_source = WebSocketClaimSource(mock_ws_client)

        # Manually push message into internal queue (simulating _receive_loop behavior)
        task_payload = {
            "id": "ws-task-42",
            "url": "https://en.wikipedia.org/wiki/WebSocket_Test",
            "dataset_id": "ds-wiki",
        }
        with ws_source._lock:
            ws_source._queue.append(task_payload)

        # collect should convert payload to WorkItem
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
        """Multiple messages should all be collected by collect()."""
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

        # Queue should be emptied
        with ws_source._lock:
            assert len(ws_source._queue) == 0

    def test_ws_collect_invalid_payload_skipped(self) -> None:
        """Invalid payload (missing url) should be skipped without affecting other messages."""
        mock_ws_client = MagicMock()
        ws_source = WebSocketClaimSource(mock_ws_client)

        with ws_source._lock:
            ws_source._queue.append({"id": "no-url-task"})  # missing url
            ws_source._queue.append({
                "id": "good-task",
                "url": "https://en.wikipedia.org/wiki/Good",
            })

        items = ws_source.collect()
        # First should be skipped (SkipClaimedTask), second should succeed
        assert len(items) == 1
        assert "good-task" in items[0].item_id
        # Should have a skip record
        assert len(ws_source.last_skips) == 1


# ---------------------------------------------------------------------------
# Test 4: Error Recovery
# ---------------------------------------------------------------------------


class TestErrorRecoveryFlow:
    """Test error recovery flow when crawling fails."""

    def test_runner_exception_recorded_and_item_requeued(self, tmp_work_dir: Path) -> None:
        """runner.run_item raises exception -> error recorded in summary -> item re-queued to backlog."""
        config = _make_worker_config(tmp_work_dir)
        mock_client = _build_mock_client()
        mock_runner = _build_mock_runner()

        # Configure claim to return a task
        mock_client.claim_repeat_crawl_task.return_value = {
            "id": "fail-task-1",
            "url": "https://en.wikipedia.org/wiki/Will_Fail",
            "dataset_id": "ds-test",
        }

        # Runner throws exception
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

        # Verify: error should be recorded
        assert len(summary["errors"]) >= 1
        error_text = " ".join(summary["errors"])
        assert "crashed" in error_text or "fail-task-1" in error_text

        # Item should be re-queued to backlog
        backlog = worker.state_store.load_backlog()
        assert len(backlog) >= 1
        requeued = backlog[0]
        assert requeued.resume is True


# ---------------------------------------------------------------------------
# Test 5: Rate Limit Backoff (429)
# ---------------------------------------------------------------------------


class TestRateLimitBackoffFlow:
    """Test 429 Rate Limit triggering dataset cooldown and re-queuing."""

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

        # Create crawler result
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

        # Simulate report success, but submit_core_submissions returns 429
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

        # Directly call _handle_result, making submit throw 429
        with patch("agent_runtime.build_submission_request") as mock_build_sub, \
             patch("agent_runtime._export_and_submit_core_submissions_for_task") as mock_export:
            mock_export.side_effect = http_error
            worker._handle_result(item, result, summary)

        # Verify: dataset cooldown is marked
        cooldowns = worker.state_store.active_dataset_cooldowns()
        assert "ds-rate-limited" in cooldowns

        # Item should be re-queued
        backlog = worker.state_store.load_backlog()
        assert len(backlog) >= 1
        requeued_item = backlog[0]
        assert requeued_item.resume is True

        # Summary should contain 429-related error
        all_text = " ".join(summary.errors + summary.messages)
        assert "429" in all_text or "Rate Limited" in all_text
