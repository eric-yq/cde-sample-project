"""Tests for data models and the no-PII guarantee (R1.5, R7.1, R7.2, R7.3)."""

from __future__ import annotations

from common import models
from common.models import NormalizedRecord


def test_strip_pii_removes_reviewer_fields(valid_vendor_review):
    stripped = models.strip_pii(valid_vendor_review)
    assert "reviewer_name" not in stripped
    assert "reviewer_email" not in stripped
    # Non-PII fields survive.
    assert stripped["review_id"] == "r-000001"
    assert stripped["text"] == valid_vendor_review["text"]


def test_normalized_record_has_no_pii_fields():
    rec = NormalizedRecord(
        review_id="r-1",
        product_id="p-1",
        text="hello",
        rating=4,
        source_language="fr",
        target_language="en",
    )
    as_dict = rec.to_dict()
    for pii in models.PII_FIELDS:
        assert pii not in as_dict


def test_normalized_record_round_trip():
    data = {
        "review_id": "r-1",
        "product_id": "p-1",
        "text": "hello",
        "rating": "4",  # string coerces to int
        "source_language": "de",
        "target_language": "en",
    }
    rec = NormalizedRecord.from_dict(data)
    assert rec.rating == 4
    assert rec.to_dict()["rating"] == 4


def test_build_approved_output_shape():
    envelope = {
        "record": {
            "review_id": "r-1",
            "product_id": "p-1",
            "source_language": "fr",
            "target_language": "en",
        },
        "translation": {"translated_text": "This shirt is soft.", "score": 0.94},
        "summary": {
            "text": "Shoppers find this shirt soft.",
            "fluency": 0.97,
            "factual_consistency": 0.95,
            "sentence_count": 1,
        },
    }
    out = models.build_approved_output(envelope)
    assert out["status"] == "approved"
    assert out["translated_text"] == "This shirt is soft."
    assert out["summary"] == "Shoppers find this shirt soft."
    assert out["scores"]["translation_score"] == 0.94
    assert out["scores"]["fluency"] == 0.97
    # No PII fields anywhere in output.
    for pii in models.PII_FIELDS:
        assert pii not in out


def test_build_rejected_output_shape():
    envelope = models.make_rejection(
        review_id="r-9",
        stage=models.STAGE_TRANSLATION_GATE,
        reason=models.REASON_LOW_TRANSLATION_QUALITY,
        scores={"translation_score": 0.41, "threshold": 0.70},
    )
    out = models.build_rejected_output(envelope)
    assert out["review_id"] == "r-9"
    assert out["status"] == "rejected"
    assert out["rejection"]["stage"] == "translation_gate"
    assert out["rejection"]["reason"] == "low_translation_quality"
    assert out["scores"]["translation_score"] == 0.41
