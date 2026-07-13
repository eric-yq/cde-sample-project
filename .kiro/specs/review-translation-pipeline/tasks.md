# Implementation Plan — Multi-Language Review Translation & Summarization Pipeline

Tasks are ordered for incremental, test-driven delivery. Each builds on prior
output; no orphaned code. Requirement references point to `requirements.md`.
The `Week` tags map to the engagement's 3-week timeline.

---

## Week 1 — Scaffolding, translation, ingestion, initial quality eval

- [ ] 1. Project scaffolding and shared foundation
  - Create the repo structure (`infra/`, `src/common`, `src/*`, `config/`, `tests/`, `scripts/`).
  - Add `config/pipeline.yaml` with target/supported languages, model ID, thresholds, scoring weights, retries.
  - Implement `src/common`: config loader, structured PII-safe logger, S3 IO helpers, AWS client factory.
  - _Requirements: R9.4, R10.2_

- [ ] 2. Define the pipeline data models
  - Implement the normalized record, approved-output, and rejected-output models with (de)serialization.
  - Ensure the normalized record structurally omits `reviewer_name`/`reviewer_email`.
  - Write unit tests for serialization and the no-PII guarantee.
  - _Requirements: R1.5, R7.1, R7.2, R7.3_

- [ ] 3. Ingestion + PII stripping (`src/ingest`)
  - [ ] 3.1 Implement schema validation and required-field/type checks.
    - _Requirements: R1.1_
  - [ ] 3.2 Drop `reviewer_name`/`reviewer_email` before any processing; never log values.
    - _Requirements: R1.2_
  - [ ] 3.3 Reject with `validation_error` on bad schema and `unsupported_language` on unknown source language.
    - _Requirements: R1.3, R1.4_
  - [ ] 3.4 Unit tests: valid input, missing fields, PII removal, unsupported language.
    - _Requirements: R1.1–R1.5, R8.5_

- [ ] 4. Translation module (`src/translate`) — Amazon Translate
  - [ ] 4.1 Wrap `translate_text` (source→target); handle `source==target` pass-through with flag.
    - _Requirements: R2.1, R2.2, R2.4_
  - [ ] 4.2 Add retry with exponential backoff for throttling/transient errors.
    - _Requirements: R2.3_
  - [ ] 4.3 Unit tests with mocked Translate (success, pass-through, retry-then-succeed, fail).
    - _Requirements: R2.1–R2.4, R8.5_

- [ ] 5. Translation quality scoring + gate (`src/translate`)
  - [ ] 5.1 Implement length-ratio component and back-translation similarity component; combine to [0,1] via config weights.
    - _Requirements: R3.1_
  - [ ] 5.2 Record score + threshold on the record; expose gate decision for the workflow Choice.
    - _Requirements: R3.2, R3.3, R3.4_
  - [ ] 5.3 Unit tests: high-quality passes, garbled/truncated fails, score is deterministic.
    - _Requirements: R3.1–R3.4, R8.5_

- [ ] 6. Synthetic dataset generator + initial 100 reviews
  - Generate ≈50 FR + ≈50 DE reviews (no PII) plus a labeled set of noisy inputs (truncated, empty, mixed-language, over-length).
  - Store under `tests/data/` with expected/label metadata.
  - _Requirements: R8.1, R8.3_

- [ ] 7. Week-1 checkpoint: initial translation quality evaluation
  - Run ingest+translate+gate over the dataset; produce a first accuracy-vs-threshold report.
  - _Requirements: R8.2, R8.4_

---

## Week 2 — Bedrock summarization, quality gate, end-to-end wiring

- [ ] 8. Summarization module (`src/summarize`) — Bedrock Converse (Claude)
  - [ ] 8.1 Build a target-language prompt requiring strict JSON (`summary`, `fluency`, `factual_consistency`).
    - _Requirements: R4.1, R4.2_
  - [ ] 8.2 Call Bedrock Converse with the configured model ID; parse and validate JSON.
    - _Requirements: R4.1, R4.2_
  - [ ] 8.3 Validate summary is 1–2 sentences and within max length; add `sentence_count`.
    - _Requirements: R4.3_
  - [ ] 8.4 In-Lambda bounded retry for malformed JSON → `summarization_error`; backoff for throttling/transient.
    - _Requirements: R4.4, R4.5_
  - [ ] 8.5 Unit tests with mocked Bedrock (valid JSON, malformed-then-valid, wrong length, throttle).
    - _Requirements: R4.1–R4.5, R8.5_

- [ ] 9. Summary quality gate (`src/summarize`)
  - Evaluate length, fluency, and factual-consistency thresholds; on failure set `low_summary_quality` and record failing check + scores.
  - Unit tests for each failing dimension and the all-pass case.
  - _Requirements: R5.1–R5.4, R8.5_

- [ ] 10. Output writer (`src/write_output`)
  - Implement approved (`results/{id}.json`) and rejected (`rejected/{id}.json`) writes; guarantee no PII in output.
  - Unit tests: approved shape, rejected shape with reason+stage, PII absence.
  - _Requirements: R7.1–R7.4_

- [ ] 11. CDK stack (`infra/`) — provision all resources
  - [ ] 11.1 Define input/output S3 buckets with Block Public Access, SSE, and output versioning.
    - _Requirements: R9.1, R9.5_
  - [ ] 11.2 Define the four Lambdas (Python 3.12) with env-injected config.
    - _Requirements: R9.1, R9.4_
  - [ ] 11.3 Define the Step Functions state machine: Ingest→Translate→TranslationGate(Choice)→Summarize→SummaryGate(Choice)→WriteApproved/WriteRejected, with per-task retries and Catch→`pipeline_error`.
    - _Requirements: R6.1, R6.2, R6.4_
  - [ ] 11.4 Least-privilege IAM per Lambda (scoped S3 prefixes, Translate, Bedrock InvokeModel on model ARN).
    - _Requirements: R9.2_
  - [ ] 11.5 `cdk synth`/`deploy` succeeds to sandbox with no manual console steps (Bedrock access noted as prereq).
    - _Requirements: R9.3_

- [ ] 12. End-to-end wiring and batch driver
  - Implement `scripts/run_batch.py` to start an execution per input file (simulated feed).
  - Run FR + DE reviews end-to-end; confirm approved/rejected routing and short-circuit on gate failure.
  - _Requirements: R6.1, R6.2_

---

## Week 3 — Quality tuning, documentation, handoff

- [ ] 13. Full evaluation harness (`tests/evaluate.py`)
  - Run all 100 reviews end-to-end; report per-item and aggregate translation accuracy vs threshold and gate outcomes; record per-review latency.
  - Demonstrate the gate rejects the noisy inputs.
  - _Requirements: R8.2, R8.3, R8.4, R6.3_

- [ ] 14. Quality tuning
  - Tune thresholds and scoring weights in `config/pipeline.yaml` to meet success criteria; re-run evaluation. Confirm no business-logic code changed during tuning.
  - _Requirements: R3.1, R5.1, R9.4_

- [ ] 15. Latency verification
  - Confirm end-to-end processing is < 10s per review under prototype conditions; capture numbers in the eval report.
  - _Requirements: R6.3_

- [ ] 16. README and architecture diagram
  - Write deployment steps, architecture diagram, and configuration guide.
  - _Requirements: R10.1_

- [ ] 17. Extensibility guide + verification
  - Document adding a new language pair via `supported_languages` config; verify a third code flows through with no code change.
  - _Requirements: R10.2, R10.3, R10.4_

- [ ] 18. Handoff walkthrough package
  - Ensure deploy + evaluate run from README alone; assemble the walkthrough for Priya's team.
  - _Requirements: R10.4_
