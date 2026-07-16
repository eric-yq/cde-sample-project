# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Output stage (R7): write approved results and rejected items to S3.

A single Lambda serves both terminal branches of the workflow. The branch is
selected by an explicit ``mode`` the state machine injects ("approved" or
"rejected"); if absent, it is inferred from the envelope status. Output never
contains PII because upstream records structurally exclude it.
"""

from __future__ import annotations

from typing import Any, Mapping

from common.config import Config
from common.logging_utils import get_logger, log_event
from common.models import (
    PII_FIELDS,
    STATUS_APPROVED,
    STATUS_REJECTED,
    build_approved_output,
    build_rejected_output,
)
from common.s3_io import REJECTED_PREFIX, RESULTS_PREFIX, S3WriteError, write_json

_logger = get_logger("write_output")


def _assert_no_pii(record: Mapping[str, Any]) -> None:
    """Defence in depth: never write a record that contains a PII key (R7.3)."""
    for pii in PII_FIELDS:
        if pii in record:
            raise ValueError(f"refusing to write output containing PII field '{pii}'")


def resolve_mode(event: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """Return (mode, envelope). ``mode`` is explicit if provided, else inferred."""
    if "mode" in event:
        return event["mode"], event.get("envelope", event)
    envelope = event
    mode = STATUS_REJECTED if envelope.get("status") == STATUS_REJECTED else STATUS_APPROVED
    return mode, envelope


def build_record(mode: str, envelope: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (s3_key, output_record) for the given mode."""
    if mode == STATUS_REJECTED:
        record = build_rejected_output(envelope)
        key = f"{REJECTED_PREFIX}{record['review_id']}.json"
    else:
        record = build_approved_output(envelope)
        key = f"{RESULTS_PREFIX}{record['review_id']}.json"
    return key, record


def process(event: Mapping[str, Any], clients: Any, config: Config) -> dict[str, Any]:
    mode, envelope = resolve_mode(event)
    key, record = build_record(mode, envelope)
    _assert_no_pii(record)
    try:
        write_json(clients.s3, config.output_bucket, key, record)
    except S3WriteError as exc:
        # Log full server-side context (review id, mode, bucket, key, error
        # detail from s3_io) so on-call can diagnose. Re-raise the generic
        # S3WriteError — the writer is the terminal stage, so there is no
        # further stage to route to; Step Functions will surface the failure
        # to the execution's error path with a safe generic message.
        log_event(
            _logger,
            "output_write_error",
            review_id=record["review_id"],
            mode=mode,
            key=key,
            detail=str(exc),
        )
        raise
    log_event(_logger, "output_written", review_id=record["review_id"], mode=mode, key=key)
    return {"written": key, "mode": mode, "review_id": record["review_id"]}


def lambda_handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    from common.aws_clients import build_clients

    config = Config.from_env()
    return process(event, build_clients(), config)
