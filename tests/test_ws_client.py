"""Tests for WebSocket client."""
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, "scripts")

from ws_client import WSMessage, ValidatorWSClient, WSDisconnected


class TestWSMessage:
    def test_parse_evaluation_task(self):
        raw = {
            "type": "evaluation_task",
            "data": {
                "task_id": "task_001",
                "assignment_id": "asg_001",
                "submission_id": "sub_001",
                "mode": "single",
            }
        }
        msg = WSMessage(raw)

        assert msg.type == "evaluation_task"
        assert msg.task_id == "task_001"
        assert msg.assignment_id == "asg_001"
        assert msg.submission_id == "sub_001"
        assert msg.mode == "single"

    def test_handles_missing_data(self):
        raw = {"type": "heartbeat"}
        msg = WSMessage(raw)

        assert msg.type == "heartbeat"
        assert msg.task_id == ""
        assert msg.data == {}


class TestValidatorWSClient:
    def test_send_ack_eval(self):
        client = ValidatorWSClient(
            ws_url="ws://test/ws",
            auth_headers={"X-Signer": "0xabc"},
        )
        client._ws = MagicMock()
        client._connected = True

        client.send_ack_eval("asg_001")

        client._ws.send.assert_called_once()
        call_arg = client._ws.send.call_args[0][0]
        assert '"ack_eval": "asg_001"' in call_arg

    def test_raises_when_not_connected(self):
        client = ValidatorWSClient(
            ws_url="ws://test/ws",
            auth_headers={},
        )
        client._connected = False

        with pytest.raises(WSDisconnected, match="not connected"):
            client.send_ack_eval("asg_001")
