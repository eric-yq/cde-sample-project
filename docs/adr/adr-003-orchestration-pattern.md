# ADR-003: Orchestration pattern

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

The pipeline is a fixed 4-stage flow (Ingest → Translate → Summarize → Write)
with two quality gates and a rejected-output branch. Each stage is an
independent Lambda. The orchestrator must:

- provide a visual, inspectable execution log per review (the customer team
  needs to be able to debug failed items after handoff);
- support explicit error handling / Catch to a rejected-output branch (R6.4);
- not require the customer team to run additional infrastructure beyond what
  CDK deploys.

## Alternatives considered

1. **AWS Step Functions (Standard workflow).** Managed, visible executions,
   built-in retry/Catch, native Lambda integration, priced per state
   transition.
2. **AWS Step Functions (Express workflow).** Higher-throughput, priced per
   invocation duration, execution history is CloudWatch-only (no console
   graph history), 5-minute max duration.
3. **Direct Lambda chaining** — the ingest Lambda invokes translate, which
   invokes summarize, etc. No orchestrator.
4. **Amazon EventBridge + per-stage queues** — publish an event per stage
   completion, subscribe the next stage.
5. **SQS between each stage.**

## Decision

Use **AWS Step Functions Standard** for orchestration.

## Rationale

- **Debuggability wins for a handoff prototype.** Standard workflows keep
  each execution's graph and inputs/outputs in the console for 90 days. This
  is the single largest value of Standard over Express for a customer who
  will inherit the system: they can point at a failed review, open the
  execution, and see exactly which stage rejected it and with what state.
- **Explicit Catch and reject routing.** Every stage state has a Catch that
  routes to `WriteRejected`, so any unhandled exception yields a
  `pipeline_error` rejection instead of a silent failure. Direct Lambda
  chaining would push this responsibility into each Lambda, duplicating
  boilerplate.
- **Config-driven gates.** The gate `Choice` states simply route on
  `$.status`. The threshold values live in `config/pipeline.yaml` and are
  applied inside the Lambdas — the workflow definition never has to change to
  retune thresholds (see ADR-005).
- **Cost is not the constraint.** At prototype scale (~12K reviews/week)
  Standard state-transition cost is negligible. The moment throughput moves
  well above that, Express becomes worth evaluating.
- **Trade-off — 25k state-transition-per-second account soft limit.** Not
  binding at prototype scale.
- **When to revisit.** If per-review orchestration cost becomes material at
  production scale, or if executions consistently run under a few seconds and
  we need higher concurrency, migrate the hot path to Express and keep
  Standard for on-call debugging.
