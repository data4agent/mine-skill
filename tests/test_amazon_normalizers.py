"""Tests for crawler.normalize.amazon_normalizers module."""
from __future__ import annotations

from typing import Any

import pytest

from crawler.normalize.amazon_normalizers import (
    normalize_date_text,
    normalize_fulfillment,
    normalize_price,
    normalize_rating,
    normalize_reviews_count,
    normalize_sales_volume_hint,
    normalize_stock_status,
    normalize_verified_purchase,
)


# ---------------------------------------------------------------------------
# normalize_price
# ---------------------------------------------------------------------------

class TestNormalizePrice:
    """Various price formats for normalize_price."""

    def test_usd(self) -> None:
        result = normalize_price("$19.99")
        assert result["final_price"] == 19.99
        assert result["currency"] == "USD"

    def test_eur_comma_decimal(self) -> None:
        result = normalize_price("€29,99")
        assert result["final_price"] == 29.99
        assert result["currency"] == "EUR"

    def test_jpy_no_decimal(self) -> None:
        result = normalize_price("JPY47,306")
        assert result["final_price"] == 47306
        assert result["currency"] == "JPY"

    def test_price_range(self) -> None:
        result = normalize_price("$19.99 - $29.99")
        assert result["currency"] == "USD"
        assert result["final_price"] == 19.99
        assert result["initial_price"] == 29.99

    def test_discount_percentage(self) -> None:
        result = normalize_price("10% off")
        assert result["discount"] == "10%"

    def test_empty_string(self) -> None:
        assert normalize_price("") == {}

    def test_none(self) -> None:
        assert normalize_price(None) == {}

    def test_gbp(self) -> None:
        result = normalize_price("£14.99")
        assert result["final_price"] == 14.99
        assert result["currency"] == "GBP"

    def test_thousands_separator(self) -> None:
        result = normalize_price("$1,234.56")
        assert result["final_price"] == 1234.56
        assert result["currency"] == "USD"


# ---------------------------------------------------------------------------
# normalize_rating
# ---------------------------------------------------------------------------

class TestNormalizeRating:
    """Various rating formats for normalize_rating."""

    def test_out_of_5_stars(self) -> None:
        assert normalize_rating("4.5 out of 5 stars") == 4.5

    def test_comma_decimal(self) -> None:
        """European format with comma decimal."""
        assert normalize_rating("4,5 von 5 Sternen") == 4.5

    def test_plain_number(self) -> None:
        assert normalize_rating("4.5") == 4.5

    def test_invalid(self) -> None:
        assert normalize_rating("no rating here") is None

    def test_none(self) -> None:
        assert normalize_rating(None) is None

    def test_empty(self) -> None:
        assert normalize_rating("") is None

    def test_out_of_range(self) -> None:
        """Plain numbers outside 0-5 range should return None."""
        assert normalize_rating("99") is None


# ---------------------------------------------------------------------------
# normalize_reviews_count
# ---------------------------------------------------------------------------

class TestNormalizeReviewsCount:
    """Various count formats for normalize_reviews_count."""

    def test_with_commas(self) -> None:
        assert normalize_reviews_count("1,234 ratings") == 1234

    def test_k_suffix(self) -> None:
        assert normalize_reviews_count("12K+") == 12000

    def test_m_suffix(self) -> None:
        assert normalize_reviews_count("1.5M") == 1500000

    def test_plain_number(self) -> None:
        assert normalize_reviews_count("42") == 42

    def test_none(self) -> None:
        assert normalize_reviews_count(None) is None

    def test_empty(self) -> None:
        assert normalize_reviews_count("") is None

    def test_k_with_decimal(self) -> None:
        assert normalize_reviews_count("2.5K ratings") == 2500


# ---------------------------------------------------------------------------
# normalize_stock_status
# ---------------------------------------------------------------------------

class TestNormalizeStockStatus:
    """Various stock status strings for normalize_stock_status."""

    def test_in_stock(self) -> None:
        assert normalize_stock_status("In Stock") == "in_stock"

    def test_out_of_stock(self) -> None:
        assert normalize_stock_status("Out of Stock") == "out_of_stock"

    def test_currently_unavailable(self) -> None:
        assert normalize_stock_status("Currently unavailable") == "out_of_stock"

    def test_low_stock(self) -> None:
        assert normalize_stock_status("Only 5 left in stock") == "low_stock"

    def test_preorder(self) -> None:
        assert normalize_stock_status("Pre-order now") == "preorder"

    def test_preorder_no_hyphen(self) -> None:
        assert normalize_stock_status("Preorder available") == "preorder"

    def test_available_ships(self) -> None:
        assert normalize_stock_status("Usually ships within 2-3 days") == "available"

    def test_available_delivery(self) -> None:
        assert normalize_stock_status("delivery available") == "available"

    def test_none(self) -> None:
        assert normalize_stock_status(None) is None

    def test_empty(self) -> None:
        assert normalize_stock_status("") is None

    def test_unknown_text(self) -> None:
        assert normalize_stock_status("random text") is None


# ---------------------------------------------------------------------------
# normalize_fulfillment
# ---------------------------------------------------------------------------

class TestNormalizeFulfillment:
    """Fulfillment type detection for normalize_fulfillment."""

    def test_fba_detection(self) -> None:
        """Fulfilled by Amazon should be identified as FBA."""
        result = normalize_fulfillment("Fulfilled by Amazon")
        assert result["fulfillment_type"] == "FBA"
        assert result["prime_eligible"] is True

    def test_fbm_detection(self) -> None:
        """Without Amazon identifier should default to FBM."""
        result = normalize_fulfillment("Ships from Seller XYZ")
        assert result["fulfillment_type"] == "FBM"

    def test_amz_detection(self) -> None:
        """Ships from Amazon should be identified as AMZ."""
        result = normalize_fulfillment("Ships from Amazon")
        assert result["fulfillment_type"] == "AMZ"
        assert result["prime_eligible"] is True

    def test_prime_eligible(self) -> None:
        """Text containing 'prime' should set FBA + prime_eligible."""
        result = normalize_fulfillment("Prime delivery")
        assert result["fulfillment_type"] == "FBA"
        assert result["prime_eligible"] is True

    def test_shipping_speed_same_day(self) -> None:
        result = normalize_fulfillment("Same-day delivery by Amazon")
        assert result["shipping_speed_tier"] == "same_day"

    def test_shipping_speed_next_day(self) -> None:
        result = normalize_fulfillment("FREE delivery Tomorrow", "Ships from Amazon")
        assert result["shipping_speed_tier"] == "next_day"

    def test_shipping_speed_two_day(self) -> None:
        result = normalize_fulfillment("2-day shipping", "Prime seller")
        assert result["shipping_speed_tier"] == "two_day"

    def test_shipping_speed_standard(self) -> None:
        result = normalize_fulfillment("Free shipping available")
        assert result["shipping_speed_tier"] == "standard"

    def test_seller_str_combined(self) -> None:
        """seller_str should be combined with fulfillment_str for detection."""
        result = normalize_fulfillment(None, "Sold by Amazon")
        assert result["fulfillment_type"] == "AMZ"

    def test_operator_precedence_amz_before_fba(self) -> None:
        """AMZ detection should take precedence over FBA (ships from and sold by amazon matches AMZ branch)."""
        # "ships from amazon" matches AMZ branch first
        result = normalize_fulfillment("Ships from Amazon warehouse")
        assert result["fulfillment_type"] == "AMZ"


# ---------------------------------------------------------------------------
# normalize_date_text
# ---------------------------------------------------------------------------

class TestNormalizeDateText:
    """Date parsing for normalize_date_text."""

    def test_english_date(self) -> None:
        assert normalize_date_text("January 15, 2024") == "2024-01-15"

    def test_english_date_with_prefix(self) -> None:
        assert normalize_date_text("Reviewed in the United States on March 5, 2024") == "2024-03-05"

    def test_chinese_date(self) -> None:
        assert normalize_date_text("2024年3月15日") == "2024-03-15"

    def test_chinese_date_with_spaces(self) -> None:
        assert normalize_date_text("2024年 3月 5日") == "2024-03-05"

    def test_invalid(self) -> None:
        assert normalize_date_text("not a date") is None

    def test_none(self) -> None:
        assert normalize_date_text(None) is None

    def test_empty(self) -> None:
        assert normalize_date_text("") is None

    def test_december(self) -> None:
        assert normalize_date_text("December 25, 2023") == "2023-12-25"


# ---------------------------------------------------------------------------
# normalize_verified_purchase
# ---------------------------------------------------------------------------

class TestNormalizeVerifiedPurchase:
    """Type conversion for normalize_verified_purchase."""

    def test_bool_true(self) -> None:
        assert normalize_verified_purchase(True) is True

    def test_bool_false(self) -> None:
        assert normalize_verified_purchase(False) is False

    def test_int_1(self) -> None:
        assert normalize_verified_purchase(1) is True

    def test_int_0(self) -> None:
        assert normalize_verified_purchase(0) is False

    def test_string_true(self) -> None:
        assert normalize_verified_purchase("true") is True

    def test_string_yes(self) -> None:
        assert normalize_verified_purchase("yes") is True

    def test_string_verified_purchase(self) -> None:
        assert normalize_verified_purchase("Verified Purchase") is True

    def test_string_false(self) -> None:
        assert normalize_verified_purchase("false") is False

    def test_string_no(self) -> None:
        assert normalize_verified_purchase("no") is False

    def test_none(self) -> None:
        assert normalize_verified_purchase(None) is None

    def test_empty_string(self) -> None:
        assert normalize_verified_purchase("") is None

    def test_unknown_string(self) -> None:
        assert normalize_verified_purchase("maybe") is None


# ---------------------------------------------------------------------------
# normalize_sales_volume_hint
# ---------------------------------------------------------------------------

class TestNormalizeSalesVolumeHint:
    """Sales volume hint parsing for normalize_sales_volume_hint."""

    def test_10k_plus(self) -> None:
        assert normalize_sales_volume_hint("10K+ bought in past month") == 10000

    def test_1_5m_plus(self) -> None:
        assert normalize_sales_volume_hint("1.5M+ bought in past month") == 1500000

    def test_plain_number(self) -> None:
        assert normalize_sales_volume_hint("500 bought in past month") == 500

    def test_invalid(self) -> None:
        assert normalize_sales_volume_hint("no numbers here") is None

    def test_none(self) -> None:
        assert normalize_sales_volume_hint(None) is None

    def test_empty(self) -> None:
        assert normalize_sales_volume_hint("") is None

    def test_5k(self) -> None:
        assert normalize_sales_volume_hint("5K") == 5000
