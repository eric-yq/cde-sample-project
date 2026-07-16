# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Minimal S3 JSON read/write helpers used by the output writer and batch driver.

S3 calls are wrapped in try/except so callers get a well-typed
:class:`S3ReadError`/:class:`S3WriteError` (chained to the underlying
``botocore.exceptions.ClientError``) instead of a raw AWS SDK error. The error
code and object coordinates are logged server-side; the raised exceptions carry
a stable message that is safe to bubble up without leaking implementation
detail. See https://boto3.amazonaws.com/v1/documentation/api/latest/guide/error-handling.html
"""

from __future__ import annotations

import json
import logging
from typing import Any

from botocore.exceptions import ClientError

_logger = logging.getLogger(__name__)

RESULTS_PREFIX = "results/"
REJECTED_PREFIX = "rejected/"


class S3ReadError(RuntimeError):
    """Raised when an S3 object cannot be read (missing, forbidden, or service error)."""


class S3WriteError(RuntimeError):
    """Raised when an S3 object cannot be written (forbidden, bucket missing, or service error)."""


def _client_error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "Unknown")


def read_json(s3_client: Any, bucket: str, key: str) -> Any:
    """Read a JSON object from ``s3://bucket/key`` and return the parsed value.

    Raises :class:`S3ReadError` on any :class:`ClientError`. NoSuchKey and
    AccessDenied are logged distinctly to aid diagnosis without exposing the
    underlying SDK exception message to callers.
    """
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = _client_error_code(exc)
        # Log the bucket, key, and SDK error code server-side so on-call has
        # enough to diagnose. The raised exception message stays generic to
        # avoid leaking storage coordinates to callers/downstream envelopes.
        _logger.exception(
            "s3_read_failed bucket=%s key=%s code=%s", bucket, key, code
        )
        if code == "NoSuchKey":
            raise S3ReadError("S3 object not found") from exc
        if code in ("AccessDenied", "403"):
            raise S3ReadError("S3 access denied") from exc
        raise S3ReadError("S3 read failed") from exc

    body = resp["Body"].read()
    return json.loads(body)


def write_json(s3_client: Any, bucket: str, key: str, data: Any) -> None:
    """Write ``data`` as pretty-printed JSON to ``s3://bucket/key``.

    Raises :class:`S3WriteError` on any :class:`ClientError`. AccessDenied and
    NoSuchBucket are logged distinctly; other codes are treated as generic
    service errors and logged with the AWS-provided error code.
    """
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
    except ClientError as exc:
        code = _client_error_code(exc)
        # Server-side log carries the bucket/key/error code; the raised
        # exception message is intentionally generic so callers or logs from
        # upstream stages never see storage coordinates.
        _logger.exception(
            "s3_write_failed bucket=%s key=%s code=%s", bucket, key, code
        )
        if code in ("AccessDenied", "403"):
            raise S3WriteError("S3 access denied") from exc
        if code == "NoSuchBucket":
            raise S3WriteError("S3 bucket not found") from exc
        raise S3WriteError("S3 write failed") from exc
