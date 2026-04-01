from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def render_env_check() -> str:
    """Check and display all environment variables needed by Mine."""
    lines = ["Environment Variable Check", "=" * 40, ""]

    required = [
        ("PLATFORM_BASE_URL", "Platform service URL (testnet: http://101.47.73.95)"),
        ("MINER_ID", "Your miner identifier"),
    ]

    optional = [
        ("AWP_WALLET_TOKEN", "Session token from awp-wallet unlock"),
        ("AWP_WALLET_BIN", "Path to awp-wallet binary (default: awp-wallet)"),
        ("SOCIAL_CRAWLER_ROOT", "Mine runtime root (default: auto-detected)"),
        ("OPENCLAW_GATEWAY_BASE_URL", "LLM gateway for PoW challenges"),
        ("WORKER_MAX_PARALLEL", "Concurrent crawl workers (default: 3)"),
        ("DATASET_REFRESH_SECONDS", "Dataset refresh interval (default: 900)"),
    ]

    lines.append("Required:")
    all_required_set = True
    for name, desc in required:
        value = os.environ.get(name, "").strip()
        if value:
            display = value if len(value) < 50 else value[:47] + "..."
            lines.append(f"  ✓ {name} = {display}")
        else:
            lines.append(f"  ✗ {name} — NOT SET")
            lines.append(f"      {desc}")
            all_required_set = False

    lines.append("")
    lines.append("Optional:")
    for name, desc in optional:
        value = os.environ.get(name, "").strip()
        if value:
            if "TOKEN" in name or "KEY" in name:
                display = value[:8] + "..." if len(value) > 8 else "***"
            else:
                display = value if len(value) < 40 else value[:37] + "..."
            lines.append(f"  ✓ {name} = {display}")
        else:
            lines.append(f"  · {name} — not set (optional)")

    lines.append("")
    if all_required_set:
        lines.append("✓ All required variables are set.")
    else:
        lines.append("✗ Some required variables are missing. Set them before running Mine.")

    return "\n".join(lines)


def run_diagnosis() -> str:
    """Run comprehensive diagnosis for 401 and connectivity issues."""
    lines = ["Mine Diagnosis", "=" * 40, ""]

    # 1. Check environment
    lines.append("1. Environment Variables")
    lines.append("-" * 30)
    platform_url = os.environ.get("PLATFORM_BASE_URL", "").strip()
    miner_id = os.environ.get("MINER_ID", "").strip()
    wallet_token = os.environ.get("AWP_WALLET_TOKEN", "").strip()

    if platform_url:
        lines.append(f"  ✓ PLATFORM_BASE_URL = {platform_url}")
    else:
        lines.append("  ✗ PLATFORM_BASE_URL — NOT SET")
        lines.append("    Fix: export PLATFORM_BASE_URL=http://101.47.73.95")

    if miner_id:
        lines.append(f"  ✓ MINER_ID = {miner_id}")
    else:
        lines.append("  ✗ MINER_ID — NOT SET")

    if wallet_token:
        lines.append(f"  ✓ AWP_WALLET_TOKEN = {wallet_token[:8]}...")
    else:
        lines.append("  ! AWP_WALLET_TOKEN — not set (will try to get from wallet)")

    lines.append("")

    # 2. Check awp-wallet
    lines.append("2. AWP Wallet Status")
    lines.append("-" * 30)
    wallet_bin = os.environ.get("AWP_WALLET_BIN", "awp-wallet").strip()
    wallet_found = bool(shutil.which(wallet_bin) or Path(wallet_bin).exists())

    if not wallet_found:
        lines.append(f"  ✗ awp-wallet not found at: {wallet_bin}")
        lines.append("    Fix: npm install -g @aspect/awp-wallet")
        return "\n".join(lines)

    lines.append(f"  ✓ awp-wallet found: {shutil.which(wallet_bin) or wallet_bin}")

    # Try to get wallet address
    import subprocess
    try:
        env = os.environ.copy()
        if not env.get("HOME") and env.get("USERPROFILE"):
            env["HOME"] = env["USERPROFILE"]
        result = subprocess.run(
            [wallet_bin, "receive"],
            capture_output=True, text=True, timeout=10, env=env
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            address = data.get("address") or data.get("eoaAddress") or ""
            if not address:
                addresses = data.get("addresses", [])
                if addresses and isinstance(addresses[0], dict):
                    address = addresses[0].get("address", "")
            if address:
                lines.append(f"  ✓ Wallet address: {address}")
            else:
                lines.append("  ! Could not get wallet address from response")
        else:
            lines.append(f"  ✗ awp-wallet receive failed: {result.stderr.strip()}")
    except Exception as exc:
        lines.append(f"  ✗ Error checking wallet: {exc}")

    lines.append("")

    # 3. Test platform connectivity
    lines.append("3. Platform Connectivity")
    lines.append("-" * 30)

    if not platform_url:
        lines.append("  ✗ Cannot test — PLATFORM_BASE_URL not set")
        return "\n".join(lines)

    import httpx
    try:
        # Test basic connectivity (no auth)
        response = httpx.get(f"{platform_url}/health", timeout=10)
        lines.append(f"  ✓ Platform reachable: {response.status_code}")
    except httpx.ConnectError:
        lines.append(f"  ✗ Cannot connect to {platform_url}")
        lines.append("    Check: Is the platform URL correct? Is your network working?")
        return "\n".join(lines)
    except Exception as exc:
        lines.append(f"  ! Health check: {exc}")

    lines.append("")

    # 4. Test authenticated endpoint
    lines.append("4. Authentication Test (Heartbeat)")
    lines.append("-" * 30)

    try:
        from agent_runtime import build_worker_from_env
        from common import resolve_wallet_config

        worker = build_worker_from_env()

        # Try heartbeat
        try:
            worker.client.send_miner_heartbeat(client_name=worker.config.client_name)
            lines.append("  ✓ Heartbeat successful — authentication working!")
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            lines.append(f"  ✗ Heartbeat failed: HTTP {status}")

            # Parse error response for details
            try:
                error_payload = error.response.json()
                error_body = error_payload.get("error", {})
                error_code = error_body.get("code", "")
                error_msg = error_body.get("message", "")

                lines.append("")
                lines.append("  Error details:")
                if error_code:
                    lines.append(f"    Code: {error_code}")
                if error_msg:
                    lines.append(f"    Message: {error_msg}")

                lines.append("")
                lines.append("  Possible causes:")

                if status == 401:
                    if error_code == "MISSING_HEADERS":
                        lines.append("    → Missing signature headers")
                        lines.append("    Fix: awp-wallet unlock --duration 3600")
                    elif error_code in {"INVALID_SIGNATURE", "SIGNATURE_MISMATCH"}:
                        lines.append("    → Signature format/content mismatch")
                        lines.append("    This may indicate platform-side signature verification changed")
                    elif error_code in {"TOKEN_EXPIRED", "SESSION_EXPIRED", "UNAUTHORIZED"}:
                        lines.append("    → Session token expired")
                        lines.append("    Fix: awp-wallet unlock --duration 3600")
                    elif error_code == "WALLET_NOT_REGISTERED":
                        lines.append("    → This wallet is not registered on the platform")
                        lines.append("    Fix: Register your wallet at the platform website")
                    elif error_code == "WALLET_BANNED":
                        lines.append("    → This wallet has been banned")
                        lines.append("    Contact: Platform support")
                    else:
                        lines.append("    → Unknown 401 error")
                        lines.append("    • Session token may be expired — try: awp-wallet unlock --duration 3600")
                        lines.append("    • Wallet may not be registered on platform")
                        lines.append("    • Platform signature requirements may have changed")

            except Exception:
                lines.append("    Could not parse error response")
                lines.append(f"    Raw: {error.response.text[:200]}")

        except RuntimeError as exc:
            lines.append(f"  ✗ Runtime error: {exc}")

    except Exception as exc:
        lines.append(f"  ✗ Could not initialize worker: {exc}")

    lines.append("")
    lines.append("=" * 40)
    lines.append("Diagnosis complete.")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mine")
    parser.add_argument(
        "command",
        choices=(
            "first-load",
            "check-again",
            "start-working",
            "check-status",
            "status-json",
            "list-datasets",
            "pause",
            "resume",
            "stop",
            "heartbeat",
            "run-once",
            "run-loop",
            "run-worker",
            "process-task-file",
            "export-core-submissions",
            "route-intent",
            "classify-intent",
            "intent-help",
            "diagnose",
            "check-env",
        ),
    )
    parser.add_argument("args", nargs="*")
    return parser


def main() -> int:
    namespace = build_parser().parse_args()
    from skill_runtime import (
        classify_intent,
        render_control_response,
        render_dataset_listing,
        render_first_load_experience,
        render_intent_help,
        render_start_working_response,
        render_status_summary,
        route_and_execute,
    )

    if namespace.command in {"first-load", "check-again"}:
        print(render_first_load_experience())
        return 0

    if namespace.command == "check-env":
        print(render_env_check())
        return 0

    if namespace.command == "diagnose":
        print(run_diagnosis())
        return 0

    if namespace.command == "intent-help":
        print(render_intent_help())
        return 0

    if namespace.command == "classify-intent":
        if not namespace.args:
            print("Usage: classify-intent <user_input>")
            return 1
        user_input = " ".join(namespace.args)
        result = classify_intent(user_input)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if namespace.command == "route-intent":
        if not namespace.args:
            print("Usage: route-intent <user_input>")
            return 1
        user_input = " ".join(namespace.args)
        from agent_runtime import build_worker_from_env
        worker = build_worker_from_env()
        result = route_and_execute(user_input, worker)
        if result.get("executed"):
            print(result.get("output", ""))
        else:
            print(result.get("output", ""))
            if result.get("needs_confirmation"):
                print("\n(Awaiting confirmation)")
        return 0

    from agent_runtime import build_worker_from_env, export_core_submissions
    worker = build_worker_from_env()

    if namespace.command == "start-working":
        selected_dataset_ids = []
        if namespace.args:
            selected_dataset_ids = [dataset_id.strip() for dataset_id in namespace.args[0].split(",") if dataset_id.strip()]
        print(render_start_working_response(worker, selected_dataset_ids=selected_dataset_ids or None))
        return 0

    if namespace.command == "check-status":
        print(render_status_summary(worker))
        return 0

    if namespace.command == "status-json":
        print(json.dumps(worker.check_status(), ensure_ascii=False, indent=2))
        return 0

    if namespace.command == "list-datasets":
        try:
            datasets = worker.list_datasets()["datasets"] if hasattr(worker, "list_datasets") else worker.client.list_datasets()
            print(render_dataset_listing(datasets))
        except Exception as exc:
            error_msg = str(exc)
            print(f"✗ Failed to list datasets: {error_msg}")
            print("")
            if "401" in error_msg or "Unauthorized" in error_msg:
                print("This appears to be an authentication issue.")
                print("Try: python scripts/run_tool.py diagnose")
                print("Or:  awp-wallet unlock --duration 3600")
            else:
                print("Check your network connection and platform URL.")
            return 1
        return 0

    if namespace.command == "pause":
        print(render_control_response(worker.pause()))
        return 0

    if namespace.command == "resume":
        print(render_control_response(worker.resume()))
        return 0

    if namespace.command == "stop":
        print(render_control_response(worker.stop()))
        return 0

    if namespace.command == "heartbeat":
        try:
            worker.client.send_miner_heartbeat(client_name=worker.config.client_name)
            print("✓ Heartbeat sent successfully")
        except Exception as exc:
            error_msg = str(exc)
            print(f"✗ Heartbeat failed: {error_msg}")
            print("")
            if "401" in error_msg or "Unauthorized" in error_msg:
                print("This appears to be an authentication issue.")
                print("Run: python scripts/run_tool.py diagnose")
                print("Or:  awp-wallet unlock --duration 3600")
            return 1
        return 0

    if namespace.command == "run-once":
        print(worker.run_once())
        return 0

    if namespace.command == "run-loop":
        interval = int(namespace.args[0]) if namespace.args else 60
        max_iter = int(namespace.args[1]) if len(namespace.args) > 1 else 0
        print(worker.run_loop(interval=interval, max_iterations=max_iter))
        return 0

    if namespace.command == "run-worker":
        interval = int(namespace.args[0]) if namespace.args else 60
        max_iter = int(namespace.args[1]) if len(namespace.args) > 1 else 1
        print(json.dumps(worker.run_worker(interval=interval, max_iterations=max_iter), ensure_ascii=False, indent=2))
        return 0

    if namespace.command == "process-task-file":
        if len(namespace.args) != 2:
            raise SystemExit("process-task-file requires: <taskType> <taskJsonPath>")
        task_type, task_json_path = namespace.args
        payload = json.loads(Path(task_json_path).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise SystemExit("task payload file must contain a JSON object")
        print(worker.process_task_payload(task_type, payload))
        return 0

    if len(namespace.args) != 3:
        raise SystemExit("export-core-submissions requires: <inputPath> <outputPath> <datasetId>")
    output = export_core_submissions(namespace.args[0], namespace.args[1], namespace.args[2])
    print(f"exported core submissions to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
