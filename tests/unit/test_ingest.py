# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Tests for the ingest stage (R1.1-R1.5, R8.5)."""

from __future__ import annotations

import copy

from common import models
from ingest import handler


def test_valid_review_is_normalized_and_pii_stripped(config, valid_vendor_review):
    envelope = handler.process(valid_vendor_review, config)
    assert envelope["status"] == models.STATUS_OK
    record = envelope["record"]
    # PII removed (R1.2).
    for pii in models.PII_FIELDS:
        assert pii not in record
    # Normalized fields present (R1.5).
    assert record["review_id"] == "r-000001"
    assert record["source_language"] == "fr"
    assert record["target_language"] == config.target_language


def test_missing_required_field_is_rejected(config, valid_vendor_review):
    bad = copy.deepcopy(valid_vendor_review)
    del bad["text"]
    envelope = handler.process(bad, config)
    assert envelope["status"] == models.STATUS_REJECTED
    assert envelope["rejection"]["reason"] == models.REASON_VALIDATION_ERROR
    assert envelope["rejection"]["stage"] == models.STAGE_INGEST


def test_empty_text_is_rejected(config, valid_vendor_review):
    bad = copy.deepcopy(valid_vendor_review)
    bad["text"] = "   "
    envelope = handler.process(bad, config)
    assert envelope["status"] == models.STATUS_REJECTED
    assert envelope["rejection"]["reason"] == models.REASON_VALIDATION_ERROR


def test_out_of_range_rating_is_rejected(config, valid_vendor_review):
    bad = copy.deepcopy(valid_vendor_review)
    bad["rating"] = 9
    envelope = handler.process(bad, config)
    assert envelope["status"] == models.STATUS_REJECTED
    assert envelope["rejection"]["reason"] == models.REASON_VALIDATION_ERROR


def test_unsupported_language_is_rejected(config, valid_vendor_review):
    bad = copy.deepcopy(valid_vendor_review)
    bad["source_language"] = "ja"  # not in supported_languages
    envelope = handler.process(bad, config)
    assert envelope["status"] == models.STATUS_REJECTED
    assert envelope["rejection"]["reason"] == models.REASON_UNSUPPORTED_LANGUAGE


def test_rejection_envelope_carries_no_pii(config, valid_vendor_review):
    bad = copy.deepcopy(valid_vendor_review)
    bad["rating"] = "not-a-number"
    envelope = handler.process(bad, config)
    # Even the rejected path must not echo PII.
    flat = repr(envelope)
    assert "Jean Dupont" not in flat
    assert "jean.dupont@example.com" not in flat
