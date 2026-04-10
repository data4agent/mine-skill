"""Unit tests for eip712_primitives.py."""
from __future__ import annotations

import json
from typing import Any

import pytest

from eip712_primitives import (
    EMPTY_HASH,
    canonical_json,
    hash_body,
    hash_headers,
    hash_query,
    keccak_hex,
)


# ---------------------------------------------------------------------------
# keccak_hex
# ---------------------------------------------------------------------------
class TestKeccakHex:
    """Test keccak256 hash computation."""

    def test_known_hash_empty_string(self) -> None:
        """keccak256 of empty string is a known value."""
        result = keccak_hex("")
        # keccak256("") = c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
        assert result == "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"

    def test_known_hash_hello(self) -> None:
        """keccak256 of a known input."""
        result = keccak_hex("hello")
        # Verify correct format
        assert result.startswith("0x")
        assert len(result) == 66  # 0x + 64 hex chars

    def test_string_input(self) -> None:
        result = keccak_hex("test data")
        assert result.startswith("0x")
        assert len(result) == 66

    def test_bytes_input(self) -> None:
        result_str = keccak_hex("test data")
        result_bytes = keccak_hex(b"test data")
        assert result_str == result_bytes

    def test_deterministic(self) -> None:
        """Same input should produce same output."""
        assert keccak_hex("abc") == keccak_hex("abc")

    def test_different_input_different_hash(self) -> None:
        assert keccak_hex("a") != keccak_hex("b")


# ---------------------------------------------------------------------------
# EMPTY_HASH
# ---------------------------------------------------------------------------
class TestEmptyHash:
    """Test EMPTY_HASH constant."""

    def test_correct_zero_hash(self) -> None:
        assert EMPTY_HASH == "0x" + "0" * 64

    def test_length(self) -> None:
        assert len(EMPTY_HASH) == 66


# ---------------------------------------------------------------------------
# hash_query
# ---------------------------------------------------------------------------
class TestHashQuery:
    """Test URL query parameter hashing."""

    def test_url_without_query(self) -> None:
        result = hash_query("https://example.com/path")
        assert result == EMPTY_HASH

    def test_url_with_query(self) -> None:
        result = hash_query("https://example.com/path?foo=bar&baz=qux")
        assert result.startswith("0x")
        assert result != EMPTY_HASH

    def test_query_order_independent(self) -> None:
        """Parameter order should not affect the hash result (sorted before hashing)."""
        r1 = hash_query("https://example.com?a=1&b=2")
        r2 = hash_query("https://example.com?b=2&a=1")
        assert r1 == r2

    def test_special_chars_in_query(self) -> None:
        result = hash_query("https://example.com?name=hello%20world&key=a+b")
        assert result.startswith("0x")
        assert result != EMPTY_HASH

    def test_empty_query_string(self) -> None:
        result = hash_query("https://example.com/path?")
        assert result == EMPTY_HASH


# ---------------------------------------------------------------------------
# hash_headers
# ---------------------------------------------------------------------------
class TestHashHeaders:
    """Test HTTP header hashing."""

    def test_with_signed_headers(self) -> None:
        headers = {"content-type": "application/json", "authorization": "Bearer xxx"}
        result = hash_headers(headers, ("content-type",))
        assert result.startswith("0x")
        assert result != EMPTY_HASH

    def test_without_matching_headers(self) -> None:
        """When signed_headers are not in headers, should return EMPTY_HASH."""
        headers = {"x-custom": "value"}
        result = hash_headers(headers, ("content-type",))
        assert result == EMPTY_HASH

    def test_empty_signed_headers(self) -> None:
        headers = {"content-type": "application/json"}
        result = hash_headers(headers, ())
        assert result == EMPTY_HASH

    def test_multiple_signed_headers_sorted(self) -> None:
        """Multiple signed headers should be sorted by name."""
        headers = {"content-type": "application/json", "accept": "text/html"}
        r1 = hash_headers(headers, ("content-type", "accept"))
        r2 = hash_headers(headers, ("accept", "content-type"))
        assert r1 == r2

    def test_header_value_normalized(self) -> None:
        """Extra whitespace in header values should be normalized."""
        headers_messy = {"content-type": "  application/json  "}
        headers_clean = {"content-type": "application/json"}
        r1 = hash_headers(headers_messy, ("content-type",))
        r2 = hash_headers(headers_clean, ("content-type",))
        assert r1 == r2


# ---------------------------------------------------------------------------
# hash_body
# ---------------------------------------------------------------------------
class TestHashBody:
    """Test request body hashing."""

    def test_none_body(self) -> None:
        result = hash_body(None, "application/json")
        assert result == EMPTY_HASH

    def test_json_body(self) -> None:
        body = {"key": "value", "num": 42}
        result = hash_body(body, "application/json")
        assert result.startswith("0x")
        assert result != EMPTY_HASH

    def test_json_body_key_order_independent(self) -> None:
        """JSON body key order should not affect the hash (canonical_json sorts keys)."""
        r1 = hash_body({"b": 2, "a": 1}, "application/json")
        r2 = hash_body({"a": 1, "b": 2}, "application/json")
        assert r1 == r2

    def test_string_body(self) -> None:
        result = hash_body("raw text body", "text/plain")
        assert result.startswith("0x")
        assert result != EMPTY_HASH

    def test_bytes_body(self) -> None:
        result = hash_body(b"binary data", "application/octet-stream")
        assert result.startswith("0x")
        assert result != EMPTY_HASH


# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------
class TestCanonicalJson:
    """Test JSON canonicalization."""

    def test_key_sorting(self) -> None:
        result = canonical_json({"c": 3, "a": 1, "b": 2})
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == ["a", "b", "c"]

    def test_compact_separators(self) -> None:
        result = canonical_json({"key": "value"})
        assert result == '{"key":"value"}'
        # No spaces
        assert ": " not in result
        assert ", " not in result

    def test_nested_sorting(self) -> None:
        result = canonical_json({"z": {"b": 2, "a": 1}, "a": 0})
        assert result.index('"a":0') < result.index('"z"')

    def test_unicode_preserved(self) -> None:
        result = canonical_json({"name": "你好"})
        assert "你好" in result
        assert "\\u" not in result  # ensure_ascii=False
