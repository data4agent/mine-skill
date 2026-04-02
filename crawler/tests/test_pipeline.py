from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest

from crawler.cli import parse_args
from crawler.contracts import CrawlerConfig
from crawler.core.pipeline import _build_enrich_input_from_record, _persist_extraction_artifacts, run_command


def test_run_command_uses_new_pipeline_by_default(monkeypatch, workspace_tmp_path: Path) -> None:
    """New 3-layer pipeline is used by default."""
    input_path = workspace_tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Test"}) + "\n",
        encoding="utf-8",
    )

    config = parse_args(["run", "--input", str(input_path), "--output", str(workspace_tmp_path / "out")])

    # Mock the new pipeline's async implementation
    mock_result = (
        [{"platform": "wikipedia", "resource_type": "article", "status": "success", "enrichment": {"status": "routed"}}],
        [],
    )
    with patch("crawler.core.pipeline._run_new_pipeline", return_value=mock_result):
        records, errors = run_command(config)

    assert errors == []
    assert records[0]["enrichment"]["status"] == "routed"


def test_crawl_command_uses_new_pipeline(workspace_tmp_path: Path) -> None:
    """Crawl command uses new pipeline by default."""
    input_path = workspace_tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Test"}) + "\n",
        encoding="utf-8",
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(workspace_tmp_path / "out")])

    mock_result = (
        [{"platform": "wikipedia", "resource_type": "article", "status": "success"}],
        [],
    )
    with patch("crawler.core.pipeline._run_new_pipeline", return_value=mock_result):
        records, errors = run_command(config)

    assert errors == []
    assert records[0]["status"] == "success"


def test_new_pipeline_uses_discovery_seed_builder(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "http"

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Test"}

    captured: dict[str, object] = {}

    def fake_build_seed_records(record: dict) -> list[SimpleNamespace]:
        captured["record"] = record
        return [
            SimpleNamespace(
                platform="generic",
                resource_type="page",
                canonical_url="https://example.com/docs",
                identity={"url": "https://example.com/docs"},
                metadata={"artifacts": {"self": "https://example.com/docs"}},
            )
        ]

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html="<html><body><article><h1>Docs</h1></article></body></html>",
            content_bytes=b"<html></html>",
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.discovery.url_builder.build_seed_records", fake_build_seed_records)
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert captured["record"] == {"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}
    assert records[0]["canonical_url"] == "https://example.com/docs"


def test_new_pipeline_resume_skips_completed_urls(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}) + "\n",
        encoding="utf-8",
    )
    fetch_calls = {"count": 0}

    class FakeAdapter:
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "http"

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Test"}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        fetch_calls["count"] += 1
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html="<html><body><article><h1>Docs</h1></article></body></html>",
            content_bytes=b"<html></html>",
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    first_config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    first_records, first_errors = run_command(first_config)
    second_config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--resume"])
    second_records, second_errors = run_command(second_config)

    assert first_errors == []
    assert len(first_records) == 1
    assert second_errors == []
    assert second_records == []
    assert fetch_calls["count"] == 1


def test_new_pipeline_deduplicates_same_canonical_url_within_run(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        (
            json.dumps({"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}) + "\n"
            + json.dumps({"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}) + "\n"
        ),
        encoding="utf-8",
    )
    fetch_calls = {"count": 0}

    class FakeAdapter:
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "http"

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Docs"}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        fetch_calls["count"] += 1
        html = "<html><body><article><h1>Docs</h1></article></body></html>"
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert len(records) == 1
    assert fetch_calls["count"] == 1


def test_new_pipeline_auto_login_retries_after_auth_expired(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    session_root = output_dir / ".sessions"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )
    session_root.mkdir(parents=True, exist_ok=True)
    (session_root / "linkedin.json").write_text(
        json.dumps({"cookies": [{"name": "li_at", "value": "seed"}, {"name": "JSESSIONID", "value": "ajax:seed"}], "origins": []}),
        encoding="utf-8",
    )
    calls = {"count": 0, "refresh": 0}

    class FakeAdapter:
        requires_auth = True

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "http"

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "John Doe"}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from crawler.fetch.error_classifier import FetchError

        calls["count"] += 1
        if calls["count"] == 1:
            err = RuntimeError("auth expired")
            err.fetch_error = FetchError("AUTH_EXPIRED", "refresh_session", "expired", True)  # type: ignore[attr-defined]
            raise err

        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        html = "<html><body><article><h1>John Doe</h1></article></body></html>"
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="playwright",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    def fake_export(session_store) -> str:
        calls["refresh"] += 1
        refreshed = session_store.root / "linkedin.json"
        refreshed.parent.mkdir(parents=True, exist_ok=True)
        refreshed.write_text(json.dumps({"cookies": [{"name": "li_at", "value": "secret"}, {"name": "JSESSIONID", "value": "ajax:1"}], "origins": []}), encoding="utf-8")
        return str(refreshed)

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)
    monkeypatch.setattr("crawler.core.auth.export_session_via_auto_browser", lambda **kwargs: fake_export(kwargs["session_store"]))

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--auto-login"])
    records, errors = run_command(config)

    assert errors == []
    assert len(records) == 1
    assert calls["refresh"] == 1
    assert calls["count"] == 2


def _fake_extracted_document() -> SimpleNamespace:
    return SimpleNamespace(
        doc_id="doc-1",
        full_text="plain text",
        full_markdown="# title",
        cleaned_html="<article><p>plain text</p></article>",
        structured=SimpleNamespace(
            title="Title",
            description="Desc",
            canonical_url="https://www.linkedin.com/in/john-doe/",
            platform_fields={"headline": "Headline"},
            field_sources={},
        ),
        chunks=[],
        quality=SimpleNamespace(content_ratio=1.0, noise_removed=0, chunking_strategy="test"),
        total_chunks=0,
    )


def test_persist_extraction_artifacts_writes_cleaned_html(workspace_tmp_path: Path) -> None:
    extracted = _fake_extracted_document()

    artifacts = _persist_extraction_artifacts(
        artifact_root=workspace_tmp_path / "artifacts",
        slug="record-1",
        extracted=extracted,
        root_for_rel=workspace_tmp_path / "out",
    )

    artifact_kinds = {artifact["kind"] for artifact in artifacts}
    assert "cleaned_html" in artifact_kinds


def test_new_pipeline_returns_auth_required_for_linkedin_without_session(workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert records == []
    assert errors[0]["error_code"] == "AUTH_REQUIRED"
    assert errors[0]["next_action"] == "provide cookies or storage state"


def test_new_pipeline_imports_cookies_before_api_fetch(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    cookies_path = workspace_tmp_path / "cookies.json"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )
    cookies_path.write_text(json.dumps({"li_at": "secret-token"}), encoding="utf-8")
    captured: dict[str, str | None] = {"storage_state_path": None}

    class FakeAdapter:
        default_backend = "api"
        requires_auth = True

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["storage_state_path"] = storage_state_path
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "json_data": {"included": []},
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Title",
                    "description": "Desc",
                    "content_type": fetched.get("content_type"),
                    "source_url": fetched.get("url"),
                },
                "plain_text": "plain text",
                "markdown": "# title",
                "structured": {"headline": "Headline"},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"headline": "Headline"}

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {"canonical_url": "https://www.linkedin.com/in/john-doe/", "fields": {}, "artifacts": {}},
    )
    monkeypatch.setattr("crawler.extract.pipeline.ExtractPipeline.extract", lambda self, fetched, platform, resource_type: _fake_extracted_document())

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--cookies", str(cookies_path)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["status"] == "success"
    assert captured["storage_state_path"] is not None
    assert Path(captured["storage_state_path"]).exists()


def test_new_pipeline_auto_login_exports_session_when_missing(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, str | None] = {"storage_state_path": None}

    class FakeAdapter:
        default_backend = "api"
        requires_auth = True

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["storage_state_path"] = storage_state_path
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {"included": []},
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {"title": "John Doe", "content_type": "application/json", "source_url": fetched["url"]},
                "plain_text": "AI Engineer",
                "markdown": "# John Doe\n\nAI Engineer",
                "structured": {"linkedin": {"headline": "AI Engineer"}},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"headline": "AI Engineer"}

    class FakeSession:
        def __init__(self, session_path: Path) -> None:
            self.session_path = session_path

    def fake_export(self, *, platform: str, output_dir: Path, login_url: str | None = None, guide_text: str | None = None) -> FakeSession:
        assert platform == "linkedin"
        exported = output_dir / ".sessions" / "linkedin.auto-browser.json"
        exported.parent.mkdir(parents=True, exist_ok=True)
        exported.write_text(
            json.dumps(
                {
                    "platform": "linkedin",
                    "source": "auto-browser",
                    "storage_state": {
                        "cookies": [
                            {"name": "li_at", "value": "secret-token", "domain": ".linkedin.com", "path": "/"},
                            {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com", "path": "/"},
                        ],
                        "origins": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return FakeSession(exported)

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {"canonical_url": "https://www.linkedin.com/in/john-doe/", "fields": {"public_identifier": "john-doe"}, "artifacts": {}},
    )
    monkeypatch.setattr("crawler.extract.pipeline.ExtractPipeline.extract", lambda self, fetched, platform, resource_type: _fake_extracted_document())
    monkeypatch.setattr("crawler.integrations.browser_auth.AutoBrowserAuthBridge.ensure_exported_session", fake_export)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--auto-login"])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["status"] == "success"
    assert captured["storage_state_path"] is not None
    assert Path(captured["storage_state_path"]).exists()


def test_new_pipeline_routes_api_platforms_through_fetch_engine_without_locking_backend(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Test"}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["adapter_backend"] = backend
            return {
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "json_data": {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "Test",
                                "extract": "Body text",
                                "categories": [{"title": "Category:Example"}],
                            }
                        }
                    }
                },
                "headers": {},
                "status_code": 200,
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Test",
                    "content_type": fetched.get("content_type"),
                    "source_url": fetched.get("url"),
                },
                "plain_text": "Body text",
                "markdown": "# Test\n\nBody text",
                "structured": {"categories": ["Example"]},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Test"}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        captured["override_backend"] = override_backend
        captured["preferred_backend"] = preferred_backend
        assert api_fetcher is not None
        payload = api_fetcher(url)
        return RawFetchResult(
            url=url,
            final_url=payload["url"],
            backend="api",
            fetch_time=datetime.now(timezone.utc),
            content_type=payload["content_type"],
            status_code=payload["status_code"],
            json_data=payload["json_data"],
            headers=payload["headers"],
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {"canonical_url": "https://en.wikipedia.org/wiki/Test", "fields": {}, "artifacts": {}},
    )
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert captured["override_backend"] is None
    assert captured["preferred_backend"] == "api"
    assert captured["adapter_backend"] == "api"
    assert records[0]["metadata"]["title"] == "Test"


def test_new_pipeline_respects_explicit_backend_override(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Test"}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return override_backend or "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["adapter_backend"] = backend
            return {
                "url": discovered["canonical_url"],
                "content_type": "text/html",
                "text": "<html><body><h1>Test</h1><p>Body text</p></body></html>",
                "headers": {},
                "status_code": 200,
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Test",
                    "content_type": fetched.get("content_type"),
                    "source_url": fetched.get("url"),
                },
                "plain_text": "Body text",
                "markdown": "# Test\n\nBody text",
                "structured": {"categories": ["Example"]},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Test"}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        captured["override_backend"] = override_backend
        captured["preferred_backend"] = preferred_backend
        return RawFetchResult(
            url=url,
            final_url=url,
            backend=override_backend or "http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html",
            status_code=200,
            html="<html><body><h1>Test</h1><p>Body text</p></body></html>",
            content_bytes=b"<html><body><h1>Test</h1><p>Body text</p></body></html>",
            headers={},
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {"canonical_url": "https://en.wikipedia.org/wiki/Test", "fields": {}, "artifacts": {}},
    )
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--backend", "http"])
    records, errors = run_command(config)

    assert errors == []
    assert captured["override_backend"] == "http"
    assert captured["preferred_backend"] is None
    assert records[0]["metadata"]["title"] == "Test"


def test_new_pipeline_crawl_persists_structured_fields_for_api_records(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Artificial intelligence"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "json_data": {
                    "query": {
                        "pages": {
                            "1164": {
                                "title": "Artificial intelligence",
                                "extract": "Artificial intelligence is the capability of computational systems.",
                                "categories": [{"title": "Category:Artificial intelligence"}],
                            }
                        }
                    }
                },
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Artificial intelligence",
                    "content_type": fetched.get("content_type"),
                    "source_url": fetched.get("url"),
                },
                "plain_text": "Artificial intelligence is the capability of computational systems.",
                "markdown": "# Artificial intelligence\n\nArtificial intelligence is the capability of computational systems.",
                "structured": {"categories": ["Artificial intelligence"]},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "Artificial intelligence"}

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "fields": {"title": "Artificial_intelligence"},
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["metadata"]["title"] == "Artificial intelligence"
    assert "computational systems" in records[0]["plain_text"]
    assert records[0]["markdown"].startswith("# Artificial intelligence")
    assert records[0]["structured"]["categories"] == ["Artificial intelligence"]


def test_new_pipeline_preserves_api_metadata_and_top_level_compat_fields(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {
                    "included": [
                        {
                            "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                            "firstName": "John",
                            "lastName": "Doe",
                            "headline": "AI Engineer",
                            "publicIdentifier": "john-doe",
                            "entityUrn": "urn:li:fsd_profile:123",
                        }
                    ]
                },
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "John Doe",
                    "content_type": "application/json",
                    "source_url": fetched["url"],
                    "entity_type": "person",
                    "source_id": "123",
                },
                "plain_text": "AI Engineer",
                "markdown": "# John Doe\n\nAI Engineer",
                "structured": {
                    "linkedin": {
                        "source_id": "123",
                        "title": "John Doe",
                        "headline": "AI Engineer",
                        "public_identifier": "john-doe",
                    }
                },
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            structured = extracted.get("structured", {})
            linkedin = structured.get("linkedin", {}) if isinstance(structured, dict) else {}
            result = dict(linkedin) if isinstance(linkedin, dict) else {}
            result.setdefault("public_identifier", discovered["fields"].get("public_identifier"))
            result.setdefault("title", extracted.get("metadata", {}).get("title"))
            return result

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": "https://www.linkedin.com/in/john-doe/",
            "fields": {"public_identifier": "john-doe"},
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["metadata"]["content_type"] == "application/json"
    assert records[0]["metadata"]["source_url"] == "https://www.linkedin.com/in/john-doe/"
    assert records[0]["metadata"]["entity_type"] == "person"
    assert records[0]["metadata"]["source_id"] == "123"
    assert records[0]["source_id"] == "123"
    assert records[0]["headline"] == "AI Engineer"
    assert records[0]["public_identifier"] == "john-doe"


def test_new_pipeline_uses_legacy_metadata_for_wikipedia_api(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Artificial intelligence"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {
                    "query": {
                        "pages": {
                            "1164": {
                                "title": "Artificial intelligence",
                                "extract": "Artificial intelligence is the capability of computational systems.",
                                "categories": [{"title": "Category:Artificial intelligence"}],
                                "pageprops": {"wikibase-shortdesc": "Intelligence of machines"},
                            }
                        }
                    }
                },
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Artificial intelligence",
                    "content_type": "application/json",
                    "source_url": fetched["url"],
                    "pageprops": {"wikibase-shortdesc": "Intelligence of machines"},
                },
                "plain_text": "Artificial intelligence is the capability of computational systems.",
                "markdown": "# Artificial intelligence\n\nArtificial intelligence is the capability of computational systems.",
                "structured": {"categories": ["Artificial intelligence"]},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {
                "title": extracted.get("metadata", {}).get("title"),
                "summary": extracted.get("plain_text", "").splitlines()[0] if extracted.get("plain_text") else "",
            }

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "fields": {"title": "Artificial_intelligence"},
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["metadata"]["pageprops"]["wikibase-shortdesc"] == "Intelligence of machines"


def test_new_pipeline_preserves_wikipedia_extractor_metadata(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "wikipedia", "resource_type": "article", "title": "Artificial intelligence"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {
                    "query": {
                        "pages": {
                            "1164": {
                                "title": "Artificial intelligence",
                                "extract": "Artificial intelligence is the capability of computational systems.",
                                "categories": [{"title": "Category:Artificial intelligence"}],
                            }
                        }
                    }
                },
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "Artificial intelligence",
                    "content_type": "application/json",
                    "source_url": fetched["url"],
                },
                "plain_text": "Artificial intelligence is the capability of computational systems.",
                "markdown": "# Artificial intelligence\n\nArtificial intelligence is the capability of computational systems.",
                "structured": {"categories": ["Artificial intelligence"]},
                "document_blocks": [],
                "extractor": "wikipedia_api",
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": extracted.get("metadata", {}).get("title")}

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "fields": {"title": "Artificial_intelligence"},
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["extractor"] == "wikipedia_api"


@pytest.mark.parametrize(
    ("platform", "resource_type", "seed_record", "canonical_url", "fields", "extractor"),
    [
        (
            "arxiv",
            "paper",
            {"arxiv_id": "2401.12345"},
            "https://arxiv.org/abs/2401.12345",
            {"arxiv_id": "2401.12345"},
            "arxiv_api",
        ),
        (
            "base",
            "address",
            {"address": "0x4200000000000000000000000000000000000006"},
            "https://basescan.org/address/0x4200000000000000000000000000000000000006",
            {"address": "0x4200000000000000000000000000000000000006"},
            "base_api",
        ),
    ],
)
def test_new_pipeline_preserves_api_extractor_metadata_for_other_platforms(
    monkeypatch,
    workspace_tmp_path: Path,
    platform: str,
    resource_type: str,
    seed_record: dict[str, str],
    canonical_url: str,
    fields: dict[str, str],
    extractor: str,
) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": platform, "resource_type": resource_type, **seed_record}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {"ok": True},
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": f"{platform} example",
                    "content_type": "application/json",
                    "source_url": fetched["url"],
                },
                "plain_text": f"{platform} content",
                "markdown": f"# {platform} example\n\n{platform} content",
                "structured": {"source_kind": platform},
                "document_blocks": [],
                "extractor": extractor,
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": extracted.get("metadata", {}).get("title")}

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda _: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": canonical_url,
            "fields": fields,
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["extractor"] == extractor


def test_new_pipeline_does_not_write_html_artifact_for_api_payload(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "base", "resource_type": "address", "address": "0x123"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        default_backend = "api"
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            return {
                "backend": "api",
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "text": '{"result":"0xabc"}',
                "json_data": {"result": "0xabc"},
            }

        def extract_content(self, record: dict, fetched: dict) -> dict:
            return {
                "metadata": {
                    "title": "address",
                    "content_type": "application/json",
                    "source_url": fetched["url"],
                },
                "plain_text": '"0xabc"',
                "markdown": '```json\n"0xabc"\n```',
                "structured": {"rpc_result": "0xabc"},
                "document_blocks": [],
            }

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"title": "address"}

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_url",
        lambda record: {
            "canonical_url": "https://basescan.org/address/0x123",
            "fields": {"address": "0x123"},
            "artifacts": {},
        },
    )

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    artifact_kinds = {artifact["kind"] for artifact in records[0]["artifacts"]}
    assert "api_response" in artifact_kinds
    assert "html" not in artifact_kinds


def test_new_pipeline_enrich_uses_existing_record_without_build_url(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "records.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps(
            {
                "platform": "linkedin",
                "resource_type": "profile",
                "canonical_url": "https://www.linkedin.com/in/test/",
                "plain_text": "Python engineer with SQL and machine learning experience.",
                "markdown": "# Test\n\nPython engineer",
                "structured": {"headline": "Senior Python Engineer"},
                "metadata": {"title": "Test User", "description": "Profile"},
                "status": "success",
                "stage": "normalized",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fail_build_url(record: dict) -> dict:
        raise AssertionError("build_url should not be called for enrich-only existing records")

    class FakeEnrichmentResult:
        def to_dict(self) -> dict:
            return {
                "doc_id": "doc-1",
                "enrichment_results": {"skills_extraction": {"field_group": "skills_extraction", "status": "success", "fields": []}},
                "enriched_fields": {},
            }

    async def fake_enrich(self, record: dict, field_groups: list[str]) -> FakeEnrichmentResult:
        assert record["canonical_url"] == "https://www.linkedin.com/in/test/"
        assert record["plain_text"].startswith("Python engineer")
        assert record["headline"] == "Senior Python Engineer"
        return FakeEnrichmentResult()

    monkeypatch.setattr("crawler.discovery.url_builder.build_url", fail_build_url)
    monkeypatch.setattr("crawler.enrich.pipeline.EnrichPipeline.enrich", fake_enrich)

    config = parse_args(
        ["enrich", "--input", str(input_path), "--output", str(output_dir), "--field-group", "skills_extraction"]
    )
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["canonical_url"] == "https://www.linkedin.com/in/test/"
    assert records[0]["enrichment"]["doc_id"] == "doc-1"


def test_new_pipeline_enrich_uses_platform_default_field_groups_when_not_overridden(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "records.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps(
            {
                "platform": "amazon",
                "resource_type": "product",
                "canonical_url": "https://www.amazon.com/dp/B000TEST",
                "plain_text": "Keychron K3 keyboard",
                "structured": {"brand": "Keychron", "price": "$99.99", "availability": "In Stock"},
                "metadata": {"title": "Keychron K3", "description": "Low-profile wireless keyboard"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        def build_enrichment_request(self, record: dict, requested_groups: tuple[str, ...] = ()) -> dict:
            return {
                "route": "commerce_graph",
                "field_groups": tuple(requested_groups) or (
                    "amazon_products_identity",
                    "amazon_products_pricing",
                    "amazon_products_description",
                    "amazon_products_category",
                    "amazon_products_visual",
                    "amazon_products_availability",
                    "amazon_products_competition",
                    "amazon_products_reviews_summary",
                    "amazon_products_variants",
                    "amazon_products_compliance",
                    "amazon_products_multimodal_images",
                    "amazon_products_multi_level_summary",
                    "amazon_products_market_positioning",
                    "amazon_products_listing_quality",
                    "amazon_products_linkable_ids",
                ),
            }

    class FakeEnrichmentResult:
        def to_dict(self) -> dict:
            return {
                "doc_id": "doc-amazon-enrich",
                "enrichment_results": {},
                "enriched_fields": {},
            }

    captured: dict[str, object] = {}

    async def fake_enrich(self, record: dict, field_groups: list[str]) -> FakeEnrichmentResult:
        captured["field_groups"] = field_groups
        return FakeEnrichmentResult()

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.enrich.pipeline.EnrichPipeline.enrich", fake_enrich)

    config = parse_args(["enrich", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["enrichment"]["doc_id"] == "doc-amazon-enrich"
    assert captured["field_groups"] == [
        "amazon_products_identity",
        "amazon_products_pricing",
        "amazon_products_description",
        "amazon_products_category",
        "amazon_products_visual",
        "amazon_products_availability",
        "amazon_products_competition",
        "amazon_products_reviews_summary",
        "amazon_products_variants",
        "amazon_products_compliance",
        "amazon_products_multimodal_images",
        "amazon_products_multi_level_summary",
        "amazon_products_market_positioning",
        "amazon_products_listing_quality",
        "amazon_products_linkable_ids",
    ]


def test_new_pipeline_run_uses_platform_default_field_groups_when_not_overridden(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "amazon", "resource_type": "product", "asin": "B000TEST"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        requires_auth = False

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "http"

        def normalize_record(self, record: dict, discovered: dict, extracted: dict, supplemental: dict) -> dict:
            return {"asin": "B000TEST", "title": "Keychron K3", "brand": "Keychron"}

        def build_enrichment_request(self, record: dict, requested_groups: tuple[str, ...] = ()) -> dict:
            return {
                "route": "commerce_graph",
                "field_groups": tuple(requested_groups) or (
                    "amazon_products_identity",
                    "amazon_products_pricing",
                    "amazon_products_description",
                    "amazon_products_category",
                    "amazon_products_visual",
                    "amazon_products_availability",
                    "amazon_products_competition",
                    "amazon_products_reviews_summary",
                    "amazon_products_variants",
                    "amazon_products_compliance",
                    "amazon_products_multimodal_images",
                    "amazon_products_multi_level_summary",
                    "amazon_products_market_positioning",
                    "amazon_products_listing_quality",
                    "amazon_products_linkable_ids",
                ),
            }

    captured: dict[str, object] = {}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        html = "<html><body><article><h1>Keychron K3</h1><p>Keyboard</p></article></body></html>"
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    class FakeEnrichmentResult:
        def to_dict(self) -> dict:
            return {"doc_id": "doc-amazon", "enrichment_results": {}, "enriched_fields": {}}

    async def fake_enrich(self, record: dict, field_groups: list[str]) -> FakeEnrichmentResult:
        captured["field_groups"] = field_groups
        captured["record"] = record
        return FakeEnrichmentResult()

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)
    monkeypatch.setattr(
        "crawler.discovery.url_builder.build_seed_records",
        lambda record: [
            SimpleNamespace(
                platform="amazon",
                resource_type="product",
                canonical_url="https://www.amazon.com/dp/B000TEST",
                identity={"asin": "B000TEST"},
                metadata={"artifacts": {}},
            )
        ],
    )
    monkeypatch.setattr("crawler.enrich.pipeline.EnrichPipeline.enrich", fake_enrich)

    config = parse_args(["run", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["enrichment"]["doc_id"] == "doc-amazon"
    assert captured["field_groups"] == [
        "amazon_products_identity",
        "amazon_products_pricing",
        "amazon_products_description",
        "amazon_products_category",
        "amazon_products_visual",
        "amazon_products_availability",
        "amazon_products_competition",
        "amazon_products_reviews_summary",
        "amazon_products_variants",
        "amazon_products_compliance",
        "amazon_products_multimodal_images",
        "amazon_products_multi_level_summary",
        "amazon_products_market_positioning",
        "amazon_products_listing_quality",
        "amazon_products_linkable_ids",
    ]


def test_new_pipeline_enrich_uses_amazon_seller_default_field_groups(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps(
            {
                "platform": "amazon",
                "resource_type": "seller",
                "seller_id": "ABC123",
                "canonical_url": "https://www.amazon.com/sp?seller=ABC123",
            }
        ) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        def build_enrichment_request(self, record: dict, requested_groups: tuple[str, ...] = ()) -> dict:
            return {
                "route": "commerce_graph",
                "field_groups": tuple(requested_groups) or (
                    "amazon_sellers_identity",
                    "amazon_sellers_performance",
                    "amazon_sellers_portfolio",
                    "amazon_sellers_business_intel",
                    "amazon_sellers_multi_level_summary",
                    "amazon_sellers_linkable_ids",
                ),
            }

    class FakeEnrichmentResult:
        def to_dict(self) -> dict:
            return {
                "doc_id": "doc-amazon-seller-enrich",
                "enrichment_results": {},
                "enriched_fields": {},
            }

    captured: dict[str, object] = {}

    async def fake_enrich(self, record: dict, field_groups: list[str]) -> FakeEnrichmentResult:
        captured["field_groups"] = field_groups
        return FakeEnrichmentResult()

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.enrich.pipeline.EnrichPipeline.enrich", fake_enrich)

    config = parse_args(["enrich", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["enrichment"]["doc_id"] == "doc-amazon-seller-enrich"
    assert captured["field_groups"] == [
        "amazon_sellers_identity",
        "amazon_sellers_performance",
        "amazon_sellers_portfolio",
        "amazon_sellers_business_intel",
        "amazon_sellers_multi_level_summary",
        "amazon_sellers_linkable_ids",
    ]


def test_build_enrich_input_from_record_promotes_structured_fields_for_other_platforms() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "wikipedia",
            "resource_type": "article",
            "canonical_url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "plain_text": "Artificial intelligence is the capability of computational systems.",
            "markdown": "# Artificial intelligence\n\nArtificial intelligence is the capability of computational systems.",
            "structured": {
                "categories": ["Artificial intelligence"],
                "wikipedia": {
                    "summary": "Intelligence demonstrated by machines",
                    "infobox": {"field": "value"},
                },
            },
            "metadata": {
                "title": "Artificial intelligence",
                "description": "Intelligence of machines",
            },
        }
    )

    assert enrich_input["title"] == "Artificial intelligence"
    assert enrich_input["description"] == "Intelligence of machines"
    assert enrich_input["categories"] == ["Artificial intelligence"]
    assert enrich_input["summary"] == "Intelligence demonstrated by machines"


def test_build_enrich_input_from_record_adds_linkedin_company_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "linkedin",
            "resource_type": "company",
            "canonical_url": "https://www.linkedin.com/company/openai/",
            "plain_text": "OpenAI builds safe AGI.",
            "markdown": "# OpenAI\n\nOpenAI builds safe AGI.",
            "structured": {
                "company_slug": "openai",
                "staff_count": 7716,
            },
            "metadata": {
                "title": "OpenAI",
                "description": "OpenAI builds safe AGI.",
            },
        }
    )

    assert enrich_input["company_name"] == "OpenAI"
    assert enrich_input["about"] == "OpenAI builds safe AGI."
    assert enrich_input["employee_count"] == 7716
    assert enrich_input["company_url"] == "https://www.linkedin.com/company/openai/"


def test_build_enrich_input_from_record_adds_linkedin_job_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "linkedin",
            "resource_type": "job",
            "canonical_url": "https://www.linkedin.com/jobs/view/123/",
            "plain_text": "Design and ship production LLM systems.",
            "metadata": {
                "title": "Staff AI Engineer",
                "description": "Design and ship production LLM systems.",
            },
            "published_at": "2026-03-01",
        }
    )

    assert enrich_input["job_title"] == "Staff AI Engineer"
    assert enrich_input["job_description"] == "Design and ship production LLM systems."
    assert enrich_input["posted_date"] == "2026-03-01"


def test_build_enrich_input_from_record_adds_amazon_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "amazon",
            "resource_type": "review",
            "canonical_url": "https://www.amazon.com/review/example",
            "plain_text": "Great keyboard with tactile switches.",
            "markdown": "Great keyboard with tactile switches.",
            "title": "Mechanical Keyboard",
            "review_count": 1520,
            "review_body": "Great keyboard with tactile switches.",
            "seller": "Keychron",
            "structured": {
                "category_path": ["Electronics", "Keyboards"],
                "highlights": ["Hot swappable", "RGB"],
            },
        }
    )

    assert enrich_input["reviews_count"] == 1520
    assert enrich_input["review_text"] == "Great keyboard with tactile switches."
    assert enrich_input["seller_name"] == "Keychron"
    assert enrich_input["category"] == ["Electronics", "Keyboards"]
    assert enrich_input["bullet_points"] == ["Hot swappable", "RGB"]


def test_build_enrich_input_from_record_adds_amazon_product_and_seller_aliases() -> None:
    product_enrich_input = _build_enrich_input_from_record(
        {
            "platform": "amazon",
            "resource_type": "product",
            "canonical_url": "https://www.amazon.com/dp/B000TEST",
            "rating": 4.8,
            "manufacturer": "Keychron",
            "current_price": "$99.99",
            "stock_status": "In Stock",
            "shipping_type": "Prime",
            "structured": {
                "category_path": ["Electronics", "Keyboards"],
                "highlights": ["Wireless", "Low-profile"],
                "image_urls": ["https://example.com/image.jpg"],
            },
            "metadata": {
                "title": "Keychron K3",
                "description": "Low-profile wireless mechanical keyboard.",
            },
        }
    )
    seller_enrich_input = _build_enrich_input_from_record(
        {
            "platform": "amazon",
            "resource_type": "seller",
            "canonical_url": "https://www.amazon.com/sp?seller=ABC",
            "name": "Keychron Official",
            "seller_rating": 4.9,
            "feedback_count": 8421,
        }
    )

    assert product_enrich_input["brand"] == "Keychron"
    assert product_enrich_input["price"] == "$99.99"
    assert product_enrich_input["availability"] == "In Stock"
    assert product_enrich_input["fulfillment"] == "Prime"
    assert product_enrich_input["images"] == ["https://example.com/image.jpg"]
    assert seller_enrich_input["seller_name"] == "Keychron Official"


def test_build_enrich_input_from_record_adds_amazon_review_extended_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "amazon",
            "resource_type": "review",
            "canonical_url": "https://www.amazon.com/review/example",
            "plain_text": "Great keyboard for travel.",
            "author": "Alice",
            "review_rating": "5.0 out of 5 stars",
            "is_verified_purchase": True,
            "photo_urls": ["https://example.com/review-1.jpg"],
        }
    )

    assert enrich_input["review_text"] == "Great keyboard for travel."
    assert enrich_input["reviewer_name"] == "Alice"
    assert enrich_input["rating"] == "5.0 out of 5 stars"
    assert enrich_input["verified_purchase"] is True
    assert enrich_input["review_images"] == ["https://example.com/review-1.jpg"]


def test_amazon_normalizer_promotes_extracted_structured_fields() -> None:
    from crawler.platforms.base import hook_normalizer

    normalizer = hook_normalizer("amazon")
    result = normalizer(
        {"platform": "amazon", "resource_type": "product"},
        {"fields": {"asin": "B000TEST"}},
        {
            "metadata": {"title": "Legacy Title"},
            "structured": {
                "brand": "Keychron",
                "price": "$99.99",
                "availability": "In Stock",
                "bullet_points": ["Wireless", "Low-profile"],
                "images": ["https://example.com/image.jpg"],
                "seller": "Keychron",
            },
        },
        {},
    )

    assert result["asin"] == "B000TEST"
    assert result["title"] == "Legacy Title"
    assert result["brand"] == "Keychron"
    assert result["price"] == "$99.99"
    assert result["availability"] == "In Stock"
    assert result["bullet_points"] == ["Wireless", "Low-profile"]
    assert result["images"] == ["https://example.com/image.jpg"]
    assert result["seller"] == "Keychron"


def test_build_enrich_input_from_record_adds_base_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "base",
            "resource_type": "transaction",
            "canonical_url": "https://basescan.org/tx/0xabc",
            "identifier": "0xabc",
            "structured": {
                "hash": "0xabc",
                "from": "0xfrom",
                "to": "0xto",
                "input_data": "0xa9059cbb",
                "gasUsed": 21000,
                "gasPrice": 1000000000,
                "blockNumber": 12345,
                "events": [{"address": "0xtoken"}],
            },
        }
    )

    assert enrich_input["tx_hash"] == "0xabc"
    assert enrich_input["from_address"] == "0xfrom"
    assert enrich_input["to_address"] == "0xto"
    assert enrich_input["input"] == "0xa9059cbb"
    assert enrich_input["gas_used"] == 21000
    assert enrich_input["gas_price"] == 1000000000
    assert enrich_input["block_number"] == 12345
    assert enrich_input["logs"] == [{"address": "0xtoken"}]


def test_build_enrich_input_from_record_adds_base_address_contract_and_defi_aliases() -> None:
    address_enrich_input = _build_enrich_input_from_record(
        {
            "platform": "base",
            "resource_type": "address",
            "canonical_url": "https://basescan.org/address/0xwallet",
            "identifier": "0xwallet",
            "eth_balance": "1.5",
            "tokens": [{"symbol": "ETH", "amount": "1.5"}],
            "transaction_list": [{"hash": "0x1"}],
            "bytecode": "0x",
        }
    )
    contract_enrich_input = _build_enrich_input_from_record(
        {
            "platform": "base",
            "resource_type": "contract",
            "canonical_url": "https://basescan.org/address/0xcontract",
            "identifier": "0xcontract",
            "bytecode": "0x6000",
            "verified_source": "contract Token {}",
            "contract_abi": [{"type": "function", "name": "balanceOf"}],
            "transaction_list": [{"hash": "0x2"}],
        }
    )
    defi_enrich_input = _build_enrich_input_from_record(
        {
            "platform": "base",
            "resource_type": "defi",
            "canonical_url": "https://defillama.com/protocol/aerodrome",
            "identifier": "aerodrome",
            "raw_metrics": {"tvl": 123},
        }
    )

    assert address_enrich_input["address"] == "0xwallet"
    assert address_enrich_input["balance"] == "1.5"
    assert address_enrich_input["token_balances"] == [{"symbol": "ETH", "amount": "1.5"}]
    assert address_enrich_input["transactions"] == [{"hash": "0x1"}]
    assert contract_enrich_input["address"] == "0xcontract"
    assert contract_enrich_input["source_code"] == "contract Token {}"
    assert contract_enrich_input["abi"] == [{"type": "function", "name": "balanceOf"}]
    assert defi_enrich_input["protocol_id"] == "aerodrome"


def test_build_enrich_input_from_record_adds_arxiv_aliases() -> None:
    enrich_input = _build_enrich_input_from_record(
        {
            "platform": "arxiv",
            "resource_type": "paper",
            "canonical_url": "https://arxiv.org/abs/2401.12345",
            "plain_text": "This paper studies robust receive combining.",
            "markdown": "# Paper\n\nThis paper studies robust receive combining.",
            "structured": {
                "authors": ["Alice", "Bob"],
                "citations": ["Ref A"],
                "figures": ["fig1.png"],
                "title_normalized": "Distributionally Robust Receive Combining",
                "abstract_plain_text": "This paper studies robust receive combining.",
                "sections_structured": [{"heading": "Introduction", "section_type": "introduction"}],
                "references_structured": [{"title": "Ref A", "year": 2021}],
                "linkable_identifiers": {"github_repos_mentioned": ["https://github.com/example/repo"]},
            },
            "metadata": {
                "title": "Distributionally Robust Receive Combining",
            },
        }
    )

    assert enrich_input["abstract"] == "This paper studies robust receive combining."
    assert enrich_input["full_text"] == "This paper studies robust receive combining."
    assert enrich_input["references"] == ["Ref A"]
    assert enrich_input["authors"] == ["Alice", "Bob"]
    assert enrich_input["figures"] == ["fig1.png"]
    assert enrich_input["title_normalized"] == "Distributionally Robust Receive Combining"
    assert enrich_input["abstract_plain_text"] == "This paper studies robust receive combining."
    assert enrich_input["sections_structured"] == [{"heading": "Introduction", "section_type": "introduction"}]
    assert enrich_input["references_structured"] == [{"title": "Ref A", "year": 2021}]
    assert enrich_input["linkable_identifiers"] == {"github_repos_mentioned": ["https://github.com/example/repo"]}


def test_new_pipeline_crawls_linkedin_search_results(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    cookies_path = workspace_tmp_path / "cookies.json"
    input_path.write_text(
        json.dumps(
            {
                "platform": "linkedin",
                "resource_type": "search",
                "query": "openai",
                "search_type": "company",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cookies_path.write_text(json.dumps({"li_at": "secret-token", "JSESSIONID": "ajax:123"}), encoding="utf-8")

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        html = """
        <html><body>
          <div><a href="/company/openai/">OpenAI</a><div>AI research company</div></div>
          <div><a href="/company/anthropic/">Anthropic</a><div>AI safety company</div></div>
        </body></html>
        """
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="playwright",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=1, total_ms=2),
        )

    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--cookies", str(cookies_path)])
    records, errors = run_command(config)

    assert errors == []
    assert records[0]["resource_type"] == "search"
    assert records[0]["results"][0]["resource_type"] == "company"
    assert records[0]["results"][0]["identifier"] == "openai"


def test_new_pipeline_crawls_generic_page_with_standard_html_extraction(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps(
            {
                "platform": "generic",
                "resource_type": "page",
                "url": "https://example.com/docs/protocol",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        captured["platform"] = platform
        captured["resource_type"] = resource_type
        captured["override_backend"] = override_backend
        html = """
        <html>
          <head>
            <title>Data Mining Protocol</title>
            <meta name="description" content="Protocol overview">
          </head>
          <body>
            <article>
              <h1>Data Mining Protocol</h1>
              <p>This page defines the protocol lifecycle and settlement rules.</p>
            </article>
          </body>
        </html>
        """
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html; charset=utf-8",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir)])
    records, errors = run_command(config)

    assert errors == []
    assert captured["platform"] == "generic"
    assert captured["resource_type"] == "page"
    assert captured["override_backend"] is None
    assert records[0]["canonical_url"] == "https://example.com/docs/protocol"
    assert records[0]["metadata"]["title"] == "Data Mining Protocol"
    assert records[0]["metadata"]["source_url"] == "https://example.com/docs/protocol"
    assert "settlement rules" in records[0]["plain_text"]
    assert records[0]["title"] == "Data Mining Protocol"


def test_run_command_dispatches_discover_crawl(monkeypatch, workspace_tmp_path: Path) -> None:
    """Discover-crawl command dispatches to discovery crawl pipeline."""
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"url": "https://example.com/docs"}) + "\n",
        encoding="utf-8",
    )

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        **kwargs,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        html = "<html><body><h1>Docs</h1><p>Content here</p></body></html>"
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = CrawlerConfig.from_mapping({
        "command": "discover-crawl",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "max_depth": 0,
        "max_pages": 1,
    })
    records, errors = run_command(config)

    assert isinstance(records, list)
    assert errors == []
    assert len(records) == 1
    assert records[0]["canonical_url"] == "https://example.com/docs"
    assert "fetched" in records[0]


def test_discover_crawl_keeps_other_candidates_running_when_auth_is_required(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        "\n".join(
            [
                json.dumps({"platform": "linkedin", "resource_type": "profile", "url": "https://www.linkedin.com/in/protected/"}),
                json.dumps({"platform": "generic", "resource_type": "page", "url": "https://example.com/docs"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeDiscoveryAdapter:
        async def crawl(self, candidate, context: dict[str, object]) -> dict[str, object]:
            fetched = await context["fetch_fn"](candidate)
            return {"fetched": fetched, "spawned_candidates": []}

    class LinkedInPlatformAdapter:
        requires_auth = True

    class GenericPlatformAdapter:
        requires_auth = False

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        **kwargs,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        html = "<html><body><h1>Docs</h1></body></html>"
        return RawFetchResult(
            url=url,
            final_url=url,
            backend="http",
            fetch_time=datetime.now(timezone.utc),
            content_type="text/html",
            status_code=200,
            html=html,
            content_bytes=html.encode("utf-8"),
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr(
        "crawler.discovery.adapters.registry.get_discovery_adapter",
        lambda platform: FakeDiscoveryAdapter(),
    )
    monkeypatch.setattr(
        "crawler.platforms.registry.get_platform_adapter",
        lambda platform: LinkedInPlatformAdapter() if platform == "linkedin" else GenericPlatformAdapter(),
    )
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = CrawlerConfig.from_mapping({
        "command": "discover-crawl",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "max_depth": 0,
        "max_pages": 10,
    })
    records, errors = run_command(config)

    assert [record["canonical_url"] for record in records] == ["https://example.com/docs"]
    assert errors[0]["error_code"] == "AUTH_REQUIRED"
    assert errors[0]["canonical_url"] == "https://www.linkedin.com/in/protected/"


def test_discover_crawl_auto_login_refresh_updates_storage_state_path_for_api_fetch(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "url": "https://www.linkedin.com/in/john-doe/"}) + "\n",
        encoding="utf-8",
    )

    class FakeDiscoveryAdapter:
        async def crawl(self, candidate, context: dict[str, object]) -> dict[str, object]:
            fetched = await context["fetch_fn"](candidate)
            return {"fetched": fetched, "spawned_candidates": []}

    class FakePlatformAdapter:
        requires_auth = True
        default_backend = "api"
        fallback_backends = ("playwright",)

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured_paths.append(storage_state_path)
            return {
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {"included": []},
            }

    captured_paths: list[str | None] = []
    attempts = {"count": 0}

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone

        from crawler.fetch.error_classifier import FetchError
        from crawler.fetch.models import FetchTiming, RawFetchResult

        attempts["count"] += 1
        if attempts["count"] == 1:
            err = RuntimeError("auth expired")
            err.fetch_error = FetchError("AUTH_EXPIRED", "refresh_session", "expired", True)  # type: ignore[attr-defined]
            raise err

        payload = api_fetcher(url)
        return RawFetchResult(
            url=url,
            final_url=payload["url"],
            backend="api",
            fetch_time=datetime.now(timezone.utc),
            content_type=payload["content_type"],
            status_code=payload["status_code"],
            json_data=payload["json_data"],
            headers=payload["headers"],
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    def fake_resolve_storage_state_path(*, config, platform, requires_auth, session_store):
        return str(session_store.root / "linkedin-initial.json")

    def fake_refresh_storage_state_path(*, config, platform, requires_auth, session_store):
        return str(session_store.root / "linkedin-refreshed.json")

    monkeypatch.setattr("crawler.discovery.adapters.registry.get_discovery_adapter", lambda platform: FakeDiscoveryAdapter())
    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakePlatformAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)
    monkeypatch.setattr("crawler.core.pipeline.resolve_storage_state_path", fake_resolve_storage_state_path)
    monkeypatch.setattr("crawler.core.pipeline.refresh_storage_state_path", fake_refresh_storage_state_path)

    config = CrawlerConfig.from_mapping({
        "command": "discover-crawl",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "max_depth": 0,
        "max_pages": 1,
        "auto_login": True,
    })
    records, errors = run_command(config)

    assert errors == []
    assert len(records) == 1
    assert captured_paths == [str(output_dir / ".sessions" / "linkedin-refreshed.json")]


def test_new_pipeline_auto_login_preserves_root_auth_error_when_resolve_storage_state_fails(monkeypatch, workspace_tmp_path: Path) -> None:
    input_path = workspace_tmp_path / "input.jsonl"
    output_dir = workspace_tmp_path / "out"
    input_path.write_text(
        json.dumps({"platform": "linkedin", "resource_type": "profile", "public_identifier": "john-doe"}) + "\n",
        encoding="utf-8",
    )

    class FakeAdapter:
        requires_auth = True

        def resolve_backend(self, record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
            return "api"

    def fail_resolve_storage_state_path(*, config, platform, requires_auth, session_store):
        from crawler.integrations.browser_auth import AutoBrowserAuthError

        raise AutoBrowserAuthError(
            "auto-browser 启动失败: 缺少依赖",
            error_code="AUTH_AUTO_LOGIN_FAILED",
            agent_hint="inspect_auto_browser_setup",
            retryable=False,
            login_url="https://www.linkedin.com/login",
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda platform: FakeAdapter())
    monkeypatch.setattr("crawler.core.pipeline.resolve_storage_state_path", fail_resolve_storage_state_path)

    config = parse_args(["crawl", "--input", str(input_path), "--output", str(output_dir), "--auto-login"])
    records, errors = run_command(config)

    assert records == []
    assert errors == [
        {
            "platform": "linkedin",
            "resource_type": "profile",
            "stage": "new_pipeline",
            "status": "failed",
            "error_code": "AUTH_AUTO_LOGIN_FAILED",
            "retryable": False,
            "next_action": "inspect auto-browser setup",
            "message": "auto-browser 启动失败: 缺少依赖",
            "login_url": "https://www.linkedin.com/login",
            "canonical_url": None,
        }
    ]


@pytest.mark.parametrize(
    ("platform", "resource_type", "seed_url", "expected_canonical_url"),
    [
        ("wikipedia", "article", "https://en.wikipedia.org/wiki/Test", "https://en.wikipedia.org/wiki/Test"),
        ("arxiv", "paper", "https://arxiv.org/abs/2401.12345", "https://arxiv.org/abs/2401.12345"),
        (
            "base",
            "address",
            "https://basescan.org/address/0x123",
            "https://basescan.org/address/0x123",
        ),
    ],
)
def test_discover_crawl_routes_api_platforms_through_api_fetcher(
    monkeypatch,
    workspace_tmp_path: Path,
    platform: str,
    resource_type: str,
    seed_url: str,
    expected_canonical_url: str,
) -> None:
    input_path = workspace_tmp_path / f"{platform}.jsonl"
    output_dir = workspace_tmp_path / f"{platform}-out"
    input_path.write_text(
        json.dumps({"platform": platform, "resource_type": resource_type, "url": seed_url}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeDiscoveryAdapter:
        async def crawl(self, candidate, context: dict[str, object]) -> dict[str, object]:
            fetched = await context["fetch_fn"](candidate)
            return {"candidate": candidate, "fetched": fetched, "spawned_candidates": []}

    class FakePlatformAdapter:
        requires_auth = False
        default_backend = "api"
        fallback_backends = ("http", "playwright")

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["adapter_backend"] = backend
            captured["discovered"] = discovered
            return {
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {"ok": True, "platform": platform},
            }

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        captured["override_backend"] = override_backend
        captured["preferred_backend"] = preferred_backend
        captured["fetch_platform"] = platform
        captured["fetch_resource_type"] = resource_type
        captured["fallback_chain"] = fallback_chain
        assert api_fetcher is not None
        payload = api_fetcher(url)
        return RawFetchResult(
            url=url,
            final_url=payload["url"],
            backend="api",
            fetch_time=datetime.now(timezone.utc),
            content_type=payload["content_type"],
            status_code=payload["status_code"],
            json_data=payload["json_data"],
            headers=payload["headers"],
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.discovery.adapters.registry.get_discovery_adapter", lambda name: FakeDiscoveryAdapter())
    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda name: FakePlatformAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = CrawlerConfig.from_mapping({
        "command": "discover-crawl",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "max_depth": 0,
        "max_pages": 1,
    })
    records, errors = run_command(config)

    assert errors == []
    assert [record["canonical_url"] for record in records] == [expected_canonical_url]
    assert captured["override_backend"] is None
    assert captured["preferred_backend"] == "api"
    assert captured["adapter_backend"] == "api"
    assert captured["fetch_platform"] == platform
    assert captured["fetch_resource_type"] == resource_type


@pytest.mark.parametrize(
    ("platform", "resource_type", "seed_url", "expected_fields"),
    [
        (
            "wikipedia",
            "article",
            "https://en.wikipedia.org/wiki/Artificial_intelligence",
            {"title": "Artificial_intelligence"},
        ),
        (
            "arxiv",
            "paper",
            "https://arxiv.org/abs/1706.03762",
            {"arxiv_id": "1706.03762"},
        ),
        (
            "base",
            "address",
            "https://basescan.org/address/0x4200000000000000000000000000000000000006",
            {"address": "0x4200000000000000000000000000000000000006"},
        ),
    ],
)
def test_discover_crawl_derives_platform_identity_from_url_only_seed(
    monkeypatch,
    workspace_tmp_path: Path,
    platform: str,
    resource_type: str,
    seed_url: str,
    expected_fields: dict[str, str],
) -> None:
    input_path = workspace_tmp_path / f"{platform}-url-only.jsonl"
    output_dir = workspace_tmp_path / f"{platform}-url-only-out"
    input_path.write_text(
        json.dumps({"platform": platform, "resource_type": resource_type, "url": seed_url}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakePlatformAdapter:
        requires_auth = False
        default_backend = "api"
        fallback_backends = ("http", "playwright")

        def fetch_record(self, record: dict, discovered: dict, backend: str, storage_state_path: str | None = None) -> dict:
            captured["record"] = record
            captured["discovered"] = discovered
            return {
                "url": discovered["canonical_url"],
                "content_type": "application/json",
                "status_code": 200,
                "headers": {},
                "json_data": {"ok": True},
            }

    async def fake_fetch(
        self,
        url: str,
        platform: str,
        resource_type: str | None = None,
        *,
        requires_auth: bool = False,
        override_backend: str | None = None,
        api_fetcher=None,
        api_kwargs=None,
        preferred_backend: str | None = None,
        fallback_chain=None,
    ):
        from datetime import datetime, timezone
        from crawler.fetch.models import FetchTiming, RawFetchResult

        payload = api_fetcher(url)
        return RawFetchResult(
            url=url,
            final_url=payload["url"],
            backend="api",
            fetch_time=datetime.now(timezone.utc),
            content_type=payload["content_type"],
            status_code=payload["status_code"],
            json_data=payload["json_data"],
            headers=payload["headers"],
            timing=FetchTiming(start_ms=0, navigation_ms=1, wait_strategy_ms=0, total_ms=1),
        )

    monkeypatch.setattr("crawler.platforms.registry.get_platform_adapter", lambda name: FakePlatformAdapter())
    monkeypatch.setattr("crawler.fetch.engine.FetchEngine.fetch", fake_fetch)

    config = CrawlerConfig.from_mapping({
        "command": "discover-crawl",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "max_depth": 0,
        "max_pages": 1,
    })
    records, errors = run_command(config)

    assert errors == []
    assert len(records) == 1
    assert captured["discovered"]["fields"] == expected_fields
