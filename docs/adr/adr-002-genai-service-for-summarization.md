# ADR-002: GenAI service for summarization

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

Approved reviews must be reduced to a 1–2 sentence summary in the target
language, and the summarizer must also emit self-assessed fluency and factual
consistency scores so the quality gate (ADR-005) can filter unfit output. The
prototype is a sandbox-scoped AWS deployment; per-review latency should be
under a couple of seconds and the integration must be one AWS SDK call away.

## Alternatives considered

1. **Amazon Bedrock (Claude 3 Haiku) via the Converse API.** Managed inference,
   IAM-scoped model access, uniform message schema across model families,
   JSON-mode-friendly system prompts, single AWS SDK call.
2. **Amazon Bedrock via `InvokeModel` with a model-specific body.** Lower-level
   API; requires per-model request/response marshalling.
3. **A third-party LLM API** (e.g. an external provider outside AWS).
4. **A self-hosted small LM on SageMaker** for tighter latency and cost
   control.

## Decision

Use **Amazon Bedrock (Anthropic Claude 3 Haiku) via the Converse API** for
summarization. The model id lives in `config/pipeline.yaml` so it can be
swapped without code changes.

## Rationale

- **API stability.** Converse abstracts over model families with the same
  request/response schema. We can swap Haiku for another Bedrock model by
  changing the `bedrock.model_id` config value; no marshalling code changes.
- **JSON discipline.** A system prompt of "always respond with a single JSON
  object" combined with a `_extract_json` guard and bounded retry (see
  `src/summarize/handler.py`) gives us deterministic-enough behaviour to feed
  the summary gate.
- **Cost & latency.** Haiku is the cheapest, fastest Claude variant, and 1–2
  sentence outputs stay well under the configured `max_tokens`. Latency fits
  the < 10s/review success criterion with margin.
- **Data governance.** All traffic stays in the AWS account and region, under
  the account's Bedrock data-usage terms. No third-party API keys.
- **Trade-off — non-determinism.** Even at `temperature ~= 0.2` responses vary
  slightly between calls. We mitigate with the summary quality gate (ADR-005)
  and the malformed-JSON bounded retry.
- **When to revisit.** If summarization quality is systematically low (rejection
  rate driven by `fluency` or `factual_consistency`) we would evaluate a
  larger Claude tier, or a fine-tuned small model on SageMaker if per-request
  cost dominates.
