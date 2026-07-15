# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  http://aws.amazon.com/asl/

"""Translate stage (R2) + translation quality gate (R3).

Calls Amazon Translate to translate source -> target, then computes a deterministic
quality score from two signals:

* length-ratio sanity: translated/source token-count ratio must sit inside a
  configured band (catches truncation and runaway output);
* back-translation similarity: translate the result back to the source language
  and compare to the original.

The gate decision is made here using the threshold from config (not in the Step
Functions definition), so thresholds can be retuned via configuration alone (R9.4).
A failing item is returned as a ``rejected`` envelope; a passing item carries its
translation and scores forward.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Mapping

from common.aws_clients import retry_with_backoff
from common.config import Config
from common.logging_utils import get_logger, log_event
from common.models import (
    REASON_LOW_TRANSLATION_QUALITY,
    REASON_PIPELINE_ERROR,
    STAGE_TRANSLATE,
    STAGE_TRANSLATION_GATE,
    NormalizedRecord,
    make_rejection,
)

_logger = get_logger("translate")

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _length_component(original: str, translated: str, band_min: float, band_max: float) -> float:
    """1.0 when the translated/original token ratio is inside the band, decaying
    toward 0.0 the further outside it falls."""
    n = len(_tokens(original))
    if n == 0:
        return 0.0
    ratio = len(_tokens(translated)) / n
    if band_min <= ratio <= band_max:
        return 1.0
    if ratio < band_min:
        return max(0.0, ratio / band_min)
    return max(0.0, band_max / ratio)


def _similarity(a: str, b: str) -> float:
    """Back-translation similarity in [0,1]: the fraction of the original text's
    distinct tokens that reappear after the round trip (token-set containment).

    Order-insensitive, so legitimate MT reordering is not penalised, while
    truncation or garbling (few of the original tokens survive) scores low.
    Calibrated on real Amazon Translate: genuine round-trips keep a clear majority
    of tokens, garbled/truncated output keeps far fewer. Deterministic.
    """
    ta = set(_tokens(a))
    tb = set(_tokens(b))
    if not ta and not tb:
        return 1.0
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def score_translation(
    *,
    original: str,
    translated: str,
    back_translated: str,
    config: Config,
) -> dict[str, float]:
    """Return the composite translation score and its components (all in [0,1])."""
    length = _length_component(
        original,
        translated,
        config.thresholds.length_ratio_min,
        config.thresholds.length_ratio_max,
    )
    back = _similarity(original, back_translated)
    composite = (
        config.scoring_weights.length * length
        + config.scoring_weights.back_translation * back
    )
    return {
        "score": round(composite, 4),
        "length_component": round(length, 4),
        "back_translation_component": round(back, 4),
    }


def _translate_call(client: Any, text: str, source: str, target: str) -> str:
    resp = client.translate_text(
        Text=text, SourceLanguageCode=source, TargetLanguageCode=target
    )
    return resp["TranslatedText"]


def translate_text(
    client: Any,
    text: str,
    source: str,
    target: str,
    *,
    config: Config,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Translate ``text`` with retry/backoff on throttling/transient errors (R2.3)."""
    return retry_with_backoff(
        lambda: _translate_call(client, text, source, target),
        max_attempts=config.retries.max_attempts,
        base_delay_seconds=config.retries.base_delay_seconds,
        sleep=sleep,
    )


def process(
    envelope: Mapping[str, Any],
    clients: Any,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Translate the record and apply the translation quality gate."""
    record = NormalizedRecord.from_dict(envelope["record"])
    try:
        return _process(envelope, record, clients, config, sleep=sleep)
    except Exception as exc:  # noqa: BLE001 - route to rejected, never crash (R6.4)
        log_event(_logger, "translate_pipeline_error", review_id=record.review_id, detail=str(exc)[:300])
        return make_rejection(
            review_id=record.review_id,
            stage=STAGE_TRANSLATE,
            reason=REASON_PIPELINE_ERROR,
            scores={"error": str(exc)[:300]},
        )


def _process(
    envelope: Mapping[str, Any],
    record: NormalizedRecord,
    clients: Any,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    result = dict(envelope)
    source, target = record.source_language, record.target_language

    # Pass-through when source == target (R2.4): no translation, perfect score.
    if source == target:
        result["translation"] = {
            "translated_text": record.text,
            "score": 1.0,
            "skipped": True,
        }
        log_event(_logger, "translation_skipped", review_id=record.review_id)
        return result

    translated = translate_text(clients.translate, record.text, source, target, config=config, sleep=sleep)
    back_translated = translate_text(clients.translate, translated, target, source, config=config, sleep=sleep)

    scores = score_translation(
        original=record.text,
        translated=translated,
        back_translated=back_translated,
        config=config,
    )
    threshold = config.thresholds.translation_score

    # Translation quality gate (R3.2/R3.3): decision uses config threshold.
    if scores["score"] < threshold:
        log_event(
            _logger,
            "translation_rejected",
            review_id=record.review_id,
            score=scores["score"],
            threshold=threshold,
        )
        return make_rejection(
            review_id=record.review_id,
            stage=STAGE_TRANSLATION_GATE,
            reason=REASON_LOW_TRANSLATION_QUALITY,
            scores={**scores, "threshold": threshold},
        )

    result["translation"] = {
        "translated_text": translated,
        "skipped": False,
        **scores,
    }
    log_event(_logger, "translation_ok", review_id=record.review_id, score=scores["score"], stage=STAGE_TRANSLATE)
    return result


def lambda_handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from common.aws_clients import build_clients

    config = Config.from_env()
    return process(event, build_clients(), config)
