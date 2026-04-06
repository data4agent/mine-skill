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
    Single-pass evaluation engine for data quality assessment.

    Uses one LLM call to perform authenticity check (M0 vs M1), consistency check,
    and quality scoring (completeness, accuracy, type correctness, sufficiency).
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
        dataset_schema: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """
        Single-pass evaluation per protocol: authenticity + consistency + quality in one LLM call.

        Args:
            cleaned_data: Original miner submission (M0).
            structured_data: Miner-extracted structured data.
            schema_fields: List of field names from schema.
            repeat_cleaned_data: Re-crawled data from repeat crawl miner (M1).
            dataset_schema: Full dataset schema definition with types and required fields.
        """
        if isinstance(cleaned_data, dict):
            cleaned_data_str = json.dumps(cleaned_data, ensure_ascii=False, indent=2)
        else:
            cleaned_data_str = str(cleaned_data)

        structured_json = json.dumps(structured_data, ensure_ascii=False, indent=2)
        if dataset_schema:
            schema_json = json.dumps(dataset_schema, ensure_ascii=False, indent=2)
        else:
            schema_json = json.dumps({"fields": schema_fields}, ensure_ascii=False, indent=2)

        has_repeat = bool(repeat_cleaned_data and repeat_cleaned_data.strip())

        # Build single prompt covering all evaluation phases
        sections = []
        sections.append("You are a data quality evaluator for a decentralized data mining network.")
        sections.append("")

        if has_repeat:
            sections.append("## Step 1: Authenticity Check (M0 vs M1)")
            sections.append("Compare the original crawl (M0) with the independent re-crawl (M1).")
            sections.append("Minor differences (timestamps, ads, layout) are normal — report match.")
            sections.append("Major content differences (fabricated data, wrong page, missing core content) — report mismatch.")
            sections.append("")
            sections.append("### Original crawl (M0)")
            sections.append(cleaned_data_str[:4000])
            sections.append("")
            sections.append("### Re-crawl (M1)")
            sections.append(str(repeat_cleaned_data)[:4000])
        else:
            sections.append("## Original data")
            sections.append(cleaned_data_str[:4000])

        sections.append("")
        sections.append("## Structured data extracted by miner")
        sections.append(structured_json)
        sections.append("")
        sections.append("## Dataset schema")
        sections.append(schema_json)

        sections.append("")
        sections.append("## Evaluation instructions")
        if has_repeat:
            sections.append("1. Determine `result`: \"match\" if M0 and M1 represent the same content, \"mismatch\" if not.")
            sections.append("   If mismatch, set score to 0 and skip quality scoring.")
            sections.append("2. If match, score structured_data quality (0-100) based on:")
        else:
            sections.append("Set result to \"match\" (no re-crawl data to compare).")
            sections.append("Score structured_data quality (0-100) based on:")

        sections.append("   - Completeness (30%): are all required schema fields present and non-empty?")
        sections.append("   - Accuracy (40%): do values correctly reflect the original data?")
        sections.append("   - Type correctness (15%): do values match their schema-defined types?")
        sections.append("   - Information sufficiency (15%): is obvious information from the source missing?")
        sections.append("")
        sections.append("## Output (strict JSON only, no markdown)")
        sections.append('{"result": "match" or "mismatch", "score": 0-100, "reason": "brief rationale"}')

        prompt = "\n".join(sections)

        try:
            response = self.llm_call(prompt)
            result = parse_json_response(response)

            if not result or "result" not in result:
                log.error("evaluation parse failed: %s", response[:200])
                return EvaluationResult(
                    result="mismatch" if has_repeat else "match",
                    verdict="rejected",
                    consistent=False,
                    score=0,
                    reason="evaluation parse failed: invalid LLM response",
                )

            eval_result = str(result.get("result", "match"))
            eval_score = int(result.get("score", 0))
            eval_reason = str(result.get("reason", ""))

            if eval_result not in ("match", "mismatch"):
                eval_result = "match"
            eval_score = max(0, min(100, eval_score))

            if eval_result == "mismatch":
                return EvaluationResult(
                    result="mismatch",
                    verdict="rejected",
                    consistent=False,
                    score=0,
                    reason=eval_reason,
                )

            return EvaluationResult(
                result="match",
                verdict="accepted" if eval_score > 0 else "rejected",
                consistent=True,
                score=eval_score,
                reason=eval_reason,
            )

        except Exception as e:
            log.error("evaluation failed: %s", str(e))
            return EvaluationResult(
                result="mismatch" if has_repeat else "match",
                verdict="rejected",
                consistent=False,
                score=0,
                reason=f"evaluation error: {str(e)}",
            )

