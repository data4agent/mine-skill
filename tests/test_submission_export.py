"""Tests for crawler.submission_export module."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from crawler.submission_export import (
    _build_structured_data,
    build_submission_request,
    export_submission_request,
)


# ---------------------------------------------------------------------------
# build_submission_request
# ---------------------------------------------------------------------------

class TestBuildSubmissionRequest:
    """Various input scenarios for build_submission_request."""

    def test_valid_records(self) -> None:
        """Records with complete fields should produce correct output."""
        records = [
            {
                "url": "https://example.com/page1",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "plain_text": "Hello World",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["dataset_id"] == "ds_1"
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["url"] == "https://example.com/page1"
        assert entry["cleaned_data"] == "Hello World"
        assert entry["crawl_timestamp"] == "2025-01-01T00:00:00Z"
        assert isinstance(entry["structured_data"], dict)

    def test_canonical_url_preferred(self) -> None:
        """canonical_url should take priority over url field."""
        records = [
            {
                "canonical_url": "https://example.com/canonical",
                "url": "https://example.com/raw",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "plain_text": "text",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["url"] == "https://example.com/canonical"

    def test_missing_url_skipped(self) -> None:
        """Records with empty url should be skipped."""
        records = [
            {"crawl_timestamp": "2025-01-01T00:00:00Z", "plain_text": "no url"},
            {"url": "", "crawl_timestamp": "2025-01-01T00:00:00Z"},
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert len(result["entries"]) == 0

    def test_missing_timestamp_skipped(self) -> None:
        """Records with empty crawl_timestamp and no generated_at should be skipped."""
        records = [
            {"url": "https://example.com", "plain_text": "no ts"},
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert len(result["entries"]) == 0

    def test_generated_at_fallback(self) -> None:
        """Should fall back to generated_at when crawl_timestamp is empty."""
        records = [
            {"url": "https://example.com/a", "plain_text": "data"},
        ]
        result = build_submission_request(
            records, dataset_id="ds_1", generated_at="2025-06-01T00:00:00Z",
        )
        assert len(result["entries"]) == 1
        assert result["entries"][0]["crawl_timestamp"] == "2025-06-01T00:00:00Z"

    def test_cleaned_data_fallback_plain_text(self) -> None:
        """plain_text has the highest priority."""
        records = [
            {
                "url": "https://example.com",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "plain_text": "plain",
                "cleaned_data": "cleaned",
                "markdown": "md",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["cleaned_data"] == "plain"

    def test_cleaned_data_fallback_cleaned_data(self) -> None:
        """Should fall back to cleaned_data when plain_text is empty."""
        records = [
            {
                "url": "https://example.com",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "cleaned_data": "cleaned",
                "markdown": "md",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["cleaned_data"] == "cleaned"

    def test_cleaned_data_fallback_markdown(self) -> None:
        """Should fall back to markdown when both plain_text and cleaned_data are empty."""
        records = [
            {
                "url": "https://example.com",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "markdown": "md content",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["cleaned_data"] == "md content"

    def test_cleaned_data_all_none(self) -> None:
        """cleaned_data should be empty string when all text fields are None."""
        records = [
            {
                "url": "https://example.com",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["cleaned_data"] == ""

    def test_empty_string_plain_text_falls_through(self) -> None:
        """Empty string plain_text should fall back."""
        records = [
            {
                "url": "https://example.com",
                "crawl_timestamp": "2025-01-01T00:00:00Z",
                "plain_text": "",
                "cleaned_data": "fallback",
            },
        ]
        result = build_submission_request(records, dataset_id="ds_1")
        assert result["entries"][0]["cleaned_data"] == "fallback"


# ---------------------------------------------------------------------------
# _build_structured_data
# ---------------------------------------------------------------------------

class TestBuildStructuredData:
    """Normal and error paths for _build_structured_data."""

    def test_success_delegates_to_flatten(self) -> None:
        """When flatten_record_for_schema returns normally, use its result directly."""
        record: dict[str, Any] = {"url": "https://example.com", "structured": {"a": 1}}
        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            return_value={"flat": True},
        ):
            result = _build_structured_data(record)
        assert result == {"flat": True}

    def test_value_error_fallback(self) -> None:
        """When flatten_record_for_schema raises ValueError, fall back to record['structured']."""
        record: dict[str, Any] = {"structured": {"key": "val"}}
        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            side_effect=ValueError("no schema"),
        ):
            result = _build_structured_data(record)
        assert result == {"key": "val"}

    def test_os_error_fallback(self) -> None:
        """When flatten_record_for_schema raises OSError, fall back to record['structured']."""
        record: dict[str, Any] = {"structured": {"x": 1}}
        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            side_effect=OSError("file not found"),
        ):
            result = _build_structured_data(record)
        assert result == {"x": 1}

    def test_fallback_no_structured_key(self) -> None:
        """When record has no structured key, fallback should return empty dict."""
        record: dict[str, Any] = {"url": "https://example.com"}
        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            side_effect=ValueError("missing"),
        ):
            result = _build_structured_data(record)
        assert result == {}

    def test_fallback_structured_not_dict(self) -> None:
        """When structured value is not a dict, should return empty dict."""
        record: dict[str, Any] = {"structured": "not a dict"}
        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            side_effect=ValueError("bad"),
        ):
            result = _build_structured_data(record)
        assert result == {}


# ---------------------------------------------------------------------------
# export_submission_request
# ---------------------------------------------------------------------------

class TestExportSubmissionRequest:
    """File writing tests for export_submission_request."""

    def test_writes_to_output_path(self, tmp_path: Path) -> None:
        """Should write payload to output_path."""
        input_file = tmp_path / "input.jsonl"
        input_file.write_text(
            json.dumps({"url": "https://example.com", "crawl_timestamp": "2025-01-01T00:00:00Z", "plain_text": "hi"}) + "\n",
            encoding="utf-8",
        )
        output_file = tmp_path / "output.json"

        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            return_value={},
        ):
            result = export_submission_request(
                input_path=input_file,
                output_path=output_file,
                dataset_id="ds_test",
                generated_at="2025-01-01T00:00:00Z",
            )

        assert result == output_file
        assert output_file.exists()
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        assert payload["dataset_id"] == "ds_test"
        assert len(payload["entries"]) == 1

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Should auto-create parent directories when output_path's parent does not exist."""
        input_file = tmp_path / "input.jsonl"
        input_file.write_text(
            json.dumps({"url": "https://example.com", "crawl_timestamp": "2025-01-01T00:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        output_file = tmp_path / "nested" / "deep" / "output.json"

        with patch(
            "crawler.submission_export.flatten_record_for_schema",
            return_value={},
        ):
            result = export_submission_request(
                input_path=input_file,
                output_path=output_file,
                dataset_id="ds_test",
                generated_at="2025-01-01T00:00:00Z",
            )

        assert output_file.exists()
        assert result == output_file
