# 多语言评论翻译与摘要流水线

<!--
    NOTE FOR ENGLISH READERS
    ------------------------
    This repository ships two mirrored README files. If you prefer English,
    open README.md at the repository root — it contains the full deployment
    guide (prerequisites, CDK bootstrap, cdk deploy, configuration reference,
    cost analysis, productionization notes, tear-down, and troubleshooting).
    The short section below duplicates the essentials in English so a
    non-Chinese reader landing on this file can still get to a working
    deployment.
-->

## English deployment summary

The full English documentation lives in `README.md` at the repository root.
The essentials below let a non-Chinese reader deploy without waiting on a
translation:

- **Prerequisites.** Python 3.12, Node.js 18+ (for the AWS CDK CLI via `npx`),
  AWS credentials for a sandbox account, and Amazon Bedrock model access for
  the configured Claude model (Bedrock console → *Model access*).
- **Setup.** From the repo root:
  `python3 -m venv .venv && source .venv/bin/activate`,
  then `pip install -r requirements-dev.txt` and
  `pip install -r infra/requirements.txt`.
- **Run tests offline (no AWS).** `python -m pytest`.
- **Run the offline evaluation.** `python tests/evaluate.py --mode offline`.
- **Bootstrap and deploy (one-time per account/region).**
  `cd infra && npx aws-cdk bootstrap && npx aws-cdk deploy`.
- **Drive the deployed pipeline.** Find the state machine ARN with
  `aws stepfunctions list-state-machines` and run
  `python scripts/run_batch.py --state-machine-arn <ARN> --region us-east-1 --limit 20`.
- **Configuration.** All tunables live in `config/pipeline.yaml`; they are
  read at CDK synth time and injected into every Lambda as environment
  variables.
- **Tear down.** `cd infra && npx aws-cdk destroy`.
- **Troubleshooting (most common).** If Bedrock calls fail with
  `AccessDeniedException`, enable Model access in the Bedrock console for the
  configured region. If `cdk deploy` cannot find the Python app, pass the
  interpreter explicitly:
  `npx aws-cdk deploy --app "../.venv/bin/python app.py"`.

### English cost analysis

Estimates use us-east-1 on-demand pricing at the time of writing (see the
[AWS Pricing Calculator](https://calculator.aws/) for current rates). AWS Free
Tier benefits are not modelled so the numbers are pessimistic.

Assumptions per review: ~500 characters of source text, Amazon Translate
invoked twice (forward + back-translation) → ~1000 characters, Bedrock Claude
3 Haiku Converse ~600 input tokens + ~120 output tokens, 4 Lambda invocations
(~1s at 128 MB), 6 Step Functions Standard state transitions, ~4 S3 requests.

| Scale | Reviews/month | Translate | Bedrock (Haiku) | Lambda | Step Functions | S3 | Total |
|---|---|---|---|---|---|---|---|
| Demo | 400 | < $0.01 | < $0.01 | Free tier | Free tier | < $0.01 | ~$0.01 |
| Pilot | ~4K (~1K/week) | ~$0.06 | ~$0.15 | Free tier | Free tier | < $0.01 | ~$0.25 |
| Production | ~48K (~12K/week) | ~$0.75 | ~$1.85 | ~$0.01 | ~$0.07 | ~$0.05 | ~$2.75 |

Trade-offs to keep in mind: at prototype scale, Step Functions Standard vs
Express cost is negligible (ADR-003); Bedrock model choice dominates
summarization cost (ADR-002) — retune `bedrock.temperature` and prompt
length before upgrading tiers; each retry re-invokes Translate/Bedrock so
`retries.max_attempts` multiplies the corresponding line items in the worst
case. For an authoritative estimate, plug the assumptions into the
[AWS Pricing Calculator](https://calculator.aws/).

See `docs/adr/` for the architecture decision records that explain *why* the
system looks the way it does before changing it.

---

一个为 **AnyCompany Apparel** 构建的原型流水线:从模拟的供应商 feed 摄入商品评论,用
**Amazon Translate** 翻译,用 **Amazon Bedrock(Claude)** 生成 1–2 句摘要,并通过
**质量门(quality gate)** 在结果对外呈现之前过滤掉低置信度的翻译和摘要。

范围:仅使用合成数据、不处理 PII、两种语言对(法语→英语、德语→英语)。这是一个原型 ——
生产扩容、监控、以及 PDP 前端集成均不在范围内(见 [边界](#边界))。

完整的需求、设计与任务拆解见
[`.kiro/specs/review-translation-pipeline/`](.kiro/specs/review-translation-pipeline/)。

---

## 架构

```
  供应商评论 JSON
        │  (Step Functions 执行输入 / 批处理驱动脚本)
        ▼
  ┌──────────┐   ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌────────────┐
  │  Ingest  │──▶│ Translate │──▶│  翻译       │──▶│ Summarize │──▶│  摘要       │──▶ WriteApproved
  │  Lambda  │   │  Lambda   │   │  质量门     │   │  Lambda   │   │  质量门     │      │ results/*.json
  └────┬─────┘   └─────┬─────┘   └─────┬──────┘   └─────┬─────┘   └─────┬──────┘      │
   剥离 PII        Amazon        status == rejected?  Amazon        status == rejected?
   校验            Translate           │             Bedrock              │
       │            (+ 回译)           ▼            (Claude,               ▼
       │                          WriteRejected      Converse)      WriteRejected
       └──────────────────────────▶ rejected/*.json ◀──────────────────────┘
                                          ▲
                     任何未处理的异常 ─────┘  (Catch → pipeline_error)

  编排: AWS Step Functions (Standard)。  存储: Amazon S3 (输入 + 输出)。
```

每个阶段的 Lambda 返回一个 `ok` 信封(附带评分)或一个 `rejected` 信封。质量门的判定
**在 Lambda 内部完成**,使用来自配置的阈值,因此 `Choice` 状态只需根据 `$.status` 路由。
这样所有可调参数都集中在 `config/pipeline.yaml` 中 —— 重新调参无需改动基础设施代码。

### PII 处理

`reviewer_name` 和 `reviewer_email` 在 ingest 的第一步、任何校验或日志记录之前就被丢弃。
归一化后的记录类型根本没有存放它们的字段,因此 PII 无法流向下游或进入输出。日志还会额外
对 PII 做脱敏,作为纵深防御。全程只使用合成数据。

---

### 架构决策

关键架构决策记录在 [`docs/adr/`](docs/adr/README.md) 目录下。修改系统之前先阅读它们,
理解**为什么**当前形态是这样的:

| # | 标题 |
|---|------|
| [ADR-001](docs/adr/adr-001-service-selection-for-translation.md) | 翻译服务选型(Amazon Translate 及其替代方案) |
| [ADR-002](docs/adr/adr-002-genai-service-for-summarization.md) | 摘要 GenAI 服务选型(通过 Converse API 调用 Bedrock Claude) |
| [ADR-003](docs/adr/adr-003-orchestration-pattern.md) | 编排模式(Step Functions Standard vs Express vs 直接链式调用) |
| [ADR-004](docs/adr/adr-004-pii-handling-strategy.md) | PII 处理策略(结构性排除 vs 运行时过滤) |
| [ADR-005](docs/adr/adr-005-quality-gate-implementation.md) | 质量门实现(Lambda 内 + 配置阈值) |
| [ADR-006](docs/adr/adr-006-translation-quality-scoring.md) | 翻译质量评分(长度比 + 回译相似度) |

### 成本分析

以下估算基于本文档撰写时 us-east-1 的按需价格(实时价格以
[AWS Pricing Calculator](https://calculator.aws/) 为准)。为了给出保守估计,
AWS 免费额度(Lambda 每月 1M 次请求、Step Functions 每月 4K 次状态转换,均为
Always Free)未参与本模型。

单条评论假设:
- 源文本约 500 字符(与商品评论长度相当)。
- Amazon Translate 调用两次(正向 + 回译),合计约 1000 字符。
- Amazon Bedrock Claude 3 Haiku 的 Converse 调用:约 600 个输入 token
  (系统提示 + 译文)与约 120 个输出 token(JSON 摘要及打分)。
- 4 次 Lambda 调用(ingest / translate / summarize / write_output),
  每次 128 MB、约 1 秒。
- Step Functions Standard 每条评论约 6 次状态转换。
- 每条通过审核的评论产生约 4 次 S3 PUT/GET。

按规模的月度粗略成本(四舍五入):

| 规模 | 评论量/月 | Translate | Bedrock (Haiku) | Lambda | Step Functions | S3 | 合计 |
|---|---|---|---|---|---|---|---|
| Demo | 400 | < $0.01 | < $0.01 | 免费额度内 | 免费额度内 | < $0.01 | ~$0.01 |
| 试点 | ~4K(约每周 1K) | ~$0.06 | ~$0.15 | 免费额度内 | 免费额度内 | < $0.01 | ~$0.25 |
| 生产 | ~48K(约每周 12K) | ~$0.75 | ~$1.85 | ~$0.01 | ~$0.07 | ~$0.05 | ~$2.75 |

需要注意的取舍:
- **Step Functions Standard vs Express (ADR-003)**:在每周 12K 的规模下,
  Standard 的状态转换费用可以忽略(~$0.07/月)。切换到 Express 会换来更低的
  单次调用成本,但会失去 Standard 在控制台保留 90 天执行历史的调试优势。
- **Bedrock 模型选择 (ADR-002)**:Haiku 主导摘要环节的成本。切换到更大的
  Claude 层级会大致按 token 单价比例放大 Bedrock 一项。升级前应先通过
  `bedrock.temperature` 和缩短 prompt 长度进行调参。
- **重试 (`config/pipeline.yaml` → `retries.max_attempts`)**:每次重试都会
  再次触发底层的 Translate 或 Bedrock 调用,最坏情况下相应的费用会被放大
  最多 `max_attempts` 倍。

如需权威且实时的估算,请将上述假设输入
[AWS Pricing Calculator](https://calculator.aws/)。

---

### 生产化考虑

本仓库是原型,面向真实客户流量之前需要补齐:

- **扩容。** 目标速率约每周 12K 条评论,当前形态足以承载。若明显超出,应参考
  ADR-003 将 Standard 工作流迁到 Express,同时为每个 Lambda 设置预留并发和
  DLQ。
- **监控与告警。** 对 Step Functions `ExecutionsFailed`、各 Lambda 的
  `Errors`/`Throttles`、以及 rejected 写入速率添加 CloudWatch 告警;通过 EMF
  发布 `RejectionReason` 指标,方便观察拒绝原因分布。
- **保留策略与加密。** 目前桶已启用 SSE 和 Block Public Access。生产环境应为
  `results/` 与 `rejected/` 添加生命周期策略,并考虑使用 KMS CMK 加密输出。
- **真实数据处理。** ADR-004 采用结构性排除,专门服务合成数据。真正的 PII
  管道需要完整的数据分级与保留设计;ADR-004 明确说明了取代它的触发条件。
- **集成。** 将摘要发布到 PDP 不在本原型范围内。输出 S3 布局稳定,后续可用
  EventBridge 触发的发布器接入,无需改动流水线。
- **错误处理。** 非可重试的 Bedrock/Translate 错误已经路由到
  `rejected/*.json`,带 `reason=pipeline_error`。生产环境应为拒绝写入速率
  配置 DLQ 或 SNS 告警,以便捕获系统性问题。

---

## 仓库结构

```
config/pipeline.yaml        所有可调参数的唯一事实来源
src/common/                 配置、模型、日志、AWS 客户端、S3 IO
src/ingest/                 校验 + PII 剥离 (R1)
src/translate/              Amazon Translate + 翻译质量门 (R2, R3)
src/summarize/              Bedrock Claude + 摘要质量门 (R4, R5)
src/write_output/           批准/拒绝结果写入 S3 (R7)
infra/                      AWS CDK 应用 (桶、Lambda、Step Functions、IAM)
tests/unit/                 离线单元测试 (无需 AWS)
tests/data/dataset.json     100 条合成评论 (50 法语 + 50 德语) + 带标注的噪声输入
tests/evaluate.py           端到端评估工具 (离线或在线)
scripts/generate_dataset.py 确定性地重新生成合成数据集
scripts/run_batch.py        用数据集驱动已部署的流水线
```

---

## 前置条件

- Python 3.12
- Node.js 18+(仅用于通过 `npx` 运行 AWS CDK CLI)
- 沙箱账号的 AWS 凭证(`aws sts get-caller-identity` 应能正常返回)
- 目标区域必须开启**Amazon Bedrock 模型访问权限**(Bedrock 控制台 → *Model access*)。
  默认模型为 `anthropic.claude-3-haiku-20240307-v1:0`。

创建虚拟环境:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt      # 测试 + 数据集 + 评估
pip install -r infra/requirements.txt    # AWS CDK 库
```

---

## 运行测试(离线,无需 AWS)

```bash
python -m pytest
```

## 运行评估

离线模式使用从数据集构建的确定性 Translate/Bedrock 假引擎,因此无需任何 AWS 访问即可
在任意环境运行 —— 非常适合可复现的演示:

```bash
python tests/evaluate.py --mode offline
```

它会报告翻译准确率与阈值的对比、确认质量门正确拒绝了带标注的噪声输入,并记录每条评论的
延迟。完整报告写入 `build/eval_report.json`。

在线模式则针对真实的 Amazon Translate + Amazon Bedrock 运行(需要凭证和 Bedrock 模型
访问权限):

```bash
python tests/evaluate.py --mode live --region us-east-1
```

---

## 部署到沙箱账号

```bash
cd infra

# 每个账号/区域一次性执行:
npx aws-cdk bootstrap

# 合成(可选)并部署:
npx aws-cdk synth
npx aws-cdk deploy
```

> 如果 CDK CLI 找不到 Python 应用的依赖,请确保虚拟环境已激活,或显式指定:
> `npx aws-cdk deploy --app "../.venv/bin/python app.py"`。

该栈会创建:一个输入桶和一个输出桶(均开启 Block Public Access、SSE,输出桶开启版本控制)、
四个 Lambda 函数、Step Functions 状态机,以及最小权限的 IAM 角色(translate 函数拥有
Translate 权限;summarize 函数拥有针对所配置模型 ARN 的 Bedrock `InvokeModel` 权限;
output 函数拥有受限的 S3 写入权限)。

### 驱动已部署的流水线

获取状态机 ARN,并把合成评论喂给它:

```bash
aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name,'PipelineStateMachine')].stateMachineArn" --output text

python scripts/run_batch.py --state-machine-arn <ARN> --region us-east-1 --limit 20
```

批准的结果落在输出桶的 `results/` 前缀下,被拒绝的项落在 `rejected/` 前缀下。

### 拆除

```bash
cd infra && npx aws-cdk destroy
```

---

## 故障排查

首次拉起流水线时常见的问题:

- **调用 Bedrock 报 `AccessDeniedException`。** `config/pipeline.yaml` 里
  `bedrock.model_id` 指定的模型没有在当前账号/区域启用 Model access。到
  Bedrock 控制台 → *Model access* 中申请对应模型的访问权。
- **CDK bootstrap 或 deploy 出现凭证/账号错误。** 先确认
  `aws sts get-caller-identity` 返回的是沙箱账号;每个账号/区域执行一次
  `npx aws-cdk bootstrap`;并保证虚拟环境已激活(`source .venv/bin/activate`),
  CDK CLI 才能识别 Python 依赖。
- **`cdk deploy` 找不到 Python 应用。** 显式指定解释器:
  `npx aws-cdk deploy --app "../.venv/bin/python app.py"`。
- **第一条评论就以 `pipeline_error` 失败。** 打开 Step Functions 控制台里
  失败的执行,进入报错 Lambda 的 CloudWatch Logs,常见原因:Bedrock 权限
  (见上)、Translate 返回 `UnsupportedLanguagePairException`(源语言必须在
  `config/pipeline.yaml` 的 `supported_languages` 中)、输出桶 S3
  `AccessDenied`(通常是 CDK writer 角色不同步,重跑 `cdk deploy`)。
- **写入输出桶 `AccessDenied`。** CDK 栈会把 writer 角色限定在输出桶及
  `results/*`/`rejected/*` 前缀。如果在 CDK 之外改过桶名,重新部署栈以
  重新下发权限策略。
- **测试报 `ModuleNotFoundError` 找不到 `common` 或 `summarize`。** 在仓库根
  目录激活虚拟环境后运行 `python -m pytest`;`pytest.ini` 已配置好导入路径,
  可以按短名导入 `src/` 下的包。
- **日志里出现 `SummarizationError: no valid summary after retries`。** 模型
  在重试预算内始终没有返回合法 JSON。确认配置里指定的是支持 Converse API
  的 Claude 模型,并适当调低 `bedrock.temperature`。

---

## 配置指南

所有可调参数都在 [`config/pipeline.yaml`](config/pipeline.yaml) 中。它们在 CDK 合成时被读取
并作为环境变量注入到每个 Lambda,因此修改后只需在下次 `cdk deploy` 时生效,**无需改动代码**。

| 键 | 含义 |
|---|---|
| `target_language` | 评论翻译成的目标(购物者)语言 |
| `supported_languages` | 接受的源语言代码 |
| `bedrock.model_id` | Claude 模型 id(必须在 Bedrock 模型访问中启用) |
| `bedrock.max_tokens` / `temperature` | 生成控制参数 |
| `thresholds.translation_score` | 通过翻译门所需的最低综合翻译分 |
| `thresholds.fluency` / `factual_consistency` | 摘要自评分的最低值 |
| `thresholds.max_summary_chars` | 摘要长度硬上限 |
| `thresholds.length_ratio_min/max` | 译文/原文长度比可接受区间 |
| `scoring_weights.length` / `back_translation` | 翻译分各组成部分的权重(和为 1.0) |
| `retries.max_attempts` / `base_delay_seconds` | AWS 调用的重试/退避参数 |

翻译分是一个确定性、可解释的组合:长度比合理性检查 + 回译相似度(把译文再翻回源语言,
与原文比较)。在这里调整权重与阈值即可。

---

## 扩展到更多语言

流水线与语言无关。要新增一个语言对:

1. 在 `config/pipeline.yaml` 的 `supported_languages` 中加入源语言代码(例如加入 `es`
   表示西班牙语)。确保 Amazon Translate 支持该 源语言→`target_language` 的语言对。
2. 重新部署:`cd infra && npx aws-cdk deploy`。

无需改动翻译、摘要或质量门的代码 —— 摘要器的 prompt 会根据语言代码推导出目标语言名称,
而质量门是阈值驱动的。如果希望新语言被评估覆盖,可在 `scripts/generate_dataset.py` 中为
其添加合成样例。

---

## 成功标准对照

| 标准 | 如何满足 / 验证 |
|---|---|
| 1. 翻译准确率高于阈值 | 确定性翻译分 + 质量门;`tests/evaluate.py` 报告平均分和 ≥ 阈值的百分比 |
| 2. 摘要为 1–2 句、流畅、事实一致 | Bedrock 严格 JSON 摘要 + 摘要门(句数、长度、流畅度、事实一致性) |
| 3. 端到端延迟 < 10 秒/条 | 由 `tests/evaluate.py` 按条报告 |
| 4. 质量门过滤低置信度输出 | 数据集含 9 条带标注的噪声输入;评估确认每条都以预期原因被拒绝 |
| 5. 团队能独立部署和扩展 | 本 README + CDK 栈 + 配置驱动的语言扩展 |

---

## 边界

本原型不在范围内(依据交付范围书):真实客户数据 / PII 处理、生产部署及扩容到约
每周 12K 条评论、监控与告警、PDP/前端集成,以及法语和德语之外的源语言。设计保留了清晰的
扩展接缝(配置驱动的语言、分阶段的 Step Functions 状态、结构化的 S3 输出),便于客户团队
在交接后自行扩展。
