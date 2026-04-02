"""Tests for fetch pipeline - both legacy backends and new unified interface."""
from __future__ import annotations

import json
import threading
import asyncio
from pathlib import Path
import httpx
import pytest

from crawler.fetch import browser_common
from crawler.fetch.camoufox_backend import fetch_with_camoufox
from crawler.fetch.http_backend import fetch_http
from crawler.fetch.playwright_backend import fetch_with_playwright
from crawler.fetch.backend_router import resolve_backend
from crawler.fetch.error_classifier import classify_content
from crawler.fetch.unified import unified_fetch


# =============================================================================
# Backend Router Tests (replaces old choose_backend tests)
# =============================================================================

def test_choose_http_for_simple_wikipedia_page() -> None:
    """Backend router should start with api for wikipedia and downgrade automatically."""
    initial, fallbacks = resolve_backend(platform="wikipedia", resource_type="article", requires_auth=False)
    assert initial == "api"
    assert "http" in fallbacks
    assert "playwright" in fallbacks


def test_choose_camoufox_for_linkedin_after_escalation() -> None:
    """Backend router should have camoufox in fallback chain for linkedin."""
    initial, fallbacks = resolve_backend(platform="linkedin", resource_type="profile", requires_auth=True)
    assert "camoufox" in fallbacks


def test_choose_playwright_for_first_pass_amazon_browser_page() -> None:
    """Backend router should start with http for amazon before browser escalation."""
    initial, fallbacks = resolve_backend(platform="amazon", resource_type="product", requires_auth=False)
    assert initial == "http"
    assert "playwright" in fallbacks
    assert "camoufox" in fallbacks


def test_amazon_adapter_requires_auth() -> None:
    from crawler.platforms.amazon import ADAPTER

    assert ADAPTER.requires_auth is True


def test_classify_content_detects_amazon_signed_out_recommendation_shell() -> None:
    html = """
    <html>
      <head>
        <title>Amazon Echo Dot (3rd Gen)</title>
        <meta name="description" content="Smart speaker with Alexa - Charcoal">
      </head>
      <body>
        <a href="https://www.amazon.com/ap/signin">Sign in</a>
        <div id="rhf-error">
          After viewing product detail pages, look here to find an easy way to navigate back to pages you are interested in.
        </div>
      </body>
    </html>
    """

    error = classify_content(html, "https://www.amazon.com/dp/B07FZ8S74R")

    assert error is not None
    assert error.error_code == "CONTENT_PARTIAL"


# =============================================================================
# Low-level Backend Tests (still valid - these test the raw backend functions)
# =============================================================================

def test_fetch_http_normalizes_response_payload(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        url = httpx.URL("https://example.com/final")
        headers = {"content-type": "text/html; charset=utf-8", "x-test": "ok"}
        encoding = "utf-8"
        text = "<html><body>Hello</body></html>"
        content = b"<html><body>Hello</body></html>"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, headers: dict | None = None) -> FakeResponse:
            assert url == "https://example.com"
            assert headers is not None
            assert "User-Agent" in headers
            return FakeResponse()

    monkeypatch.setattr("crawler.fetch.http_backend.httpx.Client", FakeClient)

    result = fetch_http("https://example.com")

    assert result["backend"] == "http"
    assert result["url"] == "https://example.com/final"
    assert result["content_type"] == "text/html; charset=utf-8"
    assert result["text"] == "<html><body>Hello</body></html>"
    assert result["content_bytes"] == b"<html><body>Hello</body></html>"


def test_fetch_http_prefers_html_meta_charset_over_bad_guess(monkeypatch) -> None:
    body = '<html><head><meta charset="utf-8"></head><body>Python’s tutorial ¶</body></html>'.encode("utf-8")

    class FakeResponse:
        status_code = 200
        url = httpx.URL("https://example.com/final")
        headers = {"content-type": "text/html", "x-test": "ok"}
        encoding = "windows-1252"
        text = body.decode("windows-1252", errors="replace")
        content = body

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, headers: dict | None = None) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("crawler.fetch.http_backend.httpx.Client", FakeClient)

    result = fetch_http("https://example.com")

    assert "Python’s tutorial ¶" in result["text"]


def test_fetch_with_backend_uses_backend_selection(monkeypatch) -> None:
    """Test that unified_fetch correctly routes to different backends."""
    fetch_calls: list[dict] = []

    # Mock FetchEngine to track calls
    async def mock_fetch(
        self,
        url,
        platform,
        resource_type,
        requires_auth,
        override_backend,
        api_fetcher,
        api_kwargs,
        **kwargs,
    ):
        from crawler.fetch.models import FetchTiming, RawFetchResult
        from datetime import datetime, timezone
        fetch_calls.append({"url": url, "platform": platform, "backend": override_backend})
        return RawFetchResult(
            url=url,
            final_url=url,
            backend=override_backend or "http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html",
            status_code=200,
            html="<html></html>",
            timing=FetchTiming(start_ms=0, navigation_ms=100, wait_strategy_ms=0, total_ms=100),
        )

    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", mock_fetch)

    # Test http backend
    result = unified_fetch("https://example.com", platform="wikipedia", backend="http")
    assert result["backend"] == "http"


def test_fetch_with_backend_passes_storage_state_to_camoufox(monkeypatch) -> None:
    """Test that storage_state_path is passed through unified_fetch."""
    captured = {}

    async def mock_fetch(
        self,
        url,
        platform,
        resource_type,
        requires_auth,
        override_backend,
        api_fetcher,
        api_kwargs,
        **kwargs,
    ):
        from crawler.fetch.models import FetchTiming, RawFetchResult
        from datetime import datetime, timezone
        captured["requires_auth"] = requires_auth
        captured["backend"] = override_backend
        return RawFetchResult(
            url=url,
            final_url=url,
            backend=override_backend or "camoufox",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html",
            status_code=200,
            html="<html></html>",
            timing=FetchTiming(start_ms=0, navigation_ms=100, wait_strategy_ms=0, total_ms=100),
        )

    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", mock_fetch)

    result = unified_fetch(
        "https://example.com",
        platform="linkedin",
        backend="camoufox",
        storage_state_path="session.json",
    )

    assert captured["backend"] == "camoufox"
    assert captured["requires_auth"] is True  # storage_state_path implies auth


# =============================================================================
# Browser Common Tests
# =============================================================================

def test_browser_common_returns_existing_storage_state_path(workspace_tmp_path: Path) -> None:
    storage_state_path = workspace_tmp_path / "linkedin.json"
    storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    result = browser_common.resolve_storage_state_path(str(storage_state_path))

    assert result == str(storage_state_path)


def test_browser_common_returns_none_for_missing_storage_state_path(workspace_tmp_path: Path) -> None:
    missing_path = workspace_tmp_path / "missing.json"

    result = browser_common.resolve_storage_state_path(str(missing_path))

    assert result is None


def test_browser_common_persists_storage_state(workspace_tmp_path: Path) -> None:
    storage_state_path = workspace_tmp_path / "linkedin.json"
    payload = {"cookies": [{"name": "li_at", "value": "fresh"}], "origins": []}

    browser_common.persist_storage_state(str(storage_state_path), payload)

    assert json.loads(storage_state_path.read_text(encoding="utf-8")) == payload


@pytest.mark.asyncio
async def test_browser_common_runs_callable_in_worker_thread_inside_async_loop() -> None:
    thread_names: list[str] = []

    def callback() -> str:
        thread_names.append(threading.current_thread().name)
        return "ok"

    result = browser_common.run_sync_compatible(callback)

    assert result == "ok"
    assert thread_names
    assert all(name != threading.current_thread().name for name in thread_names)


# =============================================================================
# Playwright Backend Tests (low-level, still useful for testing the raw backend)
# =============================================================================

def test_fetch_with_playwright_persists_storage_state(workspace_tmp_path, monkeypatch) -> None:
    storage_state_path = workspace_tmp_path / "linkedin.json"

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            assert url == "https://example.com"
            assert wait_until == "networkidle"

        def content(self) -> str:
            return "<html><body>ok</body></html>"

        def screenshot(self, type: str) -> bytes:
            assert type == "png"
            return b"png"

    class FakeContext:
        def __init__(self, storage_state: str | None) -> None:
            self.initial_storage_state = storage_state

        def new_page(self) -> FakePage:
            return FakePage()

        def storage_state(self) -> dict:
            return {
                "cookies": [{"name": "li_at", "value": "fresh", "domain": ".linkedin.com", "path": "/"}],
                "origins": [],
            }

        def close(self) -> None:
            return None

    class FakeBrowser:
        def __init__(self) -> None:
            self.context: FakeContext | None = None

        def new_context(self, storage_state: str | None = None) -> FakeContext:
            self.context = FakeContext(storage_state)
            return self.context

        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self
            self.browser = FakeBrowser()

        def launch(self, headless: bool) -> FakeBrowser:
            assert headless is True
            return self.browser

    class FakePlaywrightManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("crawler.fetch.playwright_backend.sync_playwright", lambda: FakePlaywrightManager())

    result = fetch_with_playwright("https://example.com", storage_state_path=str(storage_state_path))

    assert result["backend"] == "playwright"
    assert json.loads(storage_state_path.read_text(encoding="utf-8")) == {
        "cookies": [{"name": "li_at", "value": "fresh", "domain": ".linkedin.com", "path": "/"}],
        "origins": [],
    }


@pytest.mark.asyncio
async def test_fetch_with_playwright_runs_in_worker_thread_inside_async_loop(workspace_tmp_path, monkeypatch) -> None:
    storage_state_path = workspace_tmp_path / "linkedin.json"
    worker_thread_names: list[str] = []

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            assert url == "https://example.com"
            assert wait_until == "networkidle"

        def content(self) -> str:
            return "<html><body>ok</body></html>"

        def screenshot(self, type: str) -> bytes:
            assert type == "png"
            return b"png"

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

        def storage_state(self) -> dict:
            return {"cookies": [], "origins": []}

        def close(self) -> None:
            return None

    class FakeBrowser:
        def new_context(self, storage_state: str | None = None) -> FakeContext:
            worker_thread_names.append(threading.current_thread().name)
            return FakeContext()

        def close(self) -> None:
            return None

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = self

        def launch(self, headless: bool) -> FakeBrowser:
            assert headless is True
            return FakeBrowser()

    class FakePlaywrightManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("crawler.fetch.playwright_backend.sync_playwright", lambda: FakePlaywrightManager())

    result = fetch_with_playwright("https://example.com", storage_state_path=str(storage_state_path))

    assert result["backend"] == "playwright"
    assert worker_thread_names
    assert all(name != threading.current_thread().name for name in worker_thread_names)


# =============================================================================
# Camoufox Backend Tests
# =============================================================================

def test_fetch_with_camoufox_uses_context_storage_state_and_persists_refresh(workspace_tmp_path, monkeypatch) -> None:
    storage_state_path = workspace_tmp_path / "linkedin.json"
    storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakePage:
        def goto(self, url: str, wait_until: str) -> None:
            assert url == "https://example.com"
            assert wait_until == "domcontentloaded"

        def content(self) -> str:
            return "<html><body>ok</body></html>"

        def screenshot(self, type: str) -> bytes:
            assert type == "png"
            return b"png"

    class FakeContext:
        def __init__(self, storage_state: str | None) -> None:
            captured["context_storage_state"] = storage_state

        def new_page(self) -> FakePage:
            return FakePage()

        def storage_state(self) -> dict:
            return {
                "cookies": [{"name": "li_at", "value": "fresh", "domain": ".linkedin.com", "path": "/"}],
                "origins": [],
            }

        def close(self) -> None:
            return None

    class FakeBrowser:
        def new_context(self, storage_state: str | None = None) -> FakeContext:
            return FakeContext(storage_state)

        def close(self) -> None:
            return None

    class FakeCamoufox:
        def __init__(self, **kwargs) -> None:
            captured["launch_kwargs"] = kwargs
            self.browser = FakeBrowser()

        def __enter__(self) -> FakeBrowser:
            return self.browser

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("crawler.fetch.camoufox_backend.Camoufox", FakeCamoufox)

    result = fetch_with_camoufox("https://example.com", storage_state_path=str(storage_state_path))

    assert result["backend"] == "camoufox"
    assert captured["launch_kwargs"] == {"headless": True}
    assert captured["context_storage_state"] == str(storage_state_path)
    assert json.loads(storage_state_path.read_text(encoding="utf-8")) == {
        "cookies": [{"name": "li_at", "value": "fresh", "domain": ".linkedin.com", "path": "/"}],
        "origins": [],
    }
