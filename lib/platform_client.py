from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin

import httpx

if TYPE_CHECKING:
    from signer import WalletSigner


class PlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        signer: "WalletSigner | None" = None,
        eip712_chain_id: int = 1,
        eip712_domain_name: str = "Platform Service",
        eip712_verifying_contract: str = "0x0000000000000000000000000000000000000000",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._signer = signer
        self._eip712_chain_id = eip712_chain_id
        self._eip712_domain_name = eip712_domain_name
        self._eip712_verifying_contract = eip712_verifying_contract
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
        self._request("POST", "/api/mining/v1/miners/heartbeat", {"client": client_name})

    def claim_repeat_crawl_task(self) -> dict[str, Any] | None:
        return self._claim("/api/mining/v1/repeat-crawl-tasks/claim")

    def claim_refresh_task(self) -> dict[str, Any] | None:
        return self._claim("/api/mining/v1/refresh-tasks/claim")

    def report_repeat_crawl_task_result(self, task_id: str, payload: dict[str, Any]) -> None:
        return self._request("POST", f"/api/mining/v1/repeat-crawl-tasks/{task_id}/report", payload)

    def report_refresh_task_result(self, task_id: str, payload: dict[str, Any]) -> None:
        return self._request("POST", f"/api/mining/v1/refresh-tasks/{task_id}/report", payload)

    def submit_core_submissions(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    def send_unified_heartbeat(self, *, client_name: str, ip_address: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/mining/v1/heartbeat",
            {
                "client": client_name,
                "ip_address": ip_address,
            },
        )

    def submit_preflight(self, dataset_id: str, epoch_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/mining/v1/miners/preflight",
            {
                "dataset_id": dataset_id,
                "epoch_id": epoch_id,
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

    def check_url_occupancy(self, dataset_id: str, url: str) -> dict[str, Any]:
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
                if status_code == 401:
                    error_code = ""
                    error_message = ""
                    try:
                        error_payload = error.response.json()
                    except ValueError:
                        error_payload = {}
                    if isinstance(error_payload, dict):
                        error_body = error_payload.get("error")
                        if isinstance(error_body, dict):
                            error_code = str(error_body.get("code") or "")
                            error_message = str(error_body.get("message") or "")
                    if error_code == "MISSING_HEADERS":
                        raise RuntimeError(
                            "Platform Service requires Web3 signature headers; configure plugin config "
                            "`awpWalletToken` or `AWP_WALLET_TOKEN` (from `awp-wallet unlock --duration 3600`) "
                            "or provide equivalent signed requests."
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
                            self._last_wallet_refresh = renew_session(duration_seconds=3600)
                            renewed_session = True
                            continue
                if status_code < 500 or attempt >= self._max_retries:
                    raise
                time.sleep(0.5 * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"request failed for {method} {path}")
