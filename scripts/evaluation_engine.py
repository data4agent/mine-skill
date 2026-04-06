"""Evaluation Engine for Validator."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from openclaw_llm import call_openclaw, parse_json_response

log = logging.getLogger("validator.evaluation")

DEFAULT_TIMEOUT = 120


@dataclass
class EvaluationResult:
    """Result of data evaluation."""
    result: str  # "match" | "mismatch"
    verdict: str  # "accepted" | "rejected"
    consistent: bool
    score: int  # 0-100, meaningful only when result="match"
    reason: str


class EvaluationEngine:
    """
    Two-phase evaluation engine for structured data quality.

    Phase 1: Consistency Check - Is structured_data consistent with cleaned_data?
    Phase 2: Quality Scoring - Score on 4 dimensions (completeness, accuracy, type, sufficiency)
    """

    def __init__(
        self,
        *,
        llm_call: Callable[[str], str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Initialize the evaluation engine.

        Args:
            llm_call: Optional callable for LLM calls. If None, uses default openclaw CLI.
            timeout: Timeout in seconds for LLM calls.
        """
        self.timeout = timeout
        if llm_call is None:
            self.llm_call = lambda prompt: call_openclaw(prompt, timeout=timeout)
        else:
            self.llm_call = llm_call

    def evaluate(
        self,
        cleaned_data: str | dict[str, Any],
        structured_data: dict[str, Any],
        schema_fields: list[str],
        repeat_cleaned_data: str = "",
    ) -> EvaluationResult:
        """
        Evaluate structured data quality per protocol.

        Phase 0: Compare M0 (cleaned_data) vs M1 (repeat_cleaned_data) to determine match/mismatch.
        Phase 1: If match, check consistency of structured_data against cleaned_data.
        Phase 2: If consistent, score structured_data quality on 4 dimensions.

        Args:
            cleaned_data: Original miner submission (M0).
            structured_data: Miner-extracted structured data.
            schema_fields: List of field names from schema.
            repeat_cleaned_data: Re-crawled data from repeat crawl miner (M1).
        """
        if isinstance(cleaned_data, dict):
            cleaned_data_str = json.dumps(cleaned_data, ensure_ascii=False, indent=2)
        else:
            cleaned_data_str = str(cleaned_data)

        # Phase 0: M0 vs M1 comparison (match/mismatch)
        if repeat_cleaned_data:
            match_result = self._compare_m0_m1(cleaned_data_str, str(repeat_cleaned_data))
            if not match_result["match"]:
                return EvaluationResult(
                    result="mismatch",
                    verdict="rejected",
                    consistent=False,
                    score=0,
                    reason=match_result.get("reason", "M0 and M1 data do not match"),
                )

        # Phase 1: Consistency Check — poor quality is still "match" with low score,
        # not "mismatch". Mismatch means M0 data is fabricated (Phase 0 only).
        consistency_result = self._check_consistency(cleaned_data_str, structured_data)

        if not consistency_result["consistent"]:
            return EvaluationResult(
                result="match",
                verdict="rejected",
                consistent=False,
                score=0,
                reason=consistency_result["reason"],
            )

        # Phase 2: Quality Scoring
        try:
            scoring_result = self._score_quality(
                cleaned_data_str, structured_data, schema_fields
            )

            return EvaluationResult(
                result="match",
                verdict="accepted",
                consistent=True,
                score=scoring_result["final_score"],
                reason=scoring_result["notes"],
            )
        except Exception as e:
            log.error("scoring phase failed: %s", str(e))
            return EvaluationResult(
                result="match",
                verdict="rejected",
                consistent=True,
                score=0,
                reason=f"scoring failed: {str(e)}",
            )

    def _compare_m0_m1(self, m0_cleaned: str, m1_cleaned: str) -> dict[str, Any]:
        """Phase 0: Compare original (M0) vs repeat crawl (M1) data for match/mismatch."""
        prompt = f"""You are a data authenticity checker. Compare two independently crawled versions of the same URL.

## Original crawl (M0)
{m0_cleaned[:3000]}

## Re-crawl (M1)
{m1_cleaned[:3000]}

## Task
Determine if M0 and M1 represent the same content (match) or significantly different content (mismatch).
Minor differences (timestamps, ads, layout changes) are normal and should be "match".
Major content differences (completely different text, missing core content, fabricated data) are "mismatch".

## Output (strict JSON only, no markdown)
{{"match": true/false, "reason": "brief rationale"}}"""

        try:
            response = self.llm_call(prompt)
            result = parse_json_response(response)
            if not result or "match" not in result:
                log.error("M0/M1 comparison parse failed: %s", response[:200])
                return {"match": False, "reason": "comparison parse failed, defaulting to mismatch"}
            return {"match": result.get("match", False), "reason": result.get("reason", "")}
        except Exception as e:
            log.error("M0/M1 comparison failed: %s", str(e))
            return {"match": False, "reason": f"comparison error: {e}, defaulting to mismatch"}

    def _check_consistency(
        self, cleaned_data: str, structured_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Phase 1: Check if structured data is consistent with cleaned data.

        Args:
            cleaned_data: Original cleaned data string.
            structured_data: Miner-extracted structured data.

        Returns:
            Dict with 'consistent' (bool) and 'reason' (str).
        """
        structured_json = json.dumps(structured_data, ensure_ascii=False, indent=2)

        prompt = f"""You are a data consistency checker. Decide whether the miner's structured data
is consistent with the original cleaned data.

## Original data (source of truth)
{cleaned_data}

## Structured data extracted by miner
{structured_json}

## Criteria
- Consistent: values in structured data are supported by the original text without fabrication.
- Inconsistent: structured data adds facts not in the original, or severely distorts meaning.

## Output (strict JSON only, no markdown)
{{"consistent": true/false, "reason": "brief rationale"}}"""

        try:
            response = self.llm_call(prompt)
            result = parse_json_response(response)

            if not result or "consistent" not in result:
                log.error("consistency check parse failed: %s", response[:200])
                return {
                    "consistent": False,
                    "reason": "consistency check parse failed: invalid LLM response",
                }

            return {
                "consistent": result.get("consistent", False),
                "reason": result.get("reason", "no reason given"),
            }

        except TimeoutError as e:
            log.error("consistency check timeout: %s", str(e))
            return {
                "consistent": False,
                "reason": f"consistency check timeout: {str(e)}",
            }
        except Exception as e:
            log.error("consistency check failed: %s", str(e))
            return {
                "consistent": False,
                "reason": f"consistency check error: {str(e)}",
            }

    def _score_quality(
        self,
        cleaned_data: str,
        structured_data: dict[str, Any],
        schema_fields: list[str],
    ) -> dict[str, Any]:
        """
        Phase 2: Score data quality on multiple dimensions.

        Args:
            cleaned_data: Original cleaned data string.
            structured_data: Miner-extracted structured data.
            schema_fields: List of field names from schema.

        Returns:
            Dict with dimension scores and final_score.
        """
        structured_json = json.dumps(structured_data, ensure_ascii=False, indent=2)
        schema_json = json.dumps({"fields": schema_fields}, ensure_ascii=False, indent=2)

        prompt = f"""You are a data quality scorer. Score the miner's structured extraction.

## Schema
{schema_json}

## Original data
{cleaned_data}

## Structured data extracted by miner
{structured_json}

## Dimensions
1. Completeness (30%): are required fields present?
2. Accuracy (40%): are extracted values correct?
3. Type correctness (15%): do values match schema types?
4. Information sufficiency (15%): is critical information missing?

## Output (strict JSON only, no markdown)
{{"completeness": 0-100, "accuracy": 0-100, "type_correctness": 0-100, "sufficiency": 0-100, "final_score": 0-100, "notes": "scoring notes"}}"""

        try:
            response = self.llm_call(prompt)
            result = parse_json_response(response)

            if not result or "final_score" not in result:
                log.error("quality scoring parse failed: %s", response[:200])
                raise ValueError("quality scoring parse failed: invalid LLM response")

            return {
                "completeness": result.get("completeness", 0),
                "accuracy": result.get("accuracy", 0),
                "type_correctness": result.get("type_correctness", 0),
                "sufficiency": result.get("sufficiency", 0),
                "final_score": result.get("final_score", 0),
                "notes": result.get("notes", "no scoring notes"),
            }

        except TimeoutError as e:
            log.error("quality scoring timeout: %s", str(e))
            raise ValueError(f"quality scoring timeout: {str(e)}")
        except Exception as e:
            log.error("quality scoring failed: %s", str(e))
            raise ValueError(f"quality scoring error: {str(e)}")
