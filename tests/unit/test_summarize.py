# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  http://aws.amazon.com/asl/

"""Tests for the summarize stage + summary quality gate (R4, R5, R8.5)."""

from __future__ import annotations

import json

import pytest

from common import models
from summarize import handler


class FakeClientError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeBedrock:
    """Returns queued responses in order (repeating the last); Exceptions are raised."""

    def __init__(self, responses):
        if isinstance(responses, str):
            responses = [responses]
        self.responses = list(responses)
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        item = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return {"output": {"message": {"content": [{"text": item}]}}}


class FakeClients:
    def __init__(self, bedrock):
        self.bedrock = bedrock


def _json_response(summary, fluency=0.95, factual=0.95):
    return json.dumps(
        {"summary": summary, "fluency": fluency, "factual_consistency": factual}
    )


def _envelope(translated="This t-shirt is soft and fits perfectly.", review_id="r-1"):
    return {
        "status": models.STATUS_OK,
        "record": {
            "review_id": review_id,
            "product_id": "p-1",
            "text": "Ce t-shirt est doux.",
            "rating": 5,
            "source_language": "fr",
            "target_language": "en",
        },
        "translation": {"translated_text": translated, "score": 0.95, "skipped": False},
    }


def _no_sleep(_seconds):
    return None


def test_valid_summary_passes_gate(config):
    bedrock = FakeBedrock(_json_response("Shoppers find this t-shirt soft with an accurate fit."))
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)

    assert env["status"] == models.STATUS_OK
    assert env["summary"]["text"].startswith("Shoppers")
    assert env["summary"]["sentence_count"] == 1
    assert env["summary"]["fluency"] == 0.95


def test_summary_extracted_from_surrounding_prose(config):
    raw = 'Sure! Here you go: ' + _json_response("Great quality and true to size.") + " Hope that helps."
    bedrock = FakeBedrock(raw)
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_OK
    assert "true to size" in env["summary"]["text"]


def test_malformed_then_valid_json_retries(config):
    bedrock = FakeBedrock(["this is not json", _json_response("Soft and comfortable.")])
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_OK
    assert bedrock.calls == 2


def test_all_malformed_rejects_summarization_error(config):
    bedrock = FakeBedrock("never valid json")
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["rejection"]["reason"] == models.REASON_SUMMARIZATION_ERROR
    assert env["rejection"]["stage"] == models.STAGE_SUMMARIZE


def test_too_many_sentences_rejected(config):
    bedrock = FakeBedrock(_json_response("One thing. Two thing. Three thing."))
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["rejection"]["reason"] == models.REASON_LOW_SUMMARY_QUALITY
    assert env["scores"]["failed_check"] == "sentence_count"


def test_over_length_summary_rejected(config):
    long_summary = "A" * (config.thresholds.max_summary_chars + 50)  # single sentence, no terminator
    bedrock = FakeBedrock(_json_response(long_summary))
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["scores"]["failed_check"] == "max_summary_chars"


def test_low_fluency_rejected(config):
    bedrock = FakeBedrock(_json_response("Fine.", fluency=0.4, factual=0.95))
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["scores"]["failed_check"] == "fluency"


def test_low_factual_consistency_rejected(config):
    bedrock = FakeBedrock(_json_response("Fine product overall.", fluency=0.95, factual=0.3))
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["scores"]["failed_check"] == "factual_consistency"


def test_throttling_is_retried(config):
    bedrock = FakeBedrock([FakeClientError("ThrottlingException"), _json_response("Soft fit.")])
    env = handler.process(_envelope(), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_OK


def test_bedrock_service_error_becomes_pipeline_error(config):
    # A non-retryable service error (e.g. model access denied) must not crash the
    # Lambda; it is routed to rejected with review_id preserved (R6.4).
    bedrock = FakeBedrock([FakeClientError("ResourceNotFoundException")])
    env = handler.process(_envelope(review_id="r-42"), FakeClients(bedrock), config, sleep=_no_sleep)
    assert env["status"] == models.STATUS_REJECTED
    assert env["review_id"] == "r-42"
    assert env["rejection"]["reason"] == models.REASON_PIPELINE_ERROR
    assert env["rejection"]["stage"] == models.STAGE_SUMMARIZE


def test_count_sentences():
    assert handler.count_sentences("One sentence.") == 1
    assert handler.count_sentences("First. Second!") == 2
    assert handler.count_sentences("No terminator") == 1
