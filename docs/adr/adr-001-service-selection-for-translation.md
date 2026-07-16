# ADR-001: Service selection for translation

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

The pipeline must translate product reviews from a source language (French,
German for the prototype scope) into English so shoppers on the target locale
can read them. AnyCompany Apparel already lives inside AWS and the prototype
must be deployable to a sandbox account with no third-party network egress
approval. Requirements: ISO-language-code addressable, deterministic per input,
free of per-review cold-start cost, and covered by AWS data-processing terms.

## Alternatives considered

1. **Amazon Translate.** Fully managed, per-language-pair support, no capacity
   planning, single AWS SDK call, deterministic for a given text/pair, covered
   by AWS data usage terms.
2. **Amazon Bedrock (Claude/Titan) via the Converse API.** The same GenAI model
   we already use for summarization could be prompted to translate. One
   integration surface for both stages.
3. **Self-hosted MT model** (e.g. Helsinki-NLP OPUS on SageMaker or ECS/GPU).
   Full control of the model and vocabulary; predictable cost per inference at
   high volumes.

## Decision

Use **Amazon Translate** for the translation stage.

## Rationale

- **Fit for purpose.** Translation is a well-defined, deterministic task.
  Amazon Translate is purpose-built for it, exposes a first-class SDK
  operation (`TranslateText`), and is stable across invocations, which matters
  for the back-translation similarity signal in ADR-006.
- **Cost & latency at prototype scale.** Per-request cost is a small fraction
  of a Bedrock Converse call, and warm latency is consistently low. There is
  no cold-start capacity to manage.
- **Operational simplicity.** No custom model artefacts, no endpoint autoscaling,
  no additional VPC endpoints to configure.
- **Trade-off — vocabulary control.** We give up domain-specific vocabulary
  tuning (e.g. brand names). This is acceptable for a prototype and can be
  layered on with Amazon Translate Custom Terminology later without changing
  the pipeline shape.
- **When to revisit.** If domain-specific vocabulary quality becomes the
  blocker (rejections dominated by fluency on brand-heavy reviews) or if we
  need language pairs Translate does not support, we would evaluate Custom
  Terminology first, then Bedrock, then a self-hosted model in that order.
