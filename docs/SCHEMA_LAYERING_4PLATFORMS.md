# 4-Platform Schema Layering

This document defines field ownership for the authoritative `mine/schema(1)` contracts.

## Authority

- Source of truth: `mine/schema(1)`
- Mirrored reference only: `mine/crawler/enrich/schema(1)`

## Layering Rules

1. Use `extract` when the source page or API already exposes the field with acceptable fidelity.
2. Use `normalize` when the field is a typed, canonical, or alias-resolved form of already extracted data.
3. Use `LLM enrich` only when the field requires inference, synthesis, summarization, categorization, or cross-field reasoning.

## Wikipedia

- `extract`
  - `page_id`, `title`, `article_creation_date`, `protection_level`, `raw_text`, `HTML`
  - `categories`, `references_count`, `external_links_count`, `references`, `see_also`, `images`
  - `wikidata_id`, `cross_language_links`, `entity_name_translations`
- `normalize`
  - `dedup_key`, `canonical_url`, `URL`, `language`
  - `word_count`, `number_of_sections`, `has_infobox`, `infobox_raw`, `infobox_structured`
  - `title_disambiguated`, `canonical_entity_name`, `sections_structured`, `table_of_contents`
  - `article_summary`, `tables_structured`, `categories_cleaned`, `domain`, `topic_hierarchy`, `subject_tags`
  - `external_links_classified`, `citation_density`, `last_major_edit`, `article_quality_class`
- `LLM enrich`
  - `entity_type`, `reading_level`, `entities_extracted`, `structured_facts`, `temporal_events`, `related_entities`
  - `neutrality_score`, `edit_controversy_score`, `translation_coverage_score`
  - embeddings, image annotations, multi-level summaries, educational fields, bias/freshness fields
  - `linkable_identifiers`, contradiction/completeness/diversity maps

## arXiv

- `extract`
  - `arxiv_id`, `DOI`, `title`, `abstract`, `authors`, `categories`, `primary_category`
  - `submission_date`, `update_date`, `versions`, `submission_comments`, `journal_ref`, `license`, `PDF_url`
- `normalize`
  - `dedup_key`, `canonical_url`, `URL`, `num_authors`, `raw_text`, `page_count`, `num_figures`
  - `title_normalized`, `abstract_plain_text`, `authors_structured`
  - `topic_hierarchy`, `research_area_plain_english`, `sections_structured`
  - `references`, `references_structured`, `code_available`, `code_url`, `dataset_released`, `dataset_url`
  - `open_access_status`, `linkable_identifiers`, `total_citation_count`, `influential_citation_count`
- `LLM enrich`
  - `keywords_extracted`, `interdisciplinary_score`, `venue_mentioned`, `venue_published`, `venue_tier_mapped`, `venue_tier`
  - `acceptance_status_inferred`, contributions, methods, results, limitations, reproducibility, follow-up questions
  - embeddings, relation graph, figure/equation interpretation, multi-level summaries

## Amazon

- `extract`
  - `asin`, `review_id`, `seller_id`, `seller_name`, `canonical_url`, `URL`, `dedup_key`
  - `title`, `brand`, `images`, `main_image`, `description`, `bullet_points`, `features`
  - `categories`, `breadcrumbs`, `category_tree`, `best_sellers_rank`, `sales_volume_hint`
  - `variant_purchased`, `review_images`, `seller_response`
- `normalize`
  - `marketplace`, `initial_price`, `final_price`, `currency`, `discount`
  - `rating`, `reviews_count`, `helpful_count`, `verified_purchase`, `date_posted`
  - `estimated_monthly_sales`, `stock_status`, `fulfillment_type`
- `LLM enrich`
  - title/brand cleaning, pricing tiers, listing quality, review analysis, seller business intelligence
  - cross-dataset linkable identifiers and multimodal fields

## LinkedIn

- `extract`
  - identity and raw profile/company/job/post facts from voyager/html payloads
  - examples: `linkedin_num_id`, `company_id`, `job_posting_id`, `post_id`, `name`, `headline`, `about`, `website`
  - company factual fields such as `employees_in_linkedin`, `founded_year`, `top_topics`, `funding_stage_inferred`
  - profile factual fields such as `city`, `country_code`, `avatar`, `profile_url_custom`
- `normalize`
  - `dedup_key`, `canonical_url`, `URL`
  - canonical alias bridging such as `employees_in_linkedin` vs old `employee_count`
  - `remote_policy_detail`, typed counts, normalized URLs
- `LLM enrich`
  - profile analytics, company narrative/intelligence, job candidate view and risk analysis, post discourse analysis
  - any field requiring synthesis or inference rather than direct source extraction

## Immediate Priorities

1. Keep `schema(1)` authority singular and mirrored.
2. Prefer top-level normalized values over raw `structured` values during export.
3. Expand direct extraction first for high-confidence LinkedIn profile/company fields.
4. Keep enriching only the genuinely inferential fields.
