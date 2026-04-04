"""Direct private key signer for EIP-712 signatures (no awp-wallet dependency)."""
from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from eth_account import Account
from eth_account.messages import encode_typed_data
from Crypto.Hash import keccak


EMPTY_HASH = f"0x{'0' * 64}"
DEFAULT_SIGNED_HEADERS = ("content-type", "x-request-id")


def _normalize_header_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _keccak_hex(text: str) -> str:
    if not text:
        return EMPTY_HASH
    digest = keccak.new(digest_bits=256)
    digest.update(text.encode("utf-8"))
    return "0x" + digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_query(url: str) -> str:
    split = urlsplit(url)
    pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        pairs.append((quote(key, safe=""), quote(value, safe="")))
    if not pairs:
        return EMPTY_HASH
    pairs.sort()
    return _keccak_hex("&".join(f"{key}={value}" for key, value in pairs))


def _hash_headers(headers: dict[str, str], signed_headers: tuple[str, ...]) -> str:
    lines = []
    for header_name in sorted(signed_headers):
        value = headers.get(header_name)
        if value is None:
            continue
        lines.append(f"{header_name}:{_normalize_header_value(value)}")
    if not lines:
        return EMPTY_HASH
    return _keccak_hex("\n".join(lines))


def _hash_body(body: Any, content_type: str) -> str:
    if body is None:
        return EMPTY_HASH
    normalized_type = str(content_type or "").lower()
    if "application/json" in normalized_type:
        return _keccak_hex(_canonical_json(body))
    if isinstance(body, str):
        return _keccak_hex(body)
    return _keccak_hex(json.dumps(body, ensure_ascii=False))


class PrivateKeySigner:
    """EIP-712 signer using raw private key."""

    def __init__(self, private_key: str) -> None:
        self._account = Account.from_key(private_key)
        self._address = self._account.address

    @property
    def signer_address(self) -> str:
        return self._address

    def get_address(self) -> str:
        """与 WalletSigner.get_address() 兼容的地址获取接口。"""
        return self._address

    def sign_typed_data(self, typed_data: dict[str, Any]) -> str:
        """Sign EIP-712 typed data and return signature."""
        signable = encode_typed_data(full_message=typed_data)
        signed = self._account.sign_message(signable)
        return signed.signature.hex()

    def build_typed_data(
        self,
        *,
        method: str,
        url: str,
        body: Any,
        content_type: str,
        request_id: str,
        now: int,
        nonce: int,
        chain_id: int = 8453,
        domain_name: str = "aDATA",
        domain_version: str = "1",
        verifying_contract: str = "0x0000000000000000000000000000000000000000",
        signed_headers: tuple[str, ...] = DEFAULT_SIGNED_HEADERS,
    ) -> dict[str, Any]:
        """Build EIP-712 typed data matching platform's APIRequest schema."""
        split = urlsplit(url)
        request_headers = {
            "content-type": content_type,
            "x-request-id": request_id,
        }

        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "APIRequest": [
                    {"name": "method", "type": "string"},
                    {"name": "host", "type": "string"},
                    {"name": "path", "type": "string"},
                    {"name": "queryHash", "type": "bytes32"},
                    {"name": "headersHash", "type": "bytes32"},
                    {"name": "bodyHash", "type": "bytes32"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "issuedAt", "type": "uint256"},
                    {"name": "expiresAt", "type": "uint256"},
                ],
            },
            "primaryType": "APIRequest",
            "domain": {
                "name": domain_name,
                "version": domain_version,
                "chainId": chain_id,
                "verifyingContract": verifying_contract,
            },
            "message": {
                "method": method.upper(),
                "host": split.netloc,
                "path": split.path or "/",
                "queryHash": _hash_query(url),
                "headersHash": _hash_headers(request_headers, signed_headers),
                "bodyHash": _hash_body(body, content_type),
                "nonce": nonce,
                "issuedAt": now,
                "expiresAt": now + 60,
            },
        }

    def build_auth_headers(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        content_type: str = "application/json",
        request_id: str | None = None,
        chain_id: int = 8453,
        domain_name: str = "aDATA",
        verifying_contract: str = "0x0000000000000000000000000000000000000000",
    ) -> dict[str, str]:
        """Build EIP-712 signed auth headers for API request."""
        now = int(time.time())
        nonce = secrets.randbits(52)
        request_id = request_id or f"req-{now}"

        typed_data = self.build_typed_data(
            method=method,
            url=url,
            body=body,
            content_type=content_type,
            request_id=request_id,
            now=now,
            nonce=nonce,
            chain_id=chain_id,
            domain_name=domain_name,
            verifying_contract=verifying_contract,
        )
        signature = self.sign_typed_data(typed_data)
        message = typed_data["message"]

        return {
            "Content-Type": content_type,
            "X-Request-ID": request_id,
            "X-Signer": self._address,
            "X-Signature": f"0x{signature}" if not signature.startswith("0x") else signature,
            "X-Nonce": str(message["nonce"]),
            "X-Issued-At": str(message["issuedAt"]),
            "X-Expires-At": str(message["expiresAt"]),
            "X-Chain-Id": str(chain_id),
            "X-Signed-Headers": ",".join(DEFAULT_SIGNED_HEADERS),
        }
