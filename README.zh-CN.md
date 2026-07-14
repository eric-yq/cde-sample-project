# 多语言评论翻译与摘要流水线

> English version: [README.md](README.md)

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
