# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Pipeline configuration loading.

Configuration has a single human-editable source of truth: ``config/pipeline.yaml``.
At CDK synth time that YAML is flattened into environment variables and injected
into each Lambda (see :func:`config_to_env`). At runtime each Lambda rebuilds a
:class:`Config` purely from environment variables (:meth:`Config.from_env`) so the
runtime has no dependency on a YAML parser.

For local use (tests, evaluation) :meth:`Config.from_yaml` reads the YAML directly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, MutableMapping

# Environment variable names. Kept in one place so the CDK app (which writes them)
# and the Lambda runtime (which reads them) can never drift apart.
ENV_TARGET_LANGUAGE = "TARGET_LANGUAGE"
ENV_SUPPORTED_LANGUAGES = "SUPPORTED_LANGUAGES"
ENV_BEDROCK_MODEL_ID = "BEDROCK_MODEL_ID"
ENV_BEDROCK_MAX_TOKENS = "BEDROCK_MAX_TOKENS"
ENV_BEDROCK_TEMPERATURE = "BEDROCK_TEMPERATURE"
ENV_TRANSLATION_SCORE_THRESHOLD = "TRANSLATION_SCORE_THRESHOLD"
ENV_FLUENCY_THRESHOLD = "FLUENCY_THRESHOLD"
ENV_FACTUAL_CONSISTENCY_THRESHOLD = "FACTUAL_CONSISTENCY_THRESHOLD"
ENV_MAX_SUMMARY_CHARS = "MAX_SUMMARY_CHARS"
ENV_LENGTH_RATIO_MIN = "LENGTH_RATIO_MIN"
ENV_LENGTH_RATIO_MAX = "LENGTH_RATIO_MAX"
ENV_SCORING_WEIGHT_LENGTH = "SCORING_WEIGHT_LENGTH"
ENV_SCORING_WEIGHT_BACK_TRANSLATION = "SCORING_WEIGHT_BACK_TRANSLATION"
ENV_RETRIES_MAX_ATTEMPTS = "RETRIES_MAX_ATTEMPTS"
ENV_RETRIES_BASE_DELAY_SECONDS = "RETRIES_BASE_DELAY_SECONDS"
ENV_INPUT_BUCKET = "INPUT_BUCKET"
ENV_OUTPUT_BUCKET = "OUTPUT_BUCKET"


@dataclass(frozen=True)
class BedrockConfig:
    model_id: str
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class Thresholds:
    translation_score: float
    fluency: float
    factual_consistency: float
    max_summary_chars: int
    length_ratio_min: float
    length_ratio_max: float


@dataclass(frozen=True)
class ScoringWeights:
    length: float
    back_translation: float

    def __post_init__(self) -> None:
        total = self.length + self.back_translation
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"scoring_weights must sum to 1.0, got {total} "
                f"(length={self.length}, back_translation={self.back_translation})"
            )


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int
    base_delay_seconds: float


@dataclass(frozen=True)
class Config:
    target_language: str
    supported_languages: tuple[str, ...]
    bedrock: BedrockConfig
    thresholds: Thresholds
    scoring_weights: ScoringWeights
    retries: RetryConfig
    # Bucket names are only known at deploy time; empty for pure-logic unit tests.
    input_bucket: str = ""
    output_bucket: str = ""

    def is_supported(self, language: str) -> bool:
        return language in self.supported_languages

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
        *,
        input_bucket: str = "",
        output_bucket: str = "",
    ) -> "Config":
        """Build a Config from the nested structure of ``pipeline.yaml``."""
        bedrock = data["bedrock"]  # type: ignore[index]
        thresholds = data["thresholds"]  # type: ignore[index]
        weights = data["scoring_weights"]  # type: ignore[index]
        retries = data["retries"]  # type: ignore[index]
        return cls(
            target_language=str(data["target_language"]),
            supported_languages=tuple(str(x) for x in data["supported_languages"]),  # type: ignore[index]
            bedrock=BedrockConfig(
                model_id=str(bedrock["model_id"]),
                max_tokens=int(bedrock["max_tokens"]),
                temperature=float(bedrock["temperature"]),
            ),
            thresholds=Thresholds(
                translation_score=float(thresholds["translation_score"]),
                fluency=float(thresholds["fluency"]),
                factual_consistency=float(thresholds["factual_consistency"]),
                max_summary_chars=int(thresholds["max_summary_chars"]),
                length_ratio_min=float(thresholds["length_ratio_min"]),
                length_ratio_max=float(thresholds["length_ratio_max"]),
            ),
            scoring_weights=ScoringWeights(
                length=float(weights["length"]),
                back_translation=float(weights["back_translation"]),
            ),
            retries=RetryConfig(
                max_attempts=int(retries["max_attempts"]),
                base_delay_seconds=float(retries["base_delay_seconds"]),
            ),
            input_bucket=input_bucket,
            output_bucket=output_bucket,
        )

    @classmethod
    def from_yaml(cls, path: str, **buckets: str) -> "Config":
        """Load config from a YAML file. Requires PyYAML (dev/synth only)."""
        import yaml  # local import: not needed at Lambda runtime

        with open(path, "r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
        return cls.from_dict(data, **buckets)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Rebuild config from environment variables (Lambda runtime path)."""
        env_map = env if env is not None else os.environ
        return cls(
            target_language=env_map[ENV_TARGET_LANGUAGE],
            supported_languages=tuple(json.loads(env_map[ENV_SUPPORTED_LANGUAGES])),
            bedrock=BedrockConfig(
                model_id=env_map[ENV_BEDROCK_MODEL_ID],
                max_tokens=int(env_map[ENV_BEDROCK_MAX_TOKENS]),
                temperature=float(env_map[ENV_BEDROCK_TEMPERATURE]),
            ),
            thresholds=Thresholds(
                translation_score=float(env_map[ENV_TRANSLATION_SCORE_THRESHOLD]),
                fluency=float(env_map[ENV_FLUENCY_THRESHOLD]),
                factual_consistency=float(env_map[ENV_FACTUAL_CONSISTENCY_THRESHOLD]),
                max_summary_chars=int(env_map[ENV_MAX_SUMMARY_CHARS]),
                length_ratio_min=float(env_map[ENV_LENGTH_RATIO_MIN]),
                length_ratio_max=float(env_map[ENV_LENGTH_RATIO_MAX]),
            ),
            scoring_weights=ScoringWeights(
                length=float(env_map[ENV_SCORING_WEIGHT_LENGTH]),
                back_translation=float(env_map[ENV_SCORING_WEIGHT_BACK_TRANSLATION]),
            ),
            retries=RetryConfig(
                max_attempts=int(env_map[ENV_RETRIES_MAX_ATTEMPTS]),
                base_delay_seconds=float(env_map[ENV_RETRIES_BASE_DELAY_SECONDS]),
            ),
            input_bucket=env_map.get(ENV_INPUT_BUCKET, ""),
            output_bucket=env_map.get(ENV_OUTPUT_BUCKET, ""),
        )


def config_to_env(config: Config) -> dict[str, str]:
    """Flatten a Config into the env var map injected onto Lambdas by the CDK app.

    Bucket names are intentionally omitted here; the CDK app sets INPUT_BUCKET and
    OUTPUT_BUCKET from the actual bucket resources it creates.
    """
    return {
        ENV_TARGET_LANGUAGE: config.target_language,
        ENV_SUPPORTED_LANGUAGES: json.dumps(list(config.supported_languages)),
        ENV_BEDROCK_MODEL_ID: config.bedrock.model_id,
        ENV_BEDROCK_MAX_TOKENS: str(config.bedrock.max_tokens),
        ENV_BEDROCK_TEMPERATURE: str(config.bedrock.temperature),
        ENV_TRANSLATION_SCORE_THRESHOLD: str(config.thresholds.translation_score),
        ENV_FLUENCY_THRESHOLD: str(config.thresholds.fluency),
        ENV_FACTUAL_CONSISTENCY_THRESHOLD: str(config.thresholds.factual_consistency),
        ENV_MAX_SUMMARY_CHARS: str(config.thresholds.max_summary_chars),
        ENV_LENGTH_RATIO_MIN: str(config.thresholds.length_ratio_min),
        ENV_LENGTH_RATIO_MAX: str(config.thresholds.length_ratio_max),
        ENV_SCORING_WEIGHT_LENGTH: str(config.scoring_weights.length),
        ENV_SCORING_WEIGHT_BACK_TRANSLATION: str(config.scoring_weights.back_translation),
        ENV_RETRIES_MAX_ATTEMPTS: str(config.retries.max_attempts),
        ENV_RETRIES_BASE_DELAY_SECONDS: str(config.retries.base_delay_seconds),
    }
