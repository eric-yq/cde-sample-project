# ADR-005: Quality-gate implementation

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

Two quality gates guard the pipeline: the translation gate (a composite
translation score must clear a threshold) and the summary gate (sentence
count, length, fluency, factual consistency must all pass). Thresholds must
be tunable **without code or infrastructure changes** because they will be
retuned as more real data becomes available.

## Alternatives considered

1. **Gate inside the stage Lambda.** The Lambda that produced the artefact
   also decides whether it passes, using thresholds from
   `config/pipeline.yaml`. The Step Functions `Choice` state simply routes
   on `$.status`.
2. **Gate as a Step Functions `Choice` state with hard-coded thresholds** in
   the state machine definition.
3. **Dedicated gate Lambdas.** A separate `translation_gate` Lambda between
   translate and summarize, and a `summary_gate` Lambda after summarize.

## Decision

Use option 1: **gate decisions are made inside the stage Lambda using
threshold values loaded from `config/pipeline.yaml` at cold start. Step
Functions only routes on `$.status`.**

## Rationale

- **Config-only retuning.** The core operational lever for this pipeline is
  "raise or lower the quality bar." Keeping thresholds in `pipeline.yaml`
  means retuning is a config change + redeploy, never a code change and never
  a workflow definition change.
- **One source of scores.** The Lambda that computes the scores also applies
  the threshold. The Step Functions definition never has to know about score
  fields, so adding a new score component (e.g. a third translation
  sub-signal) is a Lambda-local change.
- **Explainable rejections.** Because the decision runs where the scores
  live, the rejected envelope carries the exact scores that failed the gate
  and a `failed_check` label. Debugging a rejected review is a single-record
  read, no cross-referencing of Step Functions state.
- **Trade-off — losing the Choice-state visual gate marker.** A `Choice`
  state named `TranslationGate` in the state graph would be visually
  informative in the Step Functions console. We compensate by naming the
  routing states clearly (`TranslationGateChoice`, `SummaryGateChoice`) and
  logging the gate decision from the Lambda.
- **Trade-off — dedicated gate Lambdas would give per-stage failure
  isolation.** Not worth the extra Lambda + IAM role for the prototype; the
  gate logic is tiny and lives naturally where the scores are produced.
- **When to revisit.** If gate logic grows to include cross-record features
  (e.g. moving averages, per-product baselines) it should move to a
  dedicated stage with its own state and telemetry.
