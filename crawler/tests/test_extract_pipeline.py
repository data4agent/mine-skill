"""Tests for the Layer 2 Extract Pipeline."""
from __future__ import annotations

import json
from pathlib import Path

from crawler.extract.content_cleaner import ContentCleaner
from crawler.extract.crawl4ai_extract import Crawl4AIExtractionResult
from crawler.extract.main_content import MainContentExtractor
from crawler.extract.chunking.hybrid_chunker import HybridChunker, _estimate_tokens
from crawler.extract.structured.json_extractor import JsonExtractor
from crawler.extract.pipeline import ExtractPipeline
from crawler.extract.models import MainContent, ContentSection


# ---------------------------------------------------------------------------
# ContentCleaner tests
# ---------------------------------------------------------------------------


def test_cleaner_removes_script_and_style_tags() -> None:
    html = """
    <html><body>
      <script>alert('x')</script>
      <style>.foo{color:red}</style>
      <p>Real content here</p>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "<script>" not in result.html
    assert "<style>" not in result.html
    assert "Real content here" in result.html
    assert result.noise_removed >= 2


def test_cleaner_removes_nav_footer_aside() -> None:
    html = """
    <html><body>
      <nav>Menu stuff</nav>
      <main><p>Main content</p></main>
      <footer>Footer stuff</footer>
      <aside>Sidebar</aside>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "Menu stuff" not in result.html
    assert "Footer stuff" not in result.html
    assert "Sidebar" not in result.html
    assert "Main content" in result.html


def test_cleaner_removes_noise_class_patterns() -> None:
    html = """
    <html><body>
      <div class="ad-banner">Ad here</div>
      <div class="sidebar-widget">Widget</div>
      <p>Article text</p>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "Ad here" not in result.html
    assert "Article text" in result.html


def test_cleaner_removes_hidden_elements() -> None:
    html = """
    <html><body>
      <div hidden>Hidden div</div>
      <div style="display: none">Invisible div</div>
      <p>Visible content</p>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "Hidden div" not in result.html
    assert "Invisible div" not in result.html
    assert "Visible content" in result.html


def test_cleaner_preserves_main_content_under_malformed_hidden_void() -> None:
    """模拟畸形 DOM：正文被挂在 display:none 的 img 下；整棵删除会导致正文为空。"""
    html = """
    <html><body>
      <img style="display:none" src="https://example.com/x.png" alt="">
        <div id="dp-container">
          <h1><span id="productTitle">Apple iPad Test Product Title</span></h1>
          <p>This is a long product description that definitely exceeds the eighty character threshold for substantial hidden text preservation logic.</p>
        </div>
      </img>
      <p>Outside</p>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "dp-container" in result.html
    assert "productTitle" in result.html
    assert "eighty character" in result.html
    assert "Outside" in result.html


def test_cleaner_removes_long_hidden_modal_content() -> None:
    html = """
    <html><body>
      <div style="display:none">
        <div class="details-panel">
          This hidden modal contains a lot of text that should stay hidden from
          extracted plain text even though it is long and uses block layout.
        </div>
      </div>
      <main><p>Visible product content</p></main>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "should stay hidden" not in result.html
    assert "Visible product content" in result.html


def test_cleaner_handles_decomposed_nested_noise_nodes() -> None:
    html = """
    <html><body>
      <div class="sidebar">
        <span>Nested noise</span>
      </div>
      <p>Visible content</p>
    </body></html>
    """
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert "Nested noise" not in result.html
    assert "Visible content" in result.html


def test_cleaner_uses_platform_selectors(monkeypatch) -> None:
    html = """
    <html><body>
      <div class="global-nav">LinkedIn Nav</div>
      <p>Profile content</p>
    </body></html>
    """
    monkeypatch.setattr(
        "crawler.extract.content_cleaner._platform_selectors_cache",
        {"linkedin": [".global-nav"]},
    )
    cleaner = ContentCleaner()
    result = cleaner.clean(html, platform="linkedin")
    assert "LinkedIn Nav" not in result.html
    assert "Profile content" in result.html


def test_cleaner_tracks_original_and_cleaned_size() -> None:
    html = "<html><body><script>x</script><p>Text</p></body></html>"
    cleaner = ContentCleaner()
    result = cleaner.clean(html)
    assert result.original_size == len(html)
    assert result.cleaned_size < result.original_size


# ---------------------------------------------------------------------------
# MainContentExtractor tests
# ---------------------------------------------------------------------------


def test_main_extractor_finds_article_tag() -> None:
    from bs4 import BeautifulSoup

    html = """
    <html><body>
      <div id="wrapper">
        <article>
          <h1>Article Title</h1>
          <p>Article paragraph with enough text to pass the 50 char threshold for semantic detection.</p>
        </article>
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    extractor = MainContentExtractor()
    result = extractor.extract(soup)
    assert "Article Title" in result.text
    assert "semantic:article" == result.selector_used


def test_main_extractor_falls_back_to_density() -> None:
    from bs4 import BeautifulSoup

    html = """
    <html><body>
      <div id="content">
        <p>This is a longer paragraph with sufficient content for density analysis.
        It contains multiple sentences that should give it a high density score
        compared to other elements on the page. The density algorithm looks at
        the ratio of text to HTML markup.</p>
      </div>
      <div id="small"><span>x</span></div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    extractor = MainContentExtractor()
    result = extractor.extract(soup)
    assert "density" in result.selector_used or "fallback" in result.selector_used


def test_main_extractor_uses_platform_selector(monkeypatch) -> None:
    from bs4 import BeautifulSoup

    monkeypatch.setattr(
        "crawler.extract.main_content._main_content_selectors_cache",
        {"wikipedia": {"article": "#mw-content-text"}},
    )
    html = """
    <html><body>
      <div id="mw-content-text">
        <p>Wikipedia article content here.</p>
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    extractor = MainContentExtractor()
    result = extractor.extract(soup, platform="wikipedia", resource_type="article")
    assert "Wikipedia article content" in result.text
    assert "platform:" in result.selector_used


def test_main_extractor_extracts_sections_from_headings() -> None:
    from bs4 import BeautifulSoup

    html = """
    <html><body>
      <article>
        <h1>Main Title</h1>
        <p>Intro paragraph with enough text content here to be meaningful.</p>
        <h2>Section One</h2>
        <p>Content for section one.</p>
        <h2>Section Two</h2>
        <p>Content for section two.</p>
        <h3>Subsection 2.1</h3>
        <p>Nested content.</p>
      </article>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    extractor = MainContentExtractor()
    result = extractor.extract(soup)
    assert len(result.sections) >= 3
    # Check section_path hierarchy: h1 > h2 > h3 gives 3-level path
    sub_sections = [s for s in result.sections if s.heading_level == 3]
    if sub_sections:
        assert len(sub_sections[0].section_path) == 3
        assert sub_sections[0].section_path[-1] == "Subsection 2.1"


# ---------------------------------------------------------------------------
# HybridChunker tests
# ---------------------------------------------------------------------------


def test_estimate_tokens_basic() -> None:
    assert _estimate_tokens("hello world") == 2
    assert _estimate_tokens("") == 0


def test_chunker_small_section_single_chunk() -> None:
    sections = [
        ContentSection(
            heading_text="Title",
            heading_level=1,
            section_path=["Title"],
            html="<h1>Title</h1><p>Short text</p>",
            text="Short text",
            markdown="# Title\n\nShort text",
            char_offset_start=0,
            char_offset_end=10,
        )
    ]
    main = MainContent(
        html="<h1>Title</h1><p>Short text</p>",
        text="Short text",
        markdown="# Title\n\nShort text",
        sections=sections,
        selector_used="test",
    )
    chunker = HybridChunker(max_chunk_tokens=512)
    chunks = chunker.chunk(main, doc_id="test-doc")
    assert len(chunks) == 1
    assert chunks[0].section_path == ["Title"]
    assert chunks[0].chunk_id == "test-doc#chunk_0"


def test_chunker_large_section_splits() -> None:
    # Create a section with 1000+ tokens
    long_text = " ".join(f"word{i}" for i in range(600))
    sections = [
        ContentSection(
            heading_text="Big Section",
            heading_level=1,
            section_path=["Big Section"],
            html=f"<p>{long_text}</p>",
            text=long_text,
            markdown=long_text,
            char_offset_start=0,
            char_offset_end=len(long_text),
        )
    ]
    main = MainContent(
        html=f"<p>{long_text}</p>",
        text=long_text,
        markdown=long_text,
        sections=sections,
        selector_used="test",
    )
    chunker = HybridChunker(max_chunk_tokens=200, min_chunk_tokens=50)
    chunks = chunker.chunk(main, doc_id="test-doc")
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.section_path == ["Big Section"]
        assert chunk.token_count_estimate > 0


def test_chunker_preserves_section_path() -> None:
    sections = [
        ContentSection(
            heading_text="A",
            heading_level=1,
            section_path=["A"],
            html="", text="Content A", markdown="Content A",
            char_offset_start=0, char_offset_end=9,
        ),
        ContentSection(
            heading_text="B",
            heading_level=2,
            section_path=["A", "B"],
            html="", text="Content B", markdown="Content B",
            char_offset_start=10, char_offset_end=19,
        ),
    ]
    main = MainContent(
        html="", text="Content A\nContent B", markdown="Content A\nContent B",
        sections=sections, selector_used="test",
    )
    chunker = HybridChunker()
    chunks = chunker.chunk(main, doc_id="doc1")
    assert chunks[0].section_path == ["A"]
    assert chunks[1].section_path == ["A", "B"]


def test_chunker_empty_content_returns_empty() -> None:
    main = MainContent(html="", text="", markdown="", sections=[], selector_used="test")
    chunker = HybridChunker()
    chunks = chunker.chunk(main, doc_id="empty")
    assert chunks == []


# ---------------------------------------------------------------------------
# JsonExtractor tests
# ---------------------------------------------------------------------------


def test_json_extractor_linkedin_profile() -> None:
    data = {
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                "firstName": "John",
                "lastName": "Doe",
                "headline": "Software Engineer",
                "publicIdentifier": "johndoe",
                "entityUrn": "urn:li:fsd_profile:123",
            }
        ]
    }
    extractor = JsonExtractor()
    result = extractor.extract_from_json(data, "linkedin", "profile", "https://linkedin.com/in/johndoe")
    assert result.title == "John Doe"
    assert result.description == "Software Engineer"
    assert result.platform_fields["public_identifier"] == "johndoe"
    assert result.field_sources["title"] == "api_json:voyager"


def test_json_extractor_linkedin_company() -> None:
    data = {
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.organization.Company",
                "name": "Acme Inc",
                "description": "We build stuff",
                "universalName": "acme-inc",
                "staffCount": 500,
                "industries": ["Technology"],
            }
        ]
    }
    extractor = JsonExtractor()
    result = extractor.extract_from_json(data, "linkedin", "company", "https://linkedin.com/company/acme-inc")
    assert result.title == "Acme Inc"
    assert result.description == "We build stuff"
    assert result.platform_fields["staff_count"] == 500


def test_json_extractor_generic_json() -> None:
    data = {"title": "Test Item", "description": "A test description", "extra": "value"}
    extractor = JsonExtractor()
    result = extractor.extract_from_json(data, "custom", "item", "https://example.com/item/1")
    assert result.title == "Test Item"
    assert result.description == "A test description"


def test_json_extractor_html_meta() -> None:
    html = """
    <html>
      <head>
        <title>Page Title</title>
        <meta property="og:title" content="OG Title">
        <meta property="og:description" content="OG Desc">
        <meta property="og:image" content="/img.png">
        <link rel="canonical" href="https://example.com/canonical">
      </head>
      <body></body>
    </html>
    """
    extractor = JsonExtractor()
    result = extractor.extract_from_html(html, "test", "page", "https://example.com/page")
    assert result.title == "OG Title"
    assert result.description == "OG Desc"
    assert result.canonical_url == "https://example.com/canonical"
    assert result.field_sources["title"] == "html_meta:og:title"


# ---------------------------------------------------------------------------
# ExtractPipeline integration tests
# ---------------------------------------------------------------------------


def test_pipeline_html_extraction_prefers_crawl4ai_adapter(monkeypatch) -> None:
    fetch_result = {
        "url": "https://example.com/post",
        "text": "<html><body><article><h1>Primary Title</h1><p>Primary body text.</p></article></body></html>",
        "content_type": "text/html",
    }

    monkeypatch.setattr(
        "crawler.extract.pipeline.extract_html_with_crawl4ai",
        lambda html, url, platform="", resource_type="": Crawl4AIExtractionResult(
            html="<article><h1>Primary Title</h1><p>Primary body text.</p></article>",
            cleaned_html="<article><h1>Primary Title</h1><p>Primary body text.</p></article>",
            markdown="# Primary Title\n\nPrimary body text.",
            text="Primary Title\nPrimary body text.",
            selector_used="crawl4ai:fit_html",
            extractor="crawl4ai",
        ),
    )

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "generic", "page")

    assert "Primary Title" in doc.full_text
    assert "Primary body text." in doc.full_text
    assert doc.quality.chunking_strategy == "hybrid:crawl4ai:fit_html"
    assert "<article>" in doc.cleaned_html


def test_pipeline_html_extraction() -> None:
    fetch_result = {
        "url": "https://en.wikipedia.org/wiki/Python",
        "text": """
        <html>
          <head>
            <title>Python - Wikipedia</title>
            <meta name="description" content="Python is a programming language">
          </head>
          <body>
            <nav>Navigation menu</nav>
            <article>
              <h1>Python (programming language)</h1>
              <p>Python is a high-level, general-purpose programming language.
              Its design philosophy emphasizes code readability with the use of
              significant indentation.</p>
              <h2>History</h2>
              <p>Python was conceived in the late 1980s by Guido van Rossum
              at Centrum Wiskunde &amp; Informatica in the Netherlands.</p>
              <h2>Features</h2>
              <p>Python is dynamically typed and garbage-collected. It supports
              multiple programming paradigms.</p>
            </article>
            <footer>Footer content</footer>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "wikipedia", "article")

    assert doc.platform == "wikipedia"
    assert doc.resource_type == "article"
    assert doc.source_url == "https://en.wikipedia.org/wiki/Python"
    assert "Python" in doc.full_text
    assert doc.total_chunks == len(doc.chunks)
    assert doc.total_chunks > 0
    assert doc.quality.noise_removed > 0
    assert doc.structured.title is not None
    # Check chunks have section paths
    for chunk in doc.chunks:
        assert chunk.chunk_id.startswith(doc.doc_id)
        assert chunk.token_count_estimate > 0


def test_pipeline_json_extraction() -> None:
    fetch_result = {
        "url": "https://www.linkedin.com/in/johndoe",
        "json_data": {
            "included": [
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                    "firstName": "John",
                    "lastName": "Doe",
                    "headline": "Software Engineer at BigCo",
                    "publicIdentifier": "johndoe",
                    "entityUrn": "urn:li:fsd_profile:abc123",
                }
            ]
        },
        "content_type": "application/json",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "linkedin", "profile")

    assert doc.platform == "linkedin"
    assert doc.structured.title == "John Doe"
    assert doc.structured.description == "Software Engineer at BigCo"
    assert doc.total_chunks > 0
    assert doc.quality.chunking_strategy == "json_structured"


def test_pipeline_json_extraction_wikipedia_has_title_text_markdown_and_structure() -> None:
    fetch_result = {
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "json_data": {
            "query": {
                "pages": {
                    "1164": {
                        "title": "Artificial intelligence",
                        "extract": "Artificial intelligence is the capability of computational systems to perform tasks associated with human intelligence.",
                        "categories": [
                            {"title": "Category:Artificial intelligence"},
                            {"title": "Category:Computer science"},
                        ],
                        "pageprops": {"wikibase-shortdesc": "Intelligence of machines"},
                    }
                }
            }
        },
        "content_type": "application/json",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "wikipedia", "article")

    assert doc.structured.title == "Artificial intelligence"
    assert "computational systems" in doc.full_text
    assert doc.full_markdown.startswith("# Artificial intelligence")
    assert doc.structured.platform_fields["categories"] == ["Artificial intelligence", "Computer science"]


def test_pipeline_json_extraction_base_has_meaningful_output() -> None:
    fetch_result = {
        "url": "https://basescan.org/address/0x4200000000000000000000000000000000000006",
        "json_data": {
            "jsonrpc": "2.0",
            "result": "0x360fe4a3fc66beffcabd",
            "id": 1,
        },
        "content_type": "application/json",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "base", "address")

    assert doc.structured.title == "address"
    assert "0x360fe4a3fc66beffcabd" in doc.full_text
    assert "```json" in doc.full_markdown
    assert doc.structured.platform_fields["rpc_result"] == "0x360fe4a3fc66beffcabd"


def test_pipeline_xml_extraction_arxiv_skips_crawl4ai_and_parses_atom(monkeypatch) -> None:
    fetch_result = {
        "url": "https://arxiv.org/abs/2303.08774",
        "text": """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2303.08774v6</id>
    <title>GPT-4 Technical Report</title>
    <updated>2024-03-04T06:01:33Z</updated>
    <published>2023-03-15T17:15:04Z</published>
    <summary>We report the development of GPT-4, a large-scale, multimodal model.</summary>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="cs.CL"/>
    <author><name>OpenAI</name></author>
    <author><name>Josh Achiam</name></author>
    <link href="https://arxiv.org/abs/2303.08774v6" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2303.08774v6" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>
""",
        "content_type": "application/atom+xml; charset=utf-8",
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("crawl4ai should not be called for arxiv atom xml")

    monkeypatch.setattr(
        "crawler.extract.pipeline.extract_html_with_crawl4ai",
        fail_if_called,
    )
    monkeypatch.setattr(
        "crawler.extract.pipeline.fetch_binary_content",
        lambda url: b"%PDF-1.4 fake",
    )
    monkeypatch.setattr(
        "crawler.extract.pipeline.extract_pdf_with_pymupdf4llm",
        lambda source, *, title=None: {
            "markdown": "# GPT-4 Technical Report\n\nFull paper body.\n\n## References\n\n[1] Ref A",
            "plain_text": "GPT-4 Technical Report\n\nFull paper body.\n\nReferences\n\n[1] Ref A",
            "document_blocks": [{"type": "section", "text": "Full paper body."}],
            "extractor": "pymupdf4llm",
            "page_count": 12,
            "parser_metadata": {"parser": "pymupdf4llm"},
        },
    )

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "arxiv", "paper")

    assert doc.structured.title == "GPT-4 Technical Report"
    assert doc.structured.description == "We report the development of GPT-4, a large-scale, multimodal model."
    assert "GPT-4 Technical Report" in doc.full_markdown
    assert "Full paper body." in doc.full_text
    assert doc.structured.platform_fields["authors"] == ["OpenAI", "Josh Achiam"]
    assert doc.structured.platform_fields["categories"] == ["cs.CL", "cs.AI"]
    assert doc.structured.platform_fields["primary_category"] == "cs.CL"
    assert doc.structured.platform_fields["published"] == "2023-03-15T17:15:04Z"
    assert doc.structured.platform_fields["updated"] == "2024-03-04T06:01:33Z"
    assert doc.structured.platform_fields["pdf_url"] == "https://arxiv.org/pdf/2303.08774v6"
    assert doc.structured.platform_fields["pdf_extractor"] == "pymupdf4llm"
    assert doc.structured.platform_fields["page_count"] == 12
    assert doc.structured.platform_fields["references"] == ["[1] Ref A"]
    assert doc.quality.chunking_strategy == "xml_structured"


def test_pipeline_json_extraction_linkedin_company_uses_voyager_shape() -> None:
    fetch_result = {
        "url": "https://www.linkedin.com/company/openai/",
        "json_data": {
            "elements": [
                {
                    "$recipeType": "com.linkedin.voyager.deco.organization.web.WebFullCompanyMain",
                    "name": "OpenAI",
                    "description": "OpenAI is an AI research and deployment company.",
                    "entityUrn": "urn:li:fs_normalized_company:11130470",
                    "universalName": "openai",
                    "staffCount": 7722,
                    "companyIndustries": [{"localizedName": "软件开发"}],
                    "headquarter": {"city": "San Francisco"},
                    "followingInfo": {"followerCount": 10478857},
                    "companyPageUrl": "https://openai.com/",
                    "specialities": ["artificial intelligence", "machine learning"],
                }
            ]
        },
        "content_type": "application/json",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "linkedin", "company")

    assert doc.structured.title == "OpenAI"
    assert "AI research and deployment company" in doc.full_text
    assert doc.full_markdown.startswith("# OpenAI")
    assert doc.structured.platform_fields["company_slug"] == "openai"
    assert doc.structured.platform_fields["follower_count"] == 10478857


def test_pipeline_html_extraction_compacts_llm_ready_content() -> None:
    fetch_result = {
        "url": "https://example.com/post",
        "text": """
        <html>
          <body>
            <article>
              <h1>Intentional Systems</h1>
              <p>Sign in to keep reading</p>
              <p>Intentional systems are built around clear interfaces and strong feedback loops.</p>
              <p>Intentional systems are built around clear interfaces and strong feedback loops.</p>
              <p>Teams use them to reduce ambiguity and operational drift over time.</p>
              <ul>
                <li>Clear ownership</li>
                <li>Fast feedback</li>
              </ul>
              <p>Share this article</p>
              <p>All rights reserved</p>
            </article>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "test", "page")

    assert "Sign in to keep reading" not in doc.full_text
    assert "Share this article" not in doc.full_text
    assert "All rights reserved" not in doc.full_text
    assert doc.full_text.count("Intentional systems are built around clear interfaces and strong feedback loops.") == 1
    assert "# Intentional Systems" in doc.full_markdown
    assert "Clear ownership" in doc.full_markdown
    assert "Fast feedback" in doc.full_markdown
    assert doc.cleaned_html
    assert "Share this article" not in doc.cleaned_html
    assert "All rights reserved" not in doc.cleaned_html


def test_pipeline_html_extraction_applies_css_schema_when_configured(workspace_tmp_path: Path) -> None:
    schema_path = workspace_tmp_path / "css-schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "title": {"selector": ".hero-title"},
                "description": {"selector": ".hero-subtitle"},
                "fields": {
                    "price": {"selector": ".price"},
                    "features": {"selector": ".feature", "multiple": True},
                    "checkout_url": {"selector": ".cta", "attribute": "href"},
                },
            }
        ),
        encoding="utf-8",
    )
    fetch_result = {
        "url": "https://example.com/product",
        "text": """
        <html>
          <head>
            <title>Fallback Title</title>
            <meta name="description" content="Fallback description">
          </head>
          <body>
            <article>
              <h1 class="hero-title">Structured Product</h1>
              <p class="hero-subtitle">Made for deterministic extraction.</p>
              <div class="price">$19</div>
              <ul>
                <li class="feature">Fast setup</li>
                <li class="feature">Clear output</li>
              </ul>
              <a class="cta" href="/checkout">Buy now</a>
            </article>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline(css_schema_path=schema_path)
    doc = pipeline.extract(fetch_result, "test", "page")

    assert doc.structured.title == "Structured Product"
    assert doc.structured.description == "Made for deterministic extraction."
    assert doc.structured.platform_fields["price"] == "$19"
    assert doc.structured.platform_fields["features"] == ["Fast setup", "Clear output"]
    assert doc.structured.platform_fields["checkout_url"] == "https://example.com/checkout"


def test_pipeline_html_extraction_extracts_amazon_product_fields() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B000TEST",
        "text": """
        <html>
          <head>
            <title>Amazon.com: Example listing</title>
          </head>
          <body>
            <div id="dp">
              <span id="productTitle">Keychron K3 Wireless Keyboard</span>
              <a id="bylineInfo" href="/stores/Keychron/page/abc">Visit the Keychron Store</a>
              <div id="corePrice_feature_div">
                <span class="a-price">
                  <span class="a-offscreen">$99.99</span>
                </span>
              </div>
              <div id="availability_feature_div">
                <span class="a-color-success">In Stock</span>
              </div>
              <div id="averageCustomerReviews_feature_div">
                <span class="a-icon-alt">4.5 out of 5 stars</span>
                <span id="acrCustomerReviewText">1,234 ratings</span>
              </div>
              <div id="wayfinding-breadcrumbs_feature_div">
                <ul>
                  <li><span class="a-list-item"><a>Electronics</a></span></li>
                  <li><span class="a-list-item"><a>Keyboards</a></span></li>
                </ul>
              </div>
              <div id="feature-bullets">
                <ul>
                  <li><span class="a-list-item">Wireless</span></li>
                  <li><span class="a-list-item">Low-profile switches</span></li>
                </ul>
              </div>
              <div id="imgTagWrapperId">
                <img src="https://example.com/main.jpg" />
              </div>
              <div id="altImages">
                <img src="https://example.com/alt-1.jpg" />
                <img src="https://example.com/alt-2.jpg" />
              </div>
              <div id="merchant-info">Ships from Amazon.com Sold by Keychron</div>
            </div>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.title == "Keychron K3 Wireless Keyboard"
    assert doc.structured.platform_fields["brand"] == "Keychron"
    assert doc.structured.platform_fields["price"] == "$99.99"
    assert doc.structured.platform_fields["availability"] == "In Stock"
    assert doc.structured.platform_fields["rating"] == "4.5 out of 5 stars"
    assert doc.structured.platform_fields["reviews_count"] == "1,234 ratings"
    assert doc.structured.platform_fields["category"] == ["Electronics", "Keyboards"]
    assert doc.structured.platform_fields["bullet_points"] == ["Wireless", "Low-profile switches"]
    assert doc.structured.platform_fields["images"] == [
        "https://example.com/main.jpg",
        "https://example.com/alt-1.jpg",
        "https://example.com/alt-2.jpg",
    ]
    assert doc.structured.platform_fields["seller"] == "Ships from Amazon.com Sold by Keychron"


def test_pipeline_html_extraction_extracts_amazon_product_extended_fields() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B000TEST",
        "text": """
        <html>
          <body>
            <div id="productDescription">
              Compact 75% mechanical keyboard with Bluetooth and low-profile switches.
            </div>
            <div id="mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE">
              FREE delivery Tomorrow by Amazon
            </div>
            <div id="twister">
              <li data-defaultasin="B000TEST-BLACK"><img alt="Black" /></li>
              <li data-defaultasin="B000TEST-WHITE"><img alt="White" /></li>
            </div>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.description == "Compact 75% mechanical keyboard with Bluetooth and low-profile switches."
    assert doc.structured.platform_fields["fulfillment"] == "FREE delivery Tomorrow by Amazon"
    assert doc.structured.platform_fields["variants"] == [
        {"asin": "B000TEST-BLACK", "label": "Black"},
        {"asin": "B000TEST-WHITE", "label": "White"},
    ]


def test_pipeline_html_extraction_prefers_non_generic_amazon_description_and_out_of_stock_state() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B09V3KXJPB",
        "text": """
        <html>
          <head>
            <meta property="og:title" content="Amazon" />
            <meta property="og:description" content="Amazon" />
            <meta name="description" content="Buy Apple iPad Air: Cases - Amazon.com FREE DELIVERY possible on eligible purchases" />
            <meta name="title" content="Amazon.com: Apple iPad Air : Electronics" />
          </head>
          <body>
            <div id="buybox">
              <div id="outOfStock" class="a-box">
                <div class="a-box-inner">
                  <div class="a-section a-spacing-small a-text-center">
                    <span class="a-size-medium a-color-price a-text-bold">Currently unavailable.</span>
                    <br/>We don't know when or if this item will be back in stock.
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.description == "Buy Apple iPad Air: Cases - Amazon.com FREE DELIVERY possible on eligible purchases"
    assert doc.structured.platform_fields["availability"] == "Currently unavailable. We don't know when or if this item will be back in stock."
    assert doc.structured.platform_fields["category"] == ["Electronics"]


def test_pipeline_html_extraction_adds_amazon_product_fallbacks_for_unavailable_and_no_reviews() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B09V3KXJPB",
        "text": """
        <html>
          <body>
            <div id="buybox">
              <div id="outOfStock" class="a-box">
                <div class="a-box-inner">
                  <div class="a-section a-spacing-small a-text-center">
                    <span class="a-size-medium a-color-price a-text-bold">Currently unavailable.</span>
                    <br/>We don't know when or if this item will be back in stock.
                  </div>
                </div>
              </div>
            </div>
            <div class="ucc-v2-widget__table__col__container__reviews">
              <span class="a-size-base">No customer reviews yet</span>
            </div>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.platform_fields["fulfillment"] == "Currently unavailable. We don't know when or if this item will be back in stock."
    assert doc.structured.platform_fields["reviews_count"] == "0 reviews"
    assert doc.structured.platform_fields["rating"] == "No customer reviews yet"


def test_pipeline_html_extraction_extracts_amazon_product_price_from_embedded_json() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B000TEST",
        "text": """
        <html>
          <body>
            <script type="text/javascript">
              var obj = jQuery.parseJSON('{"priceToPay":{"price":"$99.99"}}');
            </script>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.platform_fields["price"] == "$99.99"


def test_pipeline_html_extraction_extracts_amazon_product_variants_from_embedded_json() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B000TEST",
        "text": """
        <html>
          <body>
            <script type="text/javascript">
              var obj = jQuery.parseJSON('{"colorToAsin":{"Black":{"asin":"B000TEST-BLACK"},"White":{"asin":"B000TEST-WHITE"}}}');
            </script>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.platform_fields["variants"] == [
        {"asin": "B000TEST-BLACK", "label": "Black"},
        {"asin": "B000TEST-WHITE", "label": "White"},
    ]


def test_pipeline_html_extraction_enriches_amazon_variants_with_twister_prices() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/dp/B000TEST",
        "text": """
        <html>
          <body>
            <script type="text/javascript">
              var obj = jQuery.parseJSON('{"colorToAsin":{"Black":{"asin":"B000TEST-BLACK"},"Red":{"asin":"B000TEST-RED"}}}');
            </script>
            <script type="application/json" data-amazon-twister-responses="true">
              [{"url":"https://www.amazon.com/gp/product/ajax/twisterDimensionSlotsDefault","body":"{\\"ASIN\\":\\"B000TEST-BLACK\\",\\"Type\\":\\"JSON\\",\\"Value\\":{\\"content\\":{\\"twisterSlotJson\\":{\\"isAvailable\\":true,\\"price\\":1592.14626},\\"twisterSlotDiv\\":\\"<div><span class=\\\\\\"a-price\\\\\\"><span class=\\\\\\"a-offscreen\\\\\\">JPY 1,592</span></span></div>\\"}}}&&&{\\"ASIN\\":\\"B000TEST-RED\\",\\"Type\\":\\"JSON\\",\\"Value\\":{\\"content\\":{\\"twisterSlotJson\\":{\\"isAvailable\\":true,\\"price\\":1432.77226},\\"twisterSlotDiv\\":\\"<div><span class=\\\\\\"a-price\\\\\\"><span class=\\\\\\"a-offscreen\\\\\\">JPY 1,433</span></span></div>\\"}}}"}]
            </script>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "product")

    assert doc.structured.platform_fields["variants"] == [
        {"asin": "B000TEST-BLACK", "label": "Black", "price": "JPY 1,592", "availability": "In Stock"},
        {"asin": "B000TEST-RED", "label": "Red", "price": "JPY 1,433", "availability": "In Stock"},
    ]


def test_pipeline_html_extraction_extracts_amazon_seller_fields() -> None:
    fetch_result = {
        "url": "https://www.amazon.com/sp?seller=ABC123",
        "text": """
        <html>
          <body>
            <div id="seller-profile-container">
              <h1 id="seller-name">Keychron Official</h1>
              <div id="seller-rating">4.9 out of 5 stars</div>
              <div id="feedback-count">8,421 ratings</div>
              <div id="seller-since">On Amazon since 2019</div>
            </div>
            <div id="seller-listings">
              <div class="seller-product" data-asin="B000TEST1">
                <a class="seller-product-link" href="/dp/B000TEST1">Keychron K3</a>
                <span class="a-price"><span class="a-offscreen">$99.99</span></span>
                <span class="a-icon-alt">4.8 out of 5 stars</span>
              </div>
              <div class="seller-product" data-asin="B000TEST2">
                <a class="seller-product-link" href="/dp/B000TEST2">Keychron K2</a>
                <span class="a-price"><span class="a-offscreen">$89.99</span></span>
              </div>
            </div>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "amazon", "seller")

    assert doc.structured.title == "Keychron Official"
    assert doc.structured.platform_fields["seller_name"] == "Keychron Official"
    assert doc.structured.platform_fields["seller_rating"] == "4.9 out of 5 stars"
    assert doc.structured.platform_fields["feedback_count"] == "8,421 ratings"
    assert doc.structured.platform_fields["seller_since"] == "On Amazon since 2019"
    assert doc.structured.platform_fields["product_listings"] == [
        {
            "asin": "B000TEST1",
            "title": "Keychron K3",
            "url": "https://www.amazon.com/dp/B000TEST1",
            "price": "$99.99",
            "rating": "4.8 out of 5 stars",
        },
        {
            "asin": "B000TEST2",
            "title": "Keychron K2",
            "url": "https://www.amazon.com/dp/B000TEST2",
            "price": "$89.99",
        },
    ]


def test_pipeline_html_extraction_extracts_base_token_fields() -> None:
    fetch_result = {
        "url": "https://basescan.org/token/0x4200000000000000000000000000000000000006",
        "text": """
        <html>
          <head>
            <title>Wrapped Ether (WETH) | ERC-20 | Address: 0x42000000...000000006 | BaseScan</title>
            <meta name="description" content="Token Rep: Neutral | Price: $2,263.38 | Onchain Market Cap: $566,175,585.58 | Holders: 4,886,759 | As at Mar-31-2026 06:37:10 AM (UTC)">
            <script type="application/ld+json">
              {
                "@context": "http://schema.org",
                "@type": "Product",
                "description": "wETH is wrapped ETH",
                "name": "Wrapped Ether (WETH)",
                "url": "https://basescan.org/token/0x4200000000000000000000000000000000000006",
                "offers": {
                  "@type": "Offer",
                  "price": "2263.38",
                  "priceCurrency": "USD"
                }
              }
            </script>
          </head>
          <body>
            <main id="ContentPlaceHolder1_maincontentinner">
              <h1>Wrapped Ether (WETH)</h1>
            </main>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "base", "token")

    assert doc.structured.title == "Wrapped Ether (WETH)"
    assert doc.structured.description == "wETH is wrapped ETH"
    assert doc.structured.platform_fields["price_usd"] == "2263.38"
    assert doc.structured.platform_fields["price_currency"] == "USD"
    assert doc.structured.platform_fields["holders"] == "4,886,759"
    assert doc.structured.platform_fields["market_cap"] == "$566,175,585.58"
    assert doc.structured.platform_fields["token_reputation"] == "Neutral"


def test_pipeline_html_extraction_extracts_base_contract_fields() -> None:
    fetch_result = {
        "url": "https://basescan.org/address/0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913#code",
        "text": """
        <html>
          <head>
            <title>Circle: USDC Token | Address: 0x833589fC...4bdA02913 | BaseScan</title>
            <meta name="description" content="Contract: Verified | Token Rep: OK | Price: $0.9996 | Transactions: 120,625,756 | As at Mar-31-2026 06:37:26 AM (UTC)">
          </head>
          <body>
            <main id="ContentPlaceHolder1_maincontentinner">
              <h1>Circle: USDC Token</h1>
              <pre id="verifiedbytecode2">contract FiatTokenProxy {}</pre>
            </main>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "base", "contract")

    assert doc.structured.title == "Circle: USDC Token"
    assert doc.structured.platform_fields["contract_status"] == "Verified"
    assert doc.structured.platform_fields["token_reputation"] == "OK"
    assert doc.structured.platform_fields["price_usd"] == "$0.9996"
    assert doc.structured.platform_fields["transactions"] == "120,625,756"
    assert doc.structured.platform_fields["source_code"] == "contract FiatTokenProxy {}"


def test_pipeline_html_extraction_applies_llm_schema_when_configured(monkeypatch, workspace_tmp_path: Path) -> None:
    schema_path = workspace_tmp_path / "extract-llm-schema.json"
    schema_path.write_text(
        json.dumps({"schema_name": "extract-product", "instruction": "Extract product fields"}),
        encoding="utf-8",
    )
    fetch_result = {
        "url": "https://example.com/product",
        "text": """
        <html>
          <body>
            <article>
              <h1>Fallback Product</h1>
              <p>Compact source text for schema extraction.</p>
            </article>
          </body>
        </html>
        """,
        "content_type": "text/html",
    }

    async def fake_execute(self, payload: dict) -> dict:
        return {
            "success": True,
            "data": {
                "title": "LLM Product",
                "description": "Generated by schema extraction.",
                "fields": {"price": "$29", "sku": "SKU-29"},
            },
            "schema_name": "extract-product",
        }

    monkeypatch.setattr(
        "crawler.extract.structured.llm_schema_extractor.LLMSchemaExtractor.execute",
        fake_execute,
    )

    pipeline = ExtractPipeline(extract_llm_schema_path=schema_path, model_config={"model": "test-model", "base_url": "https://api.example.com"})
    doc = pipeline.extract(fetch_result, "test", "page")

    assert doc.structured.title == "LLM Product"
    assert doc.structured.description == "Generated by schema extraction."
    assert doc.structured.platform_fields["price"] == "$29"
    assert doc.structured.platform_fields["sku"] == "SKU-29"
    assert doc.structured.field_sources["price"] == "llm_schema:extract-product"


def test_pipeline_legacy_output() -> None:
    fetch_result = {
        "url": "https://example.com/page",
        "text": "<html><head><title>Test</title></head><body><article><p>Hello world content paragraph.</p></article></body></html>",
        "content_type": "text/html",
    }
    pipeline = ExtractPipeline()
    result = pipeline.extract_to_legacy(fetch_result, "test", "page")

    assert "metadata" in result
    assert "markdown" in result
    assert "plain_text" in result
    assert result["extractor"] == "extract_pipeline"
    assert "extract_document" in result


def test_pipeline_to_dict_serializable() -> None:
    fetch_result = {
        "url": "https://example.com",
        "text": "<html><body><article><h1>Title</h1><p>Body text content.</p></article></body></html>",
        "content_type": "text/html",
    }
    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "test", "page")
    d = doc.to_dict()

    assert isinstance(d, dict)
    assert d["platform"] == "test"
    assert isinstance(d["chunks"], list)
    assert isinstance(d["quality"], dict)
    assert isinstance(d["structured"], dict)


def test_pipeline_empty_html() -> None:
    fetch_result = {
        "url": "https://example.com/empty",
        "text": "<html><body></body></html>",
        "content_type": "text/html",
    }
    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "test", "page")
    assert doc.total_chunks == 0
    assert doc.full_text == ""


def test_pipeline_arxiv_xml_falls_back_when_pdf_extractor_missing(monkeypatch) -> None:
    fetch_result = {
        "url": "https://arxiv.org/abs/1706.03762",
        "text": """
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/1706.03762v1</id>
            <title>Attention Is All You Need</title>
            <summary>Transformer paper abstract.</summary>
            <author><name>Ashish Vaswani</name></author>
            <author><name>Noam Shazeer</name></author>
            <link title="pdf" href="https://arxiv.org/pdf/1706.03762.pdf" rel="related" type="application/pdf" />
          </entry>
        </feed>
        """,
        "content_type": "application/atom+xml",
    }

    monkeypatch.setattr(
        "crawler.extract.pipeline.fetch_binary_content",
        lambda url: b"%PDF-1.4 fake",
    )

    def fail_pdf_extract(_path: str, title: str | None = None) -> dict:
        raise RuntimeError("PyMuPDF4LLM is required for arXiv PDF extraction. Install core dependencies including pymupdf4llm.")

    monkeypatch.setattr(
        "crawler.extract.pipeline.extract_pdf_with_pymupdf4llm",
        fail_pdf_extract,
    )

    pipeline = ExtractPipeline()
    doc = pipeline.extract(fetch_result, "arxiv", "paper")

    assert doc.structured.title == "Attention Is All You Need"
    assert "Attention Is All You Need" in doc.full_text
    assert "Transformer paper abstract." in doc.full_text
    assert doc.structured.platform_fields["pdf_url"] == "https://arxiv.org/pdf/1706.03762.pdf"
    assert doc.structured.platform_fields["pdf_extractor"] is None
