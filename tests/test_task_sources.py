"""Unit tests for task_sources.py."""
from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from run_models import TaskEnvelope, WorkItem
from task_sources import (
    BackendClaimSource,
    SkipClaimedTask,
    WebSocketClaimSource,
    _is_content_url,
    build_report_payload,
    claimed_task_from_payload,
    infer_platform_task,
)


# ---------------------------------------------------------------------------
# infer_platform_task
# ---------------------------------------------------------------------------
class TestInferPlatformTask:
    """Test URL -> (platform, resource_type, fields) inference."""

    def test_wikipedia_article(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://en.wikipedia.org/wiki/Artificial_intelligence"
        )
        assert platform == "wikipedia"
        assert rtype == "article"
        assert fields["title"] == "Artificial intelligence"

    def test_wikipedia_encoded_title(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://en.wikipedia.org/wiki/Quantum%20mechanics"
        )
        assert platform == "wikipedia"
        assert fields["title"] == "Quantum mechanics"

    def test_arxiv_paper(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://arxiv.org/abs/2301.07041"
        )
        assert platform == "arxiv"
        assert rtype == "paper"
        assert fields["arxiv_id"] == "2301.07041"

    def test_linkedin_profile(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://www.linkedin.com/in/johndoe/"
        )
        assert platform == "linkedin"
        assert rtype == "profile"
        assert fields["public_identifier"] == "johndoe"

    def test_linkedin_company(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://www.linkedin.com/company/acme-corp/"
        )
        assert platform == "linkedin"
        assert rtype == "company"
        assert fields["company_slug"] == "acme-corp"

    def test_linkedin_job(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://www.linkedin.com/jobs/view/123456789/"
        )
        assert platform == "linkedin"
        assert rtype == "job"
        assert fields["job_id"] == "123456789"

    def test_linkedin_post(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://www.linkedin.com/feed/update/urn:li:activity:7000/"
        )
        assert platform == "linkedin"
        assert rtype == "post"
        assert fields["activity_urn"] == "urn:li:activity:7000"

    def test_amazon_product(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://www.amazon.com/dp/B09V3KXJPB"
        )
        assert platform == "amazon"
        assert rtype == "product"
        assert fields["asin"] == "B09V3KXJPB"

    def test_base_chain_address(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://basescan.org/address/0xABC123"
        )
        assert platform == "base"
        assert rtype == "address"
        assert fields["address"] == "0xABC123"

    def test_base_chain_tx(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://basescan.org/tx/0xDEADBEEF"
        )
        assert platform == "base"
        assert rtype == "transaction"
        assert fields["tx_hash"] == "0xDEADBEEF"

    def test_base_chain_token(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://basescan.org/token/0xTOKEN"
        )
        assert platform == "base"
        assert rtype == "token"
        assert fields["contract_address"] == "0xTOKEN"

    def test_generic_url(self) -> None:
        platform, rtype, fields = infer_platform_task(
            "https://example.com/some/page"
        )
        assert platform == "generic"
        assert rtype == "page"
        assert fields["url"] == "https://example.com/some/page"


# ---------------------------------------------------------------------------
# claimed_task_from_payload
# ---------------------------------------------------------------------------
class TestClaimedTaskFromPayload:
    """Test backend claim payload -> TaskEnvelope conversion."""

    def test_valid_payload(self) -> None:
        payload: dict[str, Any] = {
            "id": "task-001",
            "url": "https://en.wikipedia.org/wiki/Test",
            "dataset_id": "ds1",
        }
        envelope = claimed_task_from_payload("repeat_crawl", payload)
        assert envelope.task_id == "task-001"
        assert envelope.task_source == "backend_claim"
        assert envelope.task_type == "repeat_crawl"
        assert "wikipedia" in envelope.url or "wiki" in envelope.url
        assert envelope.platform == "wikipedia"
        assert envelope.resource_type == "article"

    def test_missing_id_raises(self) -> None:
        payload: dict[str, Any] = {"url": "https://example.com"}
        with pytest.raises(ValueError, match="missing id"):
            claimed_task_from_payload("refresh", payload)

    def test_missing_url_raises(self) -> None:
        payload: dict[str, Any] = {"id": "task-002"}
        with pytest.raises(SkipClaimedTask):
            claimed_task_from_payload("refresh", payload)

    def test_url_fallback_to_target_url(self) -> None:
        payload: dict[str, Any] = {
            "id": "task-003",
            "target_url": "https://en.wikipedia.org/wiki/Fallback",
        }
        envelope = claimed_task_from_payload("repeat_crawl", payload)
        assert envelope.task_id == "task-003"
        assert "wiki" in envelope.url

    def test_payload_platform_override(self) -> None:
        """Explicitly specified platform in payload overrides inferred value."""
        payload: dict[str, Any] = {
            "id": "task-004",
            "url": "https://en.wikipedia.org/wiki/Test",
            "platform": "custom_platform",
        }
        envelope = claimed_task_from_payload("refresh", payload)
        assert envelope.platform == "custom_platform"


# ---------------------------------------------------------------------------
# build_report_payload
# ---------------------------------------------------------------------------
class TestBuildReportPayload:
    """Test report payload construction fallback chain."""

    def _make_item(self) -> WorkItem:
        return WorkItem(
            item_id="test:1",
            source="backend_claim",
            url="https://example.com",
            dataset_id="ds1",
            platform="generic",
            resource_type="page",
            record={},
        )

    def test_plain_text_preferred(self) -> None:
        item = self._make_item()
        record = {
            "plain_text": "Hello world",
            "cleaned_data": "fallback",
            "markdown": "# Markdown",
        }
        result = build_report_payload(item, record)
        assert result["cleaned_data"] == "Hello world"

    def test_cleaned_data_fallback(self) -> None:
        item = self._make_item()
        record = {"cleaned_data": "cleaned content", "markdown": "# md"}
        result = build_report_payload(item, record)
        assert result["cleaned_data"] == "cleaned content"

    def test_markdown_fallback(self) -> None:
        item = self._make_item()
        record = {"markdown": "# Only markdown"}
        result = build_report_payload(item, record)
        assert result["cleaned_data"] == "# Only markdown"

    def test_all_none(self) -> None:
        item = self._make_item()
        record: dict[str, Any] = {}
        result = build_report_payload(item, record)
        assert result["cleaned_data"] == ""

    def test_empty_strings_treated_as_none(self) -> None:
        item = self._make_item()
        record = {"plain_text": "", "cleaned_data": "", "markdown": "last resort"}
        result = build_report_payload(item, record)
        assert result["cleaned_data"] == "last resort"


# ---------------------------------------------------------------------------
# _is_content_url
# ---------------------------------------------------------------------------
class TestIsContentUrl:
    """Test URL content page vs. navigation page detection."""

    def test_amazon_product_page(self) -> None:
        assert _is_content_url("https://www.amazon.com/dp/B09V3KXJPB") is True

    def test_amazon_gp_product(self) -> None:
        assert _is_content_url("https://www.amazon.com/gp/product/B09V3KXJPB") is True

    def test_amazon_homepage(self) -> None:
        assert _is_content_url("https://www.amazon.com/") is False

    def test_amazon_bestsellers(self) -> None:
        assert _is_content_url("https://www.amazon.com/gp/bestsellers/") is False

    def test_wikipedia_article(self) -> None:
        assert _is_content_url("https://en.wikipedia.org/wiki/Python") is True

    def test_wikipedia_special_page(self) -> None:
        assert _is_content_url("https://en.wikipedia.org/wiki/Special:Random") is False

    def test_wikipedia_talk_page(self) -> None:
        assert _is_content_url("https://en.wikipedia.org/wiki/Talk:Python") is False

    def test_arxiv_abs_page(self) -> None:
        assert _is_content_url("https://arxiv.org/abs/2301.07041") is True

    def test_arxiv_pdf_page(self) -> None:
        assert _is_content_url("https://arxiv.org/pdf/2301.07041") is True

    def test_arxiv_listing_page(self) -> None:
        assert _is_content_url("https://arxiv.org/list/cs/recent") is False

    def test_arxiv_homepage(self) -> None:
        assert _is_content_url("https://arxiv.org/") is False

    def test_generic_url_allowed(self) -> None:
        assert _is_content_url("https://example.com/page") is True


# ---------------------------------------------------------------------------
# BackendClaimSource.collect
# ---------------------------------------------------------------------------
class TestBackendClaimSourceCollect:
    """Test BackendClaimSource collect logic."""

    def test_both_claims_succeed(self) -> None:
        client = MagicMock()
        client.claim_repeat_crawl_task.return_value = {
            "id": "rc-1",
            "url": "https://en.wikipedia.org/wiki/A",
        }
        client.claim_refresh_task.return_value = {
            "id": "rf-1",
            "url": "https://en.wikipedia.org/wiki/B",
        }
        source = BackendClaimSource(client)
        items = source.collect()
        assert len(items) == 2
        assert source.last_errors == []

    def test_one_claim_fails(self) -> None:
        client = MagicMock()
        client.claim_repeat_crawl_task.side_effect = RuntimeError("network error")
        client.claim_refresh_task.return_value = {
            "id": "rf-2",
            "url": "https://en.wikipedia.org/wiki/C",
        }
        source = BackendClaimSource(client)
        items = source.collect()
        assert len(items) == 1
        assert len(source.last_errors) == 1

    def test_both_return_none(self) -> None:
        client = MagicMock()
        client.claim_repeat_crawl_task.return_value = None
        client.claim_refresh_task.return_value = None
        source = BackendClaimSource(client)
        items = source.collect()
        assert items == []

    def test_skip_claimed_task_recorded(self) -> None:
        """Payload missing url should record a skip rather than an error."""
        client = MagicMock()
        client.claim_repeat_crawl_task.return_value = {"id": "rc-skip"}
        client.claim_refresh_task.return_value = None
        source = BackendClaimSource(client)
        items = source.collect()
        assert items == []
        assert len(source.last_skips) == 1


# ---------------------------------------------------------------------------
# WebSocketClaimSource
# ---------------------------------------------------------------------------
class TestWebSocketClaimSource:
    """Test WebSocket claim source queue and lifecycle."""

    def test_collect_drains_queue(self) -> None:
        ws = MagicMock()
        source = WebSocketClaimSource(ws)
        # Manually inject data into the queue
        source._queue = [
            {"id": "ws-1", "url": "https://en.wikipedia.org/wiki/A"},
            {"id": "ws-2", "url": "https://en.wikipedia.org/wiki/B"},
        ]
        items = source.collect()
        assert len(items) == 2
        assert source._queue == []

    def test_collect_empty_queue(self) -> None:
        ws = MagicMock()
        source = WebSocketClaimSource(ws)
        items = source.collect()
        assert items == []

    def test_start_stop_lifecycle(self) -> None:
        ws = MagicMock()
        ws.connected = False
        source = WebSocketClaimSource(ws)

        # start should launch background thread
        source.start()
        assert source._running is True
        assert source._thread is not None

        # Calling start again should not recreate the thread
        first_thread = source._thread
        source.start()
        assert source._thread is first_thread

        # stop should set _running=False and call close
        source.stop()
        assert source._running is False
        ws.close.assert_called_once()

    def test_collect_bad_payload_records_error(self) -> None:
        """Invalid payload in queue should record error rather than crash."""
        ws = MagicMock()
        source = WebSocketClaimSource(ws)
        source._queue = [{"id": "bad-task"}]  # missing url
        items = source.collect()
        assert items == []
        assert len(source.last_skips) == 1 or len(source.last_errors) == 1
