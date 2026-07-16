# ADR-006: Translation quality scoring

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

The translation quality gate needs a per-review score that (a) can be produced
using only AWS services already in the pipeline, (b) is deterministic for a
given input so evaluation and regression tests are stable, (c) is explainable
to a non-ML customer team, and (d) can flag both truncation and semantic
drift.

## Alternatives considered

1. **Composite of length-ratio sanity + back-translation similarity.**
   - Length-ratio component: 1.0 when translated/original token count sits in
     a configured band, decaying towards 0.0 outside it.
   - Back-translation component: translate the result back to the source
     language with Amazon Translate, compare token sets to the original;
     score is the fraction of original distinct tokens that survive the
     round trip.
   - Final score is a weighted mean of the two.
2. **BLEU.** Requires reference translations, which we do not have for real
   inputs — only for the synthetic evaluation dataset.
3. **Embedding-based semantic similarity** using an Amazon Bedrock embedding
   model (or SageMaker JumpStart) on source and translation.
4. **LLM-as-judge** — ask a Bedrock model to rate the translation.

## Decision

Use option 1: **composite score = weighted mean of a length-ratio component
and a back-translation similarity component.** Weights, ratio band, and
threshold live in `config/pipeline.yaml`.

## Rationale

- **AWS-native, no extra dependency.** Uses only Amazon Translate, which is
  already deployed for the forward translation. No new service, no new IAM
  role, no third-party model.
- **Deterministic.** Amazon Translate is stable for a given input, and the
  scoring code has no randomness. Evaluation runs and regression tests give
  the same numbers each time.
- **Catches both failure modes we care about.** The length-ratio component
  detects truncation and runaway output; the back-translation component
  detects semantic drift. In the labeled noisy dataset, each labeled failure
  mode is rejected with the expected reason.
- **Explainable.** Both components are token-set arithmetic. A rejected
  review carries both sub-scores in its envelope so a reviewer can see
  exactly why it failed.
- **Trade-off — order-insensitive similarity.** Back-translation similarity
  is a token-set containment ratio, so it does not penalise legitimate MT
  reordering (this is intentional, and calibrated on real Amazon Translate
  round-trips). The cost is that it can miss subtle semantic drift where the
  vocabulary is preserved but the meaning has shifted. Given the length of
  product reviews, this is acceptable at prototype scale.
- **Trade-off — no reference translations.** BLEU (option 2) would be a
  stronger signal but is only available on the synthetic evaluation set. We
  keep BLEU-flavoured measurement inside the evaluation harness, and use
  the composite for live scoring.
- **When to revisit.** If either sub-score is systematically miscalibrated
  we would first retune the band and weights in config. If sub-scores stop
  correlating with human judgement, we would add a third component using an
  embedding model (option 3) rather than replace the deterministic score.
