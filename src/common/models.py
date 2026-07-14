"""Pipeline data models and the envelope passed between Step Functions stages.

The pipeline moves a single JSON *envelope* between stages. Each Lambda receives
the envelope, enriches it, and returns it. The two quality gates are Step Functions
``Choice`` states that read numeric fields the preceding Lambda attached.

PII guarantee: :class:`NormalizedRecord` structurally has no reviewer name/email
field, so once ingestion produces it, PII cannot flow downstream or into output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

# Envelope status values.
STATUS_OK = "ok"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

# Pipeline stages (used in rejection metadata and logging).
STAGE_INGEST = "ingest"
STAGE_TRANSLATE = "translate"
STAGE_TRANSLATION_GATE = "translation_gate"
STAGE_SUMMARIZE = "summarize"
STAGE_SUMMARY_GATE = "summary_gate"

# Rejection reasons.
REASON_VALIDATION_ERROR = "validation_error"
REASON_UNSUPPORTED_LANGUAGE = "unsupported_language"
REASON_LOW_TRANSLATION_QUALITY = "low_translation_quality"
REASON_SUMMARIZATION_ERROR = "summarization_error"
REASON_LOW_SUMMARY_QUALITY = "low_summary_quality"
REASON_PIPELINE_ERROR = "pipeline_error"

# Fields that must never survive ingestion. Dropped before any processing.
PII_FIELDS = ("reviewer_name", "reviewer_email")

# Required fields on a raw vendor review (after PII stripping is irrelevant to these).
REQUIRED_FIELDS = ("review_id", "product_id", "text", "rating", "source_language")


@dataclass(frozen=True)
class NormalizedRecord:
    """A validated, PII-free review ready for translation.

    Note there is deliberately no reviewer_name / reviewer_email field.
    """

    review_id: str
    product_id: str
    text: str
    rating: int
    source_language: str
    target_language: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizedRecord":
        return cls(
            review_id=str(data["review_id"]),
            product_id=str(data["product_id"]),
            text=str(data["text"]),
            rating=int(data["rating"]),
            source_language=str(data["source_language"]),
            target_language=str(data["target_language"]),
        )


def strip_pii(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``raw`` with all PII fields removed."""
    return {k: v for k, v in raw.items() if k not in PII_FIELDS}


def make_ok(record: NormalizedRecord) -> dict[str, Any]:
    """Envelope emitted by ingest for a valid record."""
    return {"status": STATUS_OK, "record": record.to_dict()}


def make_rejection(
    *,
    review_id: str,
    stage: str,
    reason: str,
    scores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Envelope for a rejected item. Contains no PII by construction."""
    envelope: dict[str, Any] = {
        "status": STATUS_REJECTED,
        "review_id": review_id,
        "rejection": {"stage": stage, "reason": reason},
    }
    if scores:
        envelope["scores"] = dict(scores)
    return envelope


def build_approved_output(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Map a fully-processed envelope into the approved output record (R7.1)."""
    record = envelope["record"]
    translation = envelope["translation"]
    summary = envelope["summary"]
    return {
        "review_id": record["review_id"],
        "product_id": record["product_id"],
        "source_language": record["source_language"],
        "target_language": record["target_language"],
        "translated_text": translation["translated_text"],
        "summary": summary["text"],
        "scores": {
            "translation_score": translation["score"],
            "fluency": summary["fluency"],
            "factual_consistency": summary["factual_consistency"],
            "sentence_count": summary["sentence_count"],
        },
        "status": STATUS_APPROVED,
    }


def build_rejected_output(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Map a rejected envelope into the rejected output record (R7.2)."""
    review_id = envelope.get("review_id") or envelope.get("record", {}).get("review_id", "unknown")
    out: dict[str, Any] = {
        "review_id": review_id,
        "status": STATUS_REJECTED,
        "rejection": envelope.get("rejection", {}),
    }
    if "scores" in envelope:
        out["scores"] = envelope["scores"]
    return out
