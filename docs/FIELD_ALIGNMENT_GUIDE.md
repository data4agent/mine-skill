# 字段对齐指南 (Field Alignment Guide)

本文档说明如何将 Mine 爬虫输出与 `schema(1)/*.schema.json` 对齐。

---

## 1. 理解字段来源

每个 schema 字段来自三个层之一:

| 层 | 文件位置 | 字段类型 | 示例 |
|---|---------|---------|------|
| **Extract** | `crawler/extract/structured/json_extractor.py` | 从HTML直接提取 | title, brand, price, images |
| **Normalize** | `crawler/normalize/` (待完善) | 类型转换/标准化 | rating: "4.5 out of 5" → 4.5 |
| **Enrich** | `crawler/enrich/schemas/*_field_groups.py` | LLM增强 | title_cleaned, buyer_quick_take |

---

## 2. 查看当前覆盖状态

### 方法1: 运行验证工具

```bash
cd mine
export PYTHONPATH=.
python scripts/schema_tools.py validate
```

输出示例:
```json
[
  {"schema": "amazon_products", "category": "missing_field", "detail": "products_identity -> seller_id"}
]
```

### 方法2: 查看覆盖报告

```bash
cat docs/schema-coverage-report.json | python -m json.tool
```

### 方法3: 对比 schema 和 field_groups

```bash
# 查看 schema 定义的所有字段
cat crawler/enrich/schema\(1\)/amazon_products.schema.json | jq '.properties | keys'

# 查看 field_groups 输出的字段
grep -A20 "output_fields" crawler/enrich/schemas/amazon_field_groups.py
```

---

## 3. 对齐步骤

### Step 1: 确定字段属于哪一层

```
问: 这个字段能从HTML直接提取吗?
    ├─ Yes → Extract 层
    │       例: asin, title, price, images
    │
    └─ No → 需要推理/分析吗?
            ├─ Yes → Enrich 层 (需要LLM)
            │       例: title_cleaned, buyer_quick_take, price_tier
            │
            └─ No → Normalize 层 (类型转换)
                    例: "$19.99" → {final_price: 19.99, currency: "USD"}
```

### Step 2: 添加 Extract 字段

**文件:** `crawler/extract/structured/json_extractor.py`

**找到对应平台的提取方法:**
- Amazon: `_extract_amazon_product_html()`
- Wikipedia: 相应方法
- arXiv: 相应方法

**添加新字段:**

```python
# 示例: 添加 seller_id 字段
def _extract_amazon_product_html(self, soup, canonical_url):
    # ... 现有代码 ...
    
    # 新增: 提取 seller_id
    merchant_info = soup.select_one("#merchant-info a[href*='seller=']")
    if merchant_info:
        href = merchant_info.get("href", "")
        match = re.search(r"seller=([A-Z0-9]+)", href)
        if match:
            set_field("seller_id", match.group(1), "amazon_html:merchant_info_href")
```

### Step 3: 添加 Normalize 字段

**文件:** `crawler/normalize/` (需要创建)

**示例: 创建价格解析器**

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
    
    # 匹配货币符号和数字
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

### Step 4: 添加 Enrich 字段

**文件:** `crawler/enrich/schemas/amazon_field_groups.py`

**添加新 FieldGroupSpec:**

```python
from .field_group_registry import FieldGroupSpec, OutputField

_products_my_new_group = FieldGroupSpec(
    name="products_my_new_group",
    description="描述这个字段组的用途",
    platform="amazon",
    subdataset="products",
    required_input_fields=["title", "description"],  # 需要哪些输入
    output_fields=[
        OutputField("title_cleaned", "string", "清理后的标题"),
        OutputField("price_tier", "string", "价格档次: budget/mid/premium/luxury"),
    ],
    prompt_template="my_new_group",  # 对应 prompt_templates/ 下的模板
    model_preference="fast",
)
```

**创建 Prompt 模板:**

```
# crawler/enrich/generative/prompt_templates/my_new_group.txt

Based on the product information below, extract:
1. title_cleaned: The product title without keyword stuffing
2. price_tier: Classify as budget/mid/premium/luxury based on price

Product Title: {{title}}
Price: {{final_price}} {{currency}}

Respond in JSON format.
```

### Step 5: 注册到 Registry

**文件:** `crawler/enrich/schemas/amazon_field_groups.py` 底部

```python
# 添加到导出列表
AMAZON_PRODUCTS_FIELD_GROUPS = [
    _products_identity,
    _products_pricing,
    _products_my_new_group,  # 新增
    # ...
]
```

### Step 6: 验证对齐

```bash
python scripts/schema_tools.py validate
```

确保没有 `missing_field` 错误。

---

## 4. 字段命名规范

| 规则 | 示例 |
|-----|------|
| 使用 snake_case | `seller_name`, `best_sellers_rank` |
| 布尔字段用 `is_` 或 `has_` 前缀 | `is_brand_official_store`, `has_video` |
| 数组字段用复数 | `categories`, `images`, `bullet_points` |
| 分数/评分字段以 `_score` 结尾 | `listing_quality_score`, `deal_quality_score` |
| 结构化字段以 `_structured` 结尾 | `features_structured`, `experience_structured` |
| 推断字段以 `_inferred` 结尾 | `price_tier_inferred`, `lifecycle_stage_inferred` |

---

## 5. 字段分类速查

### Amazon Products

| 分类 | 字段 | 层 |
|-----|------|---|
| **Identity** | asin, marketplace, dedup_key, canonical_url, URL | Extract |
| **Title/Brand** | title, brand, seller_name, seller_id | Extract |
| **Title/Brand Enhanced** | title_cleaned, brand_standardized | Enrich |
| **Pricing** | initial_price, final_price, currency, discount | Normalize |
| **Pricing Enhanced** | price_tier, deal_quality_score | Enrich |
| **Description** | description, bullet_points, features | Extract |
| **Description Enhanced** | features_structured, use_cases_extracted | Enrich |
| **Category** | categories, breadcrumbs, category_tree | Extract |
| **Category Enhanced** | category_standardized, niche_tags | Enrich |
| **Visual** | images, main_image, image_count | Extract |
| **Visual Enhanced** | main_image_analysis, visual_quality_score | Enrich (Multimodal) |
| **Reviews** | rating, reviews_count | Extract → Normalize |
| **Reviews Enhanced** | recent_rating_signal, review_pattern_risk_indicators | Enrich |
| **Summary** | buyer_quick_take, product_elevator_pitch | Enrich |

---

## 6. 常见问题

### Q: 字段名在 schema 和代码里不一致怎么办?

A: 在 `schema_contract.py` 的 `FIELD_RESOLVERS` 添加别名解析:

```python
FIELD_RESOLVERS = {
    "categories": lambda r: _first(
        r.get("categories"),
        r.get("category"),  # 别名
        _structured(r).get("categories"),
    ),
}
```

### Q: 如何测试单个字段的提取?

```bash
export PYTHONPATH=.
python -c "
from crawler.extract.structured.json_extractor import JsonExtractor
from bs4 import BeautifulSoup

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

### Q: 如何查看某平台的所有字段?

```bash
# Schema 定义的字段
jq '.properties | keys | length' crawler/enrich/schema\(1\)/amazon_products.schema.json

# Field groups 输出的字段
grep -o 'OutputField("[^"]*"' crawler/enrich/schemas/amazon_field_groups.py | wc -l
```

---

## 7. 参考文件

| 文件 | 用途 |
|-----|------|
| `schema(1)/Dataset_Product_Catalog_v3.md` | 产品规范 (人类可读) |
| `schema(1)/*.schema.json` | 技术规范 (JSON Schema) |
| `scripts/schema_tools.py` | 验证工具 |
| `docs/schema-coverage-gap.md` | 覆盖差距分析 |
| `docs/schema-coverage-report.json` | 详细覆盖报告 |
| `references/field_mappings.json` | 字段别名映射 |

---

## 8. 对齐工作优先级

1. **Required 字段** (必须): asin, dedup_key, canonical_url, title
2. **Identity 字段** (高优先): seller_id, marketplace, URL
3. **Core 字段** (中优先): price, rating, categories, images
4. **Enhanced 字段** (低优先): LLM增强字段
5. **Multimodal 字段** (最后): 图像分析字段

---

*最后更新: 2026-04-02*
