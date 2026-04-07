"""ValidatorRuntime – main event loop for the validator agent.

Optimized with patterns from example-worker.py:
- Consecutive failure tracking with alerting (#1)
- Status file for external monitoring (#4)
- JSONL history logging (#5)
- Hot-reloadable config file (#6)
- Auto-restart on crash (#7)
- Notification system via openclaw message (#8)
- Stats persistence across restarts (#9)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (
    resolve_eval_timeout,
    resolve_validator_id,
)
from evaluation_engine import EvaluationEngine, EvaluationResult
import httpx
from lib.platform_client import PlatformApiError
from ws_client import ValidatorWSClient, WSDisconnected, WSMessage

_HTTPStatusError = httpx.HTTPStatusError

log = logging.getLogger("validator.runtime")

HEARTBEAT_INTERVAL = 55
WS_RECEIVE_TIMEOUT = 30.0
FALLBACK_ALERT_THRESHOLD = 5


class ValidatorRuntime:
    """Orchestrates the validator lifecycle: connect, heartbeat, evaluate, report."""

    def __init__(
        self,
        *,
        platform_client: Any,
        ws_client: ValidatorWSClient,
        engine: EvaluationEngine | None = None,
        validator_id: str = "",
        heartbeat_interval: int = HEARTBEAT_INTERVAL,
        state_dir: str = "",
    ) -> None:
        self._platform = platform_client
        self._ws = ws_client
        self._engine = engine or EvaluationEngine(timeout=resolve_eval_timeout())
        self._validator_id = validator_id or resolve_validator_id()
        self._heartbeat_interval = heartbeat_interval

        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self._platform_lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None
        self._main_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._stats_lock = threading.Lock()
        self._stats: dict[str, int] = {
            "tasks_received": 0,
            "tasks_evaluated": 0,
            "tasks_accepted": 0,
            "tasks_rejected": 0,
            "errors": 0,
            "consecutive_failures": 0,
        }
        self._start_time = time.monotonic()
        # Dynamically updated from heartbeat response
        self._eligible = True
        self._min_task_interval = 30
        self._last_action = ""
        self._last_action_at = ""
        self._recent_actions: list[dict[str, str]] = []

        # File paths for persistence
        suffix = f"-{self._validator_id}" if self._validator_id else ""
        if state_dir:
            base = Path(state_dir)
        else:
            base = Path(os.environ.get("VALIDATOR_OUTPUT_ROOT", "output/validator-runs"))
        base.mkdir(parents=True, exist_ok=True)
        self._status_file = base / f"validator{suffix}-status.json"
        self._history_file = base / f"validator{suffix}-history.jsonl"
        self._config_file = base / f"validator{suffix}-config.json"

    # ------------------------------------------------------------------
    # Persistence (#4, #5, #9)
    # ------------------------------------------------------------------

    def _snapshot_stats(self) -> dict[str, int]:
        """Return a thread-safe snapshot of the stats dict."""
        with self._stats_lock:
            return dict(self._stats)

    def _inc_stat(self, key: str, delta: int = 1) -> None:
        """Thread-safe stat increment."""
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + delta

    def _set_stat(self, key: str, value: int) -> None:
        """Thread-safe stat set."""
        with self._stats_lock:
            self._stats[key] = value

    def _get_stat(self, key: str) -> int:
        """Thread-safe stat read."""
        with self._stats_lock:
            return self._stats.get(key, 0)

    def _write_status(self) -> None:
        """Write current status to JSON file for external monitoring."""
        status = {
            "running": self._running,
            "pid": os.getpid(),
            "uptime_seconds": int(time.monotonic() - self._start_time),
            "validator_id": self._validator_id,
            "eligible": self._eligible,
            "ws_connected": self._ws.connected,
            "stats": self._snapshot_stats(),
            "last_action": self._last_action,
            "last_action_at": self._last_action_at,
            "recent_actions": self._recent_actions[-30:],
            "min_task_interval": self._min_task_interval,
        }
        try:
            tmp = str(self._status_file) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(status, f, indent=2)
            os.replace(tmp, str(self._status_file))
        except OSError as e:
            log.warning("Failed to write status file: %s", e)

    def _restore_stats(self) -> None:
        """Restore stats from previous run so counters survive restarts."""
        try:
            data = json.loads(self._status_file.read_text(encoding="utf-8"))
            prev = data.get("stats", {})
            for key in self._stats:
                if key == "consecutive_failures":
                    continue  # reset on fresh start
                if key in prev and isinstance(prev[key], int):
                    self._stats[key] = prev[key]
            self._last_action = data.get("last_action", "")
            self._last_action_at = data.get("last_action_at", "")
            actions = data.get("recent_actions", [])
            if isinstance(actions, list):
                self._recent_actions = actions[-30:]
            log.info("Restored stats from previous run: %s", self._stats)
        except (OSError, json.JSONDecodeError, KeyError):
            log.info("No previous stats to restore, starting fresh")

    def _log_history(self, entry: dict[str, Any]) -> None:
        """Append evaluation record to JSONL history file."""
        entry["time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _record_action(self, action: str, detail: dict[str, Any] | None = None) -> None:
        """Record an action for status reporting."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._last_action = action
        self._last_action_at = now
        entry: dict[str, Any] = {"time": now, "action": action}
        if detail:
            entry.update(detail)
        self._recent_actions.append(entry)
        if len(self._recent_actions) > 60:
            del self._recent_actions[:len(self._recent_actions) - 30]

    # ------------------------------------------------------------------
    # Config (#6)
    # ------------------------------------------------------------------

    def _read_config(self) -> dict[str, Any]:
        """Read hot-reloadable config. Edit the file to change behavior without restart."""
        defaults: dict[str, Any] = {
            "cli_timeout": 120,
            "notify_enabled": False,
            "notify_interval": 300,
        }
        try:
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in defaults:
                    if key in data:
                        defaults[key] = data[key]
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def _write_default_config(self) -> None:
        """Write default config file if it does not exist."""
        if self._config_file.exists():
            return
        try:
            self._config_file.write_text(json.dumps({
                "cli_timeout": 120,
                "notify_enabled": False,
                "notify_interval": 300,
            }, indent=2), encoding="utf-8")
            log.info("Config file created: %s", self._config_file)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Notification (#8)
    # ------------------------------------------------------------------

    def _send_notification(self, message: str) -> None:
        """Send notification via openclaw message send (if configured)."""
        cfg = self._read_config()
        if not cfg.get("notify_enabled"):
            return
        try:
            import subprocess
            import shutil
            openclaw_bin = shutil.which("openclaw") or "openclaw"
            subprocess.run(
                [openclaw_bin, "message", "send", "--message", message],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log.warning("Failed to send notification")

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Start the validator runtime (WS loop + heartbeat)."""
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._paused = False
            self._stop_event.clear()

        log.info("ValidatorRuntime starting (id=%s)", self._validator_id)

        # Initialize OpenClaw agent for LLM evaluation calls
        try:
            import openclaw_llm
            agent_id = openclaw_llm.init(instance_id=self._validator_id)
            log.info("OpenClaw agent initialized: %s", agent_id)
        except Exception as exc:
            log.warning("OpenClaw init failed: %s (will retry on first eval)", exc)

        # Restore stats from previous run (#9)
        self._restore_stats()
        self._write_default_config()

        # Check validator application status
        try:
            with self._platform_lock:
                app = self._platform.get_my_validator_application()
            app_status = str(app.get("status") or "")
            if app_status == "pending_review":
                log.warning("Validator application is pending review, cannot start yet")
                with self._lock:
                    self._running = False
                return self.status()
            if app_status == "rejected":
                log.warning("Validator application was rejected")
                with self._lock:
                    self._running = False
                return self.status()
            if not app_status:
                log.info("No validator application found, submitting one")
                with self._platform_lock:
                    self._platform.submit_validator_application()
                log.info("Validator application submitted, waiting for approval")
                with self._lock:
                    self._running = False
                return self.status()
        except (PlatformApiError, _HTTPStatusError) as err:
            status = err.status_code if isinstance(err, PlatformApiError) else err.response.status_code
            if status == 403:
                log.error(
                    "Validator requires minimum 10,000 AWP staked on the Mine Worknet. "
                    "Either the agent can stake its own AWP, or a user can delegate stake to the agent. "
                    "Use the AWP Skill to stake and allocate, then retry."
                )
                with self._lock:
                    self._running = False
                return {**self.status(), "error": "insufficient_stake",
                        "message": "Validator requires minimum 10,000 AWP staked on the Mine Worknet. Either the agent stakes its own AWP, or a user delegates stake to the agent. Use the AWP Skill to stake and allocate, then retry."}
            log.warning("Validator application check failed: %s (proceeding anyway)", err)
        except Exception as exc:
            log.warning("Validator application check failed: %s (proceeding anyway)", exc)

        try:
            self._ws.connect()
        except WSDisconnected:
            log.warning("Initial WS connect failed; will retry in main loop")

        try:
            with self._platform_lock:
                self._platform.join_ready_pool()
            log.info("Joined validator ready pool")
        except (PlatformApiError, _HTTPStatusError) as err:
            status = err.status_code if isinstance(err, PlatformApiError) else err.response.status_code
            if status == 403:
                log.error(
                    "Failed to join validator ready pool — insufficient stake. "
                    "Validator requires minimum 10,000 AWP staked on the Mine Worknet. "
                    "Either the agent can stake its own AWP, or a user can delegate stake to the agent. "
                    "Use the AWP Skill to stake and allocate, then retry."
                )
                with self._lock:
                    self._running = False
                self._ws.close()
                return {**self.status(), "error": "insufficient_stake",
                        "message": "Validator requires minimum 10,000 AWP staked on the Mine Worknet. Either the agent stakes its own AWP, or a user delegates stake to the agent. Use the AWP Skill to stake and allocate, then retry."}
            log.warning("join_ready_pool failed: %s", err)
        except Exception as exc:
            log.warning("join_ready_pool failed: %s", exc)

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="validator-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

        self._main_thread = threading.Thread(
            target=self._main_loop, name="validator-main", daemon=True
        )
        self._main_thread.start()

        self._record_action("started")
        self._write_status()
        return self.status()

    def stop(self) -> dict[str, Any]:
        """Gracefully stop the validator runtime."""
        with self._lock:
            if not self._running:
                return self.status()
            self._running = False
        self._stop_event.set()

        log.info("ValidatorRuntime stopping")

        try:
            with self._platform_lock:
                self._platform.leave_ready_pool()
        except Exception as exc:
            log.warning("leave_ready_pool failed: %s", exc)

        self._ws.close()

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=10)
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=10)

        self._record_action("stopped")
        self._write_status()
        return self.status()

    def pause(self) -> dict[str, Any]:
        """Pause evaluation processing (heartbeat continues)."""
        with self._lock:
            self._paused = True
        log.info("ValidatorRuntime paused")
        self._record_action("paused")
        self._write_status()
        return self.status()

    def resume(self) -> dict[str, Any]:
        """Resume evaluation processing."""
        with self._lock:
            self._paused = False
        log.info("ValidatorRuntime resumed")
        self._record_action("resumed")
        self._write_status()
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return current runtime status."""
        with self._lock:
            state = "stopped"
            if self._running and self._paused:
                state = "paused"
            elif self._running:
                state = "running"
        return {
            "state": state,
            "validator_id": self._validator_id,
            "ws_connected": self._ws.connected,
            "eligible": self._eligible,
            "uptime_seconds": int(time.monotonic() - self._start_time),
            "stats": self._snapshot_stats(),
            "last_action": self._last_action,
            "last_action_at": self._last_action_at,
            "status_file": str(self._status_file),
            "history_file": str(self._history_file),
            "config_file": str(self._config_file),
        }

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        """WS receive loop with HTTP polling fallback."""
        consecutive_ws_failures = 0
        while self._running:
            if not self._ws.connected:
                try:
                    self._ws.reconnect_with_backoff()
                except Exception as exc:
                    log.error("Reconnect error: %s", exc)
                # Update counter based on reconnect result
                if self._ws.connected:
                    consecutive_ws_failures = 0
                else:
                    consecutive_ws_failures += 1
                    # Fall back to HTTP polling after consecutive WS failures
                    if consecutive_ws_failures >= 3:
                        self._poll_evaluation_task_http()
                        consecutive_ws_failures = 3  # cap to prevent overflow, keep polling
                    if self._stop_event.wait(timeout=5):
                        break
                    continue

            try:
                msg = self._ws.receive(timeout=WS_RECEIVE_TIMEOUT)
            except WSDisconnected:
                log.warning("WS disconnected during receive")
                consecutive_ws_failures += 1
                continue

            if msg is None:
                continue

            # Successful receive — reset WS failure counter
            consecutive_ws_failures = 0

            if msg.type == "evaluation_task":
                self._inc_stat("tasks_received")
                with self._lock:
                    eligible = self._eligible
                    paused = self._paused
                if not eligible:
                    log.info("Not eligible — ignoring evaluation_task %s", msg.assignment_id)
                    continue
                if paused:
                    log.info("Paused — ignoring evaluation_task %s", msg.assignment_id)
                    continue
                try:
                    self._handle_evaluation_task(msg)
                except Exception as exc:
                    self._inc_stat("errors")
                    self._inc_stat("consecutive_failures")
                    log.error("Error handling evaluation task %s: %s", msg.assignment_id, exc)
                    self._record_action(f"error: {exc}", {"task_id": msg.task_id})
                    # Alert on consecutive failures (#1)
                    consec = self._get_stat("consecutive_failures")
                    if consec >= FALLBACK_ALERT_THRESHOLD:
                        if consec % FALLBACK_ALERT_THRESHOLD == 0:
                            alert = f"WARNING: {consec} consecutive evaluation failures!"
                            log.warning(alert)
                            self._send_notification(alert)
                    self._write_status()
            else:
                log.debug("Ignoring message type=%s", msg.type)

        log.info("Main loop exited")
        self._write_status()

    def _poll_evaluation_task_http(self) -> None:
        """HTTP polling fallback when WS is unavailable."""
        with self._lock:
            eligible = self._eligible
            paused = self._paused
        if not eligible or paused:
            return
        try:
            with self._platform_lock:
                claim_data = self._platform.claim_evaluation_task()
            if not claim_data:
                return
            msg = WSMessage({"type": "evaluation_task", "data": claim_data})
            self._inc_stat("tasks_received")
            try:
                self._handle_evaluation_task(msg, via_http=True)
            except Exception as eval_exc:
                self._inc_stat("errors")
                self._inc_stat("consecutive_failures")
                log.error("HTTP fallback eval failed: %s", eval_exc)
                self._write_status()
        except Exception as exc:
            error_str = str(exc)
            if "404" not in error_str and "409" not in error_str:
                log.warning("HTTP poll claim failed: %s", exc)

    def _handle_evaluation_task(self, msg: WSMessage, *, via_http: bool = False) -> None:
        """Process a single evaluation task assignment."""
        assignment_id = msg.assignment_id
        task_id = msg.task_id
        submission_id = msg.submission_id

        # Step 1: ACK (HTTP claim is implicit ACK, WS needs explicit ACK)
        if not via_http:
            self._ws.send_ack_eval(assignment_id)
        log.info("Task claimed: assignment=%s task=%s http=%s", assignment_id, task_id, via_http)

        # Step 2: Extract evaluation data from claim payload or fetch via HTTP
        claim_data = msg.data
        dataset_id = str(claim_data.get("dataset_id") or "")
        cleaned_data = str(claim_data.get("cleaned_data") or "")
        repeat_cleaned_data = str(claim_data.get("repeat_cleaned_data") or "")
        structured_data = claim_data.get("structured_data") or {}
        schema_fields = claim_data.get("schema_fields") or []
        dataset_schema = claim_data.get("dataset_schema") or {}

        # Fallback: fetch task details via HTTP if claim payload is incomplete
        if not cleaned_data or not structured_data:
            try:
                task_detail = self._platform.get_evaluation_task(task_id)
                if isinstance(task_detail, dict):
                    cleaned_data = cleaned_data or str(task_detail.get("cleaned_data") or "")
                    repeat_cleaned_data = repeat_cleaned_data or str(task_detail.get("repeat_cleaned_data") or "")
                    structured_data = structured_data or task_detail.get("structured_data") or {}
                    if not schema_fields:
                        schema_fields = task_detail.get("schema_fields") or []
                    if not dataset_schema:
                        dataset_schema = task_detail.get("dataset_schema") or {}
            except Exception as exc:
                log.warning("Fallback fetch for task %s failed: %s", task_id, exc)

        if not isinstance(structured_data, dict):
            structured_data = {}
        if not isinstance(schema_fields, list):
            schema_fields = list(schema_fields) if schema_fields else []
        if not isinstance(dataset_schema, dict):
            dataset_schema = {}

        # Step 3: Evaluate (M0 vs M1 comparison + quality scoring)
        eval_result: EvaluationResult = self._engine.evaluate(
            cleaned_data, structured_data, schema_fields,
            repeat_cleaned_data=repeat_cleaned_data,
            dataset_schema=dataset_schema,
        )
        self._inc_stat("tasks_evaluated")

        # Step 4: Report with result (match/mismatch) and score
        with self._platform_lock:
            self._platform.report_evaluation(
                task_id, eval_result.score,
                assignment_id=assignment_id,
                result=eval_result.result,
            )

        # Reset consecutive failures on success (#1)
        self._set_stat("consecutive_failures", 0)

        if eval_result.result == "match":
            self._inc_stat("tasks_accepted")
            action = f"match score={eval_result.score} task={task_id}"
            log.info("Evaluation reported: %s", action)
        else:
            self._inc_stat("tasks_rejected")
            action = f"mismatch task={task_id}"
            log.info("Evaluation reported: %s", action)

        self._record_action(action, {
            "type": "evaluation",
            "task_id": task_id,
            "assignment_id": assignment_id,
            "result": eval_result.result,
            "score": eval_result.score,
        })
        self._log_history({
            "type": "evaluation",
            "task_id": task_id,
            "assignment_id": assignment_id,
            "dataset_id": dataset_id,
            "result": eval_result.result,
            "score": eval_result.score,
        })
        self._write_status()

        # Step 5: Wait min_task_interval, then rejoin ready pool
        with self._lock:
            wait_seconds = self._min_task_interval
        log.info("Waiting %ds (min_task_interval) before rejoining ready pool", wait_seconds)
        if self._stop_event.wait(timeout=wait_seconds):
            return
        try:
            with self._platform_lock:
                self._platform.join_ready_pool()
            log.info("Rejoined ready pool")
        except Exception as exc:
            log.warning("Rejoin ready pool failed: %s", exc)

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the platform."""
        while self._running:
            self._send_heartbeat()
            self._write_status()
            if self._stop_event.wait(timeout=self._heartbeat_interval):
                break
        log.info("Heartbeat loop exited")

    def _send_heartbeat(self) -> None:
        """Send a single heartbeat and update runtime state from response."""
        try:
            with self._platform_lock:
                resp = self._platform.send_unified_heartbeat(client_name=f"validator-{self._validator_id}")
            data = resp.get("data") if isinstance(resp, dict) else None
            if isinstance(data, dict):
                validator_info = data.get("validator")
                if isinstance(validator_info, dict):
                    with self._lock:
                        self._eligible = validator_info.get("eligible", True)
                        interval = validator_info.get("min_task_interval_seconds")
                        if isinstance(interval, (int, float)) and interval > 0:
                            self._min_task_interval = int(interval)
                    if not self._eligible:
                        log.warning("Validator not eligible (evicted or suspended)")
            log.debug("Heartbeat sent")
        except Exception as exc:
            log.warning("Heartbeat failed: %s", exc)

