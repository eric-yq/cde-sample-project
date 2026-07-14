"""Ingest stage (R1): validate a raw vendor review, strip PII, normalize.

Order of operations matters for compliance: PII fields are dropped *first*, before
any validation or logging, so reviewer name/email never flow downstream or appear
in logs.
"""

from __future__ import annotations

from typing import Any, Mapping

from common.config import Config
from common.logging_utils import get_logger, log_event
from common.models import (
    REASON_UNSUPPORTED_LANGUAGE,
    REASON_VALIDATION_ERROR,
    REQUIRED_FIELDS,
    STAGE_INGEST,
    NormalizedRecord,
    make_ok,
    make_rejection,
    strip_pii,
)

_logger = get_logger("ingest")


class ValidationError(Exception):
    """Raised when a raw review fails schema validation."""


def _validate(clean: Mapping[str, Any]) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in clean or clean[f] in (None, "")]
    if missing:
        raise ValidationError(f"missing/empty required fields: {sorted(missing)}")

    if not isinstance(clean["text"], str) or not clean["text"].strip():
        raise ValidationError("text must be a non-empty string")

    try:
        rating = int(clean["rating"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("rating must be an integer") from exc
    if not 1 <= rating <= 5:
        raise ValidationError("rating must be between 1 and 5")

    if not isinstance(clean["source_language"], str) or not clean["source_language"].strip():
        raise ValidationError("source_language must be a non-empty string")


def process(raw: Mapping[str, Any], config: Config) -> dict[str, Any]:
    """Validate and normalize a raw vendor review.

    Returns an ``ok`` envelope with a PII-free normalized record, or a ``rejected``
    envelope with reason ``validation_error`` or ``unsupported_language``.
    """
    # 1. Drop PII before anything else (R1.2).
    clean = strip_pii(raw)
    review_id = str(clean.get("review_id") or "unknown")

    # 2. Schema validation (R1.1, R1.3).
    try:
        _validate(clean)
    except ValidationError as exc:
        log_event(_logger, "ingest_rejected", review_id=review_id, reason=REASON_VALIDATION_ERROR, detail=str(exc))
        return make_rejection(review_id=review_id, stage=STAGE_INGEST, reason=REASON_VALIDATION_ERROR)

    source_language = str(clean["source_language"]).lower()

    # 3. Supported-language check (R1.4).
    if not config.is_supported(source_language):
        log_event(_logger, "ingest_rejected", review_id=review_id, reason=REASON_UNSUPPORTED_LANGUAGE, source_language=source_language)
        return make_rejection(review_id=review_id, stage=STAGE_INGEST, reason=REASON_UNSUPPORTED_LANGUAGE)

    # 4. Build the normalized, PII-free record (R1.5).
    record = NormalizedRecord(
        review_id=review_id,
        product_id=str(clean["product_id"]),
        text=str(clean["text"]),
        rating=int(clean["rating"]),
        source_language=source_language,
        target_language=config.target_language,
    )
    log_event(_logger, "ingest_ok", review_id=review_id, source_language=source_language)
    return make_ok(record)


def lambda_handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    """Step Functions entrypoint. ``event`` is the raw vendor review object."""
    config = Config.from_env()
    return process(event, config)
