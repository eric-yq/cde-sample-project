#!/usr/bin/env python3
# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""Batch driver: feed the deployed pipeline from the simulated vendor feed (R6.1).

Starts one Step Functions execution per review in the dataset, polls until each
completes, and prints an approve/reject summary. This stands in for the vendor
feed pushing reviews at the deployed prototype in the sandbox account.

Requires the stack to be deployed and AWS credentials with permission to start
executions on the pipeline state machine.

Usage:
    python scripts/run_batch.py --state-machine-arn <ARN> [--region us-east-1] [--limit N]

Find the ARN after deploy with:
    aws stepfunctions list-state-machines --query "stateMachines[?contains(name,'PipelineStateMachine')]"
"""

from __future__ import annotations

import argparse
import json
import os
import time

# How often to poll each Step Functions execution while it is RUNNING.
# One-second granularity is fine for a batch driver (per-review latency is
# dominated by Translate + Bedrock latency, not the polling interval) and
# keeps the DescribeExecution call rate well below AWS default limits.
POLL_INTERVAL_SECONDS = 1

_DATASET = os.path.join(os.path.dirname(__file__), "..", "tests", "data", "dataset.json")


def _load_reviews(dataset_path: str, limit: int | None) -> list[dict]:
    with open(dataset_path, "r", encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)
    reviews = [e["review"] for e in dataset["clean"]] + [e["review"] for e in dataset["noisy"]]
    return reviews[:limit] if limit else reviews


def run(state_machine_arn: str, region: str | None, dataset_path: str, limit: int | None) -> dict:
    import boto3

    sfn = boto3.client("stepfunctions", region_name=region)
    reviews = _load_reviews(dataset_path, limit)

    executions = []
    for review in reviews:
        resp = sfn.start_execution(stateMachineArn=state_machine_arn, input=json.dumps(review))
        executions.append((review.get("review_id", "unknown"), resp["executionArn"]))

    outcomes = {"approved": 0, "rejected": 0, "failed": 0}
    details = []
    for review_id, arn in executions:
        status = "RUNNING"
        output = None
        while status == "RUNNING":
            desc = sfn.describe_execution(executionArn=arn)
            status = desc["status"]
            output = desc.get("output")
            if status == "RUNNING":
                time.sleep(POLL_INTERVAL_SECONDS)
        if status != "SUCCEEDED":
            outcomes["failed"] += 1
            details.append({"review_id": review_id, "status": status})
            continue
        parsed = json.loads(output) if output else {}
        mode = parsed.get("mode", "unknown")
        outcomes[mode] = outcomes.get(mode, 0) + 1
        details.append({"review_id": review_id, "status": status, "mode": mode, "key": parsed.get("written")})

    return {"outcomes": outcomes, "details": details}


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive the deployed pipeline from the dataset.")
    parser.add_argument("--state-machine-arn", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument("--dataset", default=_DATASET)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    result = run(args.state_machine_arn, args.region, args.dataset, args.limit)
    print(json.dumps(result["outcomes"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
