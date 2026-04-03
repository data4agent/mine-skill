from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from common import resolve_platform_base_url, resolve_wallet_config


# Network URLs (user must explicitly choose)
TESTNET_PLATFORM_URL = "http://101.47.73.95"
MAINNET_PLATFORM_URL = ""  # TBD - will be announced when available

# Unicode symbols for consistent UX
SYM_CHECK = "✓"
SYM_CROSS = "✗"
SYM_WARN = "!"
SYM_BULLET = "•"
SYM_ARROW = "→"
SYM_DASH = "—"
SYM_BOX_H = "─"
SYM_BOX_V = "│"
SYM_BOX_TL = "┌"
SYM_BOX_TR = "┐"
SYM_BOX_BL = "└"
SYM_BOX_BR = "┘"
SYM_DIVIDER = "────────────────────────────────────────"


def text_progress_bar(current: int, total: int, width: int = 20) -> str:
    """Render a text-based progress bar like [████████░░░░] 60%"""
    if total <= 0:
        return f"[{'░' * width}] 0%"
    ratio = min(1.0, max(0.0, current / total))
    filled = int(width * ratio)
    empty = width - filled
    percent = int(ratio * 100)
    return f"[{'█' * filled}{'░' * empty}] {percent}%"


def render_status_box(title: str, rows: list[tuple[str, str]], width: int = 40) -> str:
    """Render a status box with title and key-value rows."""
    lines = [SYM_DIVIDER]
    if title:
        lines.append(f"  {title}")
        lines.append(f"  {SYM_BOX_H * (width - 4)}")
    for label, value in rows:
        lines.append(f"  {label:<20} {value}")
    lines.append(SYM_DIVIDER)
    return "\n".join(lines)


def render_step(status: str, text: str) -> str:
    """Render a step line with status icon."""
    if status == "ok":
        return f"{SYM_CHECK} {text}"
    elif status == "error":
        return f"{SYM_CROSS} {text}"
    elif status == "warn":
        return f"{SYM_WARN} {text}"
    else:
        return f"{SYM_BULLET} {text}"


def render_labeled_progress(label: str, current: int, total: int, label_width: int = 18) -> str:
    """Render a labeled progress bar like: wiki-articles    [████░░░░] 40%  12/30"""
    bar = text_progress_bar(current, total, width=12)
    return f"  {label:<{label_width}} {bar}  {current}/{total}"


def format_bytes(size: int) -> str:
    """Format byte size to human readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _read_local_version() -> str:
    """Read version from pyproject.toml in the project root."""
    crawler_root = _resolve_crawler_root()
    if crawler_root is None:
        return "unknown"
    pyproject_path = crawler_root / "pyproject.toml"
    if not pyproject_path.exists():
        return "unknown"
    try:
        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "unknown"


def _resolve_crawler_root() -> Path | None:
    root = os.environ.get("SOCIAL_CRAWLER_ROOT", "").strip()
    candidates: list[Path] = []
    if root:
        candidates.append(Path(root).resolve())
    candidates.append(Path(__file__).resolve().parents[1])
    for path in candidates:
        if path.exists():
            return path
    return None


def _wallet_ready() -> tuple[bool, str, list[str]]:
    """Check agent identity status. Returns (ok, status_line, fix_commands)."""
    wallet_bin, wallet_token = resolve_wallet_config()
    wallet_installed = bool(shutil.which(wallet_bin) or Path(wallet_bin).exists())
    if not wallet_installed:
        # Agent identity not initialized - internal setup issue
        return False, f"{SYM_CROSS} Agent identity {SYM_DASH} not initialized", [
            "# Run bootstrap to initialize agent identity",
            "powershell -ExecutionPolicy Bypass -File .\\scripts\\bootstrap.ps1" if os.name == "nt" else "./scripts/bootstrap.sh",
        ]
    if wallet_token.strip():
        return True, f"{SYM_CHECK} Agent identity {SYM_DASH} ready", []
    # Token missing but wallet exists - will auto-recover
    return True, f"{SYM_CHECK} Agent identity {SYM_DASH} ready (session managed automatically)", []


def _crawler_ready() -> tuple[bool, str, list[str]]:
    """Check crawler status. Returns (ok, status_line, fix_commands)."""
    crawler_root = _resolve_crawler_root()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if crawler_root is None:
        return False, f"{SYM_CROSS} Mine runtime {SYM_DASH} not ready (Python {py_ver})", [
            "# Bootstrap the current Mine checkout",
            "powershell -ExecutionPolicy Bypass -File .\\scripts\\bootstrap.ps1" if os.name == "nt" else "./scripts/bootstrap.sh",
        ]
    if sys.version_info < (3, 11):
        return False, f"{SYM_CROSS} Mine runtime {SYM_DASH} found, but Mine needs Python 3.11+ (current: {py_ver})", [
            "# Upgrade Python to 3.11+",
            "# Windows: Download from python.org",
            "# macOS: brew install python@3.13",
            "# Linux: apt install python3.13 or pyenv install 3.13",
            "",
            "# Then re-bootstrap:",
            "cd social-data-crawler",
            "PYTHON_BIN=/path/to/python3.13 bash scripts/bootstrap.sh",
        ]
    return True, f"{SYM_CHECK} Mine runtime {SYM_DASH} installed (Python {py_ver})", []


def _platform_line() -> tuple[bool, str, list[str]]:
    """Check platform URL. Returns (ok, status_line, fix_commands)."""
    configured = resolve_platform_base_url()
    if configured:
        # Detect network from URL
        network = "testnet" if "101.47.73.95" in configured else "configured"
        return True, f"{SYM_CHECK} Platform API {SYM_DASH} {configured} ({network})", []
    return False, f"{SYM_CROSS} Platform API {SYM_DASH} could not be resolved", []


def _version_lines() -> list[str]:
    wallet_bin, wallet_token = resolve_wallet_config()
    wallet_installed = bool(shutil.which(wallet_bin) or Path(wallet_bin).exists())
    runtime_ready = _resolve_crawler_root() is not None
    local_version = _read_local_version()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ready = sys.version_info >= (3, 11)
    version_status = f"v{local_version}" if local_version != "unknown" else "project checkout ready" if runtime_ready else "runtime not ready"
    wallet_status = f"installed {SYM_CHECK}" if wallet_installed else "missing"
    if wallet_token.strip():
        wallet_session = f"ready {SYM_CHECK}"
    elif wallet_installed:
        wallet_session = f"auto-managed ({SYM_BULLET} Mine restores or refreshes it when needed)"
    else:
        wallet_session = "not available"
    return [
        "Version check:",
        f"  {SYM_BULLET} Mine runtime version {SYM_DASH} {version_status}",
        f"  {SYM_BULLET} Python version {SYM_DASH} {python_version}{f' {SYM_CHECK}' if python_ready else ' (Mine needs Python 3.11+)'}",
        f"  {SYM_BULLET} AWP Wallet {SYM_DASH} {wallet_status}",
        f"  {SYM_BULLET} Wallet session {SYM_DASH} {wallet_session}",
    ]


def render_first_load_experience() -> str:
    """
    Scene 1: Welcome & Dependency Check
    Matches the HTML mock welcome screen.
    """
    wallet_ok, wallet_line, wallet_fixes = _wallet_ready()
    crawler_ok, crawler_line, crawler_fixes = _crawler_ready()
    platform_ok, platform_line, platform_fixes = _platform_line()

    lines = [
        "Welcome to Mine",
        "",
        "Mine runs signed data-mining work in the background while the conversation stays interactive.",
        "",
    ]

    # Version check block
    lines.extend(_version_lines())

    lines.extend([
        "",
        "Status:",
        f"  {crawler_line}",
        f"  {wallet_line}",
        f"  {platform_line}",
    ])

    if wallet_ok and crawler_ok and platform_ok:
        lines.extend([
            "",
            f"{SYM_CHECK} Mine is ready.",
            "Next action:",
            "  python scripts/run_tool.py agent-start",
            "",
            "Available actions:",
            "  python scripts/run_tool.py agent-start",
            "  python scripts/run_tool.py agent-control status",
            "  python scripts/run_tool.py agent-control stop",
            "",
            "OpenClaw aliases can map these to /mine-start, /mine-status, and /mine-stop.",
        ])
        return "\n".join(lines)

    # Collect all fix commands
    all_fixes: list[str] = []
    if not wallet_ok and wallet_fixes:
        all_fixes.extend(wallet_fixes)
    if not crawler_ok and crawler_fixes:
        if all_fixes:
            all_fixes.append("")
        all_fixes.extend(crawler_fixes)
    if not platform_ok and platform_fixes:
        if all_fixes:
            all_fixes.append("")
        all_fixes.extend(platform_fixes)
    lines.extend(["", f"{SYM_CROSS} Mine needs one fix before it can start.", "", "Next action:"])
    for fix in all_fixes:
        lines.append(f"  {fix}")

    lines.extend([
        "",
        "Then run:",
        "  python scripts/run_tool.py agent-status",
        "",
        "For deeper diagnostics:",
        "  python scripts/run_tool.py doctor",
    ])
    return "\n".join(lines)


def render_dataset_listing(client_or_datasets: Any) -> str:
    datasets = []
    if isinstance(client_or_datasets, list):
        datasets = client_or_datasets
    else:
        try:
            datasets = client_or_datasets.list_datasets()
        except Exception as exc:  # pragma: no cover
            return f"Active datasets\n  {SYM_CROSS} dataset listing failed: {exc}"
    if not datasets:
        return f"Active datasets\n  {SYM_BULLET} none available"
    lines = ["Active datasets", ""]
    for index, dataset in enumerate(datasets, start=1):
        dataset_id = str(dataset.get("dataset_id") or dataset.get("id") or f"dataset-{index}")
        domains = dataset.get("source_domains")
        if isinstance(domains, list):
            domain_text = ", ".join(str(item) for item in domains[:3])
        else:
            domain_text = str(domains or "no source domains")
        suffix = []
        if dataset.get("selected"):
            suffix.append("selected")
        if dataset.get("cooldown"):
            suffix.append("cooldown")
        suffix_text = f" [{' / '.join(suffix)}]" if suffix else ""
        miner_count = dataset.get("miner_count")
        miner_text = f" {SYM_BULLET} {miner_count} miners" if miner_count else ""
        lines.append(f"  {index}. {dataset_id} {SYM_DASH} {domain_text}{miner_text}{suffix_text}")
    return "\n".join(lines)


def render_start_working_response(worker: Any, *, selected_dataset_ids: list[str] | None = None) -> str:
    """
    Scene 2: Start Mining (first confirmation)
    Matches the HTML mock start-mining flow.
    """
    try:
        payload = worker.start_working(selected_dataset_ids=selected_dataset_ids)
    except Exception as exc:
        error_msg = str(exc)
        lines = [
            f"{SYM_CROSS} Unable to start mining yet.",
            "",
            f"  {SYM_BULLET} Error: {error_msg[:100]}",
        ]
        if "401" in error_msg or "Unauthorized" in error_msg:
            lines.extend([
                "",
                "This looks like an authentication issue. Try the guided health checks first.",
                "  1. python scripts/run_tool.py doctor",
                "  2. python scripts/run_tool.py agent-start",
            ])
        elif "wallet" in error_msg.lower() or "token" in error_msg.lower():
            lines.extend([
                "",
                "This looks like a wallet session issue.",
                f"  {SYM_BULLET} Run: powershell -ExecutionPolicy Bypass -File .\\scripts\\bootstrap.ps1" if os.name == "nt" else f"  {SYM_BULLET} Run: ./scripts/bootstrap.sh",
                f"  {SYM_BULLET} If that does not recover the session, run: awp-wallet unlock --duration 3600",
                f"  {SYM_BULLET} Retry: python scripts/run_tool.py agent-start",
            ])
        else:
            lines.extend([
                "",
                f"  {SYM_BULLET} Run: python scripts/run_tool.py doctor",
            ])
        return "\n".join(lines)

    heartbeat = payload.get("heartbeat") or {}
    status = payload.get("status") or {}
    datasets = payload.get("datasets") or []

    lines = []
    # Heartbeat status
    if heartbeat.get("unified_ok") or heartbeat.get("miner_ok"):
        lines.append(f"{SYM_CHECK} Heartbeat sent {SYM_DASH} miner registered")
    for error in heartbeat.get("errors") or []:
        lines.append(f"{SYM_WARN} Heartbeat warning: {error}")

    credit_score = status.get("credit_score")
    credit_tier = status.get("credit_tier")
    if credit_score is not None:
        tier_tag = f" [{credit_tier}]" if credit_tier else ""
        lines.append(f"{SYM_CHECK} Credit score: {credit_score}{tier_tag}")

    epoch_id = status.get("epoch_id")
    epoch_remaining = status.get("epoch_remaining")
    if epoch_id:
        remaining_text = f" ({epoch_remaining} remaining)" if epoch_remaining else ""
        lines.append(f"{SYM_CHECK} Current epoch: {epoch_id}{remaining_text}")

    if status.get("epoch_target"):
        lines.append(f"Target: {status.get('epoch_target')} submissions this epoch.")

    if payload.get("selection_required"):
        lines.extend([
            "",
            f"Found {len(datasets)} active DataSets:",
            SYM_DIVIDER,
        ])
        for index, dataset in enumerate(datasets, start=1):
            dataset_id = str(dataset.get("id") or f"dataset-{index}")
            domains = dataset.get("source_domains")
            if isinstance(domains, list):
                domain_text = ", ".join(str(item) for item in domains[:2])
            else:
                domain_text = str(domains or "no source domains")
            miner_count = dataset.get("miner_count")
            miner_text = f" {SYM_BULLET} {miner_count} miners" if miner_count else ""
            lines.append(f"  {index}. {dataset_id}")
            lines.append(f"     {domain_text}{miner_text}")
        lines.extend([
            SYM_DIVIDER,
            "",
            "Which DataSet(s) to mine? Enter numbers (e.g. 1 or 1,2 for both).",
        ])
        return "\n".join(lines)

    selected = payload.get("selected_dataset_ids") or []
    strategy = payload.get("strategy") or "round-robin batches of 5 URLs each"
    epoch_target = status.get("epoch_target") or 80

    if selected:
        lines.extend([
            "",
            f"Mining {' + '.join(selected)}.",
            f"Target: {epoch_target} submissions this epoch.",
            f"Strategy: {strategy}.",
            "",
            SYM_DIVIDER,
            "Starting autonomous mining...",
            "",
            f"{SYM_CHECK} Use agent-start for real background execution in OpenClaw",
            f"{SYM_CHECK} Status and control stay available during mining",
            "",
            "Controls:",
            "  python scripts/run_tool.py agent-control pause",
            "  python scripts/run_tool.py agent-control stop",
            "  python scripts/run_tool.py agent-control status",
            "",
            "If OpenClaw provides slash aliases, it may map these to /mine-pause, /mine-stop, and /mine-status.",
        ])
    else:
        lines.append("Mining session is ready.")
    return "\n".join(lines)


def render_control_response(payload: dict[str, Any]) -> str:
    action = payload.get("last_control_action") or payload.get("action")
    mining_state = payload.get("mining_state")

    # Use specialized renderers for pause/resume/stop
    if action == "pause" and mining_state == "paused":
        session_totals = payload.get("session_totals") or {}
        return render_pause_response(
            batch_remaining=int(payload.get("batch_remaining") or 0),
            session_submitted=int(session_totals.get("submitted_items") or 0),
            session_ok=int(session_totals.get("submitted_items") or 0) - int(session_totals.get("failed_items") or 0),
            session_failed=int(session_totals.get("failed_items") or 0),
            epoch_submitted=int(payload.get("epoch_submitted") or 0),
            epoch_target=int(payload.get("epoch_target") or 80),
        )

    if action == "resume" and mining_state == "running":
        return render_resume_response(
            credit_score=payload.get("credit_score"),
            epoch_id=payload.get("epoch_id"),
            epoch_submitted=int(payload.get("epoch_submitted") or 0),
            epoch_target=int(payload.get("epoch_target") or 80),
            remaining_time=payload.get("epoch_remaining"),
            batch_num=int(payload.get("last_batch_num") or 1) + 1,
            dataset_ids=payload.get("selected_dataset_ids"),
        )

    if action == "stop" and mining_state == "stopped":
        session_totals = payload.get("session_totals") or {}
        duration = payload.get("session_duration") or "unknown"
        return render_session_summary(
            duration=str(duration),
            submitted=int(session_totals.get("submitted_items") or 0),
            accepted=int(session_totals.get("submitted_items") or 0) - int(session_totals.get("failed_items") or 0),
            failed=int(session_totals.get("failed_items") or 0),
            crawled=int(session_totals.get("processed_items") or 0),
            dataset_count=len(payload.get("selected_dataset_ids") or []) or 1,
            epoch_submitted=int(payload.get("epoch_submitted") or 0),
            epoch_target=int(payload.get("epoch_target") or 80),
            target_reached=int(payload.get("epoch_submitted") or 0) >= int(payload.get("epoch_target") or 80),
        )

    # Generic control response
    lines = [str(payload.get("message") or "State updated.")]
    lines.append(f"{SYM_BULLET} Mining state: {mining_state}")
    if payload.get("selected_dataset_ids"):
        lines.append(f"{SYM_BULLET} Selected datasets: {', '.join(payload.get('selected_dataset_ids') or [])}")
    queues = payload.get("queues") or {}
    if queues:
        lines.append(
            f"{SYM_BULLET} Queues {SYM_DASH} backlog: {queues.get('backlog', 0)}, "
            f"auth pending: {queues.get('auth_pending', 0)}, "
            f"submit pending: {queues.get('submit_pending', 0)}"
        )
    epoch_target = payload.get("epoch_target")
    epoch_submitted = payload.get("epoch_submitted")
    if epoch_target is not None:
        bar = text_progress_bar(int(epoch_submitted or 0), int(epoch_target), width=16)
        lines.append(f"{SYM_BULLET} Epoch progress: {bar} {epoch_submitted} / {epoch_target}")
    progress = payload.get("progress")
    if isinstance(progress, dict):
        if progress.get("epoch_remaining") is not None:
            lines.append(f"{SYM_BULLET} Remaining this epoch: {progress.get('epoch_remaining')}")
    phase = payload.get("phase")
    if isinstance(phase, dict) and phase.get("label"):
        lines.append(f"{SYM_BULLET} Phase: {phase.get('label')}")
    current_batch = payload.get("current_batch")
    if isinstance(current_batch, dict) and current_batch.get("size") is not None:
        lines.append(
            f"{SYM_BULLET} Current batch: {current_batch.get('state') or 'idle'}, {current_batch.get('size')} item(s)"
        )
    reward = payload.get("reward")
    if isinstance(reward, dict) and reward.get("pending") is not None:
        lines.append(f"{SYM_BULLET} Pending rewards: {reward.get('pending')}")
    lines.append("")
    lines.append(f"Say 'pause', 'resume', or 'stop' to control mining.")
    return "\n".join(lines)


def load_batch_progress_from_output(output_dir: Path) -> dict[str, Any] | None:
    """Read progress.json from crawler output and return structured batch progress data."""
    progress_path = output_dir / "progress.json"
    if not progress_path.exists():
        return None

    try:
        import json
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Convert completed_detail to url_results format
    url_results = []
    for item in data.get("completed_detail", []):
        if not isinstance(item, dict):
            continue
        url_results.append({
            "url": item.get("url", ""),
            "status": item.get("status", "ok"),
            "size": item.get("char_count"),
            "error": item.get("error"),
        })

    return {
        "url_results": url_results,
        "completed_count": len([r for r in url_results if r["status"] == "ok"]),
        "failed_count": len([r for r in url_results if r["status"] == "failed"]),
    }


def render_batch_header(batch_num: int, dataset_id: str) -> str:
    """Render batch header like: batch 3 · wiki-articles"""
    return f"batch {batch_num} · {dataset_id}"


def render_url_progress(
    index: int,
    total: int,
    url: str,
    *,
    status: str = "ok",
    size: int | None = None,
    error: str | None = None,
) -> str:
    """Render per-URL progress line.

    status: "ok", "failed", "pending", "skipped"
    """
    # Truncate URL for display
    display_url = url
    if len(url) > 50:
        display_url = "..." + url[-47:]

    prefix = f"[{index}/{total}]"

    if status == "ok":
        size_text = f" {SYM_DASH} {size:,} chars" if size else ""
        return f"{SYM_CHECK} {prefix} {display_url}{size_text}"
    if status == "failed":
        error_text = f" {SYM_DASH} {error}" if error else ""
        return f"{SYM_CROSS} {prefix} {display_url}{error_text}"
    if status == "skipped":
        return f"{SYM_BULLET} {prefix} {display_url} (skipped)"
    # pending
    return f"{SYM_BULLET} {prefix} {display_url}..."


def render_batch_progress(
    batch_num: int,
    dataset_id: str,
    *,
    discovered: int = 0,
    available: int = 0,
    pow_passed: bool = False,
    url_results: list[dict[str, Any]] | None = None,
    structured: int = 0,
    submitted: int = 0,
    skipped: int = 0,
    skip_reason: str | None = None,
) -> str:
    """Render full batch progress matching HTML preview Scene 3.

    url_results: list of {"url": str, "status": "ok"|"failed"|"skipped", "size": int, "error": str}
    """
    lines = [render_batch_header(batch_num, dataset_id), ""]

    # Discovery phase
    if discovered > 0:
        dedup_note = f", {available} available after dedup" if available < discovered else ""
        lines.append(f"{SYM_CHECK} Discovered {discovered} URLs{dedup_note}")

    # PoW phase
    if pow_passed:
        lines.append(f"{SYM_CHECK} Passed PoW verification")

    # Crawling phase
    if url_results:
        lines.append(f"{SYM_DASH * 20}")
        lines.append("Crawling...")
        total = len(url_results)
        for idx, result in enumerate(url_results, start=1):
            lines.append(render_url_progress(
                idx,
                total,
                str(result.get("url") or ""),
                status=str(result.get("status") or "pending"),
                size=result.get("size"),
                error=result.get("error"),
            ))
        lines.append(f"{SYM_DASH * 20}")

    # Structuring phase
    if structured > 0:
        lines.append(f"{SYM_CHECK} Structured {structured} records per DataSet schema")

    # Submit phase
    if submitted > 0 or skipped > 0:
        skip_note = f" ({skipped} skipped: {skip_reason or 'fetch failed'})" if skipped > 0 else ""
        lines.append(f"{SYM_CHECK} Submitted {submitted} entries{skip_note}")

    return "\n".join(lines)


def render_epoch_progress(
    epoch_id: str,
    remaining_time: str,
    datasets: list[dict[str, Any]],
    *,
    total_submitted: int = 0,
    total_target: int = 80,
    rate_per_hour: float | None = None,
    forecast: int | None = None,
    forecast_ok: bool = True,
) -> str:
    """Render epoch progress with progress bars matching HTML preview Scene 3.

    datasets: list of {"id": str, "submitted": int, "target": int}
    """
    lines = [
        f"Epoch {epoch_id} · {remaining_time} remaining",
        "",
    ]

    # Per-dataset progress bars
    for ds in datasets:
        ds_id = str(ds.get("id") or "unknown")
        ds_submitted = int(ds.get("submitted") or 0)
        ds_target = int(ds.get("target") or 30)
        bar = text_progress_bar(ds_submitted, ds_target, width=16)
        lines.append(f"{ds_id:20} {bar} {ds_submitted} / {ds_target}")

    lines.append(f"{SYM_DASH * 40}")

    # Totals
    total_percent = int(total_submitted / total_target * 100) if total_target > 0 else 0
    lines.append(f"Total: {total_submitted} / {total_target} ({total_percent}%)")

    if rate_per_hour is not None:
        lines.append(f"Rate: {rate_per_hour:.1f} submissions/hr")

    if forecast is not None:
        if forecast_ok:
            lines.append(f"Forecast: ~{forecast} by epoch end {SYM_CHECK}")
        else:
            lines.append(f"Forecast: ~{forecast} by epoch end {SYM_WARN}")

    return "\n".join(lines)


def render_error_recovery(
    error_type: str,
    dataset_id: str,
    *,
    retry_after: int | None = None,
    fallback_dataset: str | None = None,
    message: str | None = None,
) -> str:
    """Render error recovery message matching HTML preview Scene 4.

    error_type: "rate_limited", "auth_required", "network_error", etc.
    """
    lines = []

    if error_type == "rate_limited":
        lines.append(f"{SYM_WARN} Submit failed: 429 Rate Limited")
        if retry_after:
            minutes = retry_after // 60
            lines.append(f"{SYM_BULLET} Pausing {dataset_id} for {minutes} minutes (Retry-After: {retry_after}s)")
        if fallback_dataset:
            lines.append(f"{SYM_BULLET} Switching to {fallback_dataset} in the meantime")
    elif error_type == "auth_required":
        lines.append(f"{SYM_WARN} Auth required for {dataset_id}")
        lines.append(f"{SYM_BULLET} Agent will attempt auto-recovery")
        lines.append(f"{SYM_BULLET} Say 'resume' to continue after recovery")
    elif error_type == "network_error":
        lines.append(f"{SYM_WARN} Network error: {message or 'connection failed'}")
        lines.append(f"{SYM_BULLET} Will retry in 30 seconds")
    elif error_type == "cooldown_ended":
        lines.append(f"{SYM_CHECK} {dataset_id} cooldown ended, resuming.")
    else:
        lines.append(f"{SYM_WARN} Error: {message or error_type}")

    return "\n".join(lines)


def render_pause_response(
    *,
    batch_remaining: int = 0,
    session_submitted: int = 0,
    session_ok: int = 0,
    session_failed: int = 0,
    epoch_submitted: int = 0,
    epoch_target: int = 80,
    state_path: str = "mine/.state/session.json",
) -> str:
    """
    Scene 5: Pause & Resume
    Matches the HTML mock pause screen.
    """
    lines = []

    if batch_remaining > 0:
        lines.append(f"Finishing current batch ({batch_remaining} URLs remaining)...")
        lines.append("")
        lines.append(f"{SYM_CHECK} Batch completed and submitted.")
        lines.append(SYM_DIVIDER)

    lines.append("Mining paused.")
    lines.append("")
    lines.append(SYM_DIVIDER)
    lines.append("  Session Summary")
    lines.append(f"  {SYM_BOX_H * 36}")
    lines.append(f"  This session      {session_submitted} submitted ({session_ok} ok / {session_failed} failed)")
    percent = int(epoch_submitted / epoch_target * 100) if epoch_target > 0 else 0
    lines.append(f"  Epoch progress    {epoch_submitted} / {epoch_target} ({percent}%)")
    lines.append(f"  State saved       {state_path}")
    lines.append(SYM_DIVIDER)
    lines.append("")
    lines.append("Commands: python scripts/run_tool.py agent-control resume | python scripts/run_tool.py agent-control stop")

    return "\n".join(lines)


def render_resume_response(
    *,
    credit_score: int | None = None,
    epoch_id: str | None = None,
    epoch_submitted: int = 0,
    epoch_target: int = 80,
    remaining_time: str | None = None,
    batch_num: int = 1,
    dataset_ids: list[str] | None = None,
) -> str:
    """
    Scene 5: Resume
    Matches the HTML mock resume screen.
    """
    lines = [
        f"{SYM_CHECK} Restored state from previous session",
    ]

    if credit_score is not None:
        lines.append(f"{SYM_CHECK} Heartbeat OK {SYM_DASH} credit score: {credit_score}")

    if epoch_id:
        time_note = f", {remaining_time}" if remaining_time else ""
        lines.append(f"{SYM_CHECK} Epoch {epoch_id} {SYM_DASH} {epoch_submitted}/{epoch_target} submitted{time_note}")

    if dataset_ids:
        lines.append("")
        lines.append(f"Resuming from batch {batch_num} with {' + '.join(dataset_ids)}.")
        lines.append("")
        lines.append("Commands: python scripts/run_tool.py agent-control pause | python scripts/run_tool.py agent-control stop")

    return "\n".join(lines)


def render_session_summary(
    *,
    duration: str,
    submitted: int = 0,
    accepted: int = 0,
    failed: int = 0,
    crawled: int = 0,
    dataset_count: int = 1,
    epoch_submitted: int = 0,
    epoch_target: int = 80,
    target_reached: bool = False,
) -> str:
    """
    Scene 6: Stop Mining & Session Summary
    Matches the HTML mock session-end screen.
    """
    lines = [
        "Mining session ended.",
        "",
        SYM_DIVIDER,
        "  Session Summary",
        f"  {SYM_BOX_H * 36}",
        f"  Duration          {duration}",
        f"  Submitted         {submitted} ({accepted} accepted / {failed} failed)",
        f"  Crawled           {crawled} URLs across {dataset_count} DataSet(s)",
    ]

    if target_reached:
        lines.append(f"  Epoch progress    {epoch_submitted} / {epoch_target} {SYM_DASH} target reached {SYM_CHECK}")
    else:
        percent = int(epoch_submitted / epoch_target * 100) if epoch_target > 0 else 0
        bar = text_progress_bar(epoch_submitted, epoch_target, width=12)
        lines.append(f"  Epoch progress    {bar} {epoch_submitted}/{epoch_target}")

    lines.append(SYM_DIVIDER)
    lines.append("")
    lines.append("Command: python scripts/run_tool.py agent-start")

    return "\n".join(lines)


def render_epoch_settlement(
    *,
    epoch_id: str,
    confirmed: int = 0,
    rejected: int = 0,
    reward_amount: int | float = 0,
    reward_unit: str = "aMine",
    credit_before: int | None = None,
    credit_after: int | None = None,
    credit_tier: str | None = None,
    new_epoch_id: str | None = None,
    new_epoch_hours: int | None = None,
) -> str:
    """
    Scene 6: Epoch Settlement
    Matches the HTML mock epoch settlement screen.
    """
    lines = [
        SYM_DIVIDER,
        f"  Epoch {epoch_id} Settlement",
        f"  {SYM_BOX_H * 36}",
        f"  Confirmed         {confirmed} {SYM_CHECK}",
        f"  Rejected          {rejected} {SYM_CROSS if rejected > 0 else ''}",
        f"  Reward            {reward_amount} {reward_unit}",
    ]

    if credit_before is not None and credit_after is not None:
        delta = credit_after - credit_before
        delta_text = f"+{delta}" if delta >= 0 else str(delta)
        delta_icon = SYM_CHECK if delta >= 0 else SYM_WARN
        lines.append(f"  Credit score      {credit_before} {SYM_ARROW} {credit_after} ({delta_text}) {delta_icon}")
    elif credit_after is not None:
        lines.append(f"  Credit score      {credit_after}")

    if credit_tier:
        tier_display = f"[{credit_tier}]"
        lines.append(f"  Tier              {tier_display}")

    lines.append(SYM_DIVIDER)

    if new_epoch_id:
        hours_ago = f" ({new_epoch_hours}h ago)" if new_epoch_hours else ""
        lines.append("")
        lines.append(f"New epoch {new_epoch_id} started{hours_ago}.")
        lines.append("")
        lines.append("Command: python scripts/run_tool.py agent-start")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Intent Routing
# ---------------------------------------------------------------------------

# Intent definitions from SKILL.md
INTENT_ACTIONS = {
    "A1": {
        "name": "start_mining",
        "description": "Start autonomous mining",
        "command": "start-working",
        "confirm_first_run": True,
        "keywords": ["start", "begin", "mine", "mining", "work", "working", "run", "go"],
    },
    "Q1": {
        "name": "check_status",
        "description": "Check miner status / credit score",
        "command": "check-status",
        "confirm_first_run": False,
        "keywords": ["status", "credit", "score", "miner", "state", "how am i doing"],
    },
    "Q2": {
        "name": "list_datasets",
        "description": "List active datasets",
        "command": "list-datasets",
        "confirm_first_run": False,
        "keywords": ["dataset", "datasets", "list", "available", "what can i mine"],
    },
    "Q3": {
        "name": "check_epoch",
        "description": "Check epoch progress",
        "command": "check-status",
        "confirm_first_run": False,
        "keywords": ["epoch", "progress", "target", "remaining", "how much left"],
    },
    "Q4": {
        "name": "check_history",
        "description": "Check submission history",
        "command": "check-status",
        "confirm_first_run": False,
        "keywords": ["history", "submitted", "submissions", "past", "previous"],
    },
    "Q5": {
        "name": "check_logs",
        "description": "Check mining log",
        "command": None,  # Requires reading output/agent-runs/ artifacts
        "confirm_first_run": False,
        "keywords": ["log", "logs", "errors", "debug", "what happened"],
    },
    "A2_pause": {
        "name": "pause_mining",
        "description": "Pause mining",
        "command": "pause",
        "confirm_first_run": False,
        "keywords": ["pause", "wait", "hold", "break"],
    },
    "A2_resume": {
        "name": "resume_mining",
        "description": "Resume mining",
        "command": "resume",
        "confirm_first_run": False,
        "keywords": ["resume", "continue", "unpause", "carry on"],
    },
    "A3": {
        "name": "stop_mining",
        "description": "Stop mining",
        "command": "stop",
        "confirm_first_run": True,  # Always confirm stop
        "keywords": ["stop", "end", "quit", "exit", "finish", "done"],
    },
    "C1": {
        "name": "configure",
        "description": "Configure mining preferences",
        "command": None,  # Environment variables or mine.json
        "confirm_first_run": False,
        "keywords": ["config", "configure", "settings", "preferences", "setup"],
    },
    "first_load": {
        "name": "first_load",
        "description": "First load / dependency check",
        "command": "first-load",
        "confirm_first_run": False,
        "keywords": ["check", "verify", "check again", "dependencies", "ready"],
    },
}


def classify_intent(user_input: str) -> dict[str, Any]:
    """Classify user input into an intent action.

    Returns a dict with:
    - intent_id: str (e.g., "A1", "Q1", "A3")
    - action: dict with name, description, command, confirm_first_run
    - confidence: str ("high", "medium", "low")
    - suggested_command: str | None
    """
    text = user_input.lower().strip()

    # Direct command matches (highest priority)
    if text in {"start working", "start-working", "start mining"}:
        return _intent_result("A1", "high")
    if text in {"check status", "check-status", "status"}:
        return _intent_result("Q1", "high")
    if text in {"list datasets", "list-datasets", "datasets"}:
        return _intent_result("Q2", "high")
    if text in {"pause", "pause mining"}:
        return _intent_result("A2_pause", "high")
    if text in {"resume", "resume mining", "continue"}:
        return _intent_result("A2_resume", "high")
    if text in {"stop", "stop mining", "end"}:
        return _intent_result("A3", "high")
    if text in {"check again", "first-load", "first load"}:
        return _intent_result("first_load", "high")

    # Keyword matching (medium priority)
    best_match: tuple[str, int] | None = None
    for intent_id, action in INTENT_ACTIONS.items():
        keywords = action.get("keywords", [])
        match_count = sum(1 for kw in keywords if kw in text)
        if match_count > 0:
            if best_match is None or match_count > best_match[1]:
                best_match = (intent_id, match_count)

    if best_match:
        confidence = "high" if best_match[1] >= 2 else "medium"
        return _intent_result(best_match[0], confidence)

    # Default fallback
    return {
        "intent_id": None,
        "action": None,
        "confidence": "low",
        "suggested_command": None,
        "message": "I didn't understand that. Try: start working, check status, list datasets, pause, resume, or stop.",
    }


def _intent_result(intent_id: str, confidence: str) -> dict[str, Any]:
    """Build intent classification result."""
    action = INTENT_ACTIONS.get(intent_id)
    if not action:
        return {
            "intent_id": intent_id,
            "action": None,
            "confidence": "low",
            "suggested_command": None,
        }
    return {
        "intent_id": intent_id,
        "action": action,
        "confidence": confidence,
        "suggested_command": action.get("command"),
        "needs_confirmation": action.get("confirm_first_run", False),
    }


def render_intent_help() -> str:
    """Render available intents for user guidance."""
    lines = [
        "Available commands:",
        "",
        f"  {SYM_BULLET} start working {SYM_DASH} begin autonomous mining (A1)",
        f"  {SYM_BULLET} check status {SYM_DASH} credit score, epoch progress, rewards (Q1-Q4)",
        f"  {SYM_BULLET} list datasets {SYM_DASH} see available datasets (Q2)",
        f"  {SYM_BULLET} pause {SYM_DASH} pause current mining session (A2)",
        f"  {SYM_BULLET} resume {SYM_DASH} resume paused session (A2)",
        f"  {SYM_BULLET} stop {SYM_DASH} end mining session (A3, requires confirmation)",
        f"  {SYM_BULLET} check again {SYM_DASH} re-verify dependencies",
        "",
        "Or describe what you want to do in natural language.",
    ]
    return "\n".join(lines)


def render_confirmation_prompt(intent_id: str, action: dict[str, Any]) -> str:
    """Render confirmation prompt for actions that need it."""
    name = action.get("name", "unknown")
    desc = action.get("description", "")

    if intent_id == "A3":
        return (
            f"You're about to stop mining.\n"
            f"This will:\n"
            f"  {SYM_BULLET} Finish the current batch\n"
            f"  {SYM_BULLET} Save session state\n"
            f"  {SYM_BULLET} Return a summary\n"
            f"\n"
            f"Confirm: say 'yes' or 'stop confirmed' to proceed."
        )

    if intent_id == "A1":
        return (
            f"Ready to start autonomous mining.\n"
            f"This will:\n"
            f"  {SYM_BULLET} Connect to the platform\n"
            f"  {SYM_BULLET} Discover URLs from active datasets\n"
            f"  {SYM_BULLET} Crawl, structure, and submit data\n"
            f"  {SYM_BULLET} Continue until you say pause or stop\n"
            f"\n"
            f"Confirm: say 'yes' or 'start confirmed' to begin."
        )

    return f"Confirm {desc}? Say 'yes' to proceed."


def route_and_execute(user_input: str, worker: Any, *, first_run: bool = False) -> dict[str, Any]:
    """Route user intent and execute the appropriate action.

    Returns a dict with:
    - executed: bool
    - intent_id: str | None
    - command: str | None
    - output: str
    - needs_confirmation: bool
    """
    result = classify_intent(user_input)
    intent_id = result.get("intent_id")
    action = result.get("action")
    command = result.get("suggested_command")

    # No match
    if not intent_id or not action:
        return {
            "executed": False,
            "intent_id": None,
            "command": None,
            "output": result.get("message", render_intent_help()),
            "needs_confirmation": False,
        }

    # Check if confirmation needed (stop always, start on first run)
    needs_confirmation = action.get("confirm_first_run", False)
    if intent_id == "A3":
        needs_confirmation = True
    elif intent_id == "A1" and first_run:
        needs_confirmation = True
    else:
        needs_confirmation = False

    # If needs confirmation, return prompt instead of executing
    if needs_confirmation and not _is_confirmed(user_input):
        return {
            "executed": False,
            "intent_id": intent_id,
            "command": command,
            "output": render_confirmation_prompt(intent_id, action),
            "needs_confirmation": True,
        }

    # Execute the action
    try:
        output = _execute_intent(intent_id, command, worker)
    except Exception as exc:
        output = f"Error executing {action.get('name')}: {exc}"

    return {
        "executed": True,
        "intent_id": intent_id,
        "command": command,
        "output": output,
        "needs_confirmation": False,
    }


def _is_confirmed(user_input: str) -> bool:
    """Check if user input contains confirmation."""
    text = user_input.lower().strip()
    confirmations = {"yes", "y", "confirm", "confirmed", "ok", "proceed", "do it"}
    # Also check for "start confirmed", "stop confirmed"
    if "confirmed" in text:
        return True
    return text in confirmations


def _execute_intent(intent_id: str, command: str | None, worker: Any) -> str:
    """Execute the intent and return output string."""
    if intent_id == "A1":
        return render_start_working_response(worker)

    if intent_id in {"Q1", "Q3", "Q4"}:
        return render_status_summary(worker)

    if intent_id == "Q2":
        try:
            datasets = worker.client.list_datasets()
        except Exception:
            datasets = []
        return render_dataset_listing(datasets)

    if intent_id == "Q5":
        # Read logs from output directory
        crawler_root = _resolve_crawler_root()
        if crawler_root:
            logs_dir = crawler_root / "output" / "agent-runs"
            if logs_dir.exists():
                # Find most recent run
                runs = sorted(logs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if runs:
                    latest = runs[0]
                    summary_path = latest / "_run_once" / "last-summary.json"
                    if summary_path.exists():
                        import json
                        try:
                            summary = json.loads(summary_path.read_text(encoding="utf-8"))
                            return f"Latest run summary:\n{json.dumps(summary, indent=2)}"
                        except Exception:
                            pass
        return "No recent mining logs found. Run 'start working' first."

    if intent_id == "A2_pause":
        result = worker.pause()
        return render_control_response(result)

    if intent_id == "A2_resume":
        result = worker.resume()
        return render_control_response(result)

    if intent_id == "A3":
        result = worker.stop()
        return render_control_response(result)

    if intent_id == "C1":
        return (
            "Mining preferences can be configured via environment variables:\n"
            f"  {SYM_BULLET} WORKER_MAX_PARALLEL {SYM_DASH} concurrent crawl workers (default: 3)\n"
            f"  {SYM_BULLET} DATASET_REFRESH_SECONDS {SYM_DASH} dataset refresh interval (default: 900)\n"
            f"  {SYM_BULLET} DISCOVERY_MAX_PAGES {SYM_DASH} max pages per discovery (default: 25)\n"
            f"  {SYM_BULLET} AUTH_RETRY_INTERVAL_SECONDS {SYM_DASH} retry after auth errors (default: 300)\n"
            f"\n"
            f"Or create a mine.json config file in the project root."
        )

    if intent_id == "first_load":
        return render_first_load_experience()

    return f"Unknown intent: {intent_id}"


def render_status_summary(worker: Any) -> str:
    """
    Enhanced status display matching HTML design
    """
    status = worker.check_status()
    try:
        datasets = worker.client.list_datasets()
    except Exception:
        datasets = []

    mining_state = status.get("mining_state", "idle")
    credit_score = status.get("credit_score")
    credit_tier = status.get("credit_tier")
    epoch_submitted = int(status.get("epoch_submitted") or 0)
    epoch_target = int(status.get("epoch_target") or 80)

    # Header
    lines = [
        SYM_DIVIDER,
        "  Mine Status",
        f"  {SYM_BOX_H * 36}",
    ]

    # Miner info
    miner_id = getattr(worker.config, "miner_id", None) or "unknown"
    lines.append(f"  Miner ID          {miner_id}")

    # Platform with network detection
    platform = worker.config.base_url
    network = "testnet" if "101.47.73.95" in platform else "configured"
    lines.append(f"  Platform          {platform} ({network})")

    # Mining state with icon
    state_icon = SYM_CHECK if mining_state == "running" else SYM_WARN if mining_state == "paused" else SYM_BULLET
    state_display = mining_state.upper() if mining_state == "running" else mining_state
    lines.append(f"  Mining state      {state_icon} {state_display}")

    # Credit score with tier
    if credit_score is not None:
        tier_text = f" [{credit_tier}]" if credit_tier else ""
        lines.append(f"  Credit score      {credit_score}{tier_text}")

    lines.append(SYM_DIVIDER)
    lines.append("")

    # Epoch progress with bar
    epoch_id = status.get("epoch_id")
    epoch_remaining = status.get("progress", {}).get("epoch_remaining")
    if epoch_id:
        remaining_text = f" {SYM_BULLET} {epoch_remaining} remaining" if epoch_remaining else ""
        lines.append(f"Epoch {epoch_id}{remaining_text}")
    else:
        lines.append("Epoch progress:")

    bar = text_progress_bar(epoch_submitted, epoch_target, width=20)
    percent = int(epoch_submitted / epoch_target * 100) if epoch_target > 0 else 0
    lines.append(f"{bar} {epoch_submitted} / {epoch_target}")

    # Selected datasets
    selected = status.get("selected_dataset_ids") or []
    if selected:
        lines.append("")
        lines.append(f"Mining: {' + '.join(selected)}")

    # Session totals
    progress = status.get("progress")
    if isinstance(progress, dict):
        processed = int(progress.get("session_processed_items") or 0)
        submitted = int(progress.get("session_submitted_items") or 0)
        failed = int(progress.get("session_failed_items") or 0)
        if processed > 0 or submitted > 0:
            lines.append("")
            lines.append("Session totals:")
            lines.append(f"  {SYM_BULLET} Processed: {processed}")
            lines.append(f"  {SYM_BULLET} Submitted: {submitted} ({submitted - failed} ok / {failed} failed)")

    # Queues
    queues = status.get("queues") or {}
    backlog = int(queues.get("backlog") or 0)
    auth_pending = int(queues.get("auth_pending") or 0)
    submit_pending = int(queues.get("submit_pending") or 0)
    if backlog > 0 or auth_pending > 0 or submit_pending > 0:
        lines.append("")
        lines.append(f"Queues: backlog {backlog}, auth pending {auth_pending}, submit pending {submit_pending}")

    # Rewards
    reward = status.get("reward")
    if isinstance(reward, dict) and reward.get("pending") is not None:
        lines.append("")
        lines.append(f"Pending rewards: {reward.get('pending')}")

    # Settlement
    settlement = status.get("settlement")
    if isinstance(settlement, dict):
        confirmed = settlement.get("confirmed")
        rejected = settlement.get("rejected")
        if confirmed is not None or rejected is not None:
            lines.append("")
            lines.append("Last settlement:")
            if confirmed is not None:
                lines.append(f"  {SYM_CHECK} Confirmed: {confirmed}")
            if rejected is not None:
                lines.append(f"  {SYM_CROSS} Rejected: {rejected}")
            if settlement.get("reward"):
                lines.append(f"  {SYM_BULLET} Reward: {settlement.get('reward')}")

    # Control hint
    lines.append("")
    if mining_state == "running":
        lines.append("Commands: python scripts/run_tool.py agent-control pause | python scripts/run_tool.py agent-control stop")
    elif mining_state == "paused":
        lines.append("Commands: python scripts/run_tool.py agent-control resume | python scripts/run_tool.py agent-control stop")
    elif mining_state == "stopped":
        lines.append("Commands: python scripts/run_tool.py agent-start")
    else:
        lines.append("Commands: python scripts/run_tool.py agent-start | python scripts/run_tool.py list-datasets")

    return "\n".join(lines)
