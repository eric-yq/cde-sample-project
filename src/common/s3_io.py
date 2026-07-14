"""Minimal S3 JSON read/write helpers used by the output writer and batch driver."""

from __future__ import annotations

import json
from typing import Any

RESULTS_PREFIX = "results/"
REJECTED_PREFIX = "rejected/"


def read_json(s3_client: Any, bucket: str, key: str) -> Any:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    return json.loads(body)


def write_json(s3_client: Any, bucket: str, key: str, data: Any) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
