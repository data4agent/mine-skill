"""WebSocket client for receiving evaluation task assignments from the platform."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("validator.ws")


class WSDisconnected(Exception):
    """Raised when the WebSocket connection is lost."""


class WSMessage:
    """Parsed WebSocket message from the platform."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.type: str = str(raw.get("type") or "")
        self.data: dict[str, Any] = raw.get("data") if isinstance(raw.get("data"), dict) else {}

    @property
    def task_id(self) -> str:
        return str(self.data.get("task_id") or "")

    @property
    def assignment_id(self) -> str:
        return str(self.data.get("assignment_id") or "")

    @property
    def submission_id(self) -> str:
        return str(self.data.get("submission_id") or "")

    @property
    def mode(self) -> str:
        return str(self.data.get("mode") or "single")

    def __repr__(self) -> str:
        return f"WSMessage(type={self.type!r}, task_id={self.task_id!r}, assignment_id={self.assignment_id!r})"


class ValidatorWSClient:
    """
    Manages WebSocket connection to the platform for receiving evaluation tasks.

    Protocol:
      Server -> Client: {"type": "evaluation_task", "data": {task_id, assignment_id, submission_id, mode}}
      Client -> Server: {"ack_eval": "<assignment_id>"}  (must be sent within 30s)

    Reconnection:
      Uses exponential backoff: 1s -> 2s -> 4s -> ... -> 60s max.
      On auth failure (401), refreshes wallet session before reconnecting.
    """

    def __init__(
        self,
        *,
        ws_url: str,
        auth_headers: dict[str, str],
        on_auth_refresh: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._auth_headers = auth_headers
        self._on_auth_refresh = on_auth_refresh
        self._ws: Any = None  # websockets connection object
        self._connected = False
        self._reconnect_attempt = 0
        self._max_backoff = 60
        self._lock = threading.Lock()
        self._closed = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Establish WebSocket connection with auth headers."""
        import websockets.sync.client as ws_sync

        try:
            extra_headers = dict(self._auth_headers)
            self._ws = ws_sync.connect(
                self._ws_url,
                additional_headers=extra_headers,
                open_timeout=15,
                close_timeout=5,
            )
            self._connected = True
            self._reconnect_attempt = 0
            log.info("WebSocket connected to %s", self._ws_url)
        except Exception as exc:
            self._connected = False
            log.error("WebSocket connect failed: %s", exc)
            raise WSDisconnected(f"connect failed: {exc}") from exc

    def close(self) -> None:
        """Close the WebSocket connection."""
        self._closed = True
        self._connected = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def send_ack_eval(self, assignment_id: str) -> None:
        """Send evaluation task acknowledgment. Must be called within 30s of receiving task."""
        self._send({"ack_eval": assignment_id})
        log.info("Sent ack_eval for assignment %s", assignment_id)

    def receive(self, timeout: float = 30.0) -> WSMessage | None:
        """
        Receive next message from WebSocket.
        Returns None on timeout, raises WSDisconnected on connection loss.
        """
        if not self._connected or self._ws is None:
            raise WSDisconnected("not connected")
        try:
            raw = self._ws.recv(timeout=timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                log.warning("Received non-dict message: %s", raw[:200])
                return None
            msg = WSMessage(data)
            log.debug("Received: %s", msg)
            return msg
        except TimeoutError:
            return None
        except json.JSONDecodeError as exc:
            log.warning("Invalid JSON from WebSocket: %s", exc)
            return None
        except Exception as exc:
            self._connected = False
            raise WSDisconnected(f"receive failed: {exc}") from exc

    def reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff. Refreshes auth if needed."""
        if self._closed:
            return

        self._reconnect_attempt += 1
        delay = min(2 ** self._reconnect_attempt, self._max_backoff)
        log.info(
            "Reconnecting in %ds (attempt %d)...",
            delay,
            self._reconnect_attempt,
        )
        time.sleep(delay)

        # Refresh auth headers if callback provided
        if self._on_auth_refresh is not None:
            try:
                self._auth_headers = self._on_auth_refresh()
                log.info("Auth headers refreshed for reconnection")
            except Exception as exc:
                log.warning("Auth refresh failed: %s", exc)

        try:
            self.connect()
        except WSDisconnected:
            log.warning("Reconnect attempt %d failed", self._reconnect_attempt)

    def _send(self, data: dict[str, Any]) -> None:
        if not self._connected or self._ws is None:
            raise WSDisconnected("not connected")
        try:
            self._ws.send(json.dumps(data))
        except Exception as exc:
            self._connected = False
            raise WSDisconnected(f"send failed: {exc}") from exc
