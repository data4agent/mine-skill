from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from secret_refs import read_mine_config, resolve_secret_ref

DEFAULT_PLATFORM_BASE_URL = "http://101.47.73.95"
DEFAULT_MINER_ID = "mine-agent"


def resolve_crawler_root() -> Path:
    import os

    root = os.environ.get("SOCIAL_CRAWLER_ROOT", "").strip()
    candidates: list[Path] = []
    if root:
        candidates.append(Path(root).resolve())
    candidates.append(Path(__file__).resolve().parents[1])
    for path in candidates:
        if path.exists():
            return path
    if root:
        raise RuntimeError(f"SOCIAL_CRAWLER_ROOT does not exist: {Path(root).resolve()}")
    raise RuntimeError("SOCIAL_CRAWLER_ROOT does not exist and the local Mine runtime root could not be resolved")


def inject_crawler_root() -> Path:
    root = resolve_crawler_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def resolve_local_venv_python(root: Path | None = None) -> Path | None:
    base = (root or Path(__file__).resolve().parents[1]).resolve()
    candidates = [
        base / ".venv" / "Scripts" / "python.exe",
        base / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_platform_base_url() -> str:
    return os.environ.get("PLATFORM_BASE_URL", "").strip() or DEFAULT_PLATFORM_BASE_URL


def resolve_miner_id() -> str:
    return os.environ.get("MINER_ID", "").strip() or DEFAULT_MINER_ID


def wallet_bin_candidates() -> list[str]:
    configured = os.environ.get("AWP_WALLET_BIN", "").strip()
    candidates: list[str] = []

    def add(candidate: str) -> None:
        value = candidate.strip()
        if value and value not in candidates:
            candidates.append(value)

    if configured:
        add(configured)
        resolved = shutil.which(configured)
        if resolved:
            add(resolved)

    add("awp-wallet")
    if os.name == "nt":
        add("awp-wallet.cmd")
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            add(str(Path(appdata) / "npm" / "awp-wallet.cmd"))
        add(str(Path.home() / "AppData" / "Roaming" / "npm" / "awp-wallet.cmd"))
        npm_prefix = os.environ.get("npm_config_prefix", "").strip() or os.environ.get("NPM_CONFIG_PREFIX", "").strip()
        if npm_prefix:
            add(str(Path(npm_prefix) / "awp-wallet.cmd"))
    else:
        add(str(Path.home() / ".local" / "bin" / "awp-wallet"))
        npm_prefix = os.environ.get("npm_config_prefix", "").strip() or os.environ.get("NPM_CONFIG_PREFIX", "").strip()
        if npm_prefix:
            add(str(Path(npm_prefix) / "bin" / "awp-wallet"))

    return candidates


def format_wallet_bin_display(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "awp-wallet"
    name = Path(raw).name or raw
    lowered = name.lower()
    if lowered in {"awp-wallet", "awp-wallet.cmd", "awp-wallet.exe"}:
        return "awp-wallet"
    stem = Path(name).stem
    return stem or "awp-wallet"


def resolve_wallet_bin() -> str:
    configured = os.environ.get("AWP_WALLET_BIN", "").strip()
    for candidate in wallet_bin_candidates():
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists():
            return str(candidate_path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return configured or "awp-wallet"


def resolve_wallet_config() -> tuple[str, str]:
    """Return ``(wallet_bin, wallet_token)`` from environment variables.

    * ``AWP_WALLET_BIN``   – path to awp-wallet CLI (default ``"awp-wallet"``)
    * ``AWP_WALLET_TOKEN`` – session token from ``awp-wallet unlock --duration 3600``
    * ``AWP_WALLET_TOKEN_SECRET_REF`` – JSON SecretRef resolved against Mine config providers
    """
    import os

    wallet_bin = resolve_wallet_bin()
    wallet_token = os.environ.get("AWP_WALLET_TOKEN", "").strip()
    if not wallet_token:
        ref_raw = os.environ.get("AWP_WALLET_TOKEN_SECRET_REF", "").strip()
        if ref_raw:
            try:
                ref = json.loads(ref_raw)
            except json.JSONDecodeError:
                ref = None
            if ref is not None:
                wallet_token = resolve_secret_ref(ref, read_mine_config())

    return (wallet_bin, wallet_token)
