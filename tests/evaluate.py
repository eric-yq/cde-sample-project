#!/usr/bin/env python3
"""End-to-end evaluation harness (R8.2, R8.3, R8.4, R6.3).

Runs the pipeline stages (ingest -> translate -> summarize) in-process over the
synthetic dataset and reports:

* translation accuracy vs the configured threshold on the clean set;
* that the quality gate correctly rejects the labeled noisy inputs, with the
  expected reason/stage;
* per-item and aggregate approve/reject outcomes;
* per-review end-to-end latency (success criterion: < 10s).

Two engine modes:

* ``offline`` (default): deterministic fake Translate/Bedrock engines built per
  review from the dataset's reference translations and noise flags. Requires no
  AWS access, so the harness is fully reproducible for the handoff walkthrough.
* ``live``: real Amazon Translate + Amazon Bedrock via boto3. Requires AWS
  credentials and Bedrock model access.

Usage:
    python tests/evaluate.py --mode offline
    python tests/evaluate.py --mode live --region us-east-1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Quiet the per-stage INFO logs so the evaluation summary is readable. Must be set
# before the stage handlers create their module-level loggers.
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from common import models  # noqa: E402
from common.config import Config  # noqa: E402
from ingest import handler as ingest  # noqa: E402
from summarize import handler as summarize  # noqa: E402
from translate import handler as translate  # noqa: E402

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_DATASET = os.path.join(os.path.dirname(__file__), "data", "dataset.json")
_CONFIG = os.path.join(_ROOT, "config", "pipeline.yaml")


# --- offline fake engines ---------------------------------------------------

class _OfflineTranslate:
    def __init__(self, target: str, reference: str, source_text: str, bad: bool):
        self.target = target
        self.reference = reference
        self.source_text = source_text
        self.bad = bad

    def translate_text(self, Text, SourceLanguageCode, TargetLanguageCode):  # noqa: N803
        if self.bad:
            # Truncated forward + unrelated back-translation -> low score.
            return {"TranslatedText": "?" if TargetLanguageCode == self.target else "zzz"}
        if TargetLanguageCode == self.target:
            return {"TranslatedText": self.reference}
        return {"TranslatedText": self.source_text}  # back-translation == original


class _OfflineBedrock:
    def __init__(self, reference: str, mode: str):
        self.reference = reference
        self.mode = mode

    def converse(self, **kwargs):
        if self.mode == "bad_json":
            text = "I could not produce JSON for this one."
        else:
            factual = 0.3 if self.mode == "bad_summary" else 0.95
            text = json.dumps(
                {"summary": self.reference, "fluency": 0.95, "factual_consistency": factual}
            )
        return {"output": {"message": {"content": [{"text": text}]}}}


class _Clients:
    def __init__(self, translate=None, bedrock=None):
        self.translate = translate
        self.bedrock = bedrock


def _offline_clients(entry: dict, config: Config) -> _Clients:
    review = entry["review"]
    reference = entry.get("_meta", {}).get("reference_translation", review.get("text", ""))
    mode = "good"
    if entry.get("_offline_bad_json"):
        mode = "bad_json"
    elif entry.get("_offline_bad_summary"):
        mode = "bad_summary"
    return _Clients(
        translate=_OfflineTranslate(
            config.target_language, reference, review.get("text", ""), bad=bool(entry.get("_offline_bad_translation"))
        ),
        bedrock=_OfflineBedrock(reference, mode),
    )


def _live_clients(region: str | None) -> _Clients:
    from common.aws_clients import build_clients

    c = build_clients(region_name=region)
    return _Clients(translate=c.translate, bedrock=c.bedrock)


# --- pipeline run -----------------------------------------------------------

def run_one(review: dict, clients: _Clients, config: Config, *, sleep) -> dict:
    """Run ingest -> translate -> summarize in-process, returning an outcome."""
    t0 = time.perf_counter()
    env = ingest.process(review, config)
    if env["status"] != models.STATUS_REJECTED:
        env = translate.process(env, clients, config, sleep=sleep)
    if env["status"] != models.STATUS_REJECTED:
        env = summarize.process(env, clients, config, sleep=sleep)
    latency = time.perf_counter() - t0

    review_id = review.get("review_id", "unknown")
    if env["status"] == models.STATUS_REJECTED:
        return {
            "review_id": review_id,
            "outcome": "rejected",
            "stage": env["rejection"]["stage"],
            "reason": env["rejection"]["reason"],
            "scores": env.get("scores", {}),
            "latency_s": round(latency, 4),
        }
    return {
        "review_id": review_id,
        "outcome": "approved",
        "translation_score": env["translation"].get("score"),
        "summary": env["summary"]["text"],
        "sentence_count": env["summary"]["sentence_count"],
        "latency_s": round(latency, 4),
    }


# --- reporting --------------------------------------------------------------

def evaluate(dataset: dict, config: Config, *, mode: str, region: str | None) -> dict:
    sleep = (lambda _s: None) if mode == "offline" else time.sleep
    results = {"clean": [], "noisy": []}

    for entry in dataset["clean"]:
        clients = _offline_clients(entry, config) if mode == "offline" else _live_clients(region)
        results["clean"].append({"expected": entry["expected"], **run_one(entry["review"], clients, config, sleep=sleep)})

    for entry in dataset["noisy"]:
        clients = _offline_clients(entry, config) if mode == "offline" else _live_clients(region)
        results["noisy"].append({"expected": entry["expected"], **run_one(entry["review"], clients, config, sleep=sleep)})

    return _summarize_results(results, config)


def _summarize_results(results: dict, config: Config) -> dict:
    clean = results["clean"]
    noisy = results["noisy"]

    clean_approved = [r for r in clean if r["outcome"] == "approved"]
    clean_scores = [r["translation_score"] for r in clean_approved if r.get("translation_score") is not None]
    threshold = config.thresholds.translation_score
    above = [s for s in clean_scores if s >= threshold]

    # Noisy: correct if rejected with the expected reason at the expected stage.
    noisy_correct = [
        r for r in noisy
        if r["outcome"] == "rejected"
        and r["reason"] == r["expected"].get("reason")
        and r["stage"] == r["expected"].get("stage")
    ]

    all_latencies = [r["latency_s"] for r in clean + noisy]
    max_latency = max(all_latencies) if all_latencies else 0.0

    clean_total = len(clean)
    summary = {
        "counts": {
            "clean_total": clean_total,
            "clean_approved": len(clean_approved),
            "noisy_total": len(noisy),
            "noisy_correctly_rejected": len(noisy_correct),
        },
        "translation_accuracy": {
            "threshold": threshold,
            "mean_score": round(sum(clean_scores) / len(clean_scores), 4) if clean_scores else None,
            "pct_at_or_above_threshold": round(100.0 * len(above) / len(clean_scores), 2) if clean_scores else None,
        },
        "latency": {"max_s": round(max_latency, 4), "budget_s": 10.0},
        "criteria": {
            "clean_all_approved": len(clean_approved) == clean_total,
            "noisy_all_correctly_rejected": len(noisy_correct) == len(noisy),
            "latency_under_budget": max_latency < 10.0,
        },
        "items": results,
    }
    summary["passed"] = all(summary["criteria"].values())
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the review pipeline.")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument("--dataset", default=_DATASET)
    parser.add_argument("--report", default=os.path.join(_ROOT, "build", "eval_report.json"))
    args = parser.parse_args()

    with open(args.dataset, "r", encoding="utf-8") as fh:
        dataset = json.load(fh)
    config = Config.from_yaml(_CONFIG)

    report = evaluate(dataset, config, mode=args.mode, region=args.region)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    c = report["counts"]
    ta = report["translation_accuracy"]
    print(f"mode={args.mode}")
    print(f"clean approved: {c['clean_approved']}/{c['clean_total']}")
    print(f"noisy correctly rejected: {c['noisy_correctly_rejected']}/{c['noisy_total']}")
    print(f"translation mean score: {ta['mean_score']} (>= {ta['threshold']}: {ta['pct_at_or_above_threshold']}%)")
    print(f"max latency: {report['latency']['max_s']}s (budget {report['latency']['budget_s']}s)")
    print(f"criteria: {report['criteria']}")
    print(f"PASSED: {report['passed']}  (report written to {args.report})")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
