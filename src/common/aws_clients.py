# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""AWS client factory and a small retry/backoff helper.

Business logic accepts injected clients so unit tests can pass fakes and run with
no network access. Handlers use :func:`build_clients` to obtain real boto3 clients.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

# Exponential backoff base: delay for attempt N is base_delay_seconds * BACKOFF_BASE ** (N-1).
# A base of 2 gives the standard 1x, 2x, 4x, 8x, ... progression that AWS SDK
# retries use. Changing this changes the growth rate of the retry delay.
BACKOFF_BASE = 2

# Botocore error codes that are safe to retry (throttling + transient service errors).
RETRYABLE_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "Throttling",
        "TooManyRequestsException",
        "RequestLimitExceeded",
        "ServiceUnavailableException",
        "ServiceUnavailable",
        "InternalServerException",
        "InternalFailure",
        "ModelTimeoutException",
    }
)


def is_retryable_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a transient/throttling AWS error worth retrying."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code in RETRYABLE_ERROR_CODES:
            return True
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int) and status >= 500:
            return True
    return False


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int,
    base_delay_seconds: float,
    retryable: Callable[[BaseException], bool] = is_retryable_error,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` retrying retryable errors with exponential backoff.

    Raises the last exception if all attempts fail, or immediately for a
    non-retryable exception.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            if attempt >= max_attempts or not retryable(exc):
                raise
            sleep(base_delay_seconds * (BACKOFF_BASE ** (attempt - 1)))


class Clients:
    """Lazily-created bundle of the boto3 clients the pipeline uses."""

    def __init__(self, region_name: str | None = None) -> None:
        self._region = region_name
        self._translate: Any = None
        self._bedrock: Any = None
        self._s3: Any = None

    def _session_client(self, service: str) -> Any:
        import boto3  # local import so tests need not import boto3

        return boto3.client(service, region_name=self._region)

    @property
    def translate(self) -> Any:
        if self._translate is None:
            self._translate = self._session_client("translate")
        return self._translate

    @property
    def bedrock(self) -> Any:
        if self._bedrock is None:
            self._bedrock = self._session_client("bedrock-runtime")
        return self._bedrock

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            self._s3 = self._session_client("s3")
        return self._s3


def build_clients(region_name: str | None = None) -> Clients:
    return Clients(region_name=region_name)
