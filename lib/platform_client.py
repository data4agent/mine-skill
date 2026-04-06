from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode, urljoin

import httpx
from common import (
    DEFAULT_EIP712_CHAIN_ID,
    DEFAULT_EIP712_DOMAIN_NAME,
    DEFAULT_EIP712_VERIFYING_CONTRACT,
    WALLET_SESSION_DURATION_SECONDS,
    resolve_signature_config,
)

if TYPE_CHECKING:
    from signer import WalletSigner


class PlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        signer: "WalletSigner | None" = None,
        eip712_chain_id: int | None = None,
        eip712_domain_name: str | None = None,
        eip712_domain_version: str | None = None,
        eip712_verifying_contract: str | None = None,
    ) -> None:
        signature_config = (
            resolve_signature_config()
            if eip712_chain_id is None or eip712_domain_name is None or eip712_verifying_contract is None
            else None
        )
        self._base_url = base_url.rstrip("/")
        self._signer = signer
        self._eip712_chain_id = int(
            eip712_chain_id
            if eip712_chain_id is not None
            else signature_config.get("chain_id", DEFAULT_EIP712_CHAIN_ID)
        )
        self._eip712_domain_name = str(
            eip712_domain_name
            if eip712_domain_name is not None
            else signature_config.get("domain_name", DEFAULT_EIP712_DOMAIN_NAME)
        )
        self._eip712_domain_version = str(
            eip712_domain_version
            if eip712_domain_version is not None
            else (signature_config.get("domain_version") if signature_config else "1") or "1"
        )
        self._eip712_verifying_contract = str(
            eip712_verifying_contract
            if eip712_verifying_contract is not None
            else signature_config.get("verifying_contract", DEFAULT_EIP712_VERIFYING_CONTRACT)
        )
        self._max_retries = 3
        self._last_wallet_refresh: dict[str, Any] | None = None
        headers = {
            "Content-Type": "application/json",
        }
        if token.strip():
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=30.0,
            headers=headers,
        )

    def consume_wallet_refresh(self) -> dict[str, Any] | None:
        payload = self._last_wallet_refresh
        self._last_wallet_refresh = None
        return payload

    def send_miner_heartbeat(self, *, client_name: str) -> None:
        self.send_unified_heartbeat(client_name=client_name)

    def claim_repeat_crawl_task(self) -> dict[str, Any] | None:
        return self._claim("/api/mining/v1/repeat-crawl-tasks/claim")

    def claim_refresh_task(self) -> dict[str, Any] | None:
        return self._claim("/api/mining/v1/refresh-tasks/claim")

    def report_repeat_crawl_task_result(self, task_id: str, payload: dict[str, Any]) -> None:
        return self._request("POST", f"/api/mining/v1/repeat-crawl-tasks/{task_id}/report", payload)

    def reject_repeat_crawl_task(self, task_id: str) -> dict[str, Any]:
        """POST /api/mining/v1/repeat-crawl-tasks/{id}/reject — reject task without penalty"""
        return self._request("POST", f"/api/mining/v1/repeat-crawl-tasks/{task_id}/reject", {})

    def report_refresh_task_result(self, task_id: str, payload: dict[str, Any]) -> None:
        return self._request("POST", f"/api/mining/v1/refresh-tasks/{task_id}/report", payload)

    def submit_core_submissions(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_submission_payload(payload)
        return self._request("POST", "/api/core/v1/submissions", payload)

    def fetch_core_submission(self, submission_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/api/core/v1/submissions/{submission_id}", None)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"unexpected submission payload for {submission_id}")
        return data

    def fetch_dataset(self, dataset_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/api/core/v1/datasets/{dataset_id}", None)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"unexpected dataset payload for {dataset_id}")
        return data

    def list_datasets(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/core/v1/datasets", None)
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def send_unified_heartbeat(self, *, client_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/mining/v1/heartbeat",
            {
                "client": client_name,
            },
        )

    def answer_pow_challenge(self, challenge_id: str, answer: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/mining/v1/pow-challenges/{challenge_id}/answer",
            {
                "answer": answer,
            },
        )

    def check_url_occupancy(
        self,
        dataset_id: str,
        url: str,
        *,
        structured_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dedup_payload = {
            "dataset_id": dataset_id,
            "structured_data": self._build_occupancy_structured_data(url, structured_data),
        }
        try:
            resp = self._request("POST", "/api/core/v1/dedup-occupancies/check", dedup_payload)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
        else:
            data = resp.get("data")
            return data if isinstance(data, dict) else {}

        encoded_url = quote(url, safe="")
        try:
            resp = self._request(
                "GET",
                f"/api/core/v1/url-occupancies/check?dataset_id={dataset_id}&url={encoded_url}",
                None,
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return {}
            raise
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _build_occupancy_structured_data(url: str, structured_data: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(structured_data or {})
        payload.setdefault("canonical_url", url)
        payload.setdefault("url", url)
        return {
            key: value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }

    def join_miner_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/miners/ready — join miner ready pool for repeat crawl tasks"""
        return self._request("POST", "/api/mining/v1/miners/ready", {})

    def leave_miner_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/miners/unready — leave miner ready pool"""
        return self._request("POST", "/api/mining/v1/miners/unready", {})

    def check_dedup_by_hash(self, dataset_id: str, dedup_hash: str) -> dict[str, Any]:
        """GET /api/core/v1/dedup/check — check dedup by hash"""
        resp = self._request(
            "GET",
            f"/api/core/v1/dedup/check?dataset_id={quote(dataset_id, safe='')}&dedup_hash={quote(dedup_hash, safe='')}",
            None,
        )
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def fetch_miner_status(self) -> dict[str, Any]:
        miner_id = self._signer.get_address() if self._signer else ""
        return self._request_optional_data("GET", f"/api/mining/v1/miners/{miner_id}/status")

    def fetch_settlement(self) -> dict[str, Any]:
        miner_id = self._signer.get_address() if self._signer else ""
        return self._request_optional_data("GET", f"/api/mining/v1/miners/{miner_id}/settlement")

    def fetch_reward_summary(self) -> dict[str, Any]:
        miner_id = self._signer.get_address() if self._signer else ""
        return self._request_optional_data("GET", f"/api/mining/v1/miners/{miner_id}/reward-summary")

    def _claim(self, path: str) -> dict[str, Any] | None:
        try:
            payload = self._request("POST", path, None)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return None
            raise
        data = payload.get("data")
        if data in (None, {}, []):
            return None
        if not isinstance(data, dict):
            raise ValueError(f"unexpected claim response shape for {path}")
        return data

    def _request_optional_data(self, method: str, path: str) -> dict[str, Any]:
        try:
            payload = self._request(method, path, None)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return {}
            raise
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _validate_submission_payload(self, payload: dict[str, Any]) -> None:
        dataset_id = str(payload.get("dataset_id") or "").strip()
        entries = payload.get("entries")
        if not dataset_id or not isinstance(entries, list) or not entries:
            return
        try:
            dataset = self.fetch_dataset(dataset_id)
        except Exception:
            return
        patterns = self._coerce_url_patterns(dataset)
        template_regex = self._coerce_template_style_normalizer(dataset)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            if patterns and not any(self._regex_matches(pattern, url) for pattern in patterns):
                raise RuntimeError(
                    f"submission preflight failed: url {url!r} does not match dataset url_patterns for {dataset_id}"
                )
            if template_regex:
                left_pattern = template_regex.split("→", 1)[0].strip()
                if left_pattern and self._regex_matches(left_pattern, url) and not self._regex_matches(template_regex, url):
                    raise RuntimeError(
                        "submission preflight failed: dataset "
                        f"{dataset_id} has a template-style url_normalize_regex; "
                        f"url_patterns match {url!r}, but the embedded template likely causes server-side rejection"
                    )

    @staticmethod
    def _coerce_url_patterns(dataset: dict[str, Any]) -> list[str]:
        patterns = dataset.get("url_patterns")
        if not isinstance(patterns, list):
            return []
        return [str(pattern).strip() for pattern in patterns if str(pattern).strip()]

    @staticmethod
    def _coerce_template_style_normalizer(dataset: dict[str, Any]) -> str | None:
        schema = dataset.get("schema")
        if not isinstance(schema, dict):
            return None
        pattern = schema.get("url_normalize_regex")
        if not isinstance(pattern, str) or "→" not in pattern:
            return None
        return pattern.strip()

    @staticmethod
    def _regex_matches(pattern: str, value: str) -> bool:
        try:
            return re.match(pattern, value) is not None
        except re.error:
            return False

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        last_error: Exception | None = None
        renewed_session = False
        for attempt in range(1, self._max_retries + 1):
            kwargs: dict[str, Any] = {}
            if payload is not None:
                kwargs["json"] = payload
            if self._signer is not None:
                request_url = urljoin(
                    self._base_url if self._base_url.endswith("/") else f"{self._base_url}/",
                    path.lstrip("/"),
                )
                kwargs["headers"] = self._signer.build_auth_headers(
                    method,
                    request_url,
                    payload,
                    content_type="application/json",
                    chain_id=self._eip712_chain_id,
                    domain_name=self._eip712_domain_name,
                    domain_version=self._eip712_domain_version,
                    verifying_contract=self._eip712_verifying_contract,
                )
            try:
                response = self._client.request(method, path, **kwargs)
                response.raise_for_status()
                if not response.content:
                    return {}
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError(f"unexpected response payload for {path}")
                return body
            except httpx.HTTPStatusError as error:
                last_error = error
                status_code = error.response.status_code
                # Parse structured error response
                error_code = ""
                error_message = ""
                error_retryable = False
                error_category = ""
                try:
                    error_payload = error.response.json()
                except ValueError:
                    error_payload = {}
                if isinstance(error_payload, dict):
                    # Support two error formats: top-level fields or nested error object
                    error_body = error_payload.get("error")
                    if isinstance(error_body, dict):
                        error_code = str(error_body.get("code") or "")
                        error_message = str(error_body.get("message") or "")
                        error_retryable = bool(error_body.get("retryable", False))
                        error_category = str(error_body.get("category") or "")
                    else:
                        error_code = str(error_payload.get("code") or "")
                        error_message = str(error_payload.get("message") or "")
                        error_retryable = bool(error_payload.get("retryable", False))
                        error_category = str(error_payload.get("category") or "")
                if status_code == 401:
                    if error_code == "MISSING_HEADERS":
                        raise RuntimeError(
                            "Platform API requires Web3 signature headers. "
                            "Let Mine restore the local wallet session automatically or provide equivalent signed requests."
                        ) from error
                    if (
                        self._signer is not None
                        and not renewed_session
                        and (
                            error_code in {"UNAUTHORIZED", "TOKEN_EXPIRED", "SESSION_EXPIRED"}
                            or "expired session token" in error_message.lower()
                        )
                    ):
                        renew_session = getattr(self._signer, "renew_session", None)
                        if callable(renew_session):
                            self._last_wallet_refresh = renew_session(duration_seconds=WALLET_SESSION_DURATION_SECONDS)
                            renewed_session = True
                            continue
                # Retryable server error or explicitly marked as retryable
                if (status_code >= 500 or error_retryable) and attempt < self._max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"request failed for {method} {path}")

    # === Validator Methods ===

    def get_me(self) -> dict[str, Any]:
        """GET /api/iam/v1/me"""
        resp = self._request("GET", "/api/iam/v1/me", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def submit_validator_application(self) -> dict[str, Any]:
        """POST /api/iam/v1/validator-applications"""
        return self._request("POST", "/api/iam/v1/validator-applications", {})

    def get_my_validator_application(self) -> dict[str, Any]:
        """GET /api/iam/v1/validator-applications/me"""
        resp = self._request("GET", "/api/iam/v1/validator-applications/me", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def join_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/validators/ready"""
        return self._request("POST", "/api/mining/v1/validators/ready", {})

    def leave_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/validators/unready"""
        return self._request("POST", "/api/mining/v1/validators/unready", {})

    def claim_evaluation_task(self) -> dict[str, Any] | None:
        """POST /api/mining/v1/evaluation-tasks/claim"""
        return self._claim("/api/mining/v1/evaluation-tasks/claim")

    def get_evaluation_task(self, task_id: str) -> dict[str, Any]:
        """GET /api/mining/v1/evaluation-tasks/{id}"""
        resp = self._request("GET", f"/api/mining/v1/evaluation-tasks/{task_id}", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def report_evaluation(self, task_id: str, score: int, *, assignment_id: str) -> dict[str, Any]:
        """POST /api/mining/v1/evaluation-tasks/{id}/report"""
        return self._request("POST", f"/api/mining/v1/evaluation-tasks/{task_id}/report", {
            "assignment_id": assignment_id,
            "score": score,
        })

    def create_validation_result(self, submission_id: str, verdict: str, score: int, comment: str, idempotency_key: str) -> dict[str, Any]:
        """POST /api/core/v1/validation-results"""
        return self._request("POST", "/api/core/v1/validation-results", {
            "submission_id": submission_id,
            "verdict": verdict,
            "score": score,
            "comment": comment,
            "idempotency_key": idempotency_key,
        })

    def list_validation_results(self, **params: Any) -> list[dict[str, Any]]:
        """GET /api/core/v1/validation-results"""
        query = urlencode({k: v for k, v in params.items() if v is not None})
        path = "/api/core/v1/validation-results"
        if query:
            path = f"{path}?{query}"
        resp = self._request("GET", path, None)
        data = resp.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def get_validation_result(self, result_id: str) -> dict[str, Any]:
        """GET /api/core/v1/validation-results/{id}"""
        resp = self._request("GET", f"/api/core/v1/validation-results/{result_id}", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}
