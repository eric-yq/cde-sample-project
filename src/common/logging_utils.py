# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Structured, PII-safe logging.

Emits single-line JSON logs (friendly to CloudWatch Logs Insights) and defends in
depth against PII leaking into logs: any key named like a PII field is redacted
even if a caller passes it by mistake.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .models import PII_FIELDS

_REDACTED = "***REDACTED***"


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if k in PII_FIELDS else _redact(v)) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = _redact(extra)
        # Fall back to a str() representation on non-serializable payload values
        # (e.g. a datetime or a domain object passed by mistake). The primary
        # requirement is that logging never crashes the caller — a slightly
        # degraded log line is far better than losing the event.
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "message": payload["message"],
                    "context_repr": str(payload.get("context")),
                    "logging_error": "non_json_serializable_context",
                },
                ensure_ascii=False,
            )


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return logger


def log_event(logger: logging.Logger, message: str, **context: Any) -> None:
    """Log a structured event; context is PII-redacted before emission."""
    logger.info(message, extra={"context": context})
