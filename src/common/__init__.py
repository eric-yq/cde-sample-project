# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  http://aws.amazon.com/asl/

"""Shared building blocks for the review translation & summarization pipeline.

This package is bundled into every Lambda function and is also importable by the
CDK app, the test suite, and the evaluation harness. It intentionally depends
only on the Python standard library and boto3 (which is present in the AWS Lambda
Python runtime) so that no third-party packages need to be bundled at runtime.
"""
