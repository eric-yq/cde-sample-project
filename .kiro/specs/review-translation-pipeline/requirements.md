# Requirements — Multi-Language Review Translation & Summarization Pipeline

## Introduction

AnyCompany Apparel runs direct-to-consumer e-commerce across 14 markets. Non-English
shoppers currently see product reviews that are either English-only or poorly
machine-translated, which measurably lowers conversion in non-English markets.

This spec defines a **prototype** pipeline that ingests reviews from a simulated
vendor feed, translates them with Amazon Translate, summarizes them into a 1–2
sentence overview with Amazon Bedrock (Claude), and applies a quality gate that
filters out low-confidence translations and summaries before they are surfaced.

Scope guardrails from the engagement (binding on every requirement below):

- **Synthetic data only. No PII processing.** Reviewer name and email are dropped
  at ingestion; they are never translated, summarized, stored, or logged.
- **Two language pairs only:** French→target and German→target. The pattern must
  be extensible to more languages via configuration, but only FR and DE are proven.
- **Prototype, not production.** Scaling to 12K reviews/week, monitoring, and
  go-live are out of scope (customer platform team).
- **No PDP/frontend work.** The deliverable ends at a structured output artifact.

### Glossary

- **PDP** — Product Detail Page (owned by the customer frontend team; out of scope).
- **Quality gate** — a decision step that accepts or rejects an item based on
  configurable score thresholds.
- **Target language** — the shopper's language the review is translated into.
- **Rejected item** — an item that failed a quality gate; written to a separate
  location, never surfaced.

---

## Requirement 1 — Vendor feed ingestion & PII stripping

**User story:** As the pipeline, I want to ingest and validate simulated vendor
review payloads while discarding PII, so that only non-sensitive review content
flows downstream.

#### Acceptance Criteria

1. WHEN a vendor review JSON object is submitted to the pipeline THEN the system
   SHALL validate that required fields (`review_id`, `product_id`, `text`,
   `rating`, `source_language`) are present and well-typed.
2. WHEN a review object contains `reviewer_name` or `reviewer_email` fields THEN
   the system SHALL drop those fields before any further processing and SHALL NOT
   persist or log their values.
3. IF a review object fails schema validation THEN the system SHALL route it to
   the rejected output location with a `validation_error` reason and SHALL NOT
   attempt translation.
4. WHEN `source_language` is not one of the configured supported languages THEN
   the system SHALL reject the item with an `unsupported_language` reason.
5. WHEN ingestion completes for a valid item THEN the system SHALL produce a
   normalized record containing only non-PII fields.

---

## Requirement 2 — Translation via Amazon Translate

**User story:** As the pipeline, I want to translate the source review text into
the target shopper language, so that shoppers can read reviews in their language.

#### Acceptance Criteria

1. WHEN a normalized review is processed THEN the system SHALL call Amazon
   Translate to translate `text` from `source_language` to the configured
   `target_language`.
2. WHEN translation succeeds THEN the system SHALL attach the translated text and
   the detected/declared source language to the record.
3. IF the Amazon Translate call fails with a throttling or transient error THEN
   the system SHALL retry with exponential backoff up to a configured maximum
   before failing the item.
4. WHEN the source and target language are identical THEN the system SHALL skip
   translation and pass the original text through unchanged, flagged accordingly.

---

## Requirement 3 — Translation quality gate

**User story:** As a quality owner, I want low-confidence translations filtered
out, so that shoppers never see garbled content.

#### Acceptance Criteria

1. WHEN a translation completes THEN the system SHALL compute a translation
   quality score using deterministic signals (e.g., length-ratio sanity check and
   back-translation similarity) normalized to a 0.0–1.0 range.
2. IF the translation quality score is below the configured threshold THEN the
   system SHALL route the item to the rejected location with a
   `low_translation_quality` reason and SHALL NOT summarize it.
3. WHEN the translation quality score meets or exceeds the threshold THEN the
   system SHALL pass the item to summarization.
4. WHEN an item is rejected by this gate THEN the system SHALL record the computed
   score and the threshold used.

---

## Requirement 4 — Summarization via Amazon Bedrock (Claude)

**User story:** As a shopper, I want a concise 1–2 sentence summary in my language,
so that I can grasp a review at the top of the PDP without reading everything.

#### Acceptance Criteria

1. WHEN an item passes the translation gate THEN the system SHALL call Amazon
   Bedrock using a Claude model (configurable model ID) to generate a summary in
   the target language.
2. WHEN generating the summary THEN the system SHALL instruct the model to return
   strict JSON containing the `summary`, a self-assessed `fluency` score, and a
   self-assessed `factual_consistency` score.
3. WHEN the model returns a summary THEN the system SHALL validate that the summary
   is 1–2 sentences and within a configured maximum character length.
4. IF the Bedrock response is not valid JSON or omits required fields THEN the
   system SHALL retry up to a configured maximum and, if still invalid, reject the
   item with a `summarization_error` reason.
5. IF the Bedrock call fails with a throttling or transient error THEN the system
   SHALL retry with exponential backoff up to a configured maximum.

---

## Requirement 5 — Summary quality gate

**User story:** As a quality owner, I want summaries that are the wrong length or
factually inconsistent filtered out, so that only trustworthy summaries surface.

#### Acceptance Criteria

1. WHEN a summary is generated THEN the system SHALL evaluate it against configured
   thresholds for length (1–2 sentences), fluency score, and factual-consistency
   score.
2. IF any summary check falls below its threshold THEN the system SHALL route the
   item to the rejected location with a `low_summary_quality` reason.
3. WHEN a summary passes all checks THEN the system SHALL mark the item as approved
   for output.
4. WHEN an item is rejected by this gate THEN the system SHALL record which check
   failed and the scores involved.

---

## Requirement 6 — End-to-end orchestration

**User story:** As an operator, I want the steps wired into a single orchestrated
workflow, so that a review flows from ingestion to output (or rejection) automatically.

#### Acceptance Criteria

1. WHEN a review is submitted THEN the system SHALL execute the ordered stages
   ingest → translate → translation-gate → summarize → summary-gate → output as a
   single Step Functions workflow.
2. WHEN any stage rejects an item THEN the workflow SHALL short-circuit remaining
   stages and route the item to the rejected location.
3. WHEN the workflow completes for an approved item THEN end-to-end processing
   latency SHALL be under 10 seconds per review under prototype conditions.
4. WHEN any stage raises an unhandled error THEN the workflow SHALL capture the
   error and route the item to the rejected location rather than silently dropping it.

---

## Requirement 7 — Output storage

**User story:** As a downstream consumer, I want approved results and rejected
items written to well-defined locations, so that results can be evaluated and (later)
surfaced.

#### Acceptance Criteria

1. WHEN an item is approved THEN the system SHALL write a structured output record
   to the output S3 bucket containing `review_id`, `product_id`, `source_language`,
   `target_language`, `translated_text`, `summary`, and all quality scores.
2. WHEN an item is rejected at any stage THEN the system SHALL write it to a
   distinct `rejected/` prefix (or bucket) with its rejection reason and stage.
3. WHEN output is written THEN the system SHALL NOT include any PII field.
4. WHEN output is written THEN the record SHALL be valid JSON keyed by `review_id`.

---

## Requirement 8 — Test harness & evaluation

**User story:** As the delivery engineer, I want 100 synthetic reviews with
expected outputs and an automated evaluation, so that quality can be measured
against the success criteria.

#### Acceptance Criteria

1. WHEN the test harness is present THEN it SHALL include 100 synthetic reviews
   split across French and German with no PII.
2. WHEN the evaluation runs THEN it SHALL report translation accuracy against the
   configured quality threshold across the synthetic set.
3. WHEN the evaluation runs THEN it SHALL include intentionally noisy/low-quality
   inputs and SHALL demonstrate the quality gate correctly rejects them.
4. WHEN the evaluation runs THEN it SHALL report per-item and aggregate pass/reject
   outcomes so results are reproducible.
5. WHEN unit tests run THEN core logic (validation, PII stripping, scoring, gate
   decisions) SHALL be testable without live AWS calls (mocked clients).

---

## Requirement 9 — Infrastructure as Code (CDK)

**User story:** As the customer platform team, I want the infrastructure defined as
a CDK stack, so that I can deploy and manage it reproducibly in the sandbox account.

#### Acceptance Criteria

1. WHEN the IaC is synthesized THEN it SHALL define input and output S3 buckets,
   the Lambda functions for each stage, the Step Functions workflow, and least-
   privilege IAM roles.
2. WHEN IAM roles are created THEN each Lambda SHALL be granted only the
   permissions it needs (specific S3 prefixes, Translate, and Bedrock InvokeModel).
3. WHEN the stack is deployed to the sandbox account THEN it SHALL provision
   successfully with no manual console steps.
4. WHEN configuration values (thresholds, language pairs, model ID) change THEN
   they SHALL be adjustable without code changes to business logic (env/config).
5. WHEN buckets are created THEN they SHALL block public access and encrypt data
   at rest.

---

## Requirement 10 — Documentation & extensibility

**User story:** As the customer team, I want a README and a clear extension path,
so that we can deploy and add languages independently after handoff.

#### Acceptance Criteria

1. WHEN the README is delivered THEN it SHALL include deployment steps, an
   architecture diagram, and a configuration guide.
2. WHEN the README describes extension THEN it SHALL give concrete steps to add a
   new source/target language pair via configuration.
3. WHEN a new supported language is added in configuration THEN the pipeline SHALL
   process it without changes to translation, summarization, or gate code.
4. WHEN the handoff is complete THEN the customer team SHALL be able to deploy the
   stack and run the evaluation using only the README and provided IaC.
