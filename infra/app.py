#!/usr/bin/env python3
"""CDK application entrypoint for the review translation & summarization pipeline."""

from __future__ import annotations

import os
import sys

import aws_cdk as cdk

# Make the pipeline source (config loader) importable at synth time.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from stacks.pipeline_stack import PipelineStack  # noqa: E402

app = cdk.App()

PipelineStack(
    app,
    "ReviewTranslationPipeline",
    config_path=os.path.join(_ROOT, "config", "pipeline.yaml"),
    src_path=os.path.join(_ROOT, "src"),
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
