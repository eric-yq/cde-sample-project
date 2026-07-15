# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  http://aws.amazon.com/asl/

"""Tests for the output writer (R7.1-R7.4)."""

from __future__ import annotations

import json

import pytest

from common import models
from write_output import handler


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[(Bucket, Key)] = json.loads(Body.decode("utf-8"))


class FakeClients:
    def __init__(self, s3):
        self.s3 = s3


def _approved_envelope():
    return {
        "status": models.STATUS_OK,
        "record": {
            "review_id": "r-100",
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


def test_writes_approved_result_to_results_prefix(config):
    s3 = FakeS3()
    out = handler.process({"mode": "approved", "envelope": _approved_envelope()}, FakeClients(s3), config)
    assert out["written"] == "results/r-100.json"
    written = s3.objects[(config.output_bucket, "results/r-100.json")]
    assert written["status"] == "approved"
    assert written["summary"] == "Shoppers find this shirt soft."


def test_writes_rejected_item_to_rejected_prefix(config):
    s3 = FakeS3()
    envelope = models.make_rejection(
        review_id="r-777",
        stage=models.STAGE_TRANSLATION_GATE,
        reason=models.REASON_LOW_TRANSLATION_QUALITY,
        scores={"translation_score": 0.4, "threshold": 0.7},
    )
    out = handler.process({"mode": "rejected", "envelope": envelope}, FakeClients(s3), config)
    assert out["written"] == "rejected/r-777.json"
    written = s3.objects[(config.output_bucket, "rejected/r-777.json")]
    assert written["status"] == "rejected"
    assert written["rejection"]["reason"] == "low_translation_quality"


def test_mode_inferred_from_status_when_absent(config):
    s3 = FakeS3()
    envelope = models.make_rejection(
        review_id="r-9", stage=models.STAGE_INGEST, reason=models.REASON_VALIDATION_ERROR
    )
    out = handler.process(envelope, FakeClients(s3), config)
    assert out["mode"] == models.STATUS_REJECTED
    assert out["written"] == "rejected/r-9.json"


def test_refuses_to_write_pii(config):
    s3 = FakeS3()
    # Craft an approved record then smuggle a PII key to prove the guard fires.
    bad_record = handler.build_approved_output(_approved_envelope())
    bad_record["reviewer_email"] = "leak@example.com"
    with pytest.raises(ValueError):
        handler._assert_no_pii(bad_record)


def test_output_contains_no_pii_fields(config):
    s3 = FakeS3()
    handler.process({"mode": "approved", "envelope": _approved_envelope()}, FakeClients(s3), config)
    written = s3.objects[(config.output_bucket, "results/r-100.json")]
    for pii in models.PII_FIELDS:
        assert pii not in written
