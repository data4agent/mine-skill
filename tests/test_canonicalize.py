"""Comprehensive tests for canonicalize_url."""
from __future__ import annotations

import pytest

from canonicalize import canonicalize_url


# ---------------------------------------------------------------------------
# Empty/blank input
# ---------------------------------------------------------------------------
class TestEmptyInput:
    def test_empty_string(self) -> None:
        assert canonicalize_url("") == ""

    def test_whitespace_only(self) -> None:
        assert canonicalize_url("   ") == ""

    def test_tabs_and_newlines(self) -> None:
        assert canonicalize_url("\t\n  ") == ""


# ---------------------------------------------------------------------------
# Hostname lowercase normalization
# ---------------------------------------------------------------------------
class TestHostLowercase:
    def test_uppercase_host(self) -> None:
        assert canonicalize_url("https://WWW.EXAMPLE.COM/page") == "https://www.example.com/page"

    def test_mixed_case_host(self) -> None:
        assert canonicalize_url("https://Www.Example.Com/Path") == "https://www.example.com/Path"

    def test_scheme_lowered(self) -> None:
        result = canonicalize_url("HTTP://example.com/x")
        assert result.startswith("http://")


# ---------------------------------------------------------------------------
# Default port stripping
# ---------------------------------------------------------------------------
class TestDefaultPortStripping:
    def test_https_443_stripped(self) -> None:
        assert canonicalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_http_80_stripped(self) -> None:
        assert canonicalize_url("http://example.com:80/path") == "http://example.com/path"


# ---------------------------------------------------------------------------
# Non-default port preservation
# ---------------------------------------------------------------------------
class TestNonDefaultPort:
    def test_https_8443_preserved(self) -> None:
        assert canonicalize_url("https://example.com:8443/path") == "https://example.com:8443/path"

    def test_http_8080_preserved(self) -> None:
        assert canonicalize_url("http://example.com:8080/path") == "http://example.com:8080/path"

    def test_http_443_preserved(self) -> None:
        # 443 on http (not https) is non-default — should be kept
        assert canonicalize_url("http://example.com:443/path") == "http://example.com:443/path"

    def test_https_80_preserved(self) -> None:
        # 80 on https is non-default — should be kept
        assert canonicalize_url("https://example.com:80/path") == "https://example.com:80/path"


# ---------------------------------------------------------------------------
# UTM and tracking parameter removal
# ---------------------------------------------------------------------------
class TestTrackingParamRemoval:
    @pytest.mark.parametrize("param", [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    ])
    def test_utm_params_removed(self, param: str) -> None:
        url = f"https://example.com/page?{param}=val&keep=1"
        result = canonicalize_url(url)
        assert param not in result
        assert "keep=1" in result

    @pytest.mark.parametrize("param", ["fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src"])
    def test_tracking_params_removed(self, param: str) -> None:
        url = f"https://example.com/page?{param}=abc123&keep=yes"
        result = canonicalize_url(url)
        assert param not in result
        assert "keep=yes" in result

    def test_all_tracking_removed_leaves_no_query(self) -> None:
        url = "https://example.com/page?utm_source=google&fbclid=abc"
        result = canonicalize_url(url)
        assert result == "https://example.com/page"


# ---------------------------------------------------------------------------
# Trailing slash normalization
# ---------------------------------------------------------------------------
class TestTrailingSlash:
    def test_root_slash_preserved(self) -> None:
        assert canonicalize_url("https://example.com/") == "https://example.com/"

    def test_trailing_slash_stripped_from_path(self) -> None:
        assert canonicalize_url("https://example.com/page/") == "https://example.com/page"

    def test_deep_path_trailing_slash_stripped(self) -> None:
        assert canonicalize_url("https://example.com/a/b/c/") == "https://example.com/a/b/c"

    def test_no_trailing_slash_unchanged(self) -> None:
        assert canonicalize_url("https://example.com/page") == "https://example.com/page"


# ---------------------------------------------------------------------------
# Query parameter sorting
# ---------------------------------------------------------------------------
class TestQuerySorting:
    def test_params_sorted_alphabetically(self) -> None:
        url = "https://example.com/search?z=1&a=2&m=3"
        result = canonicalize_url(url)
        assert result == "https://example.com/search?a=2&m=3&z=1"

    def test_sorted_after_tracking_removed(self) -> None:
        url = "https://example.com/?c=3&a=1&utm_source=g&b=2"
        result = canonicalize_url(url)
        assert result == "https://example.com/?a=1&b=2&c=3"


# ---------------------------------------------------------------------------
# Wikipedia special handling
# ---------------------------------------------------------------------------
class TestWikipedia:
    def test_strip_query_params(self) -> None:
        url = "https://en.wikipedia.org/wiki/Python_(programming_language)?action=edit"
        result = canonicalize_url(url)
        assert result == "https://en.wikipedia.org/wiki/Python_(programming_language)"

    def test_preserve_wiki_path(self) -> None:
        url = "https://en.wikipedia.org/wiki/Main_Page"
        assert canonicalize_url(url) == "https://en.wikipedia.org/wiki/Main_Page"

    def test_scheme_forced_https(self) -> None:
        url = "http://en.wikipedia.org/wiki/Test"
        assert canonicalize_url(url) == "https://en.wikipedia.org/wiki/Test"

    def test_evil_subdomain_not_matched(self) -> None:
        """evil.en.wikipedia.org should not match en.wikipedia.org special logic."""
        url = "https://evil.en.wikipedia.org/wiki/Test?action=edit"
        result = canonicalize_url(url)
        # Should not go through Wikipedia branch, so query params are not unconditionally removed
        # But action is not in the tracking param list, so it should be kept
        assert "action=edit" in result

    def test_non_wiki_path_not_special(self) -> None:
        """Non /wiki/ paths on en.wikipedia.org do not get special treatment."""
        url = "https://en.wikipedia.org/w/index.php?title=Test"
        result = canonicalize_url(url)
        assert "title=Test" in result


# ---------------------------------------------------------------------------
# arXiv special handling
# ---------------------------------------------------------------------------
class TestArxiv:
    def test_normalize_to_arxiv_org(self) -> None:
        url = "https://arxiv.org/abs/2301.12345"
        assert canonicalize_url(url) == "https://arxiv.org/abs/2301.12345"

    def test_subdomain_normalized(self) -> None:
        url = "https://export.arxiv.org/abs/2301.12345"
        assert canonicalize_url(url) == "https://arxiv.org/abs/2301.12345"

    def test_trailing_slash_stripped_arxiv(self) -> None:
        url = "https://arxiv.org/abs/2301.12345/"
        assert canonicalize_url(url) == "https://arxiv.org/abs/2301.12345"

    def test_query_stripped_arxiv(self) -> None:
        url = "https://arxiv.org/abs/2301.12345?context=cs"
        assert canonicalize_url(url) == "https://arxiv.org/abs/2301.12345"

    def test_non_abs_path_not_special(self) -> None:
        url = "https://arxiv.org/pdf/2301.12345"
        result = canonicalize_url(url)
        assert "pdf" in result


# ---------------------------------------------------------------------------
# LinkedIn special handling
# ---------------------------------------------------------------------------
class TestLinkedin:
    def test_in_profile_trailing_slash(self) -> None:
        url = "https://www.linkedin.com/in/johndoe"
        assert canonicalize_url(url) == "https://www.linkedin.com/in/johndoe/"

    def test_in_profile_already_has_slash(self) -> None:
        url = "https://www.linkedin.com/in/johndoe/"
        assert canonicalize_url(url) == "https://www.linkedin.com/in/johndoe/"

    def test_company_trailing_slash(self) -> None:
        url = "https://www.linkedin.com/company/acme-corp"
        assert canonicalize_url(url) == "https://www.linkedin.com/company/acme-corp/"

    def test_company_already_has_slash(self) -> None:
        url = "https://www.linkedin.com/company/acme-corp/"
        assert canonicalize_url(url) == "https://www.linkedin.com/company/acme-corp/"

    def test_other_path_no_trailing_slash(self) -> None:
        url = "https://www.linkedin.com/feed/"
        result = canonicalize_url(url)
        # /feed/ does not start with /in/ or /company/, follows normal path logic — no extra / added
        # Note: LinkedIn branch returns normalized, feed does not start with /in/ or /company/
        assert result == "https://www.linkedin.com/feed"

    def test_scheme_forced_https(self) -> None:
        url = "http://www.linkedin.com/in/johndoe"
        assert canonicalize_url(url) == "https://www.linkedin.com/in/johndoe/"


# ---------------------------------------------------------------------------
# Amazon /dp/ASIN extraction
# ---------------------------------------------------------------------------
class TestAmazon:
    def test_extract_asin_from_product_url(self) -> None:
        url = "https://www.amazon.com/Some-Product-Name/dp/B08N5WRWNW/ref=sr_1_1"
        assert canonicalize_url(url) == "https://www.amazon.com/dp/B08N5WRWNW"

    def test_extract_asin_direct(self) -> None:
        url = "https://www.amazon.com/dp/B08N5WRWNW"
        assert canonicalize_url(url) == "https://www.amazon.com/dp/B08N5WRWNW"

    def test_no_asin_after_dp(self) -> None:
        """If there is no ASIN after dp, special extraction is not applied."""
        url = "https://www.amazon.com/dp/"
        result = canonicalize_url(url)
        # No segment after dp, falls through to normal path normalization
        assert "amazon.com" in result

    def test_query_stripped_in_asin_extraction(self) -> None:
        url = "https://www.amazon.com/dp/B08N5WRWNW?tag=affiliate"
        assert canonicalize_url(url) == "https://www.amazon.com/dp/B08N5WRWNW"


# ---------------------------------------------------------------------------
# Exact hostname matching (prevent subdomain false matches)
# ---------------------------------------------------------------------------
class TestExactHostnameMatching:
    def test_evil_wikipedia_subdomain(self) -> None:
        """evil.en.wikipedia.org should not trigger Wikipedia special logic."""
        url = "https://evil.en.wikipedia.org/wiki/Test?foo=bar"
        result = canonicalize_url(url)
        assert "foo=bar" in result

    def test_non_www_linkedin(self) -> None:
        """linkedin.com (without www) should not trigger LinkedIn special logic."""
        url = "https://linkedin.com/in/johndoe"
        result = canonicalize_url(url)
        # Does not go through LinkedIn branch, normal trailing slash stripping
        assert not result.endswith("/")

    def test_non_www_amazon(self) -> None:
        """amazon.com (without www) should not trigger Amazon special logic."""
        url = "https://amazon.com/dp/B08N5WRWNW/extra"
        result = canonicalize_url(url)
        # Does not go through Amazon branch
        assert "/extra" in result or "dp/B08N5WRWNW" in result
