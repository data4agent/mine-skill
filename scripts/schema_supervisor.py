from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from background_worker import process_is_running, terminate_process


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output" / "schema-supervisor"
STATE_PATH = OUTPUT_ROOT / "state.json"
LATEST_PATH = OUTPUT_ROOT / "latest.json"
HISTORY_PATH = OUTPUT_ROOT / "history.jsonl"

RECORD_CANDIDATES: list[tuple[str, list[Path]]] = [
    (
        "wikipedia",
        [
            PROJECT_ROOT / "output" / "agent-runs" / "local_file" / "local_file_wikipedia-openai-local" / "records.jsonl",
            PROJECT_ROOT / "test_output" / "local_schema_e2e" / "wikipedia-openai-local" / "records.jsonl",
        ],
    ),
    (
        "arxiv",
        [
            PROJECT_ROOT / "output" / "agent-runs" / "local_file" / "local_file_arxiv-transformers-local" / "records.jsonl",
            PROJECT_ROOT / "test_output" / "local_schema_e2e" / "arxiv-transformers-local" / "records.jsonl",
        ],
    ),
    (
        "amazon",
        [
            PROJECT_ROOT / "output" / "agent-runs" / "local_file" / "local_file_amazon-echo-local" / "records.jsonl",
            PROJECT_ROOT / "test_output" / "local_schema_e2e" / "amazon-echo-local" / "records.jsonl",
            PROJECT_ROOT / "test_output" / "amazon_test" / "records.jsonl",
        ],
    ),
    (
        "linkedin_profile",
        [
            PROJECT_ROOT / "test_output" / "linkedin_bill_gates_run_v6" / "records.jsonl",
            PROJECT_ROOT / "output" / "linkedin-live-profile-crawl-20260402" / "records.jsonl",
        ],
    ),
    (
        "linkedin_company",
        [
            PROJECT_ROOT / "output" / "linkedin-live-company-run-20260402" / "records.recovered.jsonl",
            PROJECT_ROOT / "output" / "linkedin-live-company-run-20260402" / "records.jsonl",
        ],
    ),
]

TEST_CANDIDATES: list[Path] = [
    PROJECT_ROOT / "tests" / "test_linkedin_profile_extract.py",
    PROJECT_ROOT / "tests" / "test_linkedin_profile_html_fallback.py",
    PROJECT_ROOT / "tests" / "test_linkedin_profile_html_parse.py",
    PROJECT_ROOT / "tests" / "test_linkedin_company_html_parse.py",
    PROJECT_ROOT / "tests" / "test_linkedin_html_extract.py",
    PROJECT_ROOT / "tests" / "test_amazon_main_image.py",
    PROJECT_ROOT / "tests" / "test_amazon_extract_fallback_fields.py",
    PROJECT_ROOT / "tests" / "test_amazon_structured_extract.py",
]


def _ensure_output_root() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _first_existing_nonempty(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _selected_records() -> tuple[list[tuple[str, Path]], list[str]]:
    selected: list[tuple[str, Path]] = []
    missing: list[str] = []
    for label, candidates in RECORD_CANDIDATES:
        path = _first_existing_nonempty(candidates)
        if path is None:
            missing.append(label)
            continue
        selected.append((label, path))
    return selected, missing


def _selected_tests() -> list[Path]:
    return [path for path in TEST_CANDIDATES if path.exists()]


def _run_command(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "args": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_tests() -> dict[str, Any]:
    tests = _selected_tests()
    if not tests:
        return {"status": "skipped", "reason": "no selected tests found", "tests": []}
    result = _run_command([sys.executable, "-m", "pytest", *[str(path) for path in tests], "-q"])
    result["tests"] = [str(path.relative_to(PROJECT_ROOT)) for path in tests]
    result["status"] = "passed" if result["returncode"] == 0 else "failed"
    return result


def _run_matrix() -> dict[str, Any]:
    selected, missing = _selected_records()
    if not selected:
        return {"status": "skipped", "reason": "no non-empty records found", "missing_labels": missing, "rows": []}

    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "schema_matrix.py")]
    for label, path in selected:
        command.extend(["--record", label, str(path)])
    result = _run_command(command)
    rows: list[dict[str, Any]] = []
    if result["returncode"] == 0 and result["stdout"].strip():
        rows = json.loads(result["stdout"])
    result["rows"] = rows
    result["selected_records"] = [{"label": label, "path": str(path)} for label, path in selected]
    result["missing_labels"] = missing
    result["status"] = "passed" if result["returncode"] == 0 else "failed"
    return result


def _priority_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        total = int(row.get("properties_total") or 0)
        filled = int(row.get("properties_filled") or 0)
        coverage = (filled / total) if total else 0.0
        ranked.append(
            {
                "label": row.get("label"),
                "dataset": row.get("dataset"),
                "coverage": round(coverage, 4),
                "properties_filled": filled,
                "properties_total": total,
                "required_missing": row.get("required_missing") or [],
                "missing_sample": row.get("missing_sample") or [],
            }
        )
    ranked.sort(key=lambda item: (item["coverage"], item["properties_filled"]))
    return ranked


def run_once() -> dict[str, Any]:
    _ensure_output_root()
    tests = _run_tests()
    matrix = _run_matrix()
    payload = {
        "timestamp": _utc_now(),
        "tests": tests,
        "matrix": matrix,
        "priority_summary": _priority_summary(matrix.get("rows") or []),
    }
    _write_json(LATEST_PATH, payload)
    _append_jsonl(HISTORY_PATH, payload)
    return payload


def run_loop(interval: int, max_iterations: int = 0) -> int:
    iteration = 0
    while True:
        iteration += 1
        payload = run_once()
        payload["iteration"] = iteration
        _write_json(LATEST_PATH, payload)
        if max_iterations and iteration >= max_iterations:
            return 0
        time.sleep(max(interval, 5))


def _state_payload(pid: int, interval: int, log_path: Path) -> dict[str, Any]:
    return {
        "pid": pid,
        "interval": interval,
        "log_path": str(log_path),
        "started_at": _utc_now(),
        "command": [
            sys.executable,
            str(Path(__file__).resolve()),
            "run",
            "--interval",
            str(interval),
        ],
    }


def start_background(interval: int) -> dict[str, Any]:
    _ensure_output_root()
    status = read_status()
    if status.get("running"):
        return status
    log_path = OUTPUT_ROOT / "supervisor.log"
    with log_path.open("a", encoding="utf-8") as handle:
        creationflags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= int(getattr(subprocess, name, 0))
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "run", "--interval", str(interval)],
            cwd=PROJECT_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=creationflags,
        )
    payload = _state_payload(process.pid, interval, log_path)
    _write_json(STATE_PATH, payload)
    payload["running"] = True
    return payload


def read_status() -> dict[str, Any]:
    _ensure_output_root()
    if not STATE_PATH.exists():
        return {"running": False}
    payload = _read_json(STATE_PATH)
    pid = int(payload.get("pid") or 0)
    payload["running"] = process_is_running(pid)
    if LATEST_PATH.exists():
        payload["latest_report"] = str(LATEST_PATH)
    return payload


def stop_background() -> dict[str, Any]:
    status = read_status()
    pid = int(status.get("pid") or 0)
    terminated = terminate_process(pid) if pid else False
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    return {
        "running": False,
        "terminated": terminated,
        "pid": pid,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent schema supervisor for tests + matrix.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one or more supervisor iterations in foreground")
    run_parser.add_argument("--interval", type=int, default=300)
    run_parser.add_argument("--max-iterations", type=int, default=0)
    run_parser.add_argument("--once", action="store_true")

    start_parser = subparsers.add_parser("start", help="Start detached background supervisor")
    start_parser.add_argument("--interval", type=int, default=300)

    subparsers.add_parser("status", help="Show background supervisor status")
    subparsers.add_parser("stop", help="Stop background supervisor")
    return parser


def main() -> int:
    namespace = build_parser().parse_args()
    if namespace.command == "run":
        if namespace.once:
            print(json.dumps(run_once(), ensure_ascii=False, indent=2))
            return 0
        return run_loop(interval=namespace.interval, max_iterations=namespace.max_iterations)
    if namespace.command == "start":
        print(json.dumps(start_background(namespace.interval), ensure_ascii=False, indent=2))
        return 0
    if namespace.command == "status":
        print(json.dumps(read_status(), ensure_ascii=False, indent=2))
        return 0
    if namespace.command == "stop":
        print(json.dumps(stop_background(), ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"unsupported command: {namespace.command}")


if __name__ == "__main__":
    raise SystemExit(main())
