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
            assert result == Path("/custom/path").resolve()

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
