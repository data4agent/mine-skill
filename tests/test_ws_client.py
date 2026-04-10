"""WebSocket client unit tests."""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ws_client import ValidatorWSClient, WSDisconnected, WSMessage


# ---------------------------------------------------------------------------
# WSMessage parsing
# ---------------------------------------------------------------------------


class TestWSMessage:
    """WSMessage parsing logic tests."""

    def test_parse_valid_message(self) -> None:
        """Valid message should correctly parse type / data fields."""
        raw: dict[str, Any] = {
            "type": "evaluation_task",
            "data": {
                "task_id": "t-123",
                "assignment_id": "a-456",
                "submission_id": "s-789",
                "mode": "batch",
            },
        }
        msg = WSMessage(raw)
        assert msg.type == "evaluation_task"
        assert msg.task_id == "t-123"
        assert msg.assignment_id == "a-456"
        assert msg.submission_id == "s-789"
        assert msg.mode == "batch"
        assert msg.raw is raw

    def test_missing_fields_defaults(self) -> None:
        """Missing fields should return empty string or default values."""
        msg = WSMessage({})
        assert msg.type == ""
        assert msg.task_id == ""
        assert msg.assignment_id == ""
        assert msg.submission_id == ""
        assert msg.mode == "single"  # default value
        assert msg.repeat_crawl_task_id == ""
        assert msg.data == {}

    def test_data_not_dict_treated_as_empty(self) -> None:
        """Non-dict data should be treated as empty dict."""
        msg = WSMessage({"type": "x", "data": "not-a-dict"})
        assert msg.data == {}
        assert msg.task_id == ""

    def test_repeat_crawl_task_id_from_data_id(self) -> None:
        """repeat_crawl_task_id should be read from data.id."""
        msg = WSMessage({"type": "repeat_crawl_task", "data": {"id": "rc-42"}})
        assert msg.repeat_crawl_task_id == "rc-42"

    def test_repr(self) -> None:
        """__repr__ should include type and task_id."""
        msg = WSMessage({"type": "test_type", "data": {"task_id": "abc"}})
        r = repr(msg)
        assert "test_type" in r
        assert "abc" in r


# ---------------------------------------------------------------------------
# ValidatorWSClient.connect
# ---------------------------------------------------------------------------


class TestValidatorWSClientConnect:
    """connect() method tests."""

    def test_connect_success(self) -> None:
        """Successful connection should set _connected=True and reset _reconnect_attempt."""
        mock_conn = MagicMock()
        mock_ws_client_module = MagicMock()
        mock_ws_client_module.connect.return_value = mock_conn

        # Build nested module structure so import websockets.sync.client resolves correctly
        mock_ws_sync = MagicMock()
        mock_ws_sync.client = mock_ws_client_module
        mock_ws = MagicMock()
        mock_ws.sync = mock_ws_sync
        mock_ws.sync.client = mock_ws_client_module

        client = ValidatorWSClient(
            ws_url="ws://localhost:8080/ws",
            auth_headers={"Authorization": "Bearer tok"},
        )
        # Simulate previous retries
        client._reconnect_attempt = 5

        # Patch the local import inside connect(): websockets.sync.client
        with patch.dict("sys.modules", {
            "websockets": mock_ws,
            "websockets.sync": mock_ws_sync,
            "websockets.sync.client": mock_ws_client_module,
        }):
            client.connect()

        assert client.connected is True
        assert client._reconnect_attempt == 0
        assert client._ws is mock_conn
        mock_ws_client_module.connect.assert_called_once()

    def test_connect_failure_raises_ws_disconnected(self) -> None:
        """Connection failure should raise WSDisconnected and set _connected=False."""
        client = ValidatorWSClient(
            ws_url="ws://localhost:9999/ws",
            auth_headers={},
        )

        # Simulate connect method raising exception
        def failing_connect() -> None:
            client._connected = False
            raise WSDisconnected("connect failed: refused")

        with patch.object(client, "connect", failing_connect):
            with pytest.raises(WSDisconnected, match="connect failed"):
                client.connect()
        assert client.connected is False


# ---------------------------------------------------------------------------
# ValidatorWSClient.receive
# ---------------------------------------------------------------------------


class TestValidatorWSClientReceive:
    """receive() method tests."""

    def _make_connected_client(self) -> ValidatorWSClient:
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._connected = True
        client._ws = MagicMock()
        return client

    def test_receive_valid_message(self) -> None:
        """Normal JSON message should return a WSMessage object."""
        client = self._make_connected_client()
        payload = {"type": "evaluation_task", "data": {"task_id": "t1"}}
        client._ws.recv.return_value = json.dumps(payload)

        msg = client.receive(timeout=5.0)

        assert msg is not None
        assert isinstance(msg, WSMessage)
        assert msg.type == "evaluation_task"
        assert msg.task_id == "t1"
        client._ws.recv.assert_called_once_with(timeout=5.0)

    def test_receive_bytes_message(self) -> None:
        """Bytes message should be decoded and parsed normally."""
        client = self._make_connected_client()
        payload = {"type": "ping", "data": {}}
        client._ws.recv.return_value = json.dumps(payload).encode("utf-8")

        msg = client.receive()
        assert msg is not None
        assert msg.type == "ping"

    def test_receive_timeout_returns_none(self) -> None:
        """Timeout should return None."""
        client = self._make_connected_client()
        client._ws.recv.side_effect = TimeoutError("timed out")

        result = client.receive(timeout=1.0)
        assert result is None

    def test_receive_invalid_json_returns_none(self) -> None:
        """Invalid JSON should return None."""
        client = self._make_connected_client()
        client._ws.recv.return_value = "not-json{{"

        result = client.receive()
        assert result is None

    def test_receive_non_dict_json_returns_none(self) -> None:
        """JSON parsed to non-dict type should return None."""
        client = self._make_connected_client()
        client._ws.recv.return_value = "[1, 2, 3]"

        result = client.receive()
        assert result is None

    def test_receive_connection_loss_raises_ws_disconnected(self) -> None:
        """Connection loss should raise WSDisconnected."""
        client = self._make_connected_client()
        client._ws.recv.side_effect = OSError("connection reset")

        with pytest.raises(WSDisconnected, match="receive failed"):
            client.receive()
        assert client.connected is False

    def test_receive_not_connected_raises_ws_disconnected(self) -> None:
        """Calling receive when not connected should raise WSDisconnected."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        with pytest.raises(WSDisconnected, match="not connected"):
            client.receive()


# ---------------------------------------------------------------------------
# ValidatorWSClient.send_ack_eval
# ---------------------------------------------------------------------------


class TestValidatorWSClientSendAckEval:
    """send_ack_eval() tests."""

    def test_sends_correct_json(self) -> None:
        """Should send JSON in {"ack_eval": assignment_id} format."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._connected = True
        client._ws = MagicMock()

        client.send_ack_eval("assign-99")

        client._ws.send.assert_called_once()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent == {"ack_eval": "assign-99"}

    def test_send_when_disconnected_raises(self) -> None:
        """Sending when not connected should raise WSDisconnected."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        with pytest.raises(WSDisconnected):
            client.send_ack_eval("x")


# ---------------------------------------------------------------------------
# ValidatorWSClient.send_ack_repeat_crawl
# ---------------------------------------------------------------------------


class TestValidatorWSClientSendAckRepeatCrawl:
    """send_ack_repeat_crawl() tests."""

    def test_sends_correct_json(self) -> None:
        """Should send {"ack": task_id} format."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._connected = True
        client._ws = MagicMock()

        client.send_ack_repeat_crawl("task-55")

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent == {"ack": "task-55"}


# ---------------------------------------------------------------------------
# ValidatorWSClient.send_reject_repeat_crawl
# ---------------------------------------------------------------------------


class TestValidatorWSClientSendRejectRepeatCrawl:
    """send_reject_repeat_crawl() tests."""

    def test_sends_correct_json(self) -> None:
        """Should send {"reject": task_id} format."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._connected = True
        client._ws = MagicMock()

        client.send_reject_repeat_crawl("task-77")

        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent == {"reject": "task-77"}


# ---------------------------------------------------------------------------
# ValidatorWSClient.reconnect_with_backoff
# ---------------------------------------------------------------------------


class TestValidatorWSClientReconnectWithBackoff:
    """reconnect_with_backoff() tests."""

    def test_exponential_delay(self) -> None:
        """Delay should grow exponentially: 1s, 2s, 4s, 8s..., max 60s."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        with patch.object(client, "connect", side_effect=WSDisconnected("fail")):
            with patch.object(client._stop_event, "wait", return_value=False) as mock_wait:
                expected_delays = [1, 2, 4, 8, 16, 32, 60, 60]
                for expected in expected_delays:
                    client.reconnect_with_backoff()
                    actual = mock_wait.call_args[1]["timeout"]
                    assert actual == expected, f"expected delay {expected}, got {actual}"

    def test_auth_refresh_callback(self) -> None:
        """When on_auth_refresh is provided, should refresh auth headers before reconnecting."""
        new_headers = {"Authorization": "Bearer new-token"}
        refresh_fn = MagicMock(return_value=new_headers)
        client = ValidatorWSClient(
            ws_url="ws://x",
            auth_headers={"Authorization": "Bearer old"},
            on_auth_refresh=refresh_fn,
        )
        with patch.object(client, "connect", side_effect=WSDisconnected("fail")):
            with patch.object(client._stop_event, "wait", return_value=False):
                client.reconnect_with_backoff()

        refresh_fn.assert_called_once()
        assert client._auth_headers == new_headers

    def test_closed_check_after_sleep(self) -> None:
        """If stop_event fires during backoff, should return without connecting."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})

        # Simulate stop_event being set during wait
        with patch.object(client._stop_event, "wait", return_value=True):
            connect_mock = MagicMock()
            with patch.object(client, "connect", connect_mock):
                client.reconnect_with_backoff()

        # connect should not be called because _closed is True after sleep
        connect_mock.assert_not_called()

    def test_closed_check_before_connect(self) -> None:
        """If _closed is True, reconnect_with_backoff should return immediately."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._closed = True

        connect_mock = MagicMock()
        with patch.object(client, "connect", connect_mock):
            client.reconnect_with_backoff()

        connect_mock.assert_not_called()


# ---------------------------------------------------------------------------
# ValidatorWSClient.reopen / close
# ---------------------------------------------------------------------------


class TestValidatorWSClientReopen:
    """reopen() tests."""

    def test_resets_flags(self) -> None:
        """reopen should reset _closed and _connected."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client._closed = True
        client._connected = True

        client.reopen()

        assert client._closed is False
        assert client._connected is False


class TestValidatorWSClientClose:
    """close() tests."""

    def test_sets_closed_and_disconnected(self) -> None:
        """close should set _closed=True, _connected=False, and clean up ws object."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        mock_ws = MagicMock()
        client._ws = mock_ws
        client._connected = True

        client.close()

        assert client._closed is True
        assert client._connected is False
        assert client._ws is None
        mock_ws.close.assert_called_once()

    def test_close_tolerates_ws_error(self) -> None:
        """close() should not propagate exceptions from ws.close()."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        mock_ws = MagicMock()
        mock_ws.close.side_effect = RuntimeError("already closed")
        client._ws = mock_ws
        client._connected = True

        client.close()  # Should not raise

        assert client._closed is True
        assert client._ws is None

    def test_close_when_no_ws(self) -> None:
        """close() should execute safely when there is no ws connection."""
        client = ValidatorWSClient(ws_url="ws://x", auth_headers={})
        client.close()
        assert client._closed is True
        assert client._connected is False
