# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  http://aws.amazon.com/asl/

"""Shared pytest fixtures. All tests run offline with injected fake AWS clients."""

from __future__ import annotations

import os

import pytest

from common.config import Config

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "pipeline.yaml")


@pytest.fixture()
def config() -> Config:
    """The real pipeline config loaded from config/pipeline.yaml."""
    return Config.from_yaml(_CONFIG_PATH, input_bucket="test-input", output_bucket="test-output")


@pytest.fixture()
def valid_vendor_review() -> dict:
    """A well-formed raw vendor payload, including PII fields to be stripped."""
    return {
        "review_id": "r-000001",
        "product_id": "SKU-1001",
        "text": "Ce t-shirt est incroyablement doux et taille parfaitement.",
        "rating": 5,
        "source_language": "fr",
        "reviewer_name": "Jean Dupont",
        "reviewer_email": "jean.dupont@example.com",
    }
