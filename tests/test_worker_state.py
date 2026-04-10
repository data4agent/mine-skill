"""Unit tests for worker_state.py."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from run_models import WorkItem
from worker_state import ValidatorStateStore, WorkerStateStore


def _make_work_item(item_id: str = "test:1", url: str = "https://example.com") -> WorkItem:
    """Create a WorkItem for testing."""
    return WorkItem(
        item_id=item_id,
        source="backend_claim",
        url=url,
        dataset_id="ds_test",
        platform="generic",
        resource_type="page",
        record={"url": url},
    )


# ---------------------------------------------------------------------------
# enqueue_backlog / pop_backlog
# ---------------------------------------------------------------------------
class TestBacklog:
    """Test backlog enqueue, dequeue, and deduplication."""

    def test_enqueue_and_pop(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        items = [_make_work_item("item-1"), _make_work_item("item-2")]
        store.enqueue_backlog(items)

        popped = store.pop_backlog(1)
        assert len(popped) == 1
        assert popped[0].item_id == "item-1"

        # 1 remaining
        remaining = store.pop_backlog(10)
        assert len(remaining) == 1
        assert remaining[0].item_id == "item-2"

    def test_pop_with_limit(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        items = [_make_work_item(f"item-{i}") for i in range(5)]
        store.enqueue_backlog(items)
        popped = store.pop_backlog(3)
        assert len(popped) == 3

    def test_deduplication_by_item_id(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        store.enqueue_backlog([_make_work_item("dup-1")])
        store.enqueue_backlog([_make_work_item("dup-1")])
        all_items = store.load_backlog()
        assert len(all_items) == 1

    def test_pop_empty_backlog(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        popped = store.pop_backlog(5)
        assert popped == []


# ---------------------------------------------------------------------------
# enqueue_submit_pending
# ---------------------------------------------------------------------------
class TestSubmitPending:
    """Test submit_pending upsert deduplication."""

    def test_upsert_deduplication(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("sp-1")
        store.enqueue_submit_pending(item, {"data": "v1"})
        store.enqueue_submit_pending(item, {"data": "v2"})

        entries = store.load_submit_pending()
        assert len(entries) == 1
        assert entries[0]["payload"]["data"] == "v2"

    def test_clear_submit_pending(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("sp-clear")
        store.enqueue_submit_pending(item, {"x": 1})
        store.clear_submit_pending("sp-clear")
        assert store.load_submit_pending() == []


# ---------------------------------------------------------------------------
# pop_due_auth_pending
# ---------------------------------------------------------------------------
class TestAuthPending:
    """Test auth_pending due/not-due/in_flight logic."""

    def test_due_items_returned(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("auth-1")
        store.upsert_auth_pending(item, {"error": "rate_limit"}, retry_after_seconds=0)

        now = int(time.time()) + 1
        due = store.pop_due_auth_pending(10, now=now)
        assert len(due) == 1
        assert due[0].item_id == "auth-1"

    def test_not_yet_due_skipped(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("auth-future")
        store.upsert_auth_pending(item, {"error": "rate_limit"}, retry_after_seconds=9999)

        now = int(time.time())
        due = store.pop_due_auth_pending(10, now=now)
        assert due == []

    def test_in_flight_items_skipped(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("auth-flight")
        store.upsert_auth_pending(item, {"error": "rate_limit"}, retry_after_seconds=0)

        now = int(time.time()) + 1
        # First pop
        first = store.pop_due_auth_pending(10, now=now)
        assert len(first) == 1

        # Second should skip (in_flight)
        second = store.pop_due_auth_pending(10, now=now)
        assert second == []

    def test_limit_respected(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        for i in range(5):
            item = _make_work_item(f"auth-lim-{i}")
            store.upsert_auth_pending(item, {"error": "x"}, retry_after_seconds=0)

        now = int(time.time()) + 1
        due = store.pop_due_auth_pending(2, now=now)
        assert len(due) == 2

    def test_clear_auth_pending(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        item = _make_work_item("auth-clear")
        store.upsert_auth_pending(item, {"error": "x"}, retry_after_seconds=0)
        store.clear_auth_pending("auth-clear")
        pending = store.load_auth_pending()
        assert all(e.get("item_id") != "auth-clear" for e in pending)


# ---------------------------------------------------------------------------
# should_schedule_dataset / mark_dataset_scheduled
# ---------------------------------------------------------------------------
class TestDatasetScheduling:
    """Test dataset scheduling time checks."""

    def test_should_schedule_when_never_run(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        assert store.should_schedule_dataset("ds-new", min_interval_seconds=60) is True

    def test_should_not_schedule_too_soon(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.mark_dataset_scheduled("ds-recent", now=now)
        assert store.should_schedule_dataset("ds-recent", min_interval_seconds=60, now=now + 30) is False

    def test_should_schedule_after_interval(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.mark_dataset_scheduled("ds-old", now=now)
        assert store.should_schedule_dataset("ds-old", min_interval_seconds=60, now=now + 61) is True


# ---------------------------------------------------------------------------
# mark_dataset_cooldown / active_dataset_cooldowns
# ---------------------------------------------------------------------------
class TestDatasetCooldown:
    """Test dataset cooldown setting and expiry checking."""

    def test_cooldown_active(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.mark_dataset_cooldown("ds-cd", retry_after_seconds=300, reason="rate_limit", now=now)
        active = store.active_dataset_cooldowns(now=now)
        assert "ds-cd" in active

    def test_cooldown_expired(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.mark_dataset_cooldown("ds-cd-exp", retry_after_seconds=60, reason="rate_limit", now=now)
        active = store.active_dataset_cooldowns(now=now + 61)
        assert "ds-cd-exp" not in active

    def test_is_dataset_available(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.mark_dataset_cooldown("ds-avail", retry_after_seconds=60, reason="test", now=now)
        assert store.is_dataset_available("ds-avail", now=now) is False
        assert store.is_dataset_available("ds-avail", now=now + 61) is True


# ---------------------------------------------------------------------------
# acquire_lock / release_lock
# ---------------------------------------------------------------------------
class TestLock:
    """Test distributed lock acquire, release, and stale recovery."""

    def test_acquire_and_release(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        assert store.acquire_lock("worker-1") is True
        lock = store.load_lock()
        assert lock is not None
        assert lock["owner"] == "worker-1"

        assert store.release_lock("worker-1") is True
        assert store.load_lock() is None

    def test_re_acquire_by_same_owner(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        assert store.acquire_lock("worker-1", now=now) is True
        assert store.acquire_lock("worker-1", now=now + 10) is True
        lock = store.load_lock()
        assert lock is not None
        # acquired_at should keep the original value
        assert lock["acquired_at"] == now

    def test_different_owner_blocked(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.acquire_lock("worker-1", now=now)
        assert store.acquire_lock("worker-2", now=now + 10, stale_after_seconds=300) is False

    def test_stale_lock_recovery(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        now = 100000
        store.acquire_lock("worker-1", now=now)
        # After stale timeout, another owner can acquire
        assert store.acquire_lock("worker-2", now=now + 301, stale_after_seconds=300) is True
        lock = store.load_lock()
        assert lock is not None
        assert lock["owner"] == "worker-2"

    def test_release_wrong_owner(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        store.acquire_lock("worker-1")
        assert store.release_lock("worker-999") is False

    def test_release_no_lock(self, tmp_path: Path) -> None:
        store = WorkerStateStore(tmp_path / "state")
        assert store.release_lock() is False


# ---------------------------------------------------------------------------
# ValidatorStateStore._write_json unique temp file naming
# ---------------------------------------------------------------------------
class TestValidatorStateStore:
    """Test ValidatorStateStore basic operations and temp file naming."""

    def test_save_and_load_session(self, tmp_path: Path) -> None:
        store = ValidatorStateStore(tmp_path / "validator")
        store.save_session({"key": "value", "count": 42})
        loaded = store.load_session()
        assert loaded["key"] == "value"
        assert loaded["count"] == 42

    def test_update_session(self, tmp_path: Path) -> None:
        store = ValidatorStateStore(tmp_path / "validator")
        store.save_session({"a": 1})
        store.update_session(b=2)
        loaded = store.load_session()
        assert loaded["a"] == 1
        assert loaded["b"] == 2

    def test_write_json_unique_temp_naming(self, tmp_path: Path) -> None:
        """Verify _write_json does not fail due to filename conflicts."""
        store = ValidatorStateStore(tmp_path / "validator")
        # Multiple rapid writes should not conflict
        for i in range(10):
            store.save_session({"iteration": i})
        loaded = store.load_session()
        assert loaded["iteration"] == 9

    def test_background_session_lifecycle(self, tmp_path: Path) -> None:
        store = ValidatorStateStore(tmp_path / "validator")
        store.save_background_session(pid=12345, session_id="sess-abc")
        bg = store.load_background_session()
        assert bg["pid"] == 12345
        assert bg["session_id"] == "sess-abc"

        store.clear_background_session()
        assert store.load_background_session() == {}

    def test_load_missing_session(self, tmp_path: Path) -> None:
        store = ValidatorStateStore(tmp_path / "validator")
        assert store.load_session() == {}

    def test_corrupt_json_handled(self, tmp_path: Path) -> None:
        """Corrupt JSON file should return empty dict instead of crashing."""
        state_dir = tmp_path / "validator"
        state_dir.mkdir(parents=True)
        session_file = state_dir / "validator_session.json"
        session_file.write_text("{invalid json!!!", encoding="utf-8")

        store = ValidatorStateStore(state_dir)
        assert store.load_session() == {}
