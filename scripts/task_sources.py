from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from lib.canonicalize import canonicalize_url
from run_models import TaskEnvelope, WorkItem
from worker_state import WorkerStateStore


class SkipClaimedTask(Exception):
    """Claimed task cannot be materialized (placeholder submission, missing URL, etc.); not a local config fault."""

    pass


def _is_placeholder_submission_id(submission_id: str) -> bool:
    """Detect test/placeholder submissions to avoid useless requests and false worker errors."""
    s = submission_id.strip().lower()
    if not s:
        return True
    if s.startswith("sub_fake") or s.startswith("sub_test_") or s.startswith("sub_demo_"):
        return True
    if s.endswith("_not_created"):
        return True
    return False


def optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def claimed_task_from_payload(
    task_type: str,
    payload: dict[str, Any],
    *,
    client: Any | None = None,
) -> TaskEnvelope:
    enriched_payload = enrich_task_payload(task_type, payload, client=client)
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        raise ValueError("task payload is missing id")
    url = canonicalize_url(str(enriched_payload.get("url") or enriched_payload.get("target_url") or "").strip())
    if not url:
        if task_type == "repeat_crawl":
            raise SkipClaimedTask(f"repeat_crawl task {task_id} still has no valid url after enrichment")
        raise ValueError(f"task {task_id} is missing url")
    platform, resource_type, _ = infer_platform_task(url)
    metadata = dict(enriched_payload)
    metadata.pop("id", None)
    metadata.pop("url", None)
    metadata.pop("target_url", None)
    return TaskEnvelope(
        task_id=task_id,
        task_source="backend_claim",
        task_type=task_type,
        url=url,
        dataset_id=optional_string(enriched_payload.get("dataset_id")),
        platform=optional_string(enriched_payload.get("platform")) or platform,
        resource_type=optional_string(enriched_payload.get("resource_type")) or resource_type,
        metadata=metadata,
    )


def enrich_task_payload(task_type: str, payload: dict[str, Any], *, client: Any | None) -> dict[str, Any]:
    enriched = dict(payload)
    if enriched.get("url") or enriched.get("target_url"):
        return enriched
    submission_id = optional_string(enriched.get("submission_id"))
    if task_type == "repeat_crawl" and submission_id and client is not None:
        if _is_placeholder_submission_id(submission_id):
            raise SkipClaimedTask(
                f"repeat_crawl skipping placeholder submission_id={submission_id!r} (payload has no url)"
            )
        try:
            submission = client.fetch_core_submission(submission_id)
        except Exception as exc:
            raise SkipClaimedTask(
                f"repeat_crawl cannot resolve: submission {submission_id} fetch failed and payload has no url"
            ) from exc
        enriched.setdefault("dataset_id", submission.get("dataset_id"))
        enriched.setdefault("url", submission.get("original_url") or submission.get("normalized_url"))
    return enriched


def infer_platform_task(url: str) -> tuple[str, str, dict[str, str]]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path

    if host.endswith("en.wikipedia.org") and path.startswith("/wiki/"):
        title = unquote(path.split("/wiki/", 1)[1]).replace("_", " ")
        return "wikipedia", "article", {"title": title}

    if host.endswith("arxiv.org") and path.startswith("/abs/"):
        arxiv_id = path.split("/abs/", 1)[1].strip("/")
        return "arxiv", "paper", {"arxiv_id": arxiv_id}

    if host.endswith("www.linkedin.com"):
        linkedin_patterns = (
            (r"^/in/([^/]+)/?$", "profile", "public_identifier"),
            (r"^/company/([^/]+)/?$", "company", "company_slug"),
            (r"^/jobs/view/(\d+)/?$", "job", "job_id"),
            (r"^/feed/update/([^/]+)/?$", "post", "activity_urn"),
        )
        for pattern, resource_type, field_name in linkedin_patterns:
            match = re.match(pattern, path)
            if match:
                return "linkedin", resource_type, {field_name: match.group(1)}

    if host.endswith("www.amazon.com"):
        dp_match = re.search(r"/dp/([A-Z0-9]{10})(?:/|$)", path)
        if dp_match:
            return "amazon", "product", {"asin": dp_match.group(1)}

    if host.endswith("basescan.org") or host.endswith("base.org"):
        for prefix, resource_type, field_name in (
            ("/address/", "address", "address"),
            ("/tx/", "transaction", "tx_hash"),
            ("/token/", "token", "contract_address"),
        ):
            if path.startswith(prefix):
                return "base", resource_type, {field_name: path.split(prefix, 1)[1].strip("/")}

    return "generic", "page", {"url": url}


def build_platform_record(url: str, *, platform: str | None = None, resource_type: str | None = None) -> dict[str, Any]:
    canonical_url = canonicalize_url(url)
    inferred_platform, inferred_resource_type, discovered_fields = infer_platform_task(canonical_url)
    resolved_platform = platform or inferred_platform
    resolved_resource_type = resource_type or inferred_resource_type
    record: dict[str, Any] = {
        "platform": resolved_platform,
        "resource_type": resolved_resource_type,
    }
    if resolved_platform == "generic":
        record["url"] = canonical_url
    else:
        record.update(discovered_fields)
    return record


def local_task_from_payload(payload: dict[str, Any]) -> TaskEnvelope:
    metadata = dict(payload)
    url = canonicalize_url(str(metadata.pop("url", "") or "").strip())
    if not url:
        raise ValueError("local task payload is missing url")
    task_id_value = metadata.pop("task_id", "")
    if not task_id_value:
        task_id_value = metadata.pop("id", "")
    task_id = str(task_id_value or "").strip()
    if not task_id:
        raise ValueError("local task payload is missing task_id")
    task_type_value = str(metadata.pop("task_type", "") or "local_file")
    dataset_id = optional_string(metadata.pop("dataset_id", None))
    platform_override = optional_string(metadata.pop("platform", None))
    resource_override = optional_string(metadata.pop("resource_type", None))
    inferred_platform, inferred_resource, _ = infer_platform_task(url)
    return TaskEnvelope(
        task_id=task_id,
        task_source="local_file",
        task_type=task_type_value,
        url=url,
        dataset_id=dataset_id,
        platform=platform_override or inferred_platform,
        resource_type=resource_override or inferred_resource,
        metadata=metadata,
    )


def task_to_work_item(task: TaskEnvelope) -> WorkItem:
    record = build_platform_record(task.url, platform=task.platform, resource_type=task.resource_type)
    for key, value in task.metadata.items():
        if key in {"dataset_id", "platform", "resource_type"} or value in (None, ""):
            continue
        record[key] = value
    claim_task_id = task.task_id if task.task_source == "backend_claim" else None
    claim_task_type = task.task_type if task.task_source == "backend_claim" else None
    return WorkItem(
        item_id=f"{task.task_type}:{task.task_id}",
        source=task.task_source,
        url=task.url,
        dataset_id=task.dataset_id,
        platform=task.platform,
        resource_type=task.resource_type,
        record=record,
        metadata=dict(task.metadata),
        claim_task_id=claim_task_id,
        claim_task_type=claim_task_type,
    )


def claimed_task_to_work_item(task: TaskEnvelope) -> WorkItem:
    return task_to_work_item(task)


def build_report_payload(item: WorkItem, record: dict[str, Any]) -> dict[str, Any]:
    cleaned_data = record.get("plain_text")
    if cleaned_data in (None, ""):
        cleaned_data = record.get("cleaned_data")
    if cleaned_data in (None, ""):
        cleaned_data = record.get("markdown")
    return {
        "cleaned_data": "" if cleaned_data is None else str(cleaned_data),
        "canonical_url": record.get("canonical_url") or record.get("url") or item.url,
        "structured_data": record.get("structured") if isinstance(record.get("structured"), dict) else {},
        "crawl_timestamp": optional_string(record.get("crawl_timestamp")),
    }


class ResumeQueueSource:
    def __init__(self, state_store: WorkerStateStore) -> None:
        self.state_store = state_store

    def collect(self, *, limit: int) -> list[WorkItem]:
        backlog = self.state_store.pop_backlog(limit)
        auth_due = self.state_store.pop_due_auth_pending(limit)
        merged: dict[str, WorkItem] = {}
        for item in [*auth_due, *backlog]:
            merged[item.item_id] = item
        return list(merged.values())[:limit]


class BackendClaimSource:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.last_errors: list[str] = []
        self.last_skips: list[str] = []

    def collect(self) -> list[WorkItem]:
        self.last_errors = []
        self.last_skips = []
        items: list[WorkItem] = []
        repeat_payload = self._safe_claim(self.client.claim_repeat_crawl_task, "repeat_crawl")
        if isinstance(repeat_payload, dict):
            item = self._safe_build_work_item("repeat_crawl", repeat_payload)
            if item is not None:
                items.append(item)
        refresh_payload = self._safe_claim(self.client.claim_refresh_task, "refresh")
        if isinstance(refresh_payload, dict):
            item = self._safe_build_work_item("refresh", refresh_payload)
            if item is not None:
                items.append(item)
        return items

    def _safe_claim(self, claim_fn: Any, task_type: str) -> dict[str, Any] | None:
        try:
            payload = claim_fn()
        except Exception as exc:
            self.last_errors.append(f"claim source failed: {task_type} claim request failed: {exc}")
            return None
        return payload if isinstance(payload, dict) else None

    def _safe_build_work_item(self, task_type: str, payload: dict[str, Any]) -> WorkItem | None:
        try:
            task = claimed_task_from_payload(task_type, payload, client=self.client)
            return claimed_task_to_work_item(task)
        except SkipClaimedTask as exc:
            task_id = optional_string(payload.get("id")) or "unknown"
            self.last_skips.append(f"claim skipped {task_type} task {task_id}: {exc}")
            return None
        except Exception as exc:
            task_id = optional_string(payload.get("id")) or "unknown"
            self.last_errors.append(f"claim source failed: {task_type} task {task_id} skipped: {exc}")
            return None


class DatasetDiscoverySource:
    def __init__(self, client: Any, state_store: WorkerStateStore) -> None:
        self.client = client
        self.state_store = state_store

    def collect(self, *, min_interval_seconds: int) -> list[WorkItem]:
        items: list[WorkItem] = []
        datasets = self.client.list_datasets()

        # Smart rotation: prioritize datasets by gap to target and availability
        prioritized = self._prioritize_datasets(datasets, min_interval_seconds=min_interval_seconds)

        for dataset in prioritized:
            dataset_id = optional_string(dataset.get("dataset_id")) or optional_string(dataset.get("id"))
            if not dataset_id:
                continue
            for domain in _dataset_domains(dataset):
                seed_url = _discovery_seed_url(domain)
                platform, resource_type, _ = infer_platform_task(seed_url)
                items.append(
                    WorkItem(
                        item_id=f"discovery:{dataset_id}:{seed_url}",
                        source="dataset_discovery",
                        url=seed_url,
                        dataset_id=dataset_id,
                        platform=platform,
                        resource_type=resource_type,
                        record={
                            "url": seed_url,
                            "platform": platform,
                            "resource_type": resource_type,
                        },
                        crawler_command="discover-crawl",
                        metadata={"dataset": dataset, "source_domain": domain},
                    )
                )
            self.state_store.mark_dataset_scheduled(dataset_id)
        return items

    def _prioritize_datasets(
        self,
        datasets: list[dict[str, Any]],
        *,
        min_interval_seconds: int,
    ) -> list[dict[str, Any]]:
        """Sort datasets by priority: largest gap to target first, then by staleness.

        Priority factors:
        1. Not in cooldown (rate limited datasets go last)
        2. Gap to target (datasets further from target get priority)
        3. Time since last scheduled (stale datasets get priority)
        """
        import time

        now = int(time.time())
        cooldowns = self.state_store.active_dataset_cooldowns(now=now)

        scored: list[tuple[float, dict[str, Any]]] = []
        for dataset in datasets:
            dataset_id = optional_string(dataset.get("dataset_id")) or optional_string(dataset.get("id"))
            if not dataset_id:
                continue

            # Skip if not due for scheduling
            if not self.state_store.should_schedule_dataset(dataset_id, min_interval_seconds=min_interval_seconds):
                continue

            # Calculate priority score (higher = more priority)
            score = 0.0

            # Factor 1: Cooldown penalty (datasets in cooldown get deprioritized)
            if dataset_id in cooldowns:
                score -= 10000  # Heavy penalty for rate-limited datasets

            # Factor 2: Gap to target (from dataset metadata if available)
            epoch_submitted = int(dataset.get("epoch_submitted") or dataset.get("submitted") or 0)
            epoch_target = int(dataset.get("epoch_target") or dataset.get("target") or 80)
            gap = max(0, epoch_target - epoch_submitted)
            score += gap * 10  # Larger gap = higher priority

            # Factor 3: Completion percentage (less complete = higher priority)
            if epoch_target > 0:
                completion_ratio = epoch_submitted / epoch_target
                score += (1 - completion_ratio) * 100  # 0% complete = +100, 100% complete = 0

            # Factor 4: Time since last scheduled (staleness bonus)
            # Datasets that haven't been touched recently get a small boost
            # This is already handled by should_schedule_dataset, but we add a tiebreaker

            scored.append((score, dataset))

        # Sort by score descending (highest priority first)
        scored.sort(key=lambda x: x[0], reverse=True)

        return [dataset for _score, dataset in scored]


def build_follow_up_items_from_discovery(parent: WorkItem, records: list[dict[str, Any]]) -> list[WorkItem]:
    items: list[WorkItem] = []
    for record in records:
        canonical_url = optional_string(record.get("canonical_url"))
        if not canonical_url:
            continue
        canonical_url = canonicalize_url(canonical_url)
        platform = optional_string(record.get("platform")) or infer_platform_task(canonical_url)[0]
        resource_type = optional_string(record.get("resource_type")) or infer_platform_task(canonical_url)[1]
        items.append(
            WorkItem(
                item_id=f"followup:{parent.dataset_id or 'unknown'}:{canonical_url}",
                source="discovery_followup",
                url=canonical_url,
                dataset_id=parent.dataset_id,
                platform=platform,
                resource_type=resource_type,
                record=build_platform_record(canonical_url, platform=platform, resource_type=resource_type),
                crawler_command="run",
                metadata={"discovered_from": parent.item_id},
            )
        )
    return items


def _dataset_domains(dataset: dict[str, Any]) -> list[str]:
    domains = dataset.get("source_domains")
    if isinstance(domains, list):
        return [str(item).strip() for item in domains if str(item).strip()]
    if isinstance(domains, str):
        return [chunk.strip() for chunk in domains.split(",") if chunk.strip()]
    return []


def _discovery_seed_url(domain: str) -> str:
    raw = domain.strip()
    seed_url = raw if "://" in raw else f"https://{raw.strip('/')}/"
    parsed = urlparse(seed_url)
    host = (parsed.netloc or parsed.path).lower()
    normalized_path = parsed.path.rstrip("/")
    if (host == "wikipedia.org" or host.endswith(".wikipedia.org")) and normalized_path in {"", "/"}:
        if host == "wikipedia.org":
            host = "en.wikipedia.org"
        return canonicalize_url(f"{parsed.scheme or 'https'}://{host}/wiki/Main_Page")
    return canonicalize_url(seed_url)
