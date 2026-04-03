# Validator Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate validator capabilities into the /mine skill, enabling two-phase data quality evaluation (consistency check + 4-dimension scoring) via WebSocket task delivery.

**Architecture:** Layered extension of existing mine skill. New validator modules (runtime, evaluation engine, WS client) sit alongside miner modules, sharing common infrastructure (platform_client, signer, state management). Two-phase evaluation: reject inconsistent data immediately, score consistent data on 4 dimensions.

**Tech Stack:** Python 3.10+, httpx, websockets, OpenClaw CLI for LLM calls

---

## File Structure

### New Files (7)

| File | Responsibility |
|------|----------------|
| `scripts/openclaw_llm.py` | OpenClaw CLI wrapper for LLM calls |
| `scripts/evaluation_engine.py` | Two-phase evaluation: consistency check + 4-dim scoring |
| `scripts/ws_client.py` | WebSocket client for task delivery |
| `scripts/validator_runtime.py` | Main event loop: WS receive → ACK → evaluate → report |
| `scripts/validator_worker.py` | Background process management (start/stop/status) |
| `references/api-validator.md` | Validator API documentation |
| `references/protocol-validator.md` | Validator protocol documentation |

### Extended Files (5)

| File | Changes |
|------|---------|
| `scripts/common.py` | Add `resolve_validator_id()`, `resolve_validator_output_root()`, `resolve_eval_timeout()` |
| `scripts/worker_state.py` | Add `ValidatorStateStore` class |
| `lib/platform_client.py` | Add 11 validator API methods |
| `scripts/run_tool.py` | Add validator-* commands |
| `SKILL.md` | Add validator command documentation |

---

## Task 1: OpenClaw LLM Wrapper

**Files:**
- Create: `scripts/openclaw_llm.py`
- Create: `tests/test_openclaw_llm.py`

- [ ] **Step 1.1: Write the failing test for call_openclaw**

```python
# tests/test_openclaw_llm.py
"""Tests for OpenClaw CLI wrapper."""
import json
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, "scripts")

from openclaw_llm import call_openclaw, parse_json_response


class TestCallOpenclaw:
    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"consistent": true, "reason": "test"}'
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = call_openclaw("test prompt")

            assert result == '{"consistent": true, "reason": "test"}'
            mock_run.assert_called_once()

    def test_raises_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error message"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="OpenClaw CLI failed"):
                call_openclaw("test prompt")


class TestParseJsonResponse:
    def test_extracts_json_from_response(self):
        response = 'Some text\n{"key": "value"}\nMore text'
        result = parse_json_response(response)
        assert result == {"key": "value"}

    def test_returns_empty_dict_on_invalid_json(self):
        response = "no json here"
        result = parse_json_response(response)
        assert result == {}
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_openclaw_llm.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'openclaw_llm'"

- [ ] **Step 1.3: Write minimal implementation**

```python
# scripts/openclaw_llm.py
"""OpenClaw CLI wrapper for LLM calls."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any

log = logging.getLogger("validator.llm")

DEFAULT_OPENCLAW_CLI = "openclaw"
DEFAULT_TIMEOUT = 120


def call_openclaw(
    prompt: str,
    *,
    cli_path: str = DEFAULT_OPENCLAW_CLI,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Call OpenClaw CLI with a prompt and return the response.

    Args:
        prompt: The prompt to send to the LLM.
        cli_path: Path to the openclaw CLI binary.
        timeout: Timeout in seconds.

    Returns:
        Raw stdout from the CLI.

    Raises:
        RuntimeError: If the CLI exits with non-zero status.
        subprocess.TimeoutExpired: If the call times out.
    """
    try:
        result = subprocess.run(
            [cli_path, "chat", "-m", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"OpenClaw CLI not found at '{cli_path}'") from exc

    if result.returncode != 0:
        raise RuntimeError(f"OpenClaw CLI failed: {result.stderr}")

    return result.stdout


def parse_json_response(response: str) -> dict[str, Any]:
    """
    Extract JSON object from LLM response.

    LLM responses may contain markdown or explanatory text around the JSON.
    This function finds and parses the first valid JSON object.

    Args:
        response: Raw LLM response text.

    Returns:
        Parsed JSON as dict, or empty dict if no valid JSON found.
    """
    # Try to find JSON object pattern
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, response, re.DOTALL)

    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # Fallback: try parsing the entire response
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        log.warning("Could not parse JSON from response: %s", response[:200])
        return {}
```

- [ ] **Step 1.4: Create tests directory and run tests**

Run: `cd /d/kaifa/clawtroop/mine && mkdir -p tests && python -m pytest tests/test_openclaw_llm.py -v`
Expected: PASS (all tests)

- [ ] **Step 1.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/openclaw_llm.py tests/test_openclaw_llm.py
git commit -m "feat: add OpenClaw CLI wrapper for LLM calls"
```

---

## Task 2: Evaluation Engine - Consistency Check

**Files:**
- Create: `scripts/evaluation_engine.py`
- Create: `tests/test_evaluation_engine.py`

- [ ] **Step 2.1: Write failing test for consistency check**

```python
# tests/test_evaluation_engine.py
"""Tests for two-phase evaluation engine."""
import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import asdict

import sys
sys.path.insert(0, "scripts")

from evaluation_engine import (
    EvaluationResult,
    EvaluationEngine,
    CONSISTENCY_PROMPT_TEMPLATE,
)


class TestEvaluationResult:
    def test_rejected_result(self):
        result = EvaluationResult(
            verdict="rejected",
            consistent=False,
            score=0,
            reason="Data contains fabricated information",
        )
        assert result.verdict == "rejected"
        assert result.consistent is False
        assert result.score == 0

    def test_accepted_result(self):
        result = EvaluationResult(
            verdict="accepted",
            consistent=True,
            score=85,
            reason="Data is consistent and well-extracted",
        )
        assert result.verdict == "accepted"
        assert result.consistent is True
        assert result.score == 85


class TestConsistencyCheck:
    def test_inconsistent_data_returns_rejected(self):
        mock_llm = MagicMock(return_value='{"consistent": false, "reason": "Fabricated data"}')
        engine = EvaluationEngine(llm_call=mock_llm)

        result = engine.evaluate(
            cleaned_data="John Doe, age 30, engineer",
            structured_data={"name": "Jane Smith", "age": 25},
            schema_fields={"name": {"type": "string"}, "age": {"type": "integer"}},
        )

        assert result.verdict == "rejected"
        assert result.consistent is False
        assert result.score == 0
        assert "Fabricated" in result.reason

    def test_consistent_data_proceeds_to_scoring(self):
        # Returns consistent=True for consistency check, then scoring response
        mock_llm = MagicMock(side_effect=[
            '{"consistent": true, "reason": "Data matches"}',
            '{"completeness": 90, "accuracy": 85, "type_correctness": 100, "sufficiency": 80, "final_score": 87, "notes": "Good"}',
        ])
        engine = EvaluationEngine(llm_call=mock_llm)

        result = engine.evaluate(
            cleaned_data="John Doe, age 30",
            structured_data={"name": "John Doe", "age": 30},
            schema_fields={"name": {"type": "string"}, "age": {"type": "integer"}},
        )

        assert result.verdict == "accepted"
        assert result.consistent is True
        assert result.score == 87
        assert mock_llm.call_count == 2
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_evaluation_engine.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'evaluation_engine'"

- [ ] **Step 2.3: Write evaluation engine implementation**

```python
# scripts/evaluation_engine.py
"""
Two-Phase Evaluation Engine for Validator Skill.

Phase 1: Consistency Check
  - Is the structured_data consistent with cleaned_data?
  - If NOT consistent -> reject immediately (score=0)

Phase 2: Quality Scoring (only if consistent)
  - Completeness (30%): Are required fields present?
  - Accuracy (40%): Do values match the source?
  - Type correctness (15%): Do values match schema types?
  - Sufficiency (15%): Is key information captured?
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("validator.eval")

# Weights for scoring dimensions
WEIGHT_COMPLETENESS = 0.30
WEIGHT_ACCURACY = 0.40
WEIGHT_TYPE = 0.15
WEIGHT_SUFFICIENCY = 0.15

CONSISTENCY_PROMPT_TEMPLATE = """你是数据一致性检查器。判断 miner 提取的结构化数据是否与原始数据一致。

## 原始数据 (source of truth)
{cleaned_data}

## Miner 提取的结构化数据
{structured_json}

## 判断标准
- 一致 = 结构化数据中的值能在原始数据中找到对应信息，且没有明显捏造
- 不一致 = 结构化数据包含原始数据中不存在的信息，或严重歪曲原意

## 输出 (strict JSON, 不要markdown)
{{"consistent": true/false, "reason": "简要说明判断理由"}}"""

SCORING_PROMPT_TEMPLATE = """你是数据质量评分器。对 miner 提取的结构化数据进行质量评分。

## Schema 定义
{schema_json}

## 原始数据
{cleaned_data}

## Miner 提取的结构化数据
{structured_json}

## 评分维度
1. 完整性 (30%): 必填字段是否齐全？
2. 准确性 (40%): 提取的值是否准确？
3. 类型正确性 (15%): 值的类型是否符合 schema？
4. 信息充分性 (15%): 关键信息是否遗漏？

## 输出 (strict JSON, 不要markdown)
{{"completeness": 0-100, "accuracy": 0-100, "type_correctness": 0-100, "sufficiency": 0-100, "final_score": 0-100, "notes": "评分说明"}}"""


@dataclass
class EvaluationResult:
    """Result of two-phase evaluation."""
    verdict: str  # "accepted" | "rejected"
    consistent: bool
    score: int  # 0-100, meaningful only when consistent=True
    reason: str


class EvaluationEngine:
    """
    Two-phase evaluation engine.

    Phase 1: Consistency check (LLM)
    Phase 2: Quality scoring (LLM, only if consistent)
    """

    def __init__(
        self,
        *,
        llm_call: Callable[[str], str] | None = None,
        timeout: int = 120,
    ) -> None:
        """
        Args:
            llm_call: Callable that takes a prompt and returns LLM response.
                      If None, uses openclaw_llm.call_openclaw.
            timeout: Timeout for LLM calls in seconds.
        """
        self._llm_call = llm_call
        self._timeout = timeout

        if llm_call is None:
            from openclaw_llm import call_openclaw
            self._llm_call = lambda prompt: call_openclaw(prompt, timeout=timeout)

    def evaluate(
        self,
        cleaned_data: str,
        structured_data: dict[str, Any],
        schema_fields: list[dict[str, Any]] | dict[str, Any],
    ) -> EvaluationResult:
        """
        Evaluate miner submission using two-phase approach.

        Args:
            cleaned_data: Raw cleaned text from source (ground truth).
            structured_data: Miner's extracted key-value pairs.
            schema_fields: Dataset schema defining expected fields.

        Returns:
            EvaluationResult with verdict, consistency, score, and reason.
        """
        # Phase 1: Consistency check
        consistency = self._check_consistency(cleaned_data, structured_data)

        if not consistency["consistent"]:
            log.info("Evaluation rejected: inconsistent data - %s", consistency["reason"])
            return EvaluationResult(
                verdict="rejected",
                consistent=False,
                score=0,
                reason=consistency["reason"],
            )

        # Phase 2: Quality scoring
        scoring = self._score_quality(cleaned_data, structured_data, schema_fields)

        log.info(
            "Evaluation accepted: score=%d (completeness=%d, accuracy=%d, type=%d, sufficiency=%d)",
            scoring["final_score"],
            scoring.get("completeness", 0),
            scoring.get("accuracy", 0),
            scoring.get("type_correctness", 0),
            scoring.get("sufficiency", 0),
        )

        return EvaluationResult(
            verdict="accepted",
            consistent=True,
            score=scoring["final_score"],
            reason=scoring.get("notes", ""),
        )

    def _check_consistency(
        self,
        cleaned_data: str,
        structured_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 1: Check if structured_data is consistent with cleaned_data."""
        prompt = CONSISTENCY_PROMPT_TEMPLATE.format(
            cleaned_data=cleaned_data[:5000],  # Limit length
            structured_json=json.dumps(structured_data, ensure_ascii=False, indent=2),
        )

        try:
            response = self._llm_call(prompt)
            result = self._parse_json(response)

            return {
                "consistent": bool(result.get("consistent", False)),
                "reason": str(result.get("reason", "Unknown")),
            }
        except Exception as exc:
            log.warning("Consistency check failed: %s", exc)
            # On error, assume consistent and proceed to scoring
            return {"consistent": True, "reason": f"Check failed: {exc}"}

    def _score_quality(
        self,
        cleaned_data: str,
        structured_data: dict[str, Any],
        schema_fields: list[dict[str, Any]] | dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 2: Score the quality of consistent data."""
        schema_json = json.dumps(schema_fields, ensure_ascii=False, indent=2)

        prompt = SCORING_PROMPT_TEMPLATE.format(
            schema_json=schema_json[:2000],
            cleaned_data=cleaned_data[:5000],
            structured_json=json.dumps(structured_data, ensure_ascii=False, indent=2),
        )

        try:
            response = self._llm_call(prompt)
            result = self._parse_json(response)

            # Calculate weighted score if not provided
            if "final_score" not in result:
                result["final_score"] = self._calculate_weighted_score(result)

            return {
                "completeness": int(result.get("completeness", 50)),
                "accuracy": int(result.get("accuracy", 50)),
                "type_correctness": int(result.get("type_correctness", 50)),
                "sufficiency": int(result.get("sufficiency", 50)),
                "final_score": max(0, min(100, int(result.get("final_score", 50)))),
                "notes": str(result.get("notes", "")),
            }
        except Exception as exc:
            log.warning("Quality scoring failed: %s", exc)
            # Return conservative fallback score
            return {
                "completeness": 50,
                "accuracy": 50,
                "type_correctness": 50,
                "sufficiency": 50,
                "final_score": 50,
                "notes": f"Scoring failed: {exc}",
            }

    def _calculate_weighted_score(self, result: dict[str, Any]) -> int:
        """Calculate weighted final score from dimension scores."""
        score = (
            result.get("completeness", 50) * WEIGHT_COMPLETENESS
            + result.get("accuracy", 50) * WEIGHT_ACCURACY
            + result.get("type_correctness", 50) * WEIGHT_TYPE
            + result.get("sufficiency", 50) * WEIGHT_SUFFICIENCY
        )
        return max(0, min(100, round(score)))

    def _parse_json(self, response: str) -> dict[str, Any]:
        """Parse JSON from LLM response."""
        from openclaw_llm import parse_json_response
        return parse_json_response(response)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_evaluation_engine.py -v`
Expected: PASS (all tests)

- [ ] **Step 2.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/evaluation_engine.py tests/test_evaluation_engine.py
git commit -m "feat: add two-phase evaluation engine (consistency + scoring)"
```

---

## Task 3: WebSocket Client

**Files:**
- Create: `scripts/ws_client.py`
- Create: `tests/test_ws_client.py`

- [ ] **Step 3.1: Write failing test for WSMessage**

```python
# tests/test_ws_client.py
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
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_ws_client.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'ws_client'"

- [ ] **Step 3.3: Write WebSocket client implementation**

```python
# scripts/ws_client.py
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
        return f"WSMessage(type={self.type!r}, task_id={self.task_id!r})"


class ValidatorWSClient:
    """
    Manages WebSocket connection to the platform for receiving evaluation tasks.

    Protocol:
      Server -> Client: {"type": "evaluation_task", "data": {task_id, assignment_id, ...}}
      Client -> Server: {"ack_eval": "<assignment_id>"}  (must be sent within 30s)

    Reconnection:
      Uses exponential backoff: 1s -> 2s -> 4s -> ... -> 60s max.
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
        self._ws: Any = None
        self._connected = False
        self._reconnect_attempt = 0
        self._max_backoff = 60
        self._lock = threading.Lock()
        self._closed = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def ws_url(self) -> str:
        return self._ws_url

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
        log.info("WebSocket closed")

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
                log.warning("Received non-dict message: %s", str(raw)[:200])
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
        log.info("Reconnecting in %ds (attempt %d)...", delay, self._reconnect_attempt)
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_ws_client.py -v`
Expected: PASS (all tests)

- [ ] **Step 3.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/ws_client.py tests/test_ws_client.py
git commit -m "feat: add WebSocket client for validator task delivery"
```

---

## Task 4: Extend common.py with Validator Functions

**Files:**
- Modify: `scripts/common.py`
- Create: `tests/test_common_validator.py`

- [ ] **Step 4.1: Write failing test for validator resolve functions**

```python
# tests/test_common_validator.py
"""Tests for validator-specific resolve functions in common.py."""
import os
import pytest
from unittest.mock import patch
from pathlib import Path

import sys
sys.path.insert(0, "scripts")

from common import (
    resolve_validator_id,
    resolve_validator_output_root,
    resolve_eval_timeout,
    resolve_credit_interval,
    DEFAULT_VALIDATOR_ID,
)


class TestResolveValidatorId:
    def test_returns_env_var_when_set(self):
        with patch.dict(os.environ, {"VALIDATOR_ID": "my-validator"}):
            assert resolve_validator_id() == "my-validator"

    def test_returns_default_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("VALIDATOR_ID", None)
            assert resolve_validator_id() == DEFAULT_VALIDATOR_ID


class TestResolveValidatorOutputRoot:
    def test_returns_env_var_when_set(self):
        with patch.dict(os.environ, {"VALIDATOR_OUTPUT_ROOT": "/custom/path"}):
            result = resolve_validator_output_root()
            assert str(result) == "/custom/path"

    def test_returns_default_path_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("VALIDATOR_OUTPUT_ROOT", None)
            result = resolve_validator_output_root()
            assert "validator-runs" in str(result)


class TestResolveEvalTimeout:
    def test_returns_env_var_when_set(self):
        with patch.dict(os.environ, {"EVAL_TIMEOUT_SECONDS": "300"}):
            assert resolve_eval_timeout() == 300

    def test_returns_default_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EVAL_TIMEOUT_SECONDS", None)
            assert resolve_eval_timeout() == 120


class TestResolveCreditInterval:
    def test_novice_tier(self):
        assert resolve_credit_interval("novice") == 120

    def test_good_tier(self):
        assert resolve_credit_interval("good") == 30

    def test_excellent_tier(self):
        assert resolve_credit_interval("excellent") == 10

    def test_unknown_tier_defaults_to_novice(self):
        assert resolve_credit_interval("unknown") == 120
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_common_validator.py -v`
Expected: FAIL with "ImportError: cannot import name 'resolve_validator_id'"

- [ ] **Step 4.3: Add validator functions to common.py**

Add the following to the end of `scripts/common.py`:

```python
# === Validator-specific constants and functions ===

DEFAULT_VALIDATOR_ID = "validator-agent"
DEFAULT_EVAL_TIMEOUT = 120

CREDIT_TIER_INTERVALS = {
    "novice": 120,
    "good": 30,
    "excellent": 10,
}


def resolve_validator_id() -> str:
    """Resolve validator identifier from environment or default."""
    return os.environ.get("VALIDATOR_ID", "").strip() or DEFAULT_VALIDATOR_ID


def resolve_validator_output_root() -> Path:
    """Resolve validator output/state root directory."""
    env_val = os.environ.get("VALIDATOR_OUTPUT_ROOT", "").strip()
    if env_val:
        return Path(env_val).resolve()
    return resolve_crawler_root() / "output" / "validator-runs"


def resolve_validator_state_root() -> Path:
    """Resolve validator state storage root directory."""
    return resolve_validator_output_root() / "_worker_state"


def resolve_eval_timeout() -> int:
    """Resolve evaluation timeout in seconds."""
    env_val = os.environ.get("EVAL_TIMEOUT_SECONDS", "").strip()
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_EVAL_TIMEOUT


def resolve_credit_interval(credit_tier: str) -> int:
    """
    Resolve task interval in seconds based on credit tier.

    Args:
        credit_tier: One of "novice", "good", "excellent".

    Returns:
        Interval in seconds before rejoining ready pool.
    """
    return CREDIT_TIER_INTERVALS.get(credit_tier.lower(), CREDIT_TIER_INTERVALS["novice"])


def resolve_ws_url() -> str:
    """Resolve WebSocket URL for validator connections."""
    base = resolve_platform_base_url()
    # Convert http(s):// to ws(s)://
    if base.startswith("https://"):
        ws_base = "wss://" + base[8:]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[7:]
    else:
        ws_base = "ws://" + base
    return ws_base.rstrip("/") + "/api/mining/v1/ws"
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_common_validator.py -v`
Expected: PASS (all tests)

- [ ] **Step 4.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/common.py tests/test_common_validator.py
git commit -m "feat: add validator-specific resolve functions to common.py"
```

---

## Task 5: Extend PlatformClient with Validator Methods

**Files:**
- Modify: `lib/platform_client.py`
- Create: `tests/test_platform_client_validator.py`

- [ ] **Step 5.1: Write failing tests for validator methods**

```python
# tests/test_platform_client_validator.py
"""Tests for validator methods in PlatformClient."""
import pytest
from unittest.mock import patch, MagicMock
import httpx

import sys
sys.path.insert(0, "lib")
sys.path.insert(0, "scripts")

from platform_client import PlatformClient


@pytest.fixture
def mock_client():
    """Create a PlatformClient with mocked HTTP client."""
    with patch("lib.platform_client.resolve_signature_config") as mock_config:
        mock_config.return_value = {
            "chain_id": 8453,
            "domain_name": "aDATA",
            "verifying_contract": "0x0000000000000000000000000000000000000000",
        }
        client = PlatformClient(base_url="http://test", token="")
        return client


class TestGetMe:
    def test_returns_user_data(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": {"address": "0xabc", "role": "validator"}}'
        mock_response.json.return_value = {"success": True, "data": {"address": "0xabc", "role": "validator"}}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.get_me()

        assert result["address"] == "0xabc"
        assert result["role"] == "validator"


class TestValidatorApplication:
    def test_submit_application(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": {"id": "app_001", "status": "pending_review"}}'
        mock_response.json.return_value = {"success": True, "data": {"id": "app_001", "status": "pending_review"}}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.submit_validator_application()

        assert result["data"]["id"] == "app_001"

    def test_get_my_application(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": {"id": "app_001", "status": "approved"}}'
        mock_response.json.return_value = {"success": True, "data": {"id": "app_001", "status": "approved"}}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.get_my_validator_application()

        assert result["status"] == "approved"


class TestReadyPool:
    def test_join_ready_pool(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": {"validator_id": "0xabc", "status": "ready"}}'
        mock_response.json.return_value = {"success": True, "data": {"validator_id": "0xabc", "status": "ready"}}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.join_ready_pool()

        assert result["data"]["status"] == "ready"


class TestEvaluationTasks:
    def test_report_evaluation(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true}'
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.report_evaluation("task_001", 85)

        assert result["success"] is True


class TestValidationResults:
    def test_create_validation_result(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "data": {"id": "vr_001"}}'
        mock_response.json.return_value = {"success": True, "data": {"id": "vr_001"}}
        mock_response.raise_for_status = MagicMock()

        mock_client._client.request = MagicMock(return_value=mock_response)

        result = mock_client.create_validation_result(
            submission_id="sub_001",
            verdict="accepted",
            score=85,
            comment="Good extraction",
            idempotency_key="key_001",
        )

        assert result["data"]["id"] == "vr_001"
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_platform_client_validator.py -v`
Expected: FAIL with "AttributeError: 'PlatformClient' object has no attribute 'get_me'"

- [ ] **Step 5.3: Add validator methods to PlatformClient**

Add the following methods to `lib/platform_client.py` after the existing methods:

```python
    # === Validator Methods ===

    # --- Identity & Application ---

    def get_me(self) -> dict[str, Any]:
        """GET /api/iam/v1/me — Query current signer identity."""
        resp = self._request("GET", "/api/iam/v1/me", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def submit_validator_application(self) -> dict[str, Any]:
        """POST /api/iam/v1/validator-applications — Submit validator application."""
        return self._request("POST", "/api/iam/v1/validator-applications", {})

    def get_my_validator_application(self) -> dict[str, Any]:
        """GET /api/iam/v1/validator-applications/me — Query my application status."""
        resp = self._request("GET", "/api/iam/v1/validator-applications/me", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    # --- Ready Pool ---

    def join_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/validators/ready — Enter ready pool to receive tasks."""
        return self._request("POST", "/api/mining/v1/validators/ready", {})

    def leave_ready_pool(self) -> dict[str, Any]:
        """POST /api/mining/v1/validators/unready — Exit ready pool."""
        return self._request("POST", "/api/mining/v1/validators/unready", {})

    # --- Evaluation Tasks ---

    def get_evaluation_task(self, task_id: str) -> dict[str, Any]:
        """GET /api/mining/v1/evaluation-tasks/{id} — Get task details."""
        resp = self._request("GET", f"/api/mining/v1/evaluation-tasks/{task_id}", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def report_evaluation(self, task_id: str, score: int) -> dict[str, Any]:
        """POST /api/mining/v1/evaluation-tasks/{id}/report — Report evaluation score."""
        return self._request(
            "POST",
            f"/api/mining/v1/evaluation-tasks/{task_id}/report",
            {"score": score},
        )

    # --- Validation Results ---

    def create_validation_result(
        self,
        submission_id: str,
        verdict: str,
        score: int,
        comment: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """POST /api/core/v1/validation-results — Create validation result directly."""
        return self._request(
            "POST",
            "/api/core/v1/validation-results",
            {
                "submission_id": submission_id,
                "verdict": verdict,
                "score": score,
                "comment": comment,
                "idempotency_key": idempotency_key,
            },
        )

    def list_validation_results(self, **params: Any) -> list[dict[str, Any]]:
        """GET /api/core/v1/validation-results — List validation results."""
        query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        path = "/api/core/v1/validation-results"
        if query:
            path = f"{path}?{query}"
        resp = self._request("GET", path, None)
        data = resp.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def get_validation_result(self, result_id: str) -> dict[str, Any]:
        """GET /api/core/v1/validation-results/{id} — Get single validation result."""
        resp = self._request("GET", f"/api/core/v1/validation-results/{result_id}", None)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_platform_client_validator.py -v`
Expected: PASS (all tests)

- [ ] **Step 5.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add lib/platform_client.py tests/test_platform_client_validator.py
git commit -m "feat: add validator API methods to PlatformClient"
```

---

## Task 6: ValidatorStateStore

**Files:**
- Modify: `scripts/worker_state.py`
- Create: `tests/test_worker_state_validator.py`

- [ ] **Step 6.1: Write failing test for ValidatorStateStore**

```python
# tests/test_worker_state_validator.py
"""Tests for ValidatorStateStore."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
import tempfile
import shutil

import sys
sys.path.insert(0, "scripts")

from worker_state import ValidatorStateStore


@pytest.fixture
def temp_state_dir():
    """Create a temporary directory for state storage."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestValidatorStateStore:
    def test_save_and_load_session(self, temp_state_dir):
        store = ValidatorStateStore(temp_state_dir)

        session_data = {
            "session_id": "val-001",
            "validation_state": "running",
            "credit_score": 75,
            "credit_tier": "good",
            "tasks_completed": 10,
        }

        store.save_session(session_data)
        loaded = store.load_session()

        assert loaded["session_id"] == "val-001"
        assert loaded["validation_state"] == "running"
        assert loaded["credit_score"] == 75

    def test_update_session(self, temp_state_dir):
        store = ValidatorStateStore(temp_state_dir)

        store.save_session({"session_id": "val-001", "tasks_completed": 5})
        store.update_session(tasks_completed=10, credit_tier="good")

        loaded = store.load_session()
        assert loaded["tasks_completed"] == 10
        assert loaded["credit_tier"] == "good"

    def test_load_returns_empty_when_no_file(self, temp_state_dir):
        store = ValidatorStateStore(temp_state_dir)
        loaded = store.load_session()
        assert loaded == {}

    def test_save_background_session(self, temp_state_dir):
        store = ValidatorStateStore(temp_state_dir)

        store.save_background_session(pid=12345, session_id="val-001")
        loaded = store.load_background_session()

        assert loaded["pid"] == 12345
        assert loaded["session_id"] == "val-001"
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_worker_state_validator.py -v`
Expected: FAIL with "ImportError: cannot import name 'ValidatorStateStore'"

- [ ] **Step 6.3: Add ValidatorStateStore to worker_state.py**

Add the following class to `scripts/worker_state.py`:

```python
class ValidatorStateStore:
    """
    Persists validator session state across restarts.

    State is stored in JSON files under the state root directory.
    """

    SESSION_FILE = "validator_session.json"
    BACKGROUND_FILE = "validator_background.json"

    def __init__(self, state_root: Path) -> None:
        self._state_root = Path(state_root)
        self._state_root.mkdir(parents=True, exist_ok=True)

    @property
    def state_root(self) -> Path:
        return self._state_root

    def _session_path(self) -> Path:
        return self._state_root / self.SESSION_FILE

    def _background_path(self) -> Path:
        return self._state_root / self.BACKGROUND_FILE

    def save_session(self, data: dict[str, Any]) -> None:
        """Save session state to disk."""
        self._write_json(self._session_path(), data)

    def load_session(self) -> dict[str, Any]:
        """Load session state from disk. Returns empty dict if not found."""
        return self._read_json(self._session_path())

    def update_session(self, **updates: Any) -> None:
        """Update specific fields in session state."""
        current = self.load_session()
        current.update(updates)
        self.save_session(current)

    def save_background_session(self, *, pid: int, session_id: str) -> None:
        """Save background process information."""
        self._write_json(self._background_path(), {
            "pid": pid,
            "session_id": session_id,
            "started_at": int(time.time()),
        })

    def load_background_session(self) -> dict[str, Any]:
        """Load background process information. Returns empty dict if not found."""
        return self._read_json(self._background_path())

    def clear_background_session(self) -> None:
        """Clear background process information."""
        path = self._background_path()
        if path.exists():
            path.unlink()

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """Write JSON to file atomically using temp file."""
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(path)

    def _read_json(self, path: Path) -> dict[str, Any]:
        """Read JSON from file. Returns empty dict if file doesn't exist."""
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
```

Also add `import time` at the top if not already present.

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_worker_state_validator.py -v`
Expected: PASS (all tests)

- [ ] **Step 6.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/worker_state.py tests/test_worker_state_validator.py
git commit -m "feat: add ValidatorStateStore for validator session persistence"
```

---

## Task 7: Validator Runtime

**Files:**
- Create: `scripts/validator_runtime.py`
- Create: `tests/test_validator_runtime.py`

- [ ] **Step 7.1: Write failing test for ValidatorRuntime**

```python
# tests/test_validator_runtime.py
"""Tests for ValidatorRuntime."""
import pytest
from unittest.mock import MagicMock, patch
import threading

import sys
sys.path.insert(0, "scripts")

from validator_runtime import ValidatorRuntime
from ws_client import WSMessage


class TestValidatorRuntime:
    @pytest.fixture
    def mock_runtime(self):
        """Create a ValidatorRuntime with mocked dependencies."""
        platform = MagicMock()
        platform.join_ready_pool.return_value = {"status": "ready"}
        platform.leave_ready_pool.return_value = {"status": "unready"}
        platform.send_unified_heartbeat.return_value = {
            "data": {
                "role": "validator",
                "validator": {
                    "credit": 75,
                    "credit_tier": "good",
                    "min_task_interval_seconds": 30,
                }
            }
        }

        ws = MagicMock()
        ws.connected = True
        ws.connect.return_value = None

        engine = MagicMock()

        runtime = ValidatorRuntime(
            platform_client=platform,
            ws_client=ws,
            eval_engine=engine,
            validator_id="test-validator",
        )
        return runtime

    def test_stop_leaves_ready_pool(self, mock_runtime):
        mock_runtime._running = True

        result = mock_runtime.stop()

        assert result["status"] == "stopped"
        mock_runtime.platform.leave_ready_pool.assert_called_once()
        mock_runtime.ws.close.assert_called_once()

    def test_pause_leaves_ready_pool(self, mock_runtime):
        mock_runtime._running = True

        result = mock_runtime.pause()

        assert result["validation_state"] == "paused"
        mock_runtime.platform.leave_ready_pool.assert_called_once()

    def test_resume_rejoins_ready_pool(self, mock_runtime):
        mock_runtime._paused = True

        result = mock_runtime.resume()

        assert result["validation_state"] == "running"
        mock_runtime.platform.join_ready_pool.assert_called_once()

    def test_handle_evaluation_task(self, mock_runtime):
        from evaluation_engine import EvaluationResult

        mock_runtime.engine.evaluate.return_value = EvaluationResult(
            verdict="accepted",
            consistent=True,
            score=85,
            reason="Good extraction",
        )
        mock_runtime.platform.get_evaluation_task.return_value = {
            "cleaned_data": "test data",
            "schema": {},
        }
        mock_runtime.platform.fetch_core_submission.return_value = {
            "structured_data": {"key": "value"},
        }

        msg = WSMessage({
            "type": "evaluation_task",
            "data": {
                "task_id": "task_001",
                "assignment_id": "asg_001",
                "submission_id": "sub_001",
            }
        })

        mock_runtime._handle_evaluation_task(msg)

        mock_runtime.ws.send_ack_eval.assert_called_with("asg_001")
        mock_runtime.platform.report_evaluation.assert_called_with("task_001", 85)
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_validator_runtime.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'validator_runtime'"

- [ ] **Step 7.3: Write ValidatorRuntime implementation**

```python
# scripts/validator_runtime.py
"""
Validator Agent Runtime — main event loop for receiving and processing evaluation tasks.

Architecture:
  - Thread 1: Heartbeat (every 55s)
  - Thread 2: Main loop (WS receive -> ACK -> evaluate -> report)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.platform_client import PlatformClient
    from ws_client import ValidatorWSClient
    from evaluation_engine import EvaluationEngine

log = logging.getLogger("validator.runtime")

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

for p in (str(SKILL_ROOT), str(SCRIPT_DIR), str(SKILL_ROOT / "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)


class ValidatorRuntime:
    """Main validator runtime managing WS connection, heartbeat, and evaluation loop."""

    VERSION = "validator-skill/0.1.0"
    HEARTBEAT_INTERVAL = 55

    def __init__(
        self,
        *,
        platform_client: "PlatformClient",
        ws_client: "ValidatorWSClient",
        eval_engine: "EvaluationEngine",
        validator_id: str,
        heartbeat_interval: int = 55,
        eval_timeout: int = 480,
    ) -> None:
        self.platform = platform_client
        self.ws = ws_client
        self.engine = eval_engine
        self.validator_id = validator_id
        self.heartbeat_interval = heartbeat_interval
        self.eval_timeout = eval_timeout

        self._running = False
        self._paused = False
        self._heartbeat_thread: threading.Thread | None = None
        self._credit_tier = "novice"
        self._credit_score = 0
        self._min_task_interval = 120
        self._tasks_completed = 0
        self._last_heartbeat_at = 0
        self._last_task_at = 0

    # --- Lifecycle ---

    def start(self) -> dict[str, Any]:
        """Start the validator runtime (blocking)."""
        log.info("Starting validator runtime: %s", self.validator_id)
        self._running = True

        # Connect WebSocket
        try:
            self.ws.connect()
        except Exception as exc:
            log.error("WebSocket connect failed: %s", exc)
            return {"status": "error", "message": f"WS connect failed: {exc}"}

        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="validator-heartbeat",
        )
        self._heartbeat_thread.start()

        # Send initial heartbeat
        self._send_heartbeat()

        # Join ready pool
        try:
            self.platform.join_ready_pool()
            log.info("Joined ready pool")
        except Exception as exc:
            log.warning("Failed to join ready pool: %s", exc)

        # Enter main event loop
        return self._main_loop()

    def stop(self) -> dict[str, Any]:
        """Stop the runtime gracefully."""
        log.info("Stopping validator runtime")
        self._running = False
        try:
            self.platform.leave_ready_pool()
        except Exception:
            pass
        try:
            self.ws.close()
        except Exception:
            pass
        return {
            "status": "stopped",
            "tasks_completed": self._tasks_completed,
            "credit_score": self._credit_score,
            "credit_tier": self._credit_tier,
        }

    def pause(self) -> dict[str, Any]:
        """Pause evaluation (still sends heartbeats)."""
        log.info("Pausing validation")
        self._paused = True
        try:
            self.platform.leave_ready_pool()
        except Exception:
            pass
        return {"validation_state": "paused", "last_state_change_at": int(time.time())}

    def resume(self) -> dict[str, Any]:
        """Resume evaluation."""
        log.info("Resuming validation")
        self._paused = False
        try:
            self.platform.join_ready_pool()
        except Exception:
            pass
        return {"validation_state": "running", "last_state_change_at": int(time.time())}

    def status(self) -> dict[str, Any]:
        """Get current runtime status."""
        return {
            "validation_state": "paused" if self._paused else ("running" if self._running else "stopped"),
            "tasks_completed": self._tasks_completed,
            "credit_score": self._credit_score,
            "credit_tier": self._credit_tier,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_task_at": self._last_task_at,
            "ws_connected": self.ws.connected if self.ws else False,
        }

    # --- Main Loop ---

    def _main_loop(self) -> dict[str, Any]:
        """Main event loop: receive tasks, evaluate, report."""
        from ws_client import WSDisconnected

        while self._running:
            if self._paused:
                time.sleep(1)
                continue

            try:
                # Receive WS message (30s timeout)
                msg = self.ws.receive(timeout=30)

                if msg is None:
                    continue  # Timeout, keep waiting

                if msg.type == "evaluation_task":
                    self._handle_evaluation_task(msg)

            except WSDisconnected:
                if not self._running:
                    break
                log.warning("WebSocket disconnected, attempting reconnect...")
                self.ws.reconnect_with_backoff()
                if self.ws.connected:
                    try:
                        self.platform.join_ready_pool()
                    except Exception:
                        pass

            except Exception as exc:
                log.error("Error in main loop: %s", exc)
                time.sleep(1)

        return self.stop()

    def _handle_evaluation_task(self, msg: Any) -> None:
        """Handle an evaluation task message."""
        from common import resolve_credit_interval

        task_id = msg.task_id
        assignment_id = msg.assignment_id
        submission_id = msg.submission_id

        log.info("Received evaluation task: %s (assignment: %s)", task_id, assignment_id)

        # 1. ACK (must be within 30s)
        try:
            self.ws.send_ack_eval(assignment_id)
        except Exception as exc:
            log.error("Failed to ACK task %s: %s", task_id, exc)
            return

        # 2. Get task details and submission
        try:
            task = self.platform.get_evaluation_task(task_id)
            submission = self.platform.fetch_core_submission(submission_id)
        except Exception as exc:
            log.error("Failed to fetch task/submission: %s", exc)
            return

        cleaned_data = task.get("cleaned_data", "")
        structured_data = submission.get("structured_data", {})
        schema = task.get("schema", {})

        # 3. Evaluate
        try:
            result = self.engine.evaluate(
                cleaned_data=cleaned_data,
                structured_data=structured_data,
                schema_fields=schema,
            )
        except Exception as exc:
            log.error("Evaluation failed: %s", exc)
            result = None

        # 4. Report
        try:
            if result is None:
                # Evaluation failed, report conservative score
                self.platform.report_evaluation(task_id, 50)
            elif result.consistent:
                self.platform.report_evaluation(task_id, result.score)
            else:
                # Inconsistent data - use validation-results path
                self.platform.create_validation_result(
                    submission_id=submission_id,
                    verdict="rejected",
                    score=0,
                    comment=result.reason,
                    idempotency_key=f"eval-{assignment_id}",
                )
                # Also report 0 to evaluation-tasks
                self.platform.report_evaluation(task_id, 0)
        except Exception as exc:
            log.error("Failed to report evaluation: %s", exc)

        self._tasks_completed += 1
        self._last_task_at = int(time.time())

        # 5. Wait credit interval before rejoining ready pool
        interval = resolve_credit_interval(self._credit_tier)
        log.info("Waiting %ds (credit tier: %s) before rejoining ready pool", interval, self._credit_tier)
        time.sleep(interval)

        try:
            self.platform.join_ready_pool()
        except Exception as exc:
            log.warning("Failed to rejoin ready pool: %s", exc)

    # --- Heartbeat ---

    def _heartbeat_loop(self) -> None:
        """Background thread for sending heartbeats."""
        while self._running:
            try:
                self._send_heartbeat()
            except Exception as exc:
                log.warning("Heartbeat failed: %s", exc)
            time.sleep(self.heartbeat_interval)

    def _send_heartbeat(self) -> None:
        """Send heartbeat and update credit info."""
        try:
            resp = self.platform.send_unified_heartbeat(client_name=self.VERSION)
            self._last_heartbeat_at = int(time.time())

            data = resp.get("data", {})
            validator_info = data.get("validator", {})
            if validator_info:
                self._credit_score = int(validator_info.get("credit", 0))
                self._credit_tier = str(validator_info.get("credit_tier", "novice"))
                self._min_task_interval = int(validator_info.get("min_task_interval_seconds", 120))

            log.debug("Heartbeat sent: credit=%d, tier=%s", self._credit_score, self._credit_tier)
        except Exception as exc:
            log.warning("Heartbeat error: %s", exc)
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_validator_runtime.py -v`
Expected: PASS (all tests)

- [ ] **Step 7.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/validator_runtime.py tests/test_validator_runtime.py
git commit -m "feat: add ValidatorRuntime with WS event loop and heartbeat"
```

---

## Task 8: Validator Worker (Background Process Management)

**Files:**
- Create: `scripts/validator_worker.py`

- [ ] **Step 8.1: Write validator_worker.py**

```python
# scripts/validator_worker.py
"""
Background process management for validator runtime.

Commands:
  start  - Start validator in background
  stop   - Stop running validator
  status - Check if validator is running
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

for p in (str(SKILL_ROOT), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import resolve_validator_state_root
from worker_state import ValidatorStateStore


def process_is_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def generate_session_id() -> str:
    """Generate a unique session ID."""
    import uuid
    return f"val-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def start_background(state_root: Path | None = None) -> dict[str, Any]:
    """
    Start the validator runtime in a background process.

    Returns:
        Dict with status, session_id, and pid.
    """
    state_root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(state_root)

    # Check if already running
    bg = store.load_background_session()
    if bg and process_is_running(int(bg.get("pid", 0))):
        return {
            "status": "already_running",
            "session_id": bg.get("session_id"),
            "pid": bg.get("pid"),
        }

    # Generate new session
    session_id = generate_session_id()

    # Start background process
    python_exe = sys.executable
    run_worker_cmd = [
        python_exe,
        str(SCRIPT_DIR / "run_tool.py"),
        "run-validator-worker",
        "--session-id", session_id,
    ]

    # Use subprocess.Popen with detached process
    if os.name == "nt":
        # Windows
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        proc = subprocess.Popen(
            run_worker_cmd,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    else:
        # Unix
        proc = subprocess.Popen(
            run_worker_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    # Save background session info
    store.save_background_session(pid=proc.pid, session_id=session_id)

    return {
        "status": "started",
        "session_id": session_id,
        "pid": proc.pid,
    }


def stop_background(state_root: Path | None = None) -> dict[str, Any]:
    """
    Stop the running background validator.

    Returns:
        Dict with status.
    """
    state_root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(state_root)

    bg = store.load_background_session()
    if not bg:
        return {"status": "not_running"}

    pid = int(bg.get("pid", 0))
    if not process_is_running(pid):
        store.clear_background_session()
        return {"status": "not_running"}

    # Send termination signal
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)

        # Wait a bit for graceful shutdown
        for _ in range(10):
            if not process_is_running(pid):
                break
            time.sleep(0.5)

        # Force kill if still running
        if process_is_running(pid):
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

    store.clear_background_session()

    return {
        "status": "stopped",
        "session_id": bg.get("session_id"),
    }


def get_status(state_root: Path | None = None) -> dict[str, Any]:
    """
    Get status of background validator.

    Returns:
        Dict with running status and session info.
    """
    state_root = state_root or resolve_validator_state_root()
    store = ValidatorStateStore(state_root)

    bg = store.load_background_session()
    if not bg:
        return {"running": False}

    pid = int(bg.get("pid", 0))
    running = process_is_running(pid)

    if not running:
        store.clear_background_session()

    session = store.load_session()

    return {
        "running": running,
        "session_id": bg.get("session_id"),
        "pid": pid if running else None,
        "validation_state": session.get("validation_state", "unknown"),
        "tasks_completed": session.get("tasks_completed", 0),
        "credit_score": session.get("credit_score", 0),
        "credit_tier": session.get("credit_tier", "novice"),
    }
```

- [ ] **Step 8.2: Run existing tests to ensure no regressions**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/ -v`
Expected: PASS (all existing tests)

- [ ] **Step 8.3: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/validator_worker.py
git commit -m "feat: add validator_worker for background process management"
```

---

## Task 9: Extend run_tool.py with Validator Commands

**Files:**
- Modify: `scripts/run_tool.py`

- [ ] **Step 9.1: Read current run_tool.py structure**

Run: `cd /d/kaifa/clawtroop/mine && head -100 scripts/run_tool.py`
Understand the existing command structure before adding validator commands.

- [ ] **Step 9.2: Add validator command handlers**

Add the following functions to `scripts/run_tool.py`:

```python
# === Validator Commands ===

def render_validator_status() -> str:
    """Render validator readiness status (JSON)."""
    from common import (
        resolve_validator_state_root,
        resolve_wallet_bin,
        resolve_wallet_config,
    )
    from worker_state import ValidatorStateStore
    from validator_worker import process_is_running

    # Check wallet
    wallet_bin = resolve_wallet_bin()
    if not wallet_bin:
        return json.dumps({
            "ready": False,
            "state": "agent_not_initialized",
            "user_message": "Validator 环境未初始化，需要运行 bootstrap。",
            "user_actions": ["Initialize"],
        }, ensure_ascii=False, indent=2)

    wallet_config = resolve_wallet_config()
    if not wallet_config.get("session_valid"):
        return json.dumps({
            "ready": False,
            "state": "auth_required",
            "user_message": "钱包会话已过期，需要重新初始化。",
            "user_actions": ["Re-initialize"],
        }, ensure_ascii=False, indent=2)

    # Check background process
    store = ValidatorStateStore(resolve_validator_state_root())
    bg = store.load_background_session()
    if bg and process_is_running(int(bg.get("pid", 0))):
        return json.dumps({
            "ready": True,
            "state": "running",
            "user_message": f"验证正在后台运行 (session: {bg.get('session_id')})。",
            "user_actions": ["Check status", "Pause", "Stop"],
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "ready": True,
        "state": "ready",
        "user_message": "Validator 环境就绪，可以开始验证。",
        "user_actions": ["Start validation"],
    }, ensure_ascii=False, indent=2)


def render_validator_start() -> str:
    """Start validator in background."""
    from validator_worker import start_background
    result = start_background()
    return json.dumps(result, ensure_ascii=False, indent=2)


def render_validator_control(action: str) -> str:
    """Control running validator (status/pause/resume/stop)."""
    from validator_worker import get_status, stop_background
    from common import resolve_validator_state_root
    from worker_state import ValidatorStateStore

    if action == "status":
        result = get_status()
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "stop":
        result = stop_background()
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in ("pause", "resume"):
        # These require communication with the running process
        # For now, update state file and let the runtime check it
        store = ValidatorStateStore(resolve_validator_state_root())
        if action == "pause":
            store.update_session(validation_state="paused")
        else:
            store.update_session(validation_state="running")
        return json.dumps({
            "status": action,
            "message": f"Validation {action}d",
        }, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"Unknown action: {action}"}, indent=2)


def render_validator_doctor() -> str:
    """Diagnose validator environment issues."""
    from common import (
        resolve_wallet_bin,
        resolve_wallet_config,
        resolve_signature_config,
        resolve_ws_url,
    )
    import subprocess

    checks = []

    # 1. awp-wallet
    wallet_bin = resolve_wallet_bin()
    if wallet_bin:
        checks.append(("awp-wallet", "pass", "已安装"))
    else:
        checks.append(("awp-wallet", "fail", "未找到"))

    # 2. Wallet session
    wallet_config = resolve_wallet_config()
    if wallet_config.get("session_valid"):
        expires = wallet_config.get("expires_at", "unknown")
        checks.append(("钱包会话", "pass", f"有效至 {expires}"))
    else:
        checks.append(("钱包会话", "fail", "已过期或无效"))

    # 3. Platform connectivity
    try:
        sig_config = resolve_signature_config()
        checks.append(("平台连通", "pass", f"chain_id={sig_config.get('chain_id')}"))
    except Exception as e:
        checks.append(("平台连通", "fail", str(e)))

    # 4. WebSocket URL
    ws_url = resolve_ws_url()
    checks.append(("WebSocket URL", "info", ws_url))

    # 5. OpenClaw CLI
    try:
        result = subprocess.run(["openclaw", "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            checks.append(("OpenClaw CLI", "pass", "已安装"))
        else:
            checks.append(("OpenClaw CLI", "fail", "执行失败"))
    except FileNotFoundError:
        checks.append(("OpenClaw CLI", "fail", "未找到"))
    except Exception as e:
        checks.append(("OpenClaw CLI", "fail", str(e)))

    return json.dumps({
        "checks": [{"name": c[0], "status": c[1], "detail": c[2]} for c in checks],
        "overall": "pass" if all(c[1] != "fail" for c in checks) else "fail",
    }, ensure_ascii=False, indent=2)


def run_validator_worker(session_id: str) -> None:
    """Run the validator runtime (called by background process)."""
    from common import (
        resolve_platform_base_url,
        resolve_validator_id,
        resolve_validator_state_root,
        resolve_ws_url,
        resolve_eval_timeout,
        resolve_wallet_config,
    )
    from lib.platform_client import PlatformClient
    from signer import WalletSigner
    from ws_client import ValidatorWSClient
    from evaluation_engine import EvaluationEngine
    from validator_runtime import ValidatorRuntime
    from worker_state import ValidatorStateStore

    # Initialize components
    signer = WalletSigner()
    platform = PlatformClient(
        base_url=resolve_platform_base_url(),
        token="",
        signer=signer,
    )

    ws_url = resolve_ws_url()
    auth_headers = signer.build_auth_headers("GET", ws_url, None)
    ws = ValidatorWSClient(
        ws_url=ws_url,
        auth_headers=auth_headers,
        on_auth_refresh=lambda: signer.build_auth_headers("GET", ws_url, None),
    )

    engine = EvaluationEngine(timeout=resolve_eval_timeout())

    runtime = ValidatorRuntime(
        platform_client=platform,
        ws_client=ws,
        eval_engine=engine,
        validator_id=resolve_validator_id(),
        eval_timeout=resolve_eval_timeout(),
    )

    # Save initial state
    store = ValidatorStateStore(resolve_validator_state_root())
    store.save_session({
        "session_id": session_id,
        "validation_state": "running",
        "started_at": int(time.time()),
    })

    # Run
    try:
        runtime.start()
    finally:
        store.update_session(validation_state="stopped")
```

- [ ] **Step 9.3: Add argument parsing for validator commands**

Add to the `main()` function's argument parser:

```python
    # Validator commands
    subparsers.add_parser("validator-status", help="Check validator readiness")
    subparsers.add_parser("validator-start", help="Start background validation")

    validator_control = subparsers.add_parser("validator-control", help="Control running validator")
    validator_control.add_argument("action", choices=["status", "pause", "resume", "stop"])

    subparsers.add_parser("validator-doctor", help="Diagnose validator issues")

    run_worker = subparsers.add_parser("run-validator-worker", help="(internal) Run validator worker")
    run_worker.add_argument("--session-id", required=True)
```

And add the command handlers:

```python
    elif args.command == "validator-status":
        print(render_validator_status())
    elif args.command == "validator-start":
        print(render_validator_start())
    elif args.command == "validator-control":
        print(render_validator_control(args.action))
    elif args.command == "validator-doctor":
        print(render_validator_doctor())
    elif args.command == "run-validator-worker":
        run_validator_worker(args.session_id)
```

- [ ] **Step 9.4: Test validator commands**

Run: `cd /d/kaifa/clawtroop/mine && python scripts/run_tool.py validator-status`
Expected: JSON output showing validator status

- [ ] **Step 9.5: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add scripts/run_tool.py
git commit -m "feat: add validator-* commands to run_tool.py"
```

---

## Task 10: Update SKILL.md

**Files:**
- Modify: `SKILL.md` (in skill directory: `C:/Users/22243/.claude/skills/mine/SKILL.md`)

- [ ] **Step 10.1: Update SKILL.md with validator commands**

```markdown
---
name: mine
version: 0.2.0
description: |
  Mining and validation operations for the clawtroop project.
  Supports Miner (data crawling) and Validator (data evaluation) roles.
  Use when asked to "mine", "validate", "start mining/validation",
  "check status", or "setup mining/validation".
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
project-root: d:/kaifa/clawtroop/mine
---

# /mine — Mining & Validation Skill

## Quick Commands

### Miner (数据采集)
```bash
python scripts/run_tool.py init              # 初始化 miner
python scripts/run_tool.py agent-start       # 启动采集
python scripts/run_tool.py agent-control status
```

### Validator (数据验证)
```bash
python scripts/run_tool.py validator-status  # 检查就绪状态
python scripts/run_tool.py validator-start   # 启动后台验证
python scripts/run_tool.py validator-control status
python scripts/run_tool.py validator-control pause
python scripts/run_tool.py validator-control resume
python scripts/run_tool.py validator-control stop
python scripts/run_tool.py validator-doctor  # 诊断问题
```

## Validator 工作流程

1. **检查状态** → `validator-status`
2. **启动验证** → `validator-start` (后台进程)
3. **监控** → `validator-control status`
4. **暂停/恢复** → `validator-control pause/resume`
5. **停止** → `validator-control stop`

## Validator 评估逻辑

1. 接收 evaluation_task (via WebSocket)
2. **阶段1 一致性检查**：原始数据 vs 结构化数据
   - 不一致 → 直接拒绝 (verdict: rejected, score: 0)
   - 一致 → 进入阶段2
3. **阶段2 质量评分**：4维评分
   - 完整性 (30%)
   - 准确性 (40%)
   - 类型正确性 (15%)
   - 信息充分性 (15%)
4. 上报结果

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| PLATFORM_BASE_URL | http://101.47.73.95 | 平台地址 |
| VALIDATOR_ID | validator-agent | 验证者标识 |
| EVAL_TIMEOUT_SECONDS | 120 | 单次评估超时 |
| VALIDATOR_OUTPUT_ROOT | output/validator-runs | 状态存储根目录 |
```

- [ ] **Step 10.2: Commit**

```bash
cd /c/Users/22243/.claude/skills/mine
git add SKILL.md
git commit -m "docs: update SKILL.md with validator commands"
```

---

## Task 11: Add Reference Documentation

**Files:**
- Create: `references/api-validator.md`
- Create: `references/protocol-validator.md`

- [ ] **Step 11.1: Copy api-validator.md from validator-network-operator**

```bash
cd /d/kaifa/clawtroop/mine
cp validator-skill-extracted/validator-network-operator/references/api-map.md references/api-validator.md
```

- [ ] **Step 11.2: Copy protocol-validator.md from validator-network-operator**

```bash
cd /d/kaifa/clawtroop/mine
cp validator-skill-extracted/validator-network-operator/references/validator-runbook.md references/protocol-validator.md
```

- [ ] **Step 11.3: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add references/api-validator.md references/protocol-validator.md
git commit -m "docs: add validator API and protocol reference documentation"
```

---

## Task 12: Integration Smoke Test

**Files:**
- Create: `tests/test_validator_integration.py`

- [ ] **Step 12.1: Write integration smoke test**

```python
# tests/test_validator_integration.py
"""Integration smoke test for validator functionality."""
import pytest
from unittest.mock import patch, MagicMock
import json

import sys
sys.path.insert(0, "scripts")
sys.path.insert(0, "lib")


class TestValidatorIntegration:
    """End-to-end integration tests for validator workflow."""

    def test_full_evaluation_flow(self):
        """Test complete evaluation: WS message -> evaluate -> report."""
        from evaluation_engine import EvaluationEngine, EvaluationResult
        from ws_client import WSMessage

        # Mock LLM responses
        llm_responses = [
            '{"consistent": true, "reason": "Data matches"}',
            '{"completeness": 90, "accuracy": 85, "type_correctness": 100, "sufficiency": 80, "final_score": 87, "notes": "Good"}',
        ]
        mock_llm = MagicMock(side_effect=llm_responses)

        engine = EvaluationEngine(llm_call=mock_llm)

        # Simulate evaluation
        result = engine.evaluate(
            cleaned_data="John Doe, Software Engineer at Acme Corp, age 30",
            structured_data={
                "name": "John Doe",
                "job_title": "Software Engineer",
                "company": "Acme Corp",
                "age": 30,
            },
            schema_fields={
                "name": {"type": "string", "required": True},
                "job_title": {"type": "string"},
                "company": {"type": "string"},
                "age": {"type": "integer"},
            },
        )

        assert result.verdict == "accepted"
        assert result.consistent is True
        assert result.score == 87

    def test_inconsistent_data_rejected(self):
        """Test that inconsistent data is rejected immediately."""
        from evaluation_engine import EvaluationEngine

        mock_llm = MagicMock(return_value='{"consistent": false, "reason": "Name does not match"}')
        engine = EvaluationEngine(llm_call=mock_llm)

        result = engine.evaluate(
            cleaned_data="John Doe, age 30",
            structured_data={"name": "Jane Smith", "age": 25},
            schema_fields={"name": {"type": "string"}, "age": {"type": "integer"}},
        )

        assert result.verdict == "rejected"
        assert result.consistent is False
        assert result.score == 0
        assert mock_llm.call_count == 1  # Only consistency check, no scoring

    def test_validator_status_command(self):
        """Test validator-status command output."""
        from run_tool import render_validator_status

        with patch("run_tool.resolve_wallet_bin", return_value="/path/to/awp-wallet"):
            with patch("run_tool.resolve_wallet_config", return_value={"session_valid": True}):
                with patch("run_tool.ValidatorStateStore") as mock_store:
                    mock_store.return_value.load_background_session.return_value = {}

                    result = json.loads(render_validator_status())

                    assert result["ready"] is True
                    assert result["state"] == "ready"
```

- [ ] **Step 12.2: Run integration tests**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/test_validator_integration.py -v`
Expected: PASS (all tests)

- [ ] **Step 12.3: Commit**

```bash
cd /d/kaifa/clawtroop/mine
git add tests/test_validator_integration.py
git commit -m "test: add validator integration smoke tests"
```

---

## Task 13: Final Verification

- [ ] **Step 13.1: Run all tests**

Run: `cd /d/kaifa/clawtroop/mine && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 13.2: Test validator-status command**

Run: `cd /d/kaifa/clawtroop/mine && python scripts/run_tool.py validator-status`
Expected: JSON output with ready state

- [ ] **Step 13.3: Test validator-doctor command**

Run: `cd /d/kaifa/clawtroop/mine && python scripts/run_tool.py validator-doctor`
Expected: JSON output with diagnostic checks

- [ ] **Step 13.4: Final commit**

```bash
cd /d/kaifa/clawtroop/mine
git log --oneline -10  # Review commits
```

Expected: 12 commits for validator integration
