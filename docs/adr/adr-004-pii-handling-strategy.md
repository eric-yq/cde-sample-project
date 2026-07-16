# ADR-004: PII handling strategy

- **Status:** Accepted
- **Date:** 2025-11-01

## Context

Raw vendor reviews contain `reviewer_name` and `reviewer_email`. The
engagement scope explicitly excludes processing real PII, and the prototype
must not surface PII in any log, translation, summary, or output object.

## Alternatives considered

1. **Structural exclusion.** Define a `NormalizedRecord` dataclass with no
   PII fields, drop PII in the very first step of ingest, and let the type
   system make it impossible for downstream stages to carry PII forward.
2. **Runtime filtering.** Keep PII on the record; scrub it just before
   writing to logs, output, and any external API call, using an allow-list
   filter.
3. **Field-level tokenisation** in ingest with a separate keystore mapping
   tokens back to values — used when PII is needed downstream for some
   legitimate purpose.

## Decision

Use **structural exclusion**: drop PII in `ingest` before any validation or
logging, and normalize to a `NormalizedRecord` type that has no field for
PII. As defence in depth, the writer stage asserts that PII field names are
absent from the output record before uploading (`_assert_no_pii`).

## Rationale

- **Type system as the safety mechanism.** No downstream stage can accidentally
  include PII because there is nowhere on `NormalizedRecord` to store it.
  Runtime filtering, by contrast, is only as strong as its list of fields
  to scrub — a new PII field added upstream slips through silently.
- **Simplicity of audit.** The audit question reduces to "does
  `strip_pii()` run before any log or downstream call?" (see
  `src/ingest/`), rather than "have we enumerated every log site and every
  downstream call correctly?"
- **Zero downstream cost.** No filter overhead on every log line or every
  output write.
- **Trade-off — irreversibility.** Once dropped, PII cannot be recovered
  downstream. That is acceptable and desired for this pipeline. If a future
  use case needs the reviewer identity (e.g. moderator escalation), a
  tokenisation-based option (alternative 3) would be introduced in an ADR
  that supersedes this one.
- **When to revisit.** If real customer data (production scope) enters the
  pipeline, this ADR is superseded by a full data-classification and
  retention design; structural exclusion remains the right default even in
  that world.
