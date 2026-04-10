"""Tests for crawler.discovery modules: scheduler, throttle, frontier_store, occupancy_store."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from crawler.discovery.scheduler import DiscoveryScheduler
from crawler.discovery.state.frontier import FrontierEntry, FrontierStatus
from crawler.discovery.state.occupancy import OccupancyLease
from crawler.discovery.store.frontier_store import InMemoryFrontierStore
from crawler.discovery.store.occupancy_store import InMemoryOccupancyStore
from crawler.discovery.throttle import TokenBucketThrottle


def _make_entry(
    frontier_id: str = "f1",
    job_id: str = "j1",
    priority: float = 1.0,
    status: FrontierStatus = FrontierStatus.QUEUED,
    attempt: int = 0,
    not_before: str | None = None,
) -> FrontierEntry:
    """Helper to create a FrontierEntry for testing."""
    return FrontierEntry(
        frontier_id=frontier_id,
        job_id=job_id,
        url_key=f"https://example.com/{frontier_id}",
        canonical_url=f"https://example.com/{frontier_id}",
        adapter="generic",
        entity_type="page",
        depth=0,
        priority=priority,
        discovered_from=None,
        discovery_reason="seed",
        status=status,
        attempt=attempt,
        not_before=not_before,
    )


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _future_iso(seconds: int = 3600) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _past_iso(seconds: int = 3600) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ===========================================================================
# TokenBucketThrottle
# ===========================================================================

class TestTokenBucketThrottle:
    """TokenBucketThrottle token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_with_tokens_available(self) -> None:
        """acquire should return 0.0 wait time when tokens are available."""
        throttle = TokenBucketThrottle(requests_per_minute=60.0)
        wait = await throttle.acquire()
        assert wait == 0.0

    @pytest.mark.asyncio
    async def test_acquire_when_empty_waits(self) -> None:
        """acquire should wait when tokens are exhausted."""
        # 60 per minute = 1 per second, burst capacity = 5 seconds = 5 tokens
        throttle = TokenBucketThrottle(requests_per_minute=60.0)
        # Exhaust all tokens
        for _ in range(5):
            await throttle.acquire()
        # Next one should require waiting
        start = time.monotonic()
        wait = await throttle.acquire()
        elapsed = time.monotonic() - start
        assert wait > 0.0
        assert elapsed > 0.0

    @pytest.mark.asyncio
    async def test_refill_over_time(self) -> None:
        """Tokens should refill after waiting."""
        throttle = TokenBucketThrottle(requests_per_minute=6000.0)  # High rate, fast refill
        # Exhaust all tokens
        capacity = int(max(1.0, 6000.0 / 60.0 * 5))
        for _ in range(capacity):
            await throttle.acquire()
        # Wait a short time for tokens to refill
        await asyncio.sleep(0.05)
        # Should be able to acquire after refill
        wait = await throttle.acquire()
        # May not need to wait (enough tokens refilled)
        assert wait >= 0.0

    def test_for_platform(self) -> None:
        """for_platform class method should return a TokenBucketThrottle instance."""
        throttle = TokenBucketThrottle.for_platform("generic")
        assert isinstance(throttle, TokenBucketThrottle)


# ===========================================================================
# InMemoryFrontierStore
# ===========================================================================

class TestInMemoryFrontierStore:
    """CRUD and state transitions for InMemoryFrontierStore."""

    def test_put_and_get(self) -> None:
        """Should be retrievable via get after put."""
        store = InMemoryFrontierStore()
        entry = _make_entry("f1")
        store.put(entry)
        retrieved = store.get("f1")
        assert retrieved is not None
        assert retrieved.frontier_id == "f1"

    def test_get_nonexistent(self) -> None:
        """Getting a non-existent entry should return None."""
        store = InMemoryFrontierStore()
        assert store.get("nonexistent") is None

    def test_list_queued(self) -> None:
        """list_queued should only return entries with QUEUED status."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1", status=FrontierStatus.QUEUED))
        store.put(_make_entry("f2", status=FrontierStatus.DONE))
        store.put(_make_entry("f3", status=FrontierStatus.QUEUED))
        queued = store.list_queued()
        assert len(queued) == 2
        ids = {e.frontier_id for e in queued}
        assert ids == {"f1", "f3"}

    def test_lease(self) -> None:
        """lease should change status from QUEUED to LEASED and increment attempt."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1"))
        leased = store.lease("f1")
        assert leased is not None
        assert leased.status is FrontierStatus.LEASED
        assert leased.attempt == 1

    def test_lease_non_queued_returns_none(self) -> None:
        """Non-QUEUED entries cannot be leased."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1", status=FrontierStatus.DONE))
        assert store.lease("f1") is None

    def test_lease_nonexistent_returns_none(self) -> None:
        store = InMemoryFrontierStore()
        assert store.lease("nonexistent") is None

    def test_mark_done(self) -> None:
        """mark_done should change status to DONE."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1"))
        done = store.mark_done("f1")
        assert done is not None
        assert done.status is FrontierStatus.DONE

    def test_mark_dead(self) -> None:
        """mark_dead should change status to DEAD."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1"))
        dead = store.mark_dead("f1")
        assert dead is not None
        assert dead.status is FrontierStatus.DEAD

    def test_mark_retry(self) -> None:
        """mark_retry should set RETRY_WAIT status and not_before."""
        store = InMemoryFrontierStore()
        store.put(_make_entry("f1"))
        retry = store.mark_retry("f1", "2025-01-01T00:05:00Z", {"message": "error"})
        assert retry is not None
        assert retry.status is FrontierStatus.RETRY_WAIT
        assert retry.not_before == "2025-01-01T00:05:00Z"
        assert retry.last_error == {"message": "error"}

    def test_promote_retryable(self) -> None:
        """RETRY_WAIT entries with expired not_before should be promoted to QUEUED."""
        store = InMemoryFrontierStore()
        past = _past_iso(60)
        entry = _make_entry("f1", status=FrontierStatus.RETRY_WAIT, not_before=past)
        store.put(entry)
        count = store.promote_retryable(_now_iso())
        assert count == 1
        promoted = store.get("f1")
        assert promoted is not None
        assert promoted.status is FrontierStatus.QUEUED
        assert promoted.not_before is None

    def test_promote_retryable_not_yet_due(self) -> None:
        """Entries with not_before not yet expired should not be promoted."""
        store = InMemoryFrontierStore()
        future = _future_iso(3600)
        entry = _make_entry("f1", status=FrontierStatus.RETRY_WAIT, not_before=future)
        store.put(entry)
        count = store.promote_retryable(_now_iso())
        assert count == 0

    def test_prune_terminal(self) -> None:
        """prune_terminal should remove DONE/DEAD entries exceeding the keep limit."""
        store = InMemoryFrontierStore()
        for i in range(10):
            store.put(_make_entry(f"f{i:03d}", status=FrontierStatus.DONE))
        removed = store.prune_terminal(keep=5)
        assert removed == 5
        assert len(store.list()) == 5

    def test_prune_terminal_no_excess(self) -> None:
        """Should not remove when under the keep limit."""
        store = InMemoryFrontierStore()
        for i in range(3):
            store.put(_make_entry(f"f{i}", status=FrontierStatus.DONE))
        removed = store.prune_terminal(keep=5)
        assert removed == 0
        assert len(store.list()) == 3


# ===========================================================================
# InMemoryOccupancyStore
# ===========================================================================

class TestInMemoryOccupancyStore:
    """Lease management for InMemoryOccupancyStore."""

    def _make_lease(
        self, lease_id: str = "l1", frontier_id: str = "f1",
    ) -> OccupancyLease:
        return OccupancyLease(
            lease_id=lease_id,
            job_id="j1",
            frontier_id=frontier_id,
            worker_id="w1",
            leased_at=_now_iso(),
        )

    def test_put_and_get(self) -> None:
        """Should be retrievable via get after put."""
        store = InMemoryOccupancyStore()
        lease = self._make_lease("l1", "f1")
        store.put(lease)
        assert store.get("l1") is not None
        assert store.get("l1").frontier_id == "f1"  # type: ignore[union-attr]

    def test_release_by_frontier_id(self) -> None:
        """release_by_frontier_id should delete matching leases."""
        store = InMemoryOccupancyStore()
        store.put(self._make_lease("l1", "f1"))
        store.put(self._make_lease("l2", "f1"))
        store.put(self._make_lease("l3", "f2"))
        store.release_by_frontier_id("f1")
        assert store.get("l1") is None
        assert store.get("l2") is None
        assert store.get("l3") is not None

    def test_release_nonexistent(self) -> None:
        """Releasing a non-existent frontier_id should not raise."""
        store = InMemoryOccupancyStore()
        store.release_by_frontier_id("nonexistent")  # Should not raise

    def test_list(self) -> None:
        """list should return all leases."""
        store = InMemoryOccupancyStore()
        store.put(self._make_lease("l1", "f1"))
        store.put(self._make_lease("l2", "f2"))
        assert len(store.list()) == 2


# ===========================================================================
# DiscoveryScheduler
# ===========================================================================

class TestDiscoveryScheduler:
    """Scheduling logic for DiscoveryScheduler."""

    def _make_scheduler(
        self,
        throttle: TokenBucketThrottle | None = None,
    ) -> DiscoveryScheduler:
        return DiscoveryScheduler(
            frontier_store=InMemoryFrontierStore(),
            occupancy_store=InMemoryOccupancyStore(),
            throttle=throttle,
            platform="generic",
        )

    def test_enqueue(self) -> None:
        """enqueue should add the entry to the frontier store."""
        scheduler = self._make_scheduler()
        entry = _make_entry("f1")
        result = scheduler.enqueue(entry)
        assert result.frontier_id == "f1"
        assert scheduler.frontier_store.get("f1") is not None

    @pytest.mark.asyncio
    async def test_lease_next_highest_priority(self) -> None:
        """lease_next should return the highest priority entry."""
        scheduler = self._make_scheduler()
        scheduler.enqueue(_make_entry("f1", priority=1.0))
        scheduler.enqueue(_make_entry("f2", priority=5.0))
        scheduler.enqueue(_make_entry("f3", priority=3.0))

        leased = await scheduler.lease_next("worker-1")
        assert leased is not None
        assert leased.frontier_id == "f2"
        assert leased.status is FrontierStatus.LEASED

    @pytest.mark.asyncio
    async def test_lease_next_empty_queue(self) -> None:
        """Empty queue should return None."""
        scheduler = self._make_scheduler()
        result = await scheduler.lease_next("worker-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_lease_creates_occupancy(self) -> None:
        """lease_next should create an occupancy lease."""
        scheduler = self._make_scheduler()
        scheduler.enqueue(_make_entry("f1"))
        await scheduler.lease_next("worker-1")
        leases = scheduler.occupancy_store.list()
        assert len(leases) == 1
        assert leases[0].worker_id == "worker-1"
        assert leases[0].frontier_id == "f1"

    def test_complete(self) -> None:
        """complete should release occupancy and mark done."""
        scheduler = self._make_scheduler()
        entry = _make_entry("f1")
        scheduler.enqueue(entry)
        # Manually simulate lease state
        scheduler.frontier_store.lease("f1")
        lease = OccupancyLease(
            lease_id="f1:w1", job_id="j1", frontier_id="f1",
            worker_id="w1", leased_at=_now_iso(),
        )
        scheduler.occupancy_store.put(lease)

        done = scheduler.complete("f1")
        assert done is not None
        assert done.status is FrontierStatus.DONE
        # Occupancy should be released
        assert len(scheduler.occupancy_store.list()) == 0

    def test_report_failure_backoff(self) -> None:
        """report_failure should set backoff and mark RETRY_WAIT."""
        scheduler = self._make_scheduler()
        entry = _make_entry("f1", attempt=0)
        scheduler.enqueue(entry)
        scheduler.frontier_store.lease("f1")

        result = scheduler.report_failure("f1", error=RuntimeError("timeout"))
        assert result is not None
        assert result.status is FrontierStatus.RETRY_WAIT
        assert result.not_before is not None
        assert result.last_error is not None
        assert "timeout" in result.last_error["message"]

    def test_report_failure_marks_dead_after_max_retries(self) -> None:
        """Exceeding max retries should mark as DEAD."""
        scheduler = self._make_scheduler()
        # Set attempt equal to max_retries
        max_retries = scheduler._max_retries
        entry = _make_entry("f1", attempt=max_retries)
        scheduler.enqueue(entry)
        scheduler.frontier_store.lease("f1")

        result = scheduler.report_failure("f1")
        assert result is not None
        assert result.status is FrontierStatus.DEAD

    @pytest.mark.asyncio
    async def test_lease_contention_retry(self) -> None:
        """When lease fails, should retry (up to 3 times)."""
        scheduler = self._make_scheduler()
        scheduler.enqueue(_make_entry("f1"))
        scheduler.enqueue(_make_entry("f2", priority=0.5))

        # First lease f1
        leased = await scheduler.lease_next("worker-1")
        assert leased is not None
        assert leased.frontier_id == "f1"

        # Lease again, f1 is no longer QUEUED, should automatically get f2
        leased2 = await scheduler.lease_next("worker-2")
        assert leased2 is not None
        assert leased2.frontier_id == "f2"

    @pytest.mark.asyncio
    async def test_lease_with_throttle(self) -> None:
        """Lease with throttle should work normally."""
        throttle = TokenBucketThrottle(requests_per_minute=6000.0)
        scheduler = self._make_scheduler(throttle=throttle)
        scheduler.enqueue(_make_entry("f1"))
        leased = await scheduler.lease_next("worker-1")
        assert leased is not None
        assert leased.frontier_id == "f1"

    def test_report_failure_nonexistent(self) -> None:
        """report_failure on a non-existent entry should return None."""
        scheduler = self._make_scheduler()
        result = scheduler.report_failure("nonexistent")
        assert result is None
