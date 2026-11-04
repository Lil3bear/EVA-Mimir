# paper-pre-submission-review

面向 ICLR 投稿前审核的 Codex skill，将模拟审稿、科学证据检查、引用核验、年度投稿要求和最终 PDF 检查合并为一个流程。

仓库名为 `paper-pre-submission-review`，skill 的调用名称为 **`iclr-pre-submission-review`**。目前主要面向 ICLR；会议规则在每次审核时按目标年份、track 和投稿阶段核验，不内置旧年份的固定要求。

## 审核内容

| 模块 | 检查重点 |
| --- | --- |
| 模拟审稿 | 贡献、创新性、相关工作、优点、主要问题和作者需要回答的问题 |
| 科学证据 | 论断与证据是否对应、基线是否可比、消融是否隔离变量、理论假设与结论是否一致 |
| 数字与复现 | 提升幅度、表文一致性、不确定性、训练与评测配置 |
| 引用 | 文献身份与版本、引文是否支持论断、BibTeX 和引用键 |
| 投稿要求 | 当年官方规则、模板、匿名、页数计算、声明及补充材料 |
| 文字与 PDF | 术语和符号、论断范围、交叉引用、排版、图表与最终文件 |

同一个问题只保留一个编号，汇总所有受影响的位置，避免多个审核阶段重复提问。规则核验与写作建议分开，问题严重性与证据确定性也分开。

## 安装到 Codex

将整个仓库克隆到个人 skills 目录，并使用 skill 名作为目录名：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/chantsss/paper-pre-submission-review.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/iclr-pre-submission-review"
```

不需要另外安装两个上游 skill，也不要求特定模型、API key 或搜索服务。联网检索、PDF 渲染和 LaTeX 编译使用当前运行环境已有的能力；缺少能力时会说明未完成的检查。

## 使用

完整审核：

```text
$iclr-pre-submission-review
对这篇论文及附录做 ICLR 2027 主会初投稿前完整审核，输出必须修、建议修和文字优化清单。只审核，不修改稿件。
```

局部检查：

```text
$iclr-pre-submission-review
只检查摘要、实验表格和结论中的数字及论断是否一致。
```

修订后复核：

```text
$iclr-pre-submission-review
根据上一轮问题编号复核这版稿件，检查已修复问题和受修改影响的论断。
```

默认只审核。明确要求修改时才在授权范围内改稿。不会自动上传论文、提交投稿或运行新实验。

## 输出

完整审核默认生成两个文件，存放于项目的 `outputs/iclr-review/<paper-id>-<timestamp>/`，也可以指定输出目录：

- **`review.md`**：审核范围、优先问题、具体位置、依据、修复建议、模拟审稿及投稿规则状态。
- **`evidence.md`**：论断与证据对应表、文献核验记录、规则来源、实际检查覆盖范围。

问题分为 **必须修／建议修／文字优化**，并分别标记已确认、有条件成立或待核验。缺少官方规则、原始材料或评分表时，会保留相应不确定性；不会将缺失证据当作通过检查，也不会编造评分。

## 文件结构

```text
SKILL.md                   工作流入口
agents/openai.yaml         Codex 展示信息和默认提示词
references/
  scientific-review.md     科学与数字检查
  citations.md             文献和引用核验
  venue-rules.md           当年官方规则核验
  writing-and-pdf.md       文字、LaTeX 和最终 PDF
  report-format.md         问题优先级及报告格式
ATTRIBUTION.md             上游来源和合并说明
upstream-sources.json      上游版本及文件校验值
LICENSE                    MIT 许可证
```

## 来源与许可

改编自 [jam-cc/paper-review.skill](https://github.com/jam-cc/paper-review.skill) 和 [Orchestra Research 的 ml-paper-writing](https://github.com/Orchestra-Research/AI-Research-SKILLs/tree/main/20-ml-paper-writing/ml-paper-writing)。保留有证据的审稿方法和写作终检能力，合并重复流程，移除旧年份规则、固定问题数量及特定服务依赖。

详细版本和修改说明见 [ATTRIBUTION.md](ATTRIBUTION.md)。使用 [MIT License](LICENSE)，保留两份上游版权声明。本项目不是 ICLR 官方工具。
