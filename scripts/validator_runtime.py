"""ValidatorRuntime – main event loop for the validator agent."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from common import (
    resolve_eval_timeout,
    resolve_validator_id,
)
from evaluation_engine import EvaluationEngine, EvaluationResult
from ws_client import ValidatorWSClient, WSDisconnected, WSMessage

log = logging.getLogger("validator.runtime")

HEARTBEAT_INTERVAL = 55
WS_RECEIVE_TIMEOUT = 30.0


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
    ) -> None:
        self._platform = platform_client
        self._ws = ws_client
        self._engine = engine or EvaluationEngine(timeout=resolve_eval_timeout())
        self._validator_id = validator_id or resolve_validator_id()
        self._heartbeat_interval = heartbeat_interval

        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None
        self._main_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._stats: dict[str, int] = {
            "tasks_received": 0,
            "tasks_evaluated": 0,
            "tasks_accepted": 0,
            "tasks_rejected": 0,
            "errors": 0,
        }
        # Dynamically updated from heartbeat response
        self._eligible = True
        self._min_task_interval = 30

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

        # Check validator application status
        try:
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
                self._platform.submit_validator_application()
                log.info("Validator application submitted, waiting for approval")
                with self._lock:
                    self._running = False
                return self.status()
        except Exception as exc:
            log.warning("Validator application check failed: %s (proceeding anyway)", exc)

        try:
            self._ws.connect()
        except WSDisconnected:
            log.warning("Initial WS connect failed; will retry in main loop")

        try:
            self._platform.join_ready_pool()
            log.info("Joined validator ready pool")
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
            self._platform.leave_ready_pool()
        except Exception as exc:
            log.warning("leave_ready_pool failed: %s", exc)

        self._ws.close()

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=10)
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=10)

        return self.status()

    def pause(self) -> dict[str, Any]:
        """Pause evaluation processing (heartbeat continues)."""
        with self._lock:
            self._paused = True
        log.info("ValidatorRuntime paused")
        return self.status()

    def resume(self) -> dict[str, Any]:
        """Resume evaluation processing."""
        with self._lock:
            self._paused = False
        log.info("ValidatorRuntime resumed")
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
            "stats": dict(self._stats),
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

            if msg.type == "evaluation_task":
                self._stats["tasks_received"] += 1
                if not self._eligible:
                    log.info("Not eligible — ignoring evaluation_task %s", msg.assignment_id)
                    continue
                if self._paused:
                    log.info("Paused — ignoring evaluation_task %s", msg.assignment_id)
                    continue
                try:
                    self._handle_evaluation_task(msg)
                except Exception as exc:
                    self._stats["errors"] += 1
                    log.error("Error handling evaluation task %s: %s", msg.assignment_id, exc)
            else:
                log.debug("Ignoring message type=%s", msg.type)

        log.info("Main loop exited")

    def _poll_evaluation_task_http(self) -> None:
        """HTTP polling fallback when WS is unavailable."""
        if not self._eligible or self._paused:
            return
        try:
            claim_data = self._platform.claim_evaluation_task()
            if not claim_data:
                return
            msg = WSMessage({"type": "evaluation_task", "data": claim_data})
            self._stats["tasks_received"] += 1
            self._handle_evaluation_task(msg, via_http=True)
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

        # Step 2: Fetch task details and submission
        task_details = self._platform.get_evaluation_task(task_id)
        submission = self._platform.fetch_core_submission(submission_id)

        cleaned_data = submission.get("cleaned_data") or submission.get("raw_data") or ""
        structured_data = submission.get("structured_data") or {}
        schema_fields = self._extract_schema_fields(task_details)

        # Step 3: Evaluate
        result: EvaluationResult = self._engine.evaluate(
            cleaned_data, structured_data, schema_fields
        )
        self._stats["tasks_evaluated"] += 1

        # Step 4/5: Report based on consistency
        if result.consistent:
            self._platform.report_evaluation(task_id, result.score, assignment_id=assignment_id)
            self._stats["tasks_accepted"] += 1
            log.info(
                "Evaluation reported: task=%s score=%d verdict=%s",
                task_id, result.score, result.verdict,
            )
        else:
            idempotency_key = f"val-{self._validator_id}-{submission_id}-{uuid.uuid4().hex[:8]}"
            self._platform.create_validation_result(
                submission_id, "rejected", 0, result.reason, idempotency_key
            )
            self._platform.report_evaluation(task_id, 0, assignment_id=assignment_id)
            self._stats["tasks_rejected"] += 1
            log.info(
                "Evaluation rejected: task=%s reason=%s",
                task_id, result.reason[:120],
            )

        # Step 6: Wait min_task_interval, then rejoin ready pool
        wait_seconds = self._min_task_interval
        log.info("Waiting %ds (min_task_interval) before rejoining ready pool", wait_seconds)
        if self._stop_event.wait(timeout=wait_seconds):
            return
        try:
            self._platform.join_ready_pool()
            log.info("Rejoined ready pool")
        except Exception as exc:
            log.warning("Rejoin ready pool failed: %s", exc)

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the platform."""
        while self._running:
            self._send_heartbeat()
            if self._stop_event.wait(timeout=self._heartbeat_interval):
                break
        log.info("Heartbeat loop exited")

    def _send_heartbeat(self) -> None:
        """Send a single heartbeat and update runtime state from response."""
        try:
            resp = self._platform.send_unified_heartbeat(client_name=f"validator-{self._validator_id}")
            data = resp.get("data") if isinstance(resp, dict) else None
            if isinstance(data, dict):
                validator_info = data.get("validator")
                if isinstance(validator_info, dict):
                    self._eligible = validator_info.get("eligible", True)
                    interval = validator_info.get("min_task_interval_seconds")
                    if isinstance(interval, (int, float)) and interval > 0:
                        self._min_task_interval = int(interval)
                    if not self._eligible:
                        log.warning("Validator not eligible (evicted or suspended)")
            log.debug("Heartbeat sent")
        except Exception as exc:
            log.warning("Heartbeat failed: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_schema_fields(task_details: dict[str, Any]) -> list[str]:
        """Extract schema field names from task details."""
        schema = task_details.get("schema") or {}
        if isinstance(schema, dict):
            fields = schema.get("fields")
            if isinstance(fields, list):
                return [str(f) for f in fields if f]
            props = schema.get("properties")
            if isinstance(props, dict):
                return list(props.keys())
        return []
