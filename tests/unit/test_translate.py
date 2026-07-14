"""Tests for the translate stage + translation quality gate (R2, R3, R8.5)."""

from __future__ import annotations

import pytest

from common import models
from translate import handler


class FakeClientError(Exception):
    """Mimics botocore ClientError enough for the retry helper."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeTranslate:
    def __init__(self, mapping=None, fail_times: int = 0, fail_code: str = "ThrottlingException"):
        self.mapping = mapping or {}
        self.fail_times = fail_times
        self.fail_code = fail_code
        self.calls = 0

    def translate_text(self, Text, SourceLanguageCode, TargetLanguageCode):  # noqa: N803
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise FakeClientError(self.fail_code)
        return {"TranslatedText": self.mapping.get(Text, Text)}


class FakeClients:
    def __init__(self, translate):
        self.translate = translate


def _envelope(text, source="fr", target="en", review_id="r-1"):
    return {
        "status": models.STATUS_OK,
        "record": {
            "review_id": review_id,
            "product_id": "p-1",
            "text": text,
            "rating": 5,
            "source_language": source,
            "target_language": target,
        },
    }


def _no_sleep(_seconds):
    return None


def test_high_quality_translation_passes_gate(config):
    original = "Ce produit est excellent et tres confortable"
    translated = "This product is excellent and very comfortable"
    translate = FakeTranslate(mapping={original: translated, translated: original})
    env = handler.process(_envelope(original), FakeClients(translate), config, sleep=_no_sleep)

    assert env["status"] == models.STATUS_OK
    assert env["translation"]["translated_text"] == translated
    assert env["translation"]["score"] >= config.thresholds.translation_score
    # Forward + back-translation = two calls.
    assert translate.calls == 2


def test_garbled_translation_is_rejected(config):
    original = "Ce produit est vraiment excellent et tres confortable a porter chaque jour"
    translated = "bad"
    translate = FakeTranslate(mapping={original: translated, translated: "zzz qqq"})
    env = handler.process(_envelope(original), FakeClients(translate), config, sleep=_no_sleep)

    assert env["status"] == models.STATUS_REJECTED
    assert env["rejection"]["reason"] == models.REASON_LOW_TRANSLATION_QUALITY
    assert env["rejection"]["stage"] == models.STAGE_TRANSLATION_GATE
    assert env["scores"]["threshold"] == config.thresholds.translation_score
    assert env["scores"]["score"] < config.thresholds.translation_score


def test_passthrough_when_source_equals_target(config):
    # source == target: translation is skipped, no client call made.
    translate = FakeTranslate()
    env = handler.process(_envelope("Great product", source="en", target="en"), FakeClients(translate), config, sleep=_no_sleep)

    assert env["status"] == models.STATUS_OK
    assert env["translation"]["skipped"] is True
    assert env["translation"]["score"] == 1.0
    assert translate.calls == 0


def test_retry_then_success(config):
    original = "Bonjour le monde ceci est un test simple et clair"
    translated = "Hello world this is a simple and clear test"
    # Fail once (retryable) on the very first call, then succeed for all calls.
    translate = FakeTranslate(mapping={original: translated, translated: original}, fail_times=1)
    env = handler.process(_envelope(original), FakeClients(translate), config, sleep=_no_sleep)

    assert env["status"] == models.STATUS_OK
    assert env["translation"]["translated_text"] == translated


def test_non_retryable_error_propagates(config):
    translate = FakeTranslate(fail_times=1, fail_code="AccessDeniedException")
    with pytest.raises(FakeClientError):
        handler.translate_text(translate, "hello", "fr", "en", config=config, sleep=_no_sleep)


def test_score_is_deterministic(config):
    kwargs = dict(
        original="Ce produit est excellent",
        translated="This product is excellent",
        back_translated="Ce produit est excellent",
        config=config,
    )
    assert handler.score_translation(**kwargs) == handler.score_translation(**kwargs)
