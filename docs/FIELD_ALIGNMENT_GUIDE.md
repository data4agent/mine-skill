# Field Alignment Guide

This document explains how to align Mine crawler output with the authoritative `schema(1)/*.schema.json` files at the repo root.

The runtime contract source of truth is:

- `mine/schema(1)`

The copy under `crawler/enrich/schema(1)` is a mirrored reference, not the contract authority.

---

## 1. Where fields come from

Each schema field is produced by one of three layers:

| Layer | Location | Field type | Examples |
|-------|----------|------------|----------|
| **Extract** | `crawler/extract/structured/json_extractor.py` | Parsed from HTML | title, brand, price, images |
| **Normalize** | `crawler/normalize/` (WIP) | Type coercion / normalization | rating: "4.5 out of 5" → 4.5 |
| **Enrich** | `crawler/enrich/schemas/*_field_groups.py` | LLM enrichment | title_cleaned, buyer_quick_take |

---

## 2. Check current coverage

### Option A: run the validator

```bash
cd mine
export PYTHONPATH=.
python scripts/schema_tools.py validate
```

Example output:

```json
[
  {"schema": "amazon_products", "category": "missing_field", "detail": "products_identity -> seller_id"}
]
```

### Option B: read the coverage report

```bash
cat docs/schema-coverage-report.json | python -m json.tool
```

### Option C: compare schema vs field_groups

```bash
# All property keys defined in the schema
cat schema\(1\)/amazon_products.schema.json | jq '.properties | keys'

# Fields emitted by field_groups
grep -A20 "output_fields" crawler/enrich/schemas/amazon_field_groups.py
```

---

## 3. Alignment workflow

### Step 1: Decide which layer owns the field

```
Can this field be extracted from HTML directly?
    ├─ Yes → Extract layer
    │       e.g. asin, title, price, images
    │
    └─ No → Does it need reasoning?
            ├─ Yes → Enrich layer (LLM)
            │       e.g. title_cleaned, buyer_quick_take, price_tier
            │
            └─ No → Normalize layer (coercion)
                    e.g. "$19.99" → {final_price: 19.99, currency: "USD"}
```

### Step 2: Add Extract fields

**File:** `crawler/extract/structured/json_extractor.py`

**Find the platform-specific extractor:**
- Amazon: `_extract_amazon_product_html()`
- Wikipedia / arXiv: the corresponding helpers

**Example: add `seller_id`**

```python
def _extract_amazon_product_html(self, soup, canonical_url):
    # ... existing code ...

    # New: extract seller_id
    merchant_info = soup.select_one("#merchant-info a[href*='seller=']")
    if merchant_info:
        href = merchant_info.get("href", "")
        match = re.search(r"seller=([A-Z0-9]+)", href)
        if match:
            set_field("seller_id", match.group(1), "amazon_html:merchant_info_href")
```

### Step 3: Add Normalize helpers

**Directory:** `crawler/normalize/` (create modules as needed)

**Example: price parser**

```python
# crawler/normalize/amazon_normalizers.py

import re
from typing import Any

def normalize_price(price_str: str) -> dict[str, Any]:
    """
    Parse "$19.99" → {"final_price": 19.99, "currency": "USD"}
    """
    if not price_str:
        return {}

    match = re.match(r"([€$£¥])\s*([\d,]+\.?\d*)", price_str.strip())
    if not match:
        return {"price_raw": price_str}

    symbol, amount = match.groups()
    currency_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "CNY"}

    return {
        "final_price": float(amount.replace(",", "")),
        "currency": currency_map.get(symbol, symbol),
    }

def normalize_rating(rating_str: str) -> float | None:
    """
    Parse "4.5 out of 5 stars" → 4.5
    """
    if not rating_str:
        return None
    match = re.search(r"(\d+\.?\d*)\s*out of", rating_str)
    return float(match.group(1)) if match else None
```

### Step 4: Add Enrich field groups

**File:** `crawler/enrich/schemas/amazon_field_groups.py`

**Add a `FieldGroupSpec`:**

```python
from .field_group_registry import FieldGroupSpec, OutputField

_products_my_new_group = FieldGroupSpec(
    name="products_my_new_group",
    description="Purpose of this field group",
    platform="amazon",
    subdataset="products",
    required_input_fields=["title", "description"],
    output_fields=[
        OutputField("title_cleaned", "string", "Cleaned product title"),
        OutputField("price_tier", "string", "Price tier: budget/mid/premium/luxury"),
    ],
    prompt_template="my_new_group",
    model_preference="fast",
)
```

**Prompt template:**

```
# crawler/enrich/generative/prompt_templates/my_new_group.txt

Based on the product information below, extract:
1. title_cleaned: The product title without keyword stuffing
2. price_tier: Classify as budget/mid/premium/luxury based on price

Product Title: {{title}}
Price: {{final_price}} {{currency}}

Respond in JSON format.
```

### Step 5: Register in the module export list

**File:** `crawler/enrich/schemas/amazon_field_groups.py` (bottom)

```python
AMAZON_PRODUCTS_FIELD_GROUPS = [
    _products_identity,
    _products_pricing,
    _products_my_new_group,
    # ...
]
```

### Step 6: Validate

```bash
python scripts/schema_tools.py validate
```

There should be no `missing_field` issues.

---

## 4. Naming conventions

| Rule | Examples |
|------|----------|
| Use `snake_case` | `seller_name`, `best_sellers_rank` |
| Booleans: `is_` / `has_` prefix | `is_brand_official_store`, `has_video` |
| Arrays: plural names | `categories`, `images`, `bullet_points` |
| Scores: `_score` suffix | `listing_quality_score`, `deal_quality_score` |
| Structured blobs: `_structured` suffix | `features_structured`, `experience_structured` |
| Inferred values: `_inferred` suffix | `price_tier_inferred`, `lifecycle_stage_inferred` |

---

## 5. Quick reference (Amazon products)

| Category | Fields | Layer |
|----------|--------|-------|
| **Identity** | asin, marketplace, dedup_key, canonical_url, URL | Extract |
| **Title/Brand** | title, brand, seller_name, seller_id | Extract |
| **Title/Brand (LLM)** | title_cleaned, brand_standardized | Enrich |
| **Pricing** | initial_price, final_price, currency, discount | Normalize |
| **Pricing (LLM)** | price_tier, deal_quality_score | Enrich |
| **Description** | description, bullet_points, features | Extract |
| **Description (LLM)** | features_structured, use_cases_extracted | Enrich |
| **Category** | categories, breadcrumbs, category_tree | Extract |
| **Category (LLM)** | category_standardized, niche_tags | Enrich |
| **Visual** | images, main_image, image_count | Extract |
| **Visual (LLM)** | main_image_analysis, visual_quality_score | Enrich (multimodal) |
| **Reviews** | rating, reviews_count | Extract → Normalize |
| **Reviews (LLM)** | recent_rating_signal, review_pattern_risk_indicators | Enrich |
| **Summary** | buyer_quick_take, product_elevator_pitch | Enrich |

---

## 6. FAQ

### Q: Schema name differs from code — what now?

A: Add alias resolution in `FIELD_RESOLVERS` inside `schema_contract.py`:

```python
FIELD_RESOLVERS = {
    "categories": lambda r: _first(
        r.get("categories"),
        r.get("category"),
        _structured(r).get("categories"),
    ),
}
```

### Q: How do I test extraction for one field?

```bash
export PYTHONPATH=.
python -c "
from crawler.extract.structured.json_extractor import JsonExtractor

html = open('test_page.html').read()
extractor = JsonExtractor()
result = extractor.extract_from_html(
    html=html,
    platform='amazon',
    resource_type='product',
    url='https://www.amazon.com/dp/B0EXAMPLE'
)
print(result.platform_fields)
"
```

### Q: How do I list all fields for a platform?

```bash
jq '.properties | keys | length' crawler/enrich/schema\(1\)/amazon_products.schema.json

grep -o 'OutputField("[^"]*"' crawler/enrich/schemas/amazon_field_groups.py | wc -l
```

---

## 7. Reference files

| File | Purpose |
|------|---------|
| `schema(1)/Dataset_Product_Catalog_v3.md` | Human-readable product spec |
| `schema(1)/*.schema.json` | Authoritative machine-readable JSON Schema |
| `scripts/schema_tools.py` | Validation tooling |
| `docs/schema-coverage-gap.md` | Coverage gap analysis |
| `docs/schema-coverage-report.json` | Detailed coverage report |
| `references/field_mappings.json` | Field alias map |

---

## 8. Prioritization

1. **Required fields**: asin, dedup_key, canonical_url, title
2. **Identity (high)**: seller_id, marketplace, URL
3. **Core (medium)**: price, rating, categories, images
4. **Enhanced (lower)**: LLM-backed fields
5. **Multimodal (last)**: image-analysis fields

---

*Last updated: 2026-04-02*
