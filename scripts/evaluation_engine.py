"""Evaluation Engine for Validator."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from openclaw_llm import parse_json_response

log = logging.getLogger("validator.evaluation")

DEFAULT_TIMEOUT = 120


@dataclass
class EvaluationResult:
    """Result of data evaluation."""
    result: str  # "match" | "mismatch"
    verdict: str  # "accepted" | "rejected"
    consistent: bool
    score: int  # 0-100, meaningful only when result="match"


def _default_llm_call(
    prompt: str,
    *,
    timeout: float,
    model_config: dict[str, Any] | None,
) -> str:
    """Sync wrapper around the shared llm_enrich routing.

    Priority: OpenClaw CLI → OpenClaw gateway → direct API. Raises RuntimeError
    with the underlying failure reason when nothing is available so validator
    callers can handle it uniformly.

    This lets the validator keep running via gateway/API even on hosts where the
    ``openclaw`` binary is not installed (e.g. when the skill is invoked from a
    different agent host). The miner already uses this routing — sharing the
    path avoids a second parallel LLM integration.
    """
    from crawler.enrich.generative.llm_enrich import enrich_with_llm

    async def _run() -> str:
        result = await enrich_with_llm(
            prompt,
            model_config=model_config,
            timeout=timeout,
        )
        if not result.success:
            raise RuntimeError(result.error or "LLM call failed")
        return result.content

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Called from inside an already-running loop (rare for the
            # validator, but be defensive). Offload to a fresh loop in a thread
            # to avoid nested-loop errors.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(_run())).result()
    except RuntimeError:
        # No current loop — create one.
        pass
    return asyncio.run(_run())


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
        model_config: dict[str, Any] | None = None,
    ):
        """
        Initialize the evaluation engine.

        Args:
            llm_call: Optional callable for LLM calls. If None, uses the shared
                llm_enrich routing (CLI → gateway → API) so the validator works
                on hosts that don't have the openclaw binary installed.
            timeout: Timeout in seconds for LLM calls.
            model_config: Optional model config dict for gateway/API fallback.
                When empty, only the CLI path is available.
        """
        self.timeout = timeout
        self.model_config = model_config or {}
        if llm_call is None:
            cfg = self.model_config
            self.llm_call = lambda prompt: _default_llm_call(
                prompt, timeout=timeout, model_config=cfg
            )
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
            cleaned_data_str = json.dumps(cleaned_data, ensure_ascii=False, separators=(",", ":"))
        else:
            cleaned_data_str = str(cleaned_data)

        structured_json = json.dumps(structured_data, ensure_ascii=False, separators=(",", ":"))
        if dataset_schema:
            schema_json = json.dumps(dataset_schema, ensure_ascii=False, separators=(",", ":"))
        else:
            schema_json = json.dumps({"fields": schema_fields}, ensure_ascii=False, separators=(",", ":"))

        has_repeat = bool(repeat_cleaned_data and repeat_cleaned_data.strip())

        # Pre-LLM optimization: reduce M0 and M1 with identical rules
        cleaned_data_str = _optimize_for_eval(cleaned_data_str)
        if has_repeat:
            repeat_cleaned_data = _optimize_for_eval(str(repeat_cleaned_data))

        # Build single prompt covering all evaluation phases
        sections = []
        sections.append("You are a data quality evaluator for a decentralized data mining network.")
        sections.append("")

        if has_repeat:
            sections.append("## Data")
            sections.append("")
            sections.append("### Original crawl (M0)")
            sections.append(cleaned_data_str)
            sections.append("")
            sections.append("### Re-crawl (M1)")
            sections.append(str(repeat_cleaned_data))
        else:
            sections.append("## Original data")
            sections.append(cleaned_data_str)

        sections.append("")
        sections.append("## Structured data extracted by miner")
        sections.append(structured_json)
        sections.append("")
        sections.append("## Dataset schema")
        sections.append(schema_json)

        sections.append("")
        sections.append("## Evaluation instructions")
        if has_repeat:
            sections.append("Evaluate in this order:")
            sections.append("")
            sections.append("1. **Check if M1 is a blocked page**: If M1 is a CAPTCHA page, login wall,")
            sections.append("   access-denied page, anti-bot challenge, or any non-content error page,")
            sections.append("   then M1 is unusable for comparison. In this case, set result to \"match\"")
            sections.append("   (do NOT penalize the miner for the re-crawler being blocked) and proceed")
            sections.append("   to quality scoring based on M0 alone.")
            sections.append("")
            sections.append("2. **Authenticity check (M0 vs M1)**: If M1 is real content, compare M0 and M1.")
            sections.append("   Minor differences (timestamps, ads, layout) are normal — report \"match\".")
            sections.append("   Major content differences (fabricated data, wrong page, missing core content) — report \"mismatch\".")
            sections.append("   If mismatch, set score to 0 and skip quality scoring.")
            sections.append("")
            sections.append("3. **Quality scoring**: If match, score structured_data quality (0-100) based on:")
        else:
            sections.append("Set result to \"match\" (no re-crawl data to compare).")
            sections.append("Score structured_data quality (0-100) based on:")

        sections.append("   - Completeness (30%): are all required schema fields present and non-empty?")
        sections.append("   - Accuracy (40%): do values correctly reflect the original data?")
        sections.append("   - Type correctness (15%): do values match their schema-defined types?")
        sections.append("   - Information sufficiency (15%): is obvious information from the source missing?")
        sections.append("")
        sections.append("## Output (strict JSON only, no markdown)")
        sections.append('{"result": "match" or "mismatch", "score": 0-100}')

        prompt = "\n".join(sections)

        try:
            response = self.llm_call(prompt)
            result = parse_json_response(response)

            # Normalize keys to lowercase for case-insensitive matching
            if result:
                result = {k.lower(): v for k, v in result.items()}

            eval_result, eval_score = self._extract_result_and_score(result, response, has_repeat)

            eval_score = max(0, min(100, eval_score))

            if eval_result == "mismatch":
                return EvaluationResult(
                    result="mismatch",
                    verdict="rejected",
                    consistent=False,
                    score=0,
                )

            return EvaluationResult(
                result="match",
                verdict="accepted" if eval_score > 0 else "rejected",
                consistent=True,
                score=eval_score,
            )

        except Exception as e:
            log.error("evaluation failed (infrastructure): %s", str(e))
            # Infrastructure failure — don't penalize miners for evaluator faults
            return EvaluationResult(
                result="match",
                verdict="accepted",
                consistent=True,
                score=50,
            )

    @staticmethod
    def _extract_result_and_score(
        parsed: dict[str, Any] | None,
        raw_response: str,
        has_repeat: bool,
    ) -> tuple[str, int]:
        """Extract result and score from LLM response with maximum tolerance.

        Handles: key case variations, value case, non-JSON text, missing fields.
        Returns (result, score) tuple.
        """
        # Try from parsed JSON first (keys already lowercased)
        if parsed:
            raw_result = str(parsed.get("result", ""))
            raw_score = parsed.get("score")

            # Normalize result value
            if raw_result.lower() in ("match", "true", "yes", "authentic", "same"):
                eval_result = "match"
            elif raw_result.lower() in ("mismatch", "false", "no", "fraud", "different", "fabricated"):
                eval_result = "mismatch"
            elif not raw_result:
                # Result key empty — use parsed score if available, else text fallback
                try:
                    score = int(float(str(raw_score)))
                    if score > 0:
                        return "match", max(0, min(100, score))
                except (TypeError, ValueError):
                    pass
                return EvaluationEngine._extract_result_and_score(None, raw_response, has_repeat)
            else:
                # Ambiguous verdict — fall back to raw text extraction
                return EvaluationEngine._extract_result_and_score(None, raw_response, has_repeat)

            # Normalize score value
            try:
                eval_score = int(float(str(raw_score)))
            except (TypeError, ValueError):
                eval_score = 0

            return eval_result, eval_score

        # Fallback: extract from raw text when JSON parsing failed entirely
        text = raw_response.lower()

        # Detect result from text
        if "mismatch" in text or "fabricat" in text or "fraud" in text:
            eval_result = "mismatch"
        else:
            eval_result = "match"

        # Detect score from text (look for number near "score")
        eval_score = 0
        score_patterns = [
            r'score["\s:]*(\d+)',
            r'(\d+)["\s]*/?\s*100',
            r'(\d{1,3})\s*(?:out of|/)\s*100',
        ]
        for pattern in score_patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    val = int(m.group(1))
                    if 0 <= val <= 100:
                        eval_score = val
                        break
                except ValueError:
                    pass

        return eval_result, eval_score


# Max chars for each M0/M1 text sent to LLM (~5000 tokens)
_EVAL_MAX_CHARS = 20000

_LOW_VALUE_HEADING = re.compile(
    r"(?im)^#{1,3}\s*("
    r"references|bibliography|citations|notes|footnotes|"
    r"see also|further reading|external links|sources|"
    r"related articles|related pages|navigation|categories|"
    r"disclaimers?|copyright"
    r")\s*$"
)
_CITATION_RE = re.compile(r"\[\s*(?:\d+|note\s+\d+|citation needed)\s*\]")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _optimize_for_eval(text: str) -> str:
    """Reduce M0/M1 text before sending to LLM.

    Applies identical rules to both sides so comparison remains fair.
    """
    if not text or len(text) < _EVAL_MAX_CHARS:
        text = _CITATION_RE.sub("", text)
        text = _MULTI_BLANK_RE.sub("\n\n", text)
        return text.strip()

    lines = text.split("\n")
    result = []
    skip = False
    skip_level = 0
    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            if _LOW_VALUE_HEADING.match(f"{'#' * level} {heading_match.group(2).strip()}"):
                skip = True
                skip_level = level
                continue
            if skip and level <= skip_level:
                skip = False
        if not skip:
            result.append(line)
    text = "\n".join(result)

    text = _CITATION_RE.sub("", text)

    paragraphs = re.split(r"\n{2,}", text)
    seen: set[str] = set()
    unique = []
    for para in paragraphs:
        key = re.sub(r"\s+", " ", para.strip().lower())
        if len(key) < 20 or key not in seen:
            if len(key) >= 20:
                seen.add(key)
            unique.append(para)
    text = "\n\n".join(unique)

    text = _MULTI_BLANK_RE.sub("\n\n", text).strip()

    if len(text) > _EVAL_MAX_CHARS:
        text = text[:_EVAL_MAX_CHARS].rsplit("\n", 1)[0] + "\n..."

    return text

