"""Summarize stage (R4) + summary quality gate (R5).

Calls Amazon Bedrock (Claude) via the Converse API to produce a 1-2 sentence
summary in the target language, along with model self-assessed ``fluency`` and
``factual_consistency`` scores, returned as strict JSON.

Two retry behaviours:
* throttling / transient service errors -> exponential backoff (R4.5);
* malformed / incomplete JSON -> bounded re-invocation, then reject with
  ``summarization_error`` (R4.4).

The summary quality gate (R5) then checks length, fluency, and factual
consistency against configured thresholds.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Mapping

from common.aws_clients import retry_with_backoff
from common.config import Config
from common.logging_utils import get_logger, log_event
from common.models import (
    REASON_LOW_SUMMARY_QUALITY,
    REASON_SUMMARIZATION_ERROR,
    STAGE_SUMMARIZE,
    STAGE_SUMMARY_GATE,
    NormalizedRecord,
    make_rejection,
)

_logger = get_logger("summarize")

# Human-readable language names for the prompt.
_LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
}

_SYSTEM_PROMPT = (
    "You are a concise product-review summarizer for an e-commerce site. "
    "You always respond with a single JSON object and nothing else."
)


class SummarizationError(Exception):
    """Raised when the model does not return a usable summary after retries."""


def language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


def build_prompt(translated_text: str, target_language: str, max_chars: int) -> str:
    lang = language_name(target_language)
    return (
        f"Summarize the following product review in {lang}, in ONE or TWO short "
        f"sentences (at most {max_chars} characters). Stay factually faithful to the "
        f"review; do not add opinions or details that are not present.\n\n"
        f"Return ONLY a JSON object with exactly these keys:\n"
        f'  "summary": the {lang} summary (string),\n'
        f'  "fluency": your confidence from 0.0 to 1.0 that the summary reads '
        f"fluently in {lang},\n"
        f'  "factual_consistency": your confidence from 0.0 to 1.0 that the summary '
        f"is factually consistent with the review.\n\n"
        f"Review:\n\"\"\"\n{translated_text}\n\"\"\""
    )


def _converse(client: Any, config: Config, prompt: str) -> str:
    resp = client.converse(
        modelId=config.bedrock.model_id,
        system=[{"text": _SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={
            "maxTokens": config.bedrock.max_tokens,
            "temperature": config.bedrock.temperature,
        },
    )
    return resp["output"]["message"]["content"][0]["text"]


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in ``text``. Raises on failure."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SummarizationError("no JSON object found in model response")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SummarizationError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SummarizationError("model response was not a JSON object")
    return data


def _coerce_summary(data: Mapping[str, Any]) -> dict[str, Any]:
    if "summary" not in data or not str(data["summary"]).strip():
        raise SummarizationError("missing 'summary'")
    try:
        fluency = float(data["fluency"])
        factual = float(data["factual_consistency"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SummarizationError("missing/invalid score fields") from exc
    return {
        "summary": str(data["summary"]).strip(),
        "fluency": max(0.0, min(1.0, fluency)),
        "factual_consistency": max(0.0, min(1.0, factual)),
    }


def count_sentences(text: str) -> int:
    return len([seg for seg in re.split(r"[.!?]+", text) if seg.strip()])


def generate_summary(
    client: Any,
    translated_text: str,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Invoke Bedrock and return a validated summary dict.

    Retries throttling with backoff per call, and re-invokes on malformed JSON up
    to ``max_attempts`` times before raising SummarizationError (R4.4, R4.5).
    """
    prompt = build_prompt(translated_text, config.target_language, config.thresholds.max_summary_chars)
    last_error: Exception | None = None
    for _ in range(config.retries.max_attempts):
        raw = retry_with_backoff(
            lambda: _converse(client, config, prompt),
            max_attempts=config.retries.max_attempts,
            base_delay_seconds=config.retries.base_delay_seconds,
            sleep=sleep,
        )
        try:
            return _coerce_summary(_extract_json(raw))
        except SummarizationError as exc:
            last_error = exc
    raise SummarizationError(f"no valid summary after retries: {last_error}")


def evaluate_summary(summary: dict[str, Any], config: Config) -> tuple[bool, str | None]:
    """Summary quality gate (R5.1): returns (passed, failed_check)."""
    sentence_count = count_sentences(summary["summary"])
    if sentence_count not in (1, 2):
        return False, "sentence_count"
    if len(summary["summary"]) > config.thresholds.max_summary_chars:
        return False, "max_summary_chars"
    if summary["fluency"] < config.thresholds.fluency:
        return False, "fluency"
    if summary["factual_consistency"] < config.thresholds.factual_consistency:
        return False, "factual_consistency"
    return True, None


def process(
    envelope: Mapping[str, Any],
    clients: Any,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    result = dict(envelope)
    record = NormalizedRecord.from_dict(envelope["record"])
    translated_text = envelope["translation"]["translated_text"]

    # Summarization with bounded retry (R4).
    try:
        summary = generate_summary(clients.bedrock, translated_text, config, sleep=sleep)
    except SummarizationError as exc:
        log_event(_logger, "summarization_error", review_id=record.review_id, detail=str(exc))
        return make_rejection(
            review_id=record.review_id,
            stage=STAGE_SUMMARIZE,
            reason=REASON_SUMMARIZATION_ERROR,
        )

    sentence_count = count_sentences(summary["summary"])
    passed, failed_check = evaluate_summary(summary, config)
    scores = {
        "fluency": summary["fluency"],
        "factual_consistency": summary["factual_consistency"],
        "sentence_count": sentence_count,
        "summary_length": len(summary["summary"]),
    }

    # Summary quality gate (R5.2).
    if not passed:
        log_event(_logger, "summary_rejected", review_id=record.review_id, failed_check=failed_check, **scores)
        return make_rejection(
            review_id=record.review_id,
            stage=STAGE_SUMMARY_GATE,
            reason=REASON_LOW_SUMMARY_QUALITY,
            scores={**scores, "failed_check": failed_check},
        )

    result["summary"] = {
        "text": summary["summary"],
        "fluency": summary["fluency"],
        "factual_consistency": summary["factual_consistency"],
        "sentence_count": sentence_count,
    }
    log_event(_logger, "summary_ok", review_id=record.review_id, **scores)
    return result


def lambda_handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from common.aws_clients import build_clients

    config = Config.from_env()
    return process(event, build_clients(), config)
