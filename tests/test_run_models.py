"""Unit tests for run_models data models."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from run_models import CrawlerRunResult, TaskEnvelope, WorkerConfig, WorkerIterationSummary, WorkItem


# ---------------------------------------------------------------------------
# WorkItem
# ---------------------------------------------------------------------------


class TestWorkItem:
    """WorkItem data model tests."""

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """to_dict -> from_dict should fully restore the object."""
        original = WorkItem(
            item_id="test:item-1",
            source="backend_claim",
            url="https://example.com/page",
            dataset_id="ds-42",
            platform="generic",
            resource_type="page",
            record={"url": "https://example.com/page", "platform": "generic"},
            crawler_command="run",
            claim_task_id="ct-1",
            claim_task_type="repeat_crawl",
            metadata={"key": "value"},
            resume=True,
            output_dir="/tmp/out",
        )
        d = original.to_dict()
        restored = WorkItem.from_dict(d)

        assert restored.item_id == original.item_id
        assert restored.source == original.source
        assert restored.url == original.url
        assert restored.dataset_id == original.dataset_id
        assert restored.platform == original.platform
        assert restored.resource_type == original.resource_type
        assert restored.record == original.record
        assert restored.crawler_command == original.crawler_command
        assert restored.claim_task_id == original.claim_task_id
        assert restored.claim_task_type == original.claim_task_type
        assert restored.metadata == original.metadata
        assert restored.resume == original.resume
        assert restored.output_dir == original.output_dir

    def test_from_dict_with_empty_payload(self) -> None:
        """Empty payload should return a WorkItem with default values."""
        item = WorkItem.from_dict({})
        assert item.item_id == ""
        assert item.source == ""
        assert item.url == ""
        assert item.dataset_id is None
        assert item.platform == "generic"
        assert item.resource_type == "page"
        assert item.record == {}
        assert item.crawler_command is None
        assert item.claim_task_id is None
        assert item.claim_task_type is None
        assert item.metadata == {}
        assert item.resume is False
        assert item.output_dir is None

    def test_frozen_dataclass_immutable(self) -> None:
        """WorkItem is a frozen dataclass; attributes cannot be modified."""
        item = WorkItem(
            item_id="x",
            source="s",
            url="http://a",
            dataset_id=None,
            platform="generic",
            resource_type="page",
            record={},
        )
        with pytest.raises(AttributeError):
            item.item_id = "new-id"  # type: ignore[misc]

    def test_default_values(self) -> None:
        """Optional fields should have correct default values."""
        item = WorkItem(
            item_id="i",
            source="s",
            url="u",
            dataset_id=None,
            platform="p",
            resource_type="r",
            record={},
        )
        assert item.crawler_command is None
        assert item.claim_task_id is None
        assert item.claim_task_type is None
        assert item.metadata == {}
        assert item.resume is False
        assert item.output_dir is None

    def test_to_dict_returns_new_dicts(self) -> None:
        """to_dict should return copies of record and metadata, not original references."""
        original_record: dict[str, Any] = {"key": "val"}
        original_meta: dict[str, Any] = {"m": 1}
        item = WorkItem(
            item_id="i",
            source="s",
            url="u",
            dataset_id=None,
            platform="p",
            resource_type="r",
            record=original_record,
            metadata=original_meta,
        )
        d = item.to_dict()
        # Modifying the returned value should not affect the original object
        d["record"]["new_key"] = "new_val"
        d["metadata"]["new_m"] = 2
        assert "new_key" not in item.record
        assert "new_m" not in item.metadata

    def test_from_dict_empty_string_dataset_id_is_none(self) -> None:
        """Empty string dataset_id should be converted to None."""
        item = WorkItem.from_dict({"dataset_id": ""})
        assert item.dataset_id is None


# ---------------------------------------------------------------------------
# TaskEnvelope
# ---------------------------------------------------------------------------


class TestTaskEnvelope:
    """TaskEnvelope data model tests."""

    def test_all_fields(self) -> None:
        """All fields should be correctly assigned."""
        env = TaskEnvelope(
            task_id="t-1",
            task_source="backend_claim",
            task_type="repeat_crawl",
            url="https://example.com",
            dataset_id="ds-1",
            platform="generic",
            resource_type="page",
            metadata={"extra": "data"},
        )
        assert env.task_id == "t-1"
        assert env.task_source == "backend_claim"
        assert env.task_type == "repeat_crawl"
        assert env.url == "https://example.com"
        assert env.dataset_id == "ds-1"
        assert env.platform == "generic"
        assert env.resource_type == "page"
        assert env.metadata == {"extra": "data"}

    def test_optional_fields(self) -> None:
        """dataset_id can be None."""
        env = TaskEnvelope(
            task_id="t-2",
            task_source="local",
            task_type="local_file",
            url="http://x",
            dataset_id=None,
            platform="generic",
            resource_type="page",
        )
        assert env.dataset_id is None
        assert env.metadata == {}

    def test_frozen(self) -> None:
        """TaskEnvelope is frozen and cannot be modified."""
        env = TaskEnvelope(
            task_id="t",
            task_source="s",
            task_type="t",
            url="u",
            dataset_id=None,
            platform="p",
            resource_type="r",
        )
        with pytest.raises(AttributeError):
            env.task_id = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WorkerConfig
# ---------------------------------------------------------------------------


class TestWorkerConfig:
    """WorkerConfig data model tests."""

    def test_default_values(self) -> None:
        """Optional fields should have correct default values."""
        config = WorkerConfig(
            base_url="https://api.example.com",
            token="tok",
            miner_id="m1",
            output_root=Path("/tmp/out"),
            crawler_root=Path("/opt/crawler"),
            python_bin="python3",
            state_root=Path("/tmp/state"),
        )
        assert config.default_backend is None
        assert config.client_name == "mine/0.2"
        assert config.max_parallel == 3
        assert config.per_dataset_parallel is True
        assert config.dataset_refresh_seconds == 900
        assert config.discovery_max_pages == 25
        assert config.discovery_max_depth == 1
        assert config.auth_retry_interval_seconds == 300
        assert config.gateway_model_config == {}
        assert config.eip712_domain_version == "1"

    def test_custom_eip712_params(self) -> None:
        """Custom EIP-712 parameters should correctly override defaults."""
        config = WorkerConfig(
            base_url="https://api.example.com",
            token="tok",
            miner_id="m1",
            output_root=Path("/tmp/out"),
            crawler_root=Path("/opt/crawler"),
            python_bin="python3",
            state_root=Path("/tmp/state"),
            eip712_domain_name="CustomDomain",
            eip712_domain_version="2",
            eip712_chain_id=1,
            eip712_verifying_contract="0x1234567890abcdef1234567890abcdef12345678",
        )
        assert config.eip712_domain_name == "CustomDomain"
        assert config.eip712_domain_version == "2"
        assert config.eip712_chain_id == 1
        assert config.eip712_verifying_contract == "0x1234567890abcdef1234567890abcdef12345678"

    def test_frozen(self) -> None:
        """WorkerConfig is frozen and cannot be modified."""
        config = WorkerConfig(
            base_url="u",
            token="t",
            miner_id="m",
            output_root=Path("/a"),
            crawler_root=Path("/b"),
            python_bin="p",
            state_root=Path("/c"),
        )
        with pytest.raises(AttributeError):
            config.base_url = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CrawlerRunResult
# ---------------------------------------------------------------------------


class TestCrawlerRunResult:
    """CrawlerRunResult data model tests."""

    def test_output_dir_and_records(self) -> None:
        """output_dir, records, errors should be correctly assigned."""
        result = CrawlerRunResult(
            output_dir=Path("/tmp/run-1"),
            records=[{"url": "http://a", "plain_text": "hello"}],
            errors=[],
            summary={"total": 1},
            exit_code=0,
            argv=["python", "-m", "crawler", "run"],
        )
        assert result.output_dir == Path("/tmp/run-1")
        assert len(result.records) == 1
        assert result.records[0]["plain_text"] == "hello"
        assert result.errors == []
        assert result.exit_code == 0
        assert result.summary == {"total": 1}

    def test_with_errors(self) -> None:
        """Results with errors should be correctly stored."""
        result = CrawlerRunResult(
            output_dir=Path("/tmp/run-2"),
            records=[],
            errors=[{"error_code": "TIMEOUT", "message": "timed out"}],
            summary={},
            exit_code=1,
            argv=["python", "-m", "crawler", "run"],
            stdout="",
            stderr="Error occurred",
        )
        assert len(result.errors) == 1
        assert result.errors[0]["error_code"] == "TIMEOUT"
        assert result.exit_code == 1
        assert result.stderr == "Error occurred"

    def test_default_stdout_stderr(self) -> None:
        """stdout and stderr should default to empty string."""
        result = CrawlerRunResult(
            output_dir=Path("/tmp"),
            records=[],
            errors=[],
            summary={},
            exit_code=0,
            argv=[],
        )
        assert result.stdout == ""
        assert result.stderr == ""


# ---------------------------------------------------------------------------
# WorkerIterationSummary
# ---------------------------------------------------------------------------


class TestWorkerIterationSummary:
    """WorkerIterationSummary data model tests."""

    def test_to_dict(self) -> None:
        """to_dict should include all fields with correct values."""
        summary = WorkerIterationSummary(iteration=5)
        summary.heartbeat_sent = True
        summary.claimed_items = 2
        summary.processed_items = 1
        summary.submitted_items = 1
        summary.errors.append("something failed")
        summary.messages.append("processed item-1")

        d = summary.to_dict()

        assert d["iteration"] == 5
        assert d["heartbeat_sent"] is True
        assert d["claimed_items"] == 2
        assert d["processed_items"] == 1
        assert d["submitted_items"] == 1
        assert d["errors"] == ["something failed"]
        assert d["messages"] == ["processed item-1"]

    def test_default_field_values(self) -> None:
        """Default fields should be 0 / False / empty list."""
        summary = WorkerIterationSummary(iteration=1)
        assert summary.heartbeat_sent is False
        assert summary.unified_heartbeat_sent is False
        assert summary.claimed_items == 0
        assert summary.discovery_items == 0
        assert summary.resumed_items == 0
        assert summary.processed_items == 0
        assert summary.submitted_items == 0
        assert summary.discovered_followups == 0
        assert summary.skipped_items == 0
        assert summary.retry_pending == 0
        assert summary.auth_pending == []
        assert summary.messages == []
        assert summary.errors == []

    def test_mutable_unlike_other_models(self) -> None:
        """WorkerIterationSummary is not frozen; attributes can be modified."""
        summary = WorkerIterationSummary(iteration=1)
        summary.processed_items = 10
        assert summary.processed_items == 10

    def test_to_dict_returns_list_copies(self) -> None:
        """to_dict should return copies of lists."""
        summary = WorkerIterationSummary(iteration=1)
        summary.errors.append("err1")
        d = summary.to_dict()
        d["errors"].append("err2")
        assert len(summary.errors) == 1

    def test_to_dict_completeness(self) -> None:
        """to_dict should include all known fields."""
        summary = WorkerIterationSummary(iteration=1)
        d = summary.to_dict()
        expected_keys = {
            "iteration",
            "heartbeat_sent",
            "unified_heartbeat_sent",
            "claimed_items",
            "discovery_items",
            "resumed_items",
            "processed_items",
            "submitted_items",
            "discovered_followups",
            "skipped_items",
            "retry_pending",
            "auth_pending",
            "messages",
            "errors",
        }
        assert set(d.keys()) == expected_keys
