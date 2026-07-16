# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
# Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""CDK stack for the review translation & summarization pipeline (R9).

Provisions:
* input and output S3 buckets (Block Public Access + SSE; output versioned);
* four Python 3.12 Lambda functions (ingest, translate, summarize, write_output)
  configured entirely from environment variables derived from config/pipeline.yaml;
* a Standard Step Functions workflow wiring the stages with per-stage quality
  gates (Choice on status) and a catch-all that routes unexpected errors to the
  rejected output instead of dropping items;
* least-privilege IAM: each function gets only the permissions it needs.
"""

from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from common.config import (
    ENV_INPUT_BUCKET,
    ENV_OUTPUT_BUCKET,
    Config,
    config_to_env,
)


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config_path: str,
        src_path: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config = Config.from_yaml(config_path)

        # --- Storage (R9.1, R9.5) -------------------------------------------
        common_bucket_props = dict(
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,  # prototype/sandbox convenience
            auto_delete_objects=True,
        )
        input_bucket = s3.Bucket(self, "InputBucket", **common_bucket_props)
        output_bucket = s3.Bucket(
            self,
            "OutputBucket",
            versioned=True,  # auditability of results/rejected (R9.5)
            **common_bucket_props,
        )

        # --- Lambda functions (R9.1) ----------------------------------------
        code = _lambda.Code.from_asset(src_path)
        base_env = config_to_env(config)
        base_env[ENV_INPUT_BUCKET] = input_bucket.bucket_name
        base_env[ENV_OUTPUT_BUCKET] = output_bucket.bucket_name

        def make_fn(name: str, handler: str, timeout: int) -> _lambda.Function:
            return _lambda.Function(
                self,
                name,
                runtime=_lambda.Runtime.PYTHON_3_12,
                code=code,
                handler=handler,
                environment=dict(base_env),
                timeout=Duration.seconds(timeout),
                memory_size=256,
            )

        ingest_fn = make_fn("IngestFn", "ingest.handler.lambda_handler", 15)
        translate_fn = make_fn("TranslateFn", "translate.handler.lambda_handler", 30)
        summarize_fn = make_fn("SummarizeFn", "summarize.handler.lambda_handler", 60)
        write_fn = make_fn("WriteOutputFn", "write_output.handler.lambda_handler", 15)

        # --- Least-privilege IAM (R9.2) -------------------------------------
        # ingest: no data-plane permissions (operates on the event payload only).
        translate_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["translate:TranslateText"],
                resources=["*"],  # Amazon Translate does not support resource ARNs
            )
        )
        summarize_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=self._bedrock_resource_arns(config.bedrock.model_id),
            )
        )
        # write_output: write only to the two output prefixes.
        output_bucket.grant_put(write_fn, "results/*")
        output_bucket.grant_put(write_fn, "rejected/*")

        # --- Step Functions workflow (R6) -----------------------------------
        state_machine = self._build_state_machine(
            ingest_fn, translate_fn, summarize_fn, write_fn
        )

        # The state machine may read incoming reviews from the input bucket when
        # driven by the batch script; allow the driver's role separately. Here we
        # only grant the machine's implicit lambda-invoke perms (handled by CDK).
        input_bucket.grant_read(state_machine.role)

    # ------------------------------------------------------------------------

    def _bedrock_resource_arns(self, model_id: str) -> list[str]:
        """Resource ARNs for bedrock:InvokeModel.

        Active Claude models are invoked via cross-region inference profiles
        (ids prefixed us./eu./apac./global.). Invoking a profile requires
        permission on both the profile ARN and the underlying foundation model
        ARNs in the regions the profile routes to, so we allow the foundation
        model across regions (`:*:`). A bare foundation-model id is handled too.
        """
        geo_prefixes = ("us.", "eu.", "apac.", "global.")
        if model_id.startswith(geo_prefixes):
            fm_id = model_id.split(".", 1)[1]
            return [
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{model_id}",
                f"arn:aws:bedrock:*::foundation-model/{fm_id}",
            ]
        return [f"arn:aws:bedrock:{self.region}::foundation-model/{model_id}"]

    def _build_state_machine(
        self,
        ingest_fn: _lambda.Function,
        translate_fn: _lambda.Function,
        summarize_fn: _lambda.Function,
        write_fn: _lambda.Function,
    ) -> sfn.StateMachine:
        def lambda_task(cid: str, fn: _lambda.Function) -> tasks.LambdaInvoke:
            task = tasks.LambdaInvoke(
                self, cid, lambda_function=fn, payload_response_only=True
            )
            # Retry only transient Lambda/service faults; business rejections are
            # returned as data, not errors, so they are not retried.
            task.add_retry(
                errors=[
                    "Lambda.TooManyRequestsException",
                    "Lambda.ServiceException",
                    "Lambda.SdkClientException",
                ],
                interval=Duration.seconds(2),
                max_attempts=3,
                backoff_rate=2.0,
            )
            return task

        # Terminal write states.
        write_approved = tasks.LambdaInvoke(
            self,
            "WriteApproved",
            lambda_function=write_fn,
            payload=sfn.TaskInput.from_object(
                {"mode": "approved", "envelope": sfn.JsonPath.entire_payload}
            ),
            payload_response_only=True,
        )
        write_rejected = tasks.LambdaInvoke(
            self,
            "WriteRejected",
            lambda_function=write_fn,
            payload=sfn.TaskInput.from_object(
                {"mode": "rejected", "envelope": sfn.JsonPath.entire_payload}
            ),
            payload_response_only=True,
        )

        # On any unhandled error, mark a minimal rejection and write it (R6.4).
        pipeline_error = sfn.Pass(
            self,
            "MarkPipelineError",
            parameters={
                "status": "rejected",
                "review_id": "unknown",
                "rejection": {"stage": "pipeline", "reason": "pipeline_error"},
            },
        ).next(write_rejected)

        ingest = lambda_task("Ingest", ingest_fn)
        translate = lambda_task("Translate", translate_fn)
        summarize = lambda_task("Summarize", summarize_fn)
        for stage_task in (ingest, translate, summarize):
            stage_task.add_catch(pipeline_error, errors=["States.ALL"], result_path="$.error")

        def gate(cid: str, on_ok: sfn.IChainable) -> sfn.Choice:
            return (
                sfn.Choice(self, cid)
                .when(sfn.Condition.string_equals("$.status", "rejected"), write_rejected)
                .otherwise(on_ok)
            )

        # Wire: ingest -> gate -> translate -> gate -> summarize -> gate -> write
        definition = ingest.next(
            gate(
                "PostIngestGate",
                translate.next(
                    gate(
                        "TranslationGate",
                        summarize.next(gate("SummaryGate", write_approved)),
                    )
                ),
            )
        )

        return sfn.StateMachine(
            self,
            "PipelineStateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.minutes(5),
        )
