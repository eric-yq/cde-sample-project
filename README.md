# Multi-Language Review Translation & Summarization Pipeline

> 中文版: [README.zh-CN.md](README.zh-CN.md)

A prototype pipeline for **AnyCompany Apparel** that ingests product reviews from a
simulated vendor feed, translates them with **Amazon Translate**, summarizes them
into a 1–2 sentence overview with **Amazon Bedrock (Claude)**, and applies a
**quality gate** that filters out low-confidence translations and summaries before
they are surfaced.

Scope: synthetic data only, no PII, two language pairs (French→English and
German→English). It is a prototype — production scaling, monitoring, and PDP
integration are intentionally out of scope (see [Boundaries](#boundaries)).

The full requirements, design, and task breakdown live in
[`.kiro/specs/review-translation-pipeline/`](.kiro/specs/review-translation-pipeline/).

---

## Architecture

```
  vendor review JSON
        │  (Step Functions execution input / batch driver)
        ▼
  ┌──────────┐   ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌────────────┐
  │  Ingest  │──▶│ Translate │──▶│  Trans.    │──▶│ Summarize │──▶│  Summary   │──▶ WriteApproved
  │  Lambda  │   │  Lambda   │   │  Gate      │   │  Lambda   │   │  Gate      │      │ results/*.json
  └────┬─────┘   └─────┬─────┘   └─────┬──────┘   └─────┬─────┘   └─────┬──────┘      │
   drop PII        Amazon        status == rejected?  Amazon        status == rejected?
   validate        Translate           │             Bedrock              │
       │            (+ back-           ▼            (Claude,               ▼
       │           translation)   WriteRejected      Converse)      WriteRejected
       └──────────────────────────▶ rejected/*.json ◀──────────────────────┘
                                          ▲
                     any unhandled error ─┘  (Catch → pipeline_error)

  Orchestration: AWS Step Functions (Standard).  Storage: Amazon S3 (input + output).
```

Each stage Lambda returns either an `ok` envelope (enriched with scores) or a
`rejected` envelope. The quality-gate decisions are made **inside the Lambdas**
using thresholds from configuration, so the `Choice` states simply route on
`$.status`. This keeps all tunables in `config/pipeline.yaml` — retuning never
requires touching the infrastructure code.

### PII handling

`reviewer_name` and `reviewer_email` are dropped in the first ingest step, before
any validation or logging. The normalized record type has no field for them, so
PII cannot flow downstream or into output. Logs are additionally PII-redacting as
defence in depth. Only synthetic data is used.

---

### Architecture decisions

The consequential design choices are recorded as ADRs under
[`docs/adr/`](docs/adr/README.md). Start there to understand *why* the system
looks the way it does before changing it:

| # | Title |
|---|-------|
| [ADR-001](docs/adr/adr-001-service-selection-for-translation.md) | Service selection for translation (Amazon Translate vs alternatives) |
| [ADR-002](docs/adr/adr-002-genai-service-for-summarization.md) | GenAI service for summarization (Bedrock Claude via Converse API) |
| [ADR-003](docs/adr/adr-003-orchestration-pattern.md) | Orchestration pattern (Step Functions Standard vs Express vs direct chaining) |
| [ADR-004](docs/adr/adr-004-pii-handling-strategy.md) | PII handling strategy (structural exclusion vs runtime filtering) |
| [ADR-005](docs/adr/adr-005-quality-gate-implementation.md) | Quality-gate implementation (in-Lambda + config thresholds) |
| [ADR-006](docs/adr/adr-006-translation-quality-scoring.md) | Translation quality scoring (length ratio + back-translation) |

### Cost analysis

Estimates below use us-east-1 on-demand pricing at the time of writing (see the
[AWS Pricing Calculator](https://calculator.aws/) for current rates). AWS Free
Tier benefits — 1M Lambda requests/month, 4K Step Functions state transitions/month —
are Always Free and are not modelled here so the numbers are pessimistic.

Assumptions per review:
- ~500 characters of source text (product-review length).
- Amazon Translate is invoked twice (forward + back-translation) → ~1000 characters.
- Amazon Bedrock Claude 3 Haiku Converse call: ~600 input tokens (system prompt +
  translated review) and ~120 output tokens (JSON with summary + scores).
- 4 Lambda invocations (ingest, translate, summarize, write_output), each ~1s at
  128 MB.
- 6 Step Functions Standard state transitions per review.
- 4 S3 PUT/GET operations per approved review.

Approximate monthly cost by scale (rounded):

| Scale | Reviews/month | Translate | Bedrock (Haiku) | Lambda | Step Functions | S3 | Total |
|---|---|---|---|---|---|---|---|
| Demo | 400 | < $0.01 | < $0.01 | Free tier | Free tier | < $0.01 | ~$0.01 |
| Pilot | ~4K (~1K/week) | ~$0.06 | ~$0.15 | Free tier | Free tier | < $0.01 | ~$0.25 |
| Production | ~48K (~12K/week) | ~$0.75 | ~$1.85 | ~$0.01 | ~$0.07 | ~$0.05 | ~$2.75 |

Trade-offs worth noting:
- **Step Functions Standard vs Express (ADR-003).** At 12K reviews/week, Standard
  state-transition cost is negligible (~$0.07/mo). Express would trade the
  90-day console execution history for a lower per-invocation cost that is not
  material at this scale — see ADR-003 for when to revisit.
- **Bedrock model choice (ADR-002).** Haiku dominates the summarization cost;
  moving to a larger Claude tier would multiply the Bedrock line item by roughly
  the token-price ratio. Retune first via `bedrock.temperature` and prompt
  length before upgrading.
- **Retries (`config/pipeline.yaml` → `retries.max_attempts`).** Each retry
  re-invokes the underlying Translate or Bedrock call and multiplies the
  associated line-item cost by up to `max_attempts` in the worst case.

For an authoritative and current estimate, plug the assumptions above into the
[AWS Pricing Calculator](https://calculator.aws/).

---

### Productionization notes

This is a prototype. The following would need to be added before running against
real customer traffic. See [Boundaries](#boundaries) for the full out-of-scope
list.

- **Scaling.** At the target rate of ~12K reviews/week the current shape is
  comfortable. Above that, revisit ADR-003 (Standard → Express workflow) and
  set Lambda reserved concurrency + a DLQ per stage.
- **Monitoring and alerting.** Add CloudWatch alarms on the Step Functions
  `ExecutionsFailed` metric, per-Lambda `Errors` and `Throttles`, and the
  rejected-output write rate. Emit a `RejectionReason` metric via EMF so the
  gate rejection mix is observable.
- **Retention and encryption.** The buckets have SSE and Block Public Access
  today. For production, add lifecycle policies on `results/` and `rejected/`,
  and consider KMS CMK-based encryption for output.
- **Real data handling.** ADR-004 is deliberately structural-exclusion for
  synthetic data. Real PII pipelines need a full data-classification and
  retention design; ADR-004 states the trigger to supersede it.
- **Integration.** Publishing summaries onto the PDP is out of scope here.
  The output S3 layout is stable, so an EventBridge-triggered publisher can
  be added without touching the pipeline.
- **Error handling.** Non-retryable Bedrock/Translate errors already route to
  `rejected/*.json` with `reason=pipeline_error`. In production, wire a DLQ
  or an SNS alert on the rejected-output rate to catch systemic issues.

---

## Repository layout

```
config/pipeline.yaml        Single source of truth for all tunables
src/common/                 Config, models, logging, AWS clients, S3 IO
src/ingest/                 Validation + PII stripping (R1)
src/translate/              Amazon Translate + translation quality gate (R2, R3)
src/summarize/              Bedrock Claude + summary quality gate (R4, R5)
src/write_output/           Approved/rejected S3 writes (R7)
infra/                      AWS CDK app (buckets, Lambdas, Step Functions, IAM)
tests/unit/                 Offline unit tests (no AWS required)
tests/data/dataset.json     100 synthetic reviews (50 FR + 50 DE) + labeled noisy inputs
tests/evaluate.py           End-to-end evaluation harness (offline or live)
scripts/generate_dataset.py Regenerates the synthetic dataset deterministically
scripts/run_batch.py        Drives the deployed pipeline from the dataset
```

---

## Prerequisites

- Python 3.12
- Node.js 18+ (only for the AWS CDK CLI, run via `npx`)
- AWS credentials for the sandbox account (`aws sts get-caller-identity` should work)
- **Amazon Bedrock model access** for the configured Claude model must be enabled
  in the target region (Bedrock console → *Model access*). The default model is
  `anthropic.claude-3-haiku-20240307-v1:0`.

Set up a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt      # tests + dataset + evaluation
pip install -r infra/requirements.txt    # AWS CDK libraries
```

---

## Run the tests (offline, no AWS)

```bash
python -m pytest
```

## Run the evaluation

Offline mode uses deterministic fake Translate/Bedrock engines built from the
dataset, so it runs anywhere with no AWS access — ideal for a reproducible demo:

```bash
python tests/evaluate.py --mode offline
```

It reports translation accuracy vs the threshold, confirms the quality gate
rejects the labeled noisy inputs, and records per-review latency. A full report is
written to `build/eval_report.json`.

Live mode runs against real Amazon Translate + Amazon Bedrock (requires creds and
Bedrock model access):

```bash
python tests/evaluate.py --mode live --region us-east-1
```

---

## Deploy to the sandbox account

```bash
cd infra

# One-time per account/region:
npx aws-cdk bootstrap

# Synthesize (optional) and deploy:
npx aws-cdk synth
npx aws-cdk deploy
```

> If the CDK CLI does not find the Python app dependencies, ensure your virtual
> environment is active, or pass it explicitly:
> `npx aws-cdk deploy --app "../.venv/bin/python app.py"`.

The stack creates: an input and an output S3 bucket (Block Public Access, SSE,
output versioned), the four Lambda functions, the Step Functions state machine,
and least-privilege IAM roles (Translate for the translate function; Bedrock
`InvokeModel` on the configured model ARN for the summarize function; scoped S3
writes for the output function).

### Drive the deployed pipeline

Find the state machine ARN and feed it the synthetic reviews:

```bash
aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name,'PipelineStateMachine')].stateMachineArn" --output text

python scripts/run_batch.py --state-machine-arn <ARN> --region us-east-1 --limit 20
```

Approved results land under `results/` and rejected items under `rejected/` in the
output bucket.

### Tear down

```bash
cd infra && npx aws-cdk destroy
```

---

## Troubleshooting

Common failure modes when standing the pipeline up for the first time:

- **`AccessDeniedException` invoking a Bedrock model.** The configured model
  in `config/pipeline.yaml` (`bedrock.model_id`) does not have Model access
  enabled in this account/region. Open the Bedrock console → *Model access* in
  the same region as the CDK stack and request access to the exact model id.
- **CDK bootstrap or deploy fails with a credentials or account error.**
  Confirm `aws sts get-caller-identity` returns the sandbox account, run
  `npx aws-cdk bootstrap` once per account/region, and make sure the CDK app
  is invoked from an active virtual environment (`source .venv/bin/activate`)
  so the CDK CLI picks up the Python dependencies.
- **`cdk deploy` cannot find the Python app.** Pass the interpreter
  explicitly: `npx aws-cdk deploy --app "../.venv/bin/python app.py"`.
- **Step Functions execution ends with `pipeline_error` on the very first
  review.** Open the failed execution in the Step Functions console, follow
  the CloudWatch Logs link for the stage Lambda that raised, and check for:
  Bedrock access errors (see above), a Translate `UnsupportedLanguagePairException`
  (the source language must be in `config/pipeline.yaml`'s
  `supported_languages`), or an S3 `AccessDenied` on the output bucket
  (indicates the CDK output-writer role is out of sync — redeploy).
- **`AccessDenied` writing to the output bucket.** The CDK stack scopes the
  writer role to the output bucket and the `results/*`/`rejected/*` prefixes.
  If you renamed the bucket outside CDK, redeploy the stack to reissue the
  policy.
- **Tests fail with `ModuleNotFoundError` for `common` or `summarize`.** Run
  tests from the repo root (`python -m pytest`) with the virtual environment
  active; `pytest.ini` sets the import path so tests can import the `src/`
  packages by short name.
- **`SummarizationError: no valid summary after retries` in the logs.** The
  model returned non-JSON output past the bounded retry budget. Verify the
  configured model id is a Claude model with the Converse API surface, and
  that `bedrock.temperature` in config is low enough for JSON-mode behaviour.

---

## Configuration guide

All tunables live in [`config/pipeline.yaml`](config/pipeline.yaml). They are read
at CDK synth time and injected into every Lambda as environment variables, so a
change takes effect on the next `cdk deploy` with **no code changes**.

| Key | Meaning |
|---|---|
| `target_language` | Shopper language reviews are translated into |
| `supported_languages` | Accepted source language codes |
| `bedrock.model_id` | Claude model id (must be enabled in Bedrock model access) |
| `bedrock.max_tokens` / `temperature` | Generation controls |
| `thresholds.translation_score` | Min composite translation score to pass the gate |
| `thresholds.fluency` / `factual_consistency` | Min summary self-assessed scores |
| `thresholds.max_summary_chars` | Hard cap on summary length |
| `thresholds.length_ratio_min/max` | Acceptable translated/source length ratio band |
| `scoring_weights.length` / `back_translation` | Translation score component weights (sum to 1.0) |
| `retries.max_attempts` / `base_delay_seconds` | Retry/backoff for AWS calls |

The translation score is a deterministic, explainable blend of a length-ratio
sanity check and a back-translation similarity (translate the result back to the
source language and compare to the original). Tune the weights and thresholds here.

---

## Extending to more languages

The pipeline is language-agnostic. To add a language pair:

1. Add the source language code to `supported_languages` in `config/pipeline.yaml`
   (for example, add `es` for Spanish). Ensure Amazon Translate supports the
   source→`target_language` pair.
2. Redeploy: `cd infra && npx aws-cdk deploy`.

No changes to the translation, summarization, or quality-gate code are required —
the summarizer prompt derives the target-language name from the code, and the
gates are threshold-driven. Add synthetic examples for the new language to
`scripts/generate_dataset.py` if you want it covered by the evaluation.

---

## Success criteria mapping

| Criterion | How it is met / verified |
|---|---|
| 1. Translation accuracy above threshold | Deterministic translation score + gate; `tests/evaluate.py` reports mean score and % ≥ threshold |
| 2. Summaries 1–2 sentences, fluent, factually consistent | Bedrock strict-JSON summary + summary gate (sentence count, length, fluency, factual consistency) |
| 3. End-to-end latency < 10s/review | Reported per review by `tests/evaluate.py` |
| 4. Quality gate filters low-confidence outputs | 9 labeled noisy inputs in the dataset; evaluation confirms each is rejected with the expected reason |
| 5. Team can deploy and extend independently | This README + CDK stack + config-driven language extension |

---

## Boundaries

Out of scope for this prototype (per the engagement): real customer data / PII
processing, production deployment and scaling to ~12K reviews/week, monitoring and
alerting, PDP/frontend integration, and source languages beyond French and German.
The design leaves clean seams (config-driven languages, per-stage Step Functions
states, structured S3 output) for the customer team to fan out post-handoff.
