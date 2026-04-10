"""Tests for crawler.extract.pre_llm_optimizer module."""
from __future__ import annotations

from typing import Any

import pytest

from crawler.extract.pre_llm_optimizer import (
    _deduplicate_paragraphs,
    _remove_low_value_sections,
    _smart_truncate,
    optimize_for_llm,
)


# ---------------------------------------------------------------------------
# _smart_truncate
# ---------------------------------------------------------------------------

class TestSmartTruncate:
    """Truncation logic for _smart_truncate."""

    def test_within_limit(self) -> None:
        """Text within limit should be returned as-is."""
        text = "Short text\nSecond line"
        result = _smart_truncate(text, max_chars=100)
        assert result == text

    def test_exceeds_limit(self) -> None:
        """Text exceeding limit should be truncated."""
        lines = [f"Line {i}: " + "x" * 50 for i in range(20)]
        text = "\n".join(lines)
        result = _smart_truncate(text, max_chars=200)
        assert len(result) <= 200 + 100  # Allow extra length for trailing line
        assert result.startswith("Line 0:")

    def test_first_line_exceeding_limit_kept(self) -> None:
        """First line exceeding limit should be kept (break condition is i > 0)."""
        long_first_line = "A" * 500
        text = long_first_line + "\nSecond line"
        result = _smart_truncate(text, max_chars=100)
        # First line should be kept because loop condition is i > 0
        assert result == long_first_line

    def test_empty_text(self) -> None:
        """Empty text should return empty string."""
        result = _smart_truncate("", max_chars=100)
        assert result == ""


# ---------------------------------------------------------------------------
# _remove_low_value_sections
# ---------------------------------------------------------------------------

class TestRemoveLowValueSections:
    """Section filtering logic for _remove_low_value_sections."""

    def test_removes_references_section(self) -> None:
        """Should remove References section."""
        text = "# Title\nContent here.\n## References\nRef 1\nRef 2\n## Next Section\nMore content"
        result = _remove_low_value_sections(text)
        assert "References" not in result
        assert "Ref 1" not in result
        assert "Next Section" in result
        assert "More content" in result

    def test_removes_bibliography(self) -> None:
        """Should remove Bibliography section."""
        text = "# Main\nBody text\n## Bibliography\nBook 1\nBook 2"
        result = _remove_low_value_sections(text)
        assert "Bibliography" not in result
        assert "Book 1" not in result
        assert "Body text" in result

    def test_removes_see_also(self) -> None:
        """Should remove See Also section."""
        text = "# Article\nParagraph\n## See Also\nLink 1\nLink 2"
        result = _remove_low_value_sections(text)
        assert "See Also" not in result
        assert "Link 1" not in result
        assert "Paragraph" in result

    def test_preserves_other_content(self) -> None:
        """Non-low-value sections should be fully preserved."""
        text = "# Title\nIntro\n## Methods\nMethod text\n## Results\nResult text"
        result = _remove_low_value_sections(text)
        assert "Methods" in result
        assert "Method text" in result
        assert "Results" in result
        assert "Result text" in result

    def test_nested_headings_within_low_value(self) -> None:
        """Deeper headings within low-value sections should also be removed."""
        text = "# Title\nIntro\n## References\nRef text\n### Sub-reference\nSub text\n## Conclusion\nConclusion text"
        result = _remove_low_value_sections(text)
        assert "References" not in result
        assert "Sub-reference" not in result
        assert "Sub text" not in result
        assert "Conclusion" in result

    def test_resume_after_low_value_section(self) -> None:
        """Should resume collecting when encountering same-level or higher-level heading."""
        text = (
            "# Article\n"
            "Intro text\n"
            "## See Also\n"
            "See also content\n"
            "## History\n"
            "History content"
        )
        result = _remove_low_value_sections(text)
        assert "See Also" not in result
        assert "See also content" not in result
        assert "History" in result
        assert "History content" in result


# ---------------------------------------------------------------------------
# _deduplicate_paragraphs
# ---------------------------------------------------------------------------

class TestDeduplicateParagraphs:
    """Deduplication logic for _deduplicate_paragraphs."""

    def test_removes_duplicate_paragraphs(self) -> None:
        """Duplicate long paragraphs should only keep the first occurrence."""
        para = "This is a paragraph that is long enough to be considered for deduplication."
        text = f"{para}\n\n{para}\n\nAnother unique paragraph that is also long enough."
        result = _deduplicate_paragraphs(text)
        # Should appear only once
        assert result.count(para) == 1
        assert "Another unique paragraph" in result

    def test_keeps_short_paragraphs(self) -> None:
        """Short paragraphs (< 20 chars) should be kept even if duplicated."""
        text = "Hi\n\nHi\n\nThis is a longer paragraph that will be deduplicated."
        result = _deduplicate_paragraphs(text)
        # "Hi" is short enough, should be kept twice
        assert result.count("Hi") == 2

    def test_case_insensitive_dedup(self) -> None:
        """Deduplication comparison should be case-insensitive."""
        para1 = "This is a test paragraph for deduplication checking."
        para2 = "this is a test paragraph for deduplication checking."
        text = f"{para1}\n\n{para2}"
        result = _deduplicate_paragraphs(text)
        # Only keep the first one
        parts = [p for p in result.split("\n\n") if p.strip()]
        assert len(parts) == 1

    def test_whitespace_normalized(self) -> None:
        """Deduplication should ignore extra whitespace."""
        para1 = "A long enough paragraph with normal spacing for test."
        para2 = "A  long  enough  paragraph  with  normal  spacing  for  test."
        text = f"{para1}\n\n{para2}"
        result = _deduplicate_paragraphs(text)
        parts = [p for p in result.split("\n\n") if p.strip()]
        assert len(parts) == 1


# ---------------------------------------------------------------------------
# optimize_for_llm
# ---------------------------------------------------------------------------

class TestOptimizeForLlm:
    """Full pipeline tests for optimize_for_llm."""

    def test_full_pipeline(self) -> None:
        """Full optimization pipeline should remove low-value sections, citation markers, and deduplicate."""
        text = (
            "# Test Article\n"
            "2024-01-15\n"
            "Main content here.[1]\n"
            "\n"
            "## References\n"
            "Ref 1\n"
            "Ref 2\n"
        )
        result_text, fields = optimize_for_llm(text, max_chars=50000)
        # Citation marker [1] should be removed
        assert "[1]" not in result_text
        # References section should be removed
        assert "References" not in result_text
        assert "Ref 1" not in result_text
        # Main content should be preserved
        assert "Main content here." in result_text
        # pre_extracted should contain fields
        assert "title" in fields
        assert fields["title"] == "Test Article"

    def test_pre_extracted_dict_preservation(self) -> None:
        """Passed-in pre_extracted dict should be preserved with new fields added."""
        pre = {"custom_key": "custom_value"}
        text = "# Article Title\n2024-03-15\nSome text."
        _, fields = optimize_for_llm(text, pre_extracted=pre)
        assert fields["custom_key"] == "custom_value"
        assert "title" in fields

    def test_empty_text(self) -> None:
        """Empty text should be returned directly."""
        result_text, fields = optimize_for_llm("")
        assert result_text == ""
        assert fields == {}

    def test_pre_extracted_none_creates_new_dict(self) -> None:
        """pre_extracted as None should create a new dict."""
        text = "# Title\nSome content"
        _, fields = optimize_for_llm(text)
        assert isinstance(fields, dict)
        assert "title" in fields

    def test_truncation_applied(self) -> None:
        """Excessively long text should be truncated."""
        long_text = "# Title\n" + "Content line.\n" * 5000
        result_text, _ = optimize_for_llm(long_text, max_chars=500)
        assert len(result_text) <= 600  # Allow some margin (last line may exceed)

    def test_language_detection_chinese(self) -> None:
        """Chinese content should be detected as zh."""
        text = "# 标题\n这是一段中文内容，用于测试语言检测功能。"
        _, fields = optimize_for_llm(text)
        assert fields.get("language") == "zh"

    def test_breadcrumb_removal(self) -> None:
        """Breadcrumb navigation should be removed."""
        text = "Home > Products > Widget\n# Widget\nDescription here."
        result_text, _ = optimize_for_llm(text)
        assert "Home > Products" not in result_text
        assert "Description here." in result_text
