# Design — Multi-Language Review Translation & Summarization Pipeline

## Overview

A serverless, event-driven prototype that turns a raw vendor review into a
quality-gated, translated 1–2 sentence summary in the shopper's language. The
pipeline is orchestrated by AWS Step Functions and implemented as small,
single-responsibility AWS Lambda functions. Amazon Translate handles translation;
Amazon Bedrock (Claude) handles summarization with self-assessed quality scores.
Two deterministic quality gates filter low-confidence output before it is written
to an approved-output location.

Design priorities, in order: **correctness of the quality gate**, **no PII**,
**latency < 10s/review**, and **the customer team can deploy and extend it alone**.

This is a prototype. Throughput scaling (12K/week), monitoring/alerting, and go-live
are explicitly out of scope and are called out where relevant so the customer team
knows where to take it next.

### Requirements coverage map

| Requirement | Where addressed |
|---|---|
| R1 Ingestion & PII stripping | `ingest` Lambda, Normalized Record model |
| R2 Translation | `translate` Lambda (Amazon Translate) |
| R3 Translation quality gate | `translate` Lambda scoring + Choice state |
| R4 Summarization | `summarize` Lambda (Bedrock Converse, Claude) |
| R5 Summary quality gate | `summarize` Lambda scoring + Choice state |
| R6 Orchestration | Step Functions state machine |
| R7 Output storage | `write_output` + S3 layout |
| R8 Test harness | `tests/`, synthetic data generator, eval script |
| R9 IaC (CDK) | `infra/` CDK app + stack |
| R10 Docs & extensibility | README + `config/languages` design |

---

## Architecture

```
                       ┌──────────────────────────────────────┐
                       │  Input S3 bucket  (incoming/*.json)   │
                       └───────────────┬──────────────────────┘
                                       │  (manual start / batch driver)
                                       ▼
                        ┌──────────────────────────────┐
                        │   Step Functions state machine │
                        └──────────────────────────────┘
   ┌─────────┐   ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌────────────┐
   │ Ingest  │──▶│ Translate │──▶│ TransGate  │──▶│ Summarize │──▶│ SummaryGate│──┐
   │ Lambda  │   │  Lambda   │   │  (Choice)  │   │  Lambda   │   │  (Choice)  │  │
   └────┬────┘   └─────┬─────┘   └─────┬──────┘   └─────┬─────┘   └─────┬──────┘  │
        │ reject       │ retry         │ reject         │ retry         │ reject   │ pass
        ▼              ▼               ▼                ▼               ▼          ▼
   ┌───────────────────────────────────────────────────┐        ┌──────────────────┐
   │  Output S3 bucket — rejected/  (reason + stage)    │        │ Output — results/│
   └───────────────────────────────────────────────────┘        └──────────────────┘

   External services:  Amazon Translate  •  Amazon Bedrock (Claude via Converse API)
```

Translate and Summarize call AWS AI services; each is wrapped with retry/backoff.
The two gates are Step Functions `Choice` states that read a score the preceding
Lambda attached to the payload and branch to either the next stage or a shared
`WriteRejected` task.

### Why these choices

- **Step Functions over a single fat Lambda:** the scope doc explicitly lists a
  Step Functions workflow, and per-stage states give clean retry policies, visible
  execution history for the handoff walkthrough, and easy insertion of future stages.
- **Amazon Bedrock Converse API:** a single, model-agnostic request/response shape.
  Swapping the Claude model ID (or another provider later) needs only a config change,
  which directly supports the "extensible / deploy independently" success criterion.
- **CDK (Python):** one language across infra, Lambda code, and tests lowers the
  cognitive load for the customer team taking over.
- **Deterministic translation gate:** back-translation + length-ratio gives a
  reproducible, explainable score for evaluation, rather than an opaque model call.

---

## Technology choices

| Concern | Choice | Notes |
|---|---|---|
| IaC | AWS CDK v2 (Python) | Single stack; `cdk deploy` to sandbox |
| Runtime | Python 3.12 Lambda | boto3 for Translate + Bedrock |
| Orchestration | AWS Step Functions (Standard) | Visible per-stage execution history |
| Translation | Amazon Translate | `translate_text`; also used for back-translation |
| Summarization | Amazon Bedrock, Claude via **Converse API** | Model ID from config; default a Claude Haiku-class model for latency/cost |
| Storage | Amazon S3 | Input, results, rejected; SSE + block public access |
| Testing | pytest + moto/stubs | Core logic unit-tested with mocked AWS |
| Packaging | CDK `PythonFunction` / bundling | Shared `common` layer or per-fn deps |

> The default Bedrock model ID is set in config and confirmed against the sandbox
> account's enabled models during Week 1 (model access must be granted in Bedrock
> console). The design does not hard-code a model ID in business logic.

---

## Step Functions workflow

States (Standard workflow):

1. **Ingest** (`Task` → ingest Lambda)
   - Output: `{ status: "ok" | "rejected", record?, rejection? }`
   - Retry: none (deterministic, no external call).
2. **PostIngestChoice** (`Choice`) — if `status == rejected` → `WriteRejected`,
   else → `Translate`.
3. **Translate** (`Task` → translate Lambda)
   - Retry: `Translate.ThrottlingException`, transient 5xx → backoff (2s, x2, max N).
   - Attaches `translation_score`.
4. **TranslationGate** (`Choice`) — `translation_score >= translation_threshold`
   → `Summarize`, else set reason `low_translation_quality` → `WriteRejected`.
5. **Summarize** (`Task` → summarize Lambda)
   - Retry: Bedrock throttling / transient → backoff; invalid-JSON handled inside
     the Lambda with its own bounded retry.
   - Attaches `summary`, `fluency`, `factual_consistency`.
6. **SummaryGate** (`Choice`) — all summary checks pass → `WriteApproved`, else
   reason `low_summary_quality` → `WriteRejected`.
7. **WriteApproved** (`Task` → write_output Lambda, mode=approved) → `Success`.
8. **WriteRejected** (`Task` → write_output Lambda, mode=rejected) → `Success`.

A top-level `Catch` on each `Task` routes unhandled errors to `WriteRejected`
with reason `pipeline_error` (R6.4 — never silently drop).

State I/O is the pipeline record (below); each Lambda receives the record and
returns it enriched. Result paths keep the record intact between stages.

---

## Component design

All Lambdas share a `common` module: config loading, S3 IO helpers, the record
data model, structured logging (PII-safe), and a Bedrock/Translate client factory.

### `ingest` (R1)
- **Input:** raw vendor JSON.
- **Behavior:** validate schema; **drop `reviewer_name` and `reviewer_email`**
  before anything else; verify `source_language` is supported.
- **Output:** normalized record (no PII) or a rejection with reason
  `validation_error` / `unsupported_language`.

### `translate` (R2, R3)
- **Input:** normalized record.
- **Behavior:**
  - If `source_language == target_language`, skip (flag `translation_skipped=true`,
    score `1.0`).
  - Else call `translate_text` (source→target).
  - Compute `translation_score` (see Scoring below).
- **Output:** record + `translated_text`, `translation_score`.

### `summarize` (R4, R5)
- **Input:** record that passed the translation gate.
- **Behavior:** build a target-language prompt instructing Claude to return
  **strict JSON**: `{ "summary": str, "fluency": 0-1, "factual_consistency": 0-1 }`.
  Call Bedrock Converse. Parse + validate JSON; if malformed, retry up to N; then
  reject `summarization_error`. Validate summary sentence count (1–2) and max length.
- **Output:** record + `summary`, `fluency`, `factual_consistency`, `sentence_count`.

### `write_output` (R7)
- **mode=approved:** write result JSON to `results/{review_id}.json`.
- **mode=rejected:** write to `rejected/{review_id}.json` with `rejection.reason`
  and `rejection.stage`.
- Guarantees no PII field is ever included.

---

## Scoring & quality-gate logic

### Translation score (deterministic, R3.1)
Composite in [0,1], reproducible for evaluation:
- **Length-ratio sanity:** ratio of translated to source token count; penalize
  ratios outside a configured band (catches truncation / runaway output).
- **Back-translation similarity:** translate the target text back to the source
  language and compare to the original with a normalized token-overlap /
  similarity metric.
- `translation_score = weighted_avg(length_component, backtranslation_component)`
  with weights in config.

> Trade-off: back-translation doubles Translate calls but stays well within the
> 10s budget and gives an explainable, model-free signal ideal for the evaluation
> deliverable. Documented as a tunable in the README.

### Summary checks (R5.1)
- `sentence_count in {1, 2}` and `len(summary) <= max_summary_chars`.
- `fluency >= fluency_threshold`.
- `factual_consistency >= factual_threshold`.
All must pass; otherwise `low_summary_quality` with the failing check recorded.

Thresholds live in config so tuning (Week 3) needs no code change.

---

## Data models

### Vendor input (simulated feed)
```json
{
  "review_id": "r-000123",
  "product_id": "SKU-4457",
  "text": "Ce t-shirt est incroyablement doux et taille parfaitement.",
  "rating": 5,
  "source_language": "fr",
  "reviewer_name": "DROPPED at ingest",
  "reviewer_email": "DROPPED at ingest"
}
```

### Normalized record (post-ingest, no PII)
```json
{
  "review_id": "r-000123",
  "product_id": "SKU-4457",
  "text": "Ce t-shirt est incroyablement doux et taille parfaitement.",
  "rating": 5,
  "source_language": "fr",
  "target_language": "en"
}
```

### Approved output (`results/{review_id}.json`, R7.1)
```json
{
  "review_id": "r-000123",
  "product_id": "SKU-4457",
  "source_language": "fr",
  "target_language": "en",
  "translated_text": "This t-shirt is incredibly soft and fits perfectly.",
  "summary": "Shoppers find this t-shirt very soft with an accurate fit.",
  "scores": {
    "translation_score": 0.94,
    "fluency": 0.97,
    "factual_consistency": 0.95,
    "sentence_count": 1
  },
  "status": "approved"
}
```

### Rejected output (`rejected/{review_id}.json`, R7.2)
```json
{
  "review_id": "r-000777",
  "status": "rejected",
  "rejection": { "stage": "translation_gate", "reason": "low_translation_quality" },
  "scores": { "translation_score": 0.41, "threshold": 0.70 }
}
```

---

## Configuration (R9.4, R10.2/10.3)

A single config source (env vars set by CDK + a `config/` file for defaults) drives
all tunables — **no business-logic code changes to retune or add a language**:

```yaml
target_language: en
supported_languages: [fr, de]        # add new codes here to extend
bedrock:
  model_id: anthropic.claude-3-haiku-20240307-v1:0   # overridable
  max_tokens: 300
  temperature: 0.2
thresholds:
  translation_score: 0.70
  fluency: 0.80
  factual_consistency: 0.80
  max_summary_chars: 320
  length_ratio_band: [0.5, 2.0]
scoring_weights:
  length: 0.3
  back_translation: 0.7
retries:
  max_attempts: 3
  base_delay_seconds: 2
```

Adding a language = add its code to `supported_languages` and ensure Translate
supports the pair. No code change (R10.3).

---

## Error handling

| Failure | Handling |
|---|---|
| Schema invalid / unsupported language | Reject at ingest (no external calls) |
| Translate throttling / 5xx | SFN retry w/ exponential backoff, max N; then reject `pipeline_error` |
| Bedrock throttling / 5xx | SFN retry w/ backoff; then reject `pipeline_error` |
| Bedrock returns non-JSON / missing fields | In-Lambda bounded retry; then reject `summarization_error` |
| Summary wrong length / low scores | Reject `low_summary_quality` (expected path, not an error) |
| Any unhandled exception in a Task | SFN `Catch` → `WriteRejected` reason `pipeline_error` |

No item is ever silently dropped (R6.2, R6.4). Logs are structured and PII-safe.

---

## Security & compliance

- **PII:** `reviewer_name` / `reviewer_email` dropped in the first ingest step and
  never persisted or logged. Only synthetic data is used. This is enforced by the
  Normalized Record model omitting those fields entirely.
- **IAM (R9.2, least privilege):** ingest → read input prefix; translate →
  `translate:TranslateText` + read/write working data; summarize →
  `bedrock:InvokeModel` on the configured model ARN only; write_output → write to
  `results/` and `rejected/` prefixes only.
- **S3 (R9.5):** SSE (S3-managed or KMS), Block Public Access on all buckets,
  versioning on output for auditability.
- **Bedrock model access** must be enabled in the sandbox account (a console/CLI
  one-time grant); documented in README prerequisites.

---

## Testing strategy (R8)

- **Unit tests (no live AWS):** schema validation, PII stripping, translation
  scoring math, summary sentence/length checks, gate decision logic. AWS clients
  mocked (moto / botocore stubs).
- **Synthetic dataset:** a generator produces 100 reviews (≈50 FR, ≈50 DE) plus a
  set of intentionally noisy inputs (truncated, mixed-language, empty, over-length)
  to prove the gate rejects them (R8.3).
- **Evaluation script:** runs the dataset (against real services or a record/replay
  fixture), reports per-item and aggregate translation accuracy vs threshold and
  gate pass/reject outcomes (R8.2, R8.4). Reproducible via a single command.
- **Latency check:** the evaluation records per-review end-to-end time to
  demonstrate < 10s (R6.3).

---

## Deployment (R9.3)

- Prereqs: AWS credentials for the sandbox, CDK bootstrapped, Bedrock model access
  granted, Python 3.12.
- `cdk deploy` provisions buckets, Lambdas, state machine, IAM — no console steps.
- A small driver script starts an execution per input file (simulated feed). The
  README documents both single-review and batch invocation.

---

## Proposed project structure

```
cde-sample-project/
├── infra/
│   ├── app.py                     # CDK app entrypoint
│   └── stacks/
│       └── pipeline_stack.py      # buckets, lambdas, state machine, IAM
├── src/
│   ├── common/                    # config, models, s3 io, clients, logging
│   ├── ingest/handler.py          # R1
│   ├── translate/handler.py       # R2, R3 (scoring)
│   ├── summarize/handler.py       # R4, R5 (Bedrock Converse + checks)
│   └── write_output/handler.py    # R7
├── config/
│   └── pipeline.yaml              # thresholds, languages, model id
├── tests/
│   ├── unit/                      # mocked-AWS unit tests
│   ├── data/                      # 100 synthetic reviews + expected outputs
│   └── evaluate.py                # end-to-end evaluation + report
├── scripts/
│   └── run_batch.py               # start executions from input files
└── README.md                      # deploy, architecture, config, extend
```

---

## Out of scope (restated for the handoff)

Production scaling to 12K/week, monitoring/alerting/dashboards, PDP/frontend
integration, real-data/PII handling, and languages beyond FR/DE. The design leaves
clean seams for each (config-driven languages, per-stage states, structured output)
so the customer team can fan out post-handoff.
