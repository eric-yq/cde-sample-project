# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Shared test helpers used across unit tests.

Prefer this module over duplicating small fakes in individual test files, so
retry/backoff and error-classification tests share exactly the same shape of
error object (mimicking botocore.exceptions.ClientError closely enough for the
retry helper's dispatch logic).
"""

from __future__ import annotations


class FakeClientError(Exception):
    """Minimal botocore.exceptions.ClientError look-alike for tests.

    The retry helper (src/common/aws_clients.py) inspects two things on the
    exception:

    * ``exc.response["Error"]["Code"]`` — the AWS service error code, used to
      decide whether the error is retryable (throttling, transient service
      errors).
    * ``exc.response["ResponseMetadata"]["HTTPStatusCode"]`` — used as a
      fallback for 5xx errors that do not carry a specific retryable code.

    This fake replicates that surface without pulling in ``botocore`` as a
    test-time dependency.
    """

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
