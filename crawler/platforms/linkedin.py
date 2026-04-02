from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from bs4 import BeautifulSoup, Tag

from crawler.fetch.api_backend import fetch_api_get

from .base import (
    PlatformAdapter,
    PlatformDiscoveryPlan,
    PlatformEnrichmentPlan,
    PlatformErrorPlan,
    PlatformExtractPlan,
    PlatformFetchPlan,
    PlatformNormalizePlan,
    default_fetch_executor,
    default_backend_resolver,
    hook_normalizer,
    route_enrichment_groups,
    strategy_extractor,
)

FETCH_PLAN = PlatformFetchPlan(default_backend="api", fallback_backends=("playwright", "camoufox"), requires_auth=True)
EXTRACT_PLAN = PlatformExtractPlan(strategy="document")
NORMALIZE_PLAN = PlatformNormalizePlan(hook_name="linkedin")
ENRICH_PLAN = PlatformEnrichmentPlan(
    route="social_graph",
    field_groups=(
        "linkedin_profiles_identity",
        "linkedin_profiles_current_role",
        "linkedin_profiles_about",
    ),
)

QUERY_IDS = {
    "profile_by_vanity": "voyagerIdentityDashProfiles.34ead06db82a2cc9a778fac97f69ad6a",
    "job_posting": "voyagerJobsDashJobPostings.891aed7916d7453a37e4bbf5f1f60de4",
}

SEARCH_TYPE_PATHS = {
    "company": "companies",
    "companies": "companies",
    "profile": "people",
    "people": "people",
    "job": "jobs",
    "jobs": "jobs",
    "post": "content",
    "content": "content",
}

DECORATION_IDS = {
    "company_main": "com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12",
}


def _load_cookie_map(storage_state_path: str | None) -> dict[str, str]:
    if storage_state_path is None:
        return {}
    payload = json.loads(open(storage_state_path, "r", encoding="utf-8").read())
    cookies = payload.get("cookies", []) if isinstance(payload, dict) else []
    return {item.get("name"): item.get("value") for item in cookies if isinstance(item, dict)}


def _storage_state_headers(
    storage_state_path: str | None,
    record: dict[str, Any] | None = None,
    discovered: dict[str, Any] | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    cookie_map = _load_cookie_map(storage_state_path)
    jsessionid = (cookie_map.get("JSESSIONID") or "").strip('"')
    if jsessionid.startswith("ajax:"):
        csrf_token = jsessionid
    elif jsessionid:
        csrf_token = f"ajax:{jsessionid}"
    else:
        csrf_token = ""
    lang = (cookie_map.get("lang") or "").lower()
    x_li_lang = "zh_CN" if "zh-cn" in lang else "en_US"
    headers = {
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": x_li_lang,
        "referer": (discovered or {}).get("canonical_url") or "https://www.linkedin.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "x-li-track": json.dumps(
            {
                "clientVersion": "1.13.*",
                "osName": "web",
                "timezoneOffset": 8,
                "deviceFormFactor": "DESKTOP",
                "mpName": "voyager-web",
                "displayDensity": 1,
                "displayWidth": 1920,
                "displayHeight": 1080,
            },
            separators=(",", ":"),
        ),
        "x-li-page-instance": f"urn:li:page:d_flagship3_profile_view_base;{uuid4()}",
    }
    if cookie_map:
        headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookie_map.items())
    if csrf_token:
        headers["csrf-token"] = csrf_token
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _fetch_linkedin_json(
    *,
    canonical_url: str,
    endpoint: str,
    storage_state_path: str | None,
    discovered: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return fetch_api_get(
        canonical_url=canonical_url,
        api_endpoint=endpoint,
        headers=_storage_state_headers(storage_state_path, None, discovered, extra_headers=extra_headers),
    )


def _build_profile_lookup_endpoint(public_identifier: str) -> str:
    return (
        "https://www.linkedin.com/voyager/api/graphql?includeWebMetadata=true"
        f"&variables=(vanityName:{quote(public_identifier)})"
        f"&queryId={QUERY_IDS['profile_by_vanity']}"
    )


def _build_company_lookup_endpoint(company_slug: str) -> str:
    return (
        "https://www.linkedin.com/voyager/api/organization/companies"
        f"?decorationId={quote(DECORATION_IDS['company_main'])}"
        "&q=universalName"
        f"&universalName={quote(company_slug)}"
    )


def _build_linkedin_endpoint(record: dict) -> str:
    if record["resource_type"] == "search":
        search_path = SEARCH_TYPE_PATHS.get(str(record.get("search_type", "company")).lower(), "companies")
        return f"https://www.linkedin.com/search/results/{search_path}/?keywords={quote(str(record.get('query', '')))}"
    if record["resource_type"] == "job":
        urn = quote(f"urn:li:fsd_jobPosting:{record['job_id']}")
        return (
            "https://www.linkedin.com/voyager/api/graphql?includeWebMetadata=true"
            f"&variables=(jobPostingUrn:{urn})"
            f"&queryId={QUERY_IDS['job_posting']}"
        )
    raise ValueError(f"linkedin api fetch not supported for {record['resource_type']}")


def _enrich_linkedin_record_from_url(record: dict[str, Any], canonical_url: str) -> dict[str, Any]:
    enriched = dict(record)
    patterns = (
        (r"^https://www\.linkedin\.com/in/([^/]+)/?$", "profile", "public_identifier"),
        (r"^https://www\.linkedin\.com/company/([^/]+)/?$", "company", "company_slug"),
        (r"^https://www\.linkedin\.com/jobs/view/(\d+)/?$", "job", "job_id"),
        (r"^https://www\.linkedin\.com/feed/update/([^/]+)/?$", "post", "activity_urn"),
    )
    for pattern, resource_type, key in patterns:
        if enriched.get("resource_type") != resource_type:
            continue
        if enriched.get(key):
            return enriched
        match = re.match(pattern, canonical_url)
        if match:
            enriched[key] = match.group(1)
            return enriched
    return enriched


def _fetch_linkedin_api(record: dict, discovered: dict, storage_state_path: str | None) -> dict:
    canonical_url = discovered["canonical_url"]
    record = _enrich_linkedin_record_from_url(record, canonical_url)
    resource_type = record["resource_type"]
    if resource_type == "search":
        return fetch_api_get(
            canonical_url=canonical_url,
            api_endpoint=canonical_url,
            headers=_storage_state_headers(
                storage_state_path,
                record,
                discovered,
                extra_headers={"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            ),
        )
    if resource_type == "profile":
        return _fetch_linkedin_json(
            canonical_url=canonical_url,
            endpoint=_build_profile_lookup_endpoint(record["public_identifier"]),
            storage_state_path=storage_state_path,
            discovered=discovered,
        )
    if resource_type == "company":
        return _fetch_linkedin_json(
            canonical_url=canonical_url,
            endpoint=_build_company_lookup_endpoint(record["company_slug"]),
            storage_state_path=storage_state_path,
            discovered=discovered,
        )
    return _fetch_linkedin_json(
        canonical_url=canonical_url,
        endpoint=_build_linkedin_endpoint(record),
        storage_state_path=storage_state_path,
        discovered=discovered,
    )


def _resolve_linkedin_backend(record: dict, override_backend: str | None = None, retry_count: int = 0) -> str:
    if override_backend:
        return override_backend
    if record["resource_type"] == "search":
        if retry_count > 0 and FETCH_PLAN.fallback_backends:
            return FETCH_PLAN.fallback_backends[min(retry_count - 1, len(FETCH_PLAN.fallback_backends) - 1)]
        return "api"
    # For post: start with playwright, escalate to camoufox on retry
    if record["resource_type"] == "post":
        if retry_count > 0 and FETCH_PLAN.fallback_backends:
            return FETCH_PLAN.fallback_backends[min(retry_count - 1, len(FETCH_PLAN.fallback_backends) - 1)]
        return "playwright"
    if retry_count > 0 and FETCH_PLAN.fallback_backends:
        return FETCH_PLAN.fallback_backends[min(retry_count - 1, len(FETCH_PLAN.fallback_backends) - 1)]
    return FETCH_PLAN.default_backend


def _extract_linkedin(record: dict, fetched: dict) -> dict:
    if record["resource_type"] == "search":
        return _extract_linkedin_search(record, fetched)
    data = fetched.get("json_data") or {}
    extracted = _extract_linkedin_structured(record, data)
    metadata = {
        "title": extracted.get("title") or record.get("public_identifier") or record.get("company_slug") or record.get("job_id"),
        "content_type": fetched.get("content_type"),
        "source_url": fetched["url"],
    }
    metadata.update({k: v for k, v in extracted.get("metadata_extra", {}).items() if v not in (None, "", [], {})})

    plain_text = extracted.get("plain_text") or json.dumps(data, ensure_ascii=False, default=str)
    markdown = extracted.get("markdown") or f"# {metadata['title']}\n\n{plain_text}".strip()
    structured = {
        "voyager": data,
        "linkedin": extracted.get("structured", {}),
    }
    return {
        "metadata": metadata,
        "plain_text": plain_text,
        "markdown": markdown,
        "document_blocks": [],
        "structured": structured,
        "extractor": "linkedin_api",
    }


def _extract_linkedin_structured(record: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if record["resource_type"] == "company":
        return _extract_linkedin_company(data)
    if record["resource_type"] == "profile":
        return _extract_linkedin_profile(data)
    if record["resource_type"] == "job":
        return _extract_linkedin_job(data)
    plain_text = json.dumps(data, ensure_ascii=False, default=str)
    return {"title": record.get("activity_urn"), "plain_text": plain_text, "markdown": f"```json\n{plain_text}\n```", "structured": {}}


def _extract_linkedin_search(record: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    html = fetched.get("text") or fetched.get("html") or fetched.get("content_bytes", b"").decode("utf-8", "ignore")
    soup = BeautifulSoup(html, "html.parser")
    search_type = str(record.get("search_type", "company")).lower()
    results = _extract_linkedin_search_results(soup, search_type)
    display_type = SEARCH_TYPE_PATHS.get(search_type, search_type)
    title = f"LinkedIn search: {record.get('query', '')} ({display_type})".strip()

    if results:
        plain_lines = [
            f"{item['title']} | {item['entity_type']} | {item.get('subtitle', '')}".rstrip(" |")
            for item in results
        ]
        markdown_lines = [
            f"- [{item['title']}]({item['canonical_url']}) - {item['entity_type']}"
            + (f" - {item['subtitle']}" if item.get("subtitle") else "")
            for item in results
        ]
    else:
        plain_lines = [f"No LinkedIn search results for {record.get('query', '')}"]
        markdown_lines = [plain_lines[0]]

    return {
        "metadata": {
            "title": title,
            "content_type": fetched.get("content_type"),
            "source_url": fetched.get("url"),
            "entity_type": "search",
            "query": record.get("query"),
            "search_type": display_type,
            "result_count": len(results),
        },
        "plain_text": "\n".join(plain_lines),
        "markdown": "# " + title + "\n\n" + "\n".join(markdown_lines),
        "document_blocks": [],
        "structured": {
            "linkedin": {
                "query": record.get("query"),
                "search_type": display_type,
                "results": results,
                "result_count": len(results),
            }
        },
        "extractor": "linkedin_search_html",
    }


def _extract_linkedin_search_results(soup: BeautifulSoup, search_type: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        candidate = _search_candidate_from_anchor(anchor, search_type)
        if candidate is None:
            continue
        canonical_url = candidate["canonical_url"]
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        results.append(candidate)
        if len(results) >= 10:
            break

    return results


def _search_candidate_from_anchor(anchor: Tag, search_type: str) -> dict[str, Any] | None:
    href = str(anchor.get("href", "")).strip()
    if not href:
        return None

    normalized_href = _normalize_linkedin_href(href)
    if normalized_href is None:
        return None

    candidate = _candidate_from_href(normalized_href, search_type)
    if candidate is None:
        return None

    title = " ".join(anchor.stripped_strings).strip()
    if not title:
        return None

    subtitle = _candidate_subtitle(anchor, title)
    candidate["title"] = title
    candidate["subtitle"] = subtitle
    candidate["search_type"] = SEARCH_TYPE_PATHS.get(search_type, search_type)
    candidate["discovery_input"] = {
        "platform": "linkedin",
        "resource_type": candidate["resource_type"],
        candidate["identifier_field"]: candidate["identifier"],
    }
    return candidate


def _normalize_linkedin_href(href: str) -> str | None:
    if href.startswith("/"):
        href = urljoin("https://www.linkedin.com", href)
    if not href.startswith("https://www.linkedin.com/"):
        return None
    parts = urlsplit(href)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + ("/" if parts.path and not parts.path.endswith("/") else ""), "", ""))


def _candidate_from_href(href: str, search_type: str) -> dict[str, Any] | None:
    patterns = {
        "company": (r"https://www\.linkedin\.com/company/([^/]+)/?$", "company", "company", "company_slug"),
        "profile": (r"https://www\.linkedin\.com/in/([^/]+)/?$", "person", "profile", "public_identifier"),
        "job": (r"https://www\.linkedin\.com/jobs/view/(\d+)/?$", "job", "job", "job_id"),
        "post": (r"https://www\.linkedin\.com/feed/update/([^/]+)/?$", "post", "post", "activity_urn"),
    }
    requested = search_type.lower()
    accepted_types = [requested] if requested in patterns else ["company", "profile", "job", "post"]
    for candidate_type in accepted_types:
        pattern, entity_type, resource_type, identifier_field = patterns[candidate_type]
        match = re.match(pattern, href)
        if not match:
            continue
        return {
            "entity_type": entity_type,
            "resource_type": resource_type,
            "canonical_url": href,
            "identifier": match.group(1),
            "identifier_field": identifier_field,
        }
    return None


def _candidate_subtitle(anchor: Tag, title: str) -> str:
    container = anchor
    for _ in range(4):
        if container.parent is None or not isinstance(container.parent, Tag):
            break
        container = container.parent
    text = container.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line != title:
            return line
    return ""


def _extract_linkedin_company(data: dict[str, Any]) -> dict[str, Any]:
    payload_items = _linkedin_items(data)
    company = _select_company_item(payload_items)
    title = company.get("name")
    text = company.get("description") or _multi_locale_text(company.get("multiLocaleDescriptions")) or company.get("tagline") or ""
    headquarters = _headquarters_label(company)
    follower_count = _follower_count(payload_items, company)
    logo_url = _logo_url(company)
    structured = {
        "source_id": _linkedin_id(company.get("dashEntityUrn") or company.get("entityUrn")),
        "title": title,
        "description": text,
        "company_slug": company.get("universalName"),
        "industry": _industry_label(company),
        "staff_count": company.get("staffCount"),
        "staff_count_range_start": (company.get("staffCountRange") or {}).get("start"),
        "headquarters": headquarters,
        "follower_count": follower_count,
        "logo_url": logo_url,
        "website_url": company.get("companyPageUrl"),
        "specialties": company.get("specialities") or [],
    }
    return {
        "title": title,
        "plain_text": text,
        "markdown": f"# {title}\n\n{text}".strip() if title or text else "",
        "structured": structured,
        "metadata_extra": {
            "entity_type": "organization",
            "source_id": structured["source_id"],
        },
    }


def _extract_linkedin_profile(data: dict[str, Any]) -> dict[str, Any]:
    payload_items = _linkedin_items(data)
    profile = _select_richest_item(payload_items, "Profile")
    first = profile.get("firstName") or ""
    last = profile.get("lastName") or ""
    title = " ".join(part for part in (first, last) if part).strip() or None
    headline = profile.get("headline") or ""
    structured = {
        "source_id": _linkedin_id(profile.get("entityUrn")),
        "title": title,
        "headline": headline,
        "public_identifier": profile.get("publicIdentifier"),
    }
    return {
        "title": title,
        "plain_text": headline,
        "markdown": f"# {title}\n\n{headline}".strip() if title or headline else "",
        "structured": structured,
        "metadata_extra": {
            "entity_type": "person",
            "source_id": structured["source_id"],
        },
    }


def _extract_linkedin_job(data: dict[str, Any]) -> dict[str, Any]:
    included = _linkedin_items(data)
    job = _select_richest_item(included, "JobPosting")
    company = _select_richest_item(included, "Company", "Organization")
    description = ((job.get("description") or {}).get("text") if isinstance(job.get("description"), dict) else job.get("description")) or ""
    location = _lookup_entity_text(included, job.get("*location"))
    structured = {
        "source_id": _linkedin_id(job.get("entityUrn")),
        "title": job.get("title"),
        "description": description,
        "company_name": company.get("name") or ((job.get("companyDetails") or {}).get("name")),
        "company_id": _linkedin_id(company.get("entityUrn") or (((job.get("companyDetails") or {}).get("jobCompany") or {}).get("*company"))),
        "location": location,
        "published_at": _normalize_epoch(job.get("listedAt") or job.get("originalListedAt")),
        "employment_type": _lookup_entity_text(included, job.get("*employmentStatus")),
    }
    return {
        "title": structured["title"],
        "plain_text": description,
        "markdown": f"# {structured['title']}\n\n{description}".strip() if structured["title"] or description else "",
        "structured": structured,
        "metadata_extra": {
            "entity_type": "job",
            "source_id": structured["source_id"],
            "published_at": structured["published_at"],
        },
    }


def _select_richest_item(included: list[dict[str, Any]], *type_keywords: str) -> dict[str, Any]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in included:
        item_type = item.get("$type") or item.get("_type") or item.get("$recipeType") or item.get("_recipeType") or ""
        if any(keyword in item_type for keyword in type_keywords):
            score = sum(1 for value in item.values() if value not in (None, "", [], {}))
            candidates.append((score, item))
    if not candidates:
        return {}
    candidates.sort(key=lambda value: value[0], reverse=True)
    return candidates[0][1]


def _linkedin_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[int] = set()

    def append_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        item_id = id(item)
        if item_id in seen:
            return
        seen.add(item_id)
        items.append(item)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            included = node.get("included")
            if isinstance(included, list):
                for item in included:
                    append_item(item)
            elements = node.get("elements")
            if isinstance(elements, list):
                for item in elements:
                    append_item(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return items


def _merge_linkedin_payloads(*payloads: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    included: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if key not in {"included", "data"}:
                merged[key] = value
        payload_included = payload.get("included")
        if isinstance(payload_included, list):
            included.extend(item for item in payload_included if isinstance(item, dict))
        payload_data = payload.get("data")
        if isinstance(payload_data, dict):
            payload_elements = payload_data.get("elements")
            if isinstance(payload_elements, list):
                elements.extend(item for item in payload_elements if isinstance(item, dict))
            for key, value in payload_data.items():
                if key != "elements":
                    merged.setdefault("data", {})[key] = value
    if included:
        merged["included"] = included
    if elements:
        merged.setdefault("data", {})["elements"] = elements
    return merged


def _profile_urn_from_payload(data: dict[str, Any]) -> str | None:
    for item in _linkedin_items(data):
        entity_urn = item.get("entityUrn")
        if isinstance(entity_urn, str) and entity_urn.startswith("urn:li:fsd_profile:"):
            return entity_urn
    profile = _select_richest_item(_linkedin_items(data), "Profile")
    entity_urn = profile.get("entityUrn")
    return entity_urn if isinstance(entity_urn, str) else None


def _company_id_from_payload(data: dict[str, Any]) -> str | None:
    for item in _linkedin_items(data):
        entity_urn = item.get("entityUrn")
        if isinstance(entity_urn, str) and entity_urn.startswith("urn:li:fsd_company:"):
            return _linkedin_id(entity_urn)
    company = _select_company_item(_linkedin_items(data))
    entity_urn = company.get("entityUrn") or company.get("dashEntityUrn")
    company_id = _linkedin_id(entity_urn)
    if company_id:
        return company_id
    for item in _linkedin_items(data):
        nested = item.get("*entityResult") or item.get("*organizationalTarget")
        candidate = _linkedin_id(nested)
        if candidate:
            return candidate
    return None


def _select_company_item(included: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in included:
        item_type = item.get("$type") or item.get("_type") or item.get("$recipeType") or item.get("_recipeType") or ""
        is_company_like = any(keyword in item_type for keyword in ("Company", "Organization"))
        has_company_shape = bool(item.get("name")) and (
            bool(item.get("universalName"))
            or str(item.get("entityUrn", "")).startswith("urn:li:fs_normalized_company:")
            or str(item.get("entityUrn", "")).startswith("urn:li:fsd_company:")
        )
        if is_company_like or has_company_shape:
            score = sum(1 for value in item.values() if value not in (None, "", [], {}))
            candidates.append((score, item))
    if not candidates:
        return {}
    candidates.sort(key=lambda value: value[0], reverse=True)
    return candidates[0][1]


def _linkedin_id(entity_urn: Any) -> str | None:
    if not isinstance(entity_urn, str) or ":" not in entity_urn:
        return None
    return entity_urn.split(":")[-1]


def _normalize_epoch(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    timestamp = value / 1000 if value > 1e12 else value
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _lookup_entity_text(included: list[dict[str, Any]], entity_urn: Any) -> str | None:
    if not isinstance(entity_urn, str):
        return None
    for item in included:
        if item.get("entityUrn") == entity_urn:
            return item.get("defaultLocalizedName") or item.get("localizedName") or item.get("abbreviatedLocalizedName")
    return None


def _multi_locale_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    localized = payload.get("localized")
    if not isinstance(localized, dict) or not localized:
        return None
    preferred = payload.get("preferredLocale") or {}
    if isinstance(preferred, dict):
        key = f"{preferred.get('language')}_{preferred.get('country')}"
        if key in localized:
            return localized[key]
    return next(iter(localized.values()), None)


def _headquarters_label(company: dict[str, Any]) -> str | None:
    grouped = company.get("groupedLocationsByCountry") or company.get("groupedLocations")
    if isinstance(grouped, list) and grouped:
        first = grouped[0]
        if isinstance(first, dict):
            return first.get("localizedName")
    headquarter = company.get("headquarter")
    if isinstance(headquarter, dict):
        return headquarter.get("city")
    return None


def _follower_count(included: list[dict[str, Any]], company: dict[str, Any]) -> int | None:
    following_info = company.get("followingInfo")
    if isinstance(following_info, dict) and isinstance(following_info.get("followerCount"), int):
        return following_info.get("followerCount")
    following_urn = company.get("*followingInfo") or company.get("*followingState") or company.get("dashFollowingStateUrn")
    if isinstance(following_urn, str):
        for item in included:
            if item.get("entityUrn") == following_urn:
                return item.get("followerCount")
    return None


def _logo_url(company: dict[str, Any]) -> str | None:
    image = None
    if isinstance(company.get("logo"), dict):
        image = company["logo"].get("image")
    if not isinstance(image, dict) and isinstance(company.get("logos"), dict):
        image = company["logos"].get("logo")
    if isinstance(image, dict) and "com.linkedin.common.VectorImage" in image:
        image = image.get("com.linkedin.common.VectorImage")
    if not isinstance(image, dict):
        return None
    root_url = image.get("rootUrl")
    artifacts = image.get("artifacts")
    if not root_url or not isinstance(artifacts, list) or not artifacts:
        return None
    best = max((artifact for artifact in artifacts if isinstance(artifact, dict)), key=lambda artifact: artifact.get("width", 0), default=None)
    if not best:
        return None
    return f"{root_url}{best.get('fileIdentifyingUrlPathSegment', '')}"


def _industry_label(company: dict[str, Any]) -> str | None:
    industries = company.get("industries")
    if isinstance(industries, list) and industries:
        first = industries[0]
        if isinstance(first, dict):
            return first.get("localizedName") or first.get("name")
        if isinstance(first, str):
            return first

    company_industries = company.get("companyIndustries")
    if isinstance(company_industries, list) and company_industries:
        first = company_industries[0]
        if isinstance(first, dict):
            return first.get("localizedName") or first.get("name")
        if isinstance(first, str):
            return first

    return None


ADAPTER = PlatformAdapter(
    platform="linkedin",
    discovery=PlatformDiscoveryPlan(
        resource_types=("search", "profile", "company", "post", "job"),
        canonicalizer="linkedin",
    ),
    fetch=FETCH_PLAN,
    extract=EXTRACT_PLAN,
    normalize=NORMALIZE_PLAN,
    enrich=ENRICH_PLAN,
    error=PlatformErrorPlan(normalized_code="LINKEDIN_FETCH_FAILED"),
    resolve_backend_fn=_resolve_linkedin_backend,
    fetch_fn=default_fetch_executor(_fetch_linkedin_api),
    extract_fn=_extract_linkedin,
    normalize_fn=hook_normalizer(NORMALIZE_PLAN.hook_name),
    enrichment_fn=route_enrichment_groups(ENRICH_PLAN),
)
