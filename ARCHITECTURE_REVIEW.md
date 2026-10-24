# HerEvidence 架构与三小时冲刺评估

## 这个 agent 实际怎样工作

`run_agent.py` 启动 `agent.run`；`fetch_trials.py` 从 ClinicalTrials.gov API 获取记录，或 `fixtures.py` 提供合成记录；`store.py` 的 SQLite 队列保存任务进度。`auditor.py` 对每条记录运行四项固定检查，`rules.py` 筛选候选文字，`llm.py` 只处理语义分类。`verifier.py` 对部分 LLM 结论做引文和抽样复核，`supervisor.py` 对错误信号、循环、停滞和预算做停机控制。最后写判定、缺口报告和待人工审核的询问草稿。

这是**固定任务的审计流水线，加一个能监控并停止执行的 agent 控制层**。它不会自己选择新的研究问题或动态规划工具调用。研究型 agent 常用“观察—推理—行动—再观察”的循环；[ReAct 原论文](https://arxiv.org/abs/2210.03629) 探讨了交错推理与外部行动，[AgentBench 原论文](https://arxiv.org/abs/2308.03688) 强调评估 agent 在环境中完成任务而非仅评单次模型回答。就本项目而言，继续增加自由行动能力的收益低于先建立可信标签与证据链。

## 五层评估，而不是一个 accuracy

| 层级 | 问题 | 当前测量 | 目前缺口 |
|---|---|---|---|
| 数据获取 | API 字段和版本是否正确？ | 冻结 25 份官方 v2 JSON、SHA-256 | 实时抓取与解析尚无系统性 schema 回归测试 |
| 临床任务定义 | 标签是否有一致含义？ | `LABELING_GUIDE.md` 与初标 | 还缺第二名人类评审与裁定 |
| 模型／规则判定 | 与参考标签是否一致？ | `eval_gold.py` 四任务逐标签 precision、recall、混淆矩阵、拒答率 | 当前只跑了 mock；未跑真实 LLM |
| 证据 | 引句、数值、字段路径能否回到原始记录？ | 初标的路径、引句、示例数值与哈希验证 | 线上判定仍只保存 quote，不保存完整字段路径与结果数值 |
| Agent 控制 | 会不会失控、重复、超预算、发布不可信结果？ | 合成 sabotage/loop/stuck/budget 演示 | 监督器的“错误率”来自引文失败和复核分歧，不是真实标签错误率 |

官方 [ClinicalTrials.gov API v2 说明](https://www.nlm.nih.gov/pubs/techbull/ma24/ma24_clinicaltrials_api.html) 与 [NLM 单条记录 API 示例](https://www.nlm.nih.gov/pubs/techbull/ja25/ja25_clinical_trials_screen-scraping.html) 支持使用 JSON API 和 NCT ID 获取可复核记录。我们保存的是抓取时的快照；线上记录之后可能更新。

## 代码审阅发现的架构风险

1. `fetch_trials.normalize_trial` 丢弃了 outcome 的 `measurements[].value`，也从传给 auditor 的 `baseline_measures` 中省略了各类别人数；它另算 `female_n` / `male_n` 用于代表性报告。当前 auditor 仍只能看标题／描述／分组名，无法依据“性别组对应真实结局数值”的新准则独立验证阳性判定。
2. `auditor.py` 的基线检查只看标题包含 `sex` 或 `gender`。真实样本 `NCT00074724` 的标题存在，但人数值缺失；参考初标为 `NOT_REPORTED_IN_RECORD`，程序判 `REPORTED`。
3. `verifier.py` 对规则判定直接设 `verified=1`；对“未找到”的结论没有搜索范围证据。抽样复核使用相近输入，两个判断可能同错。
4. `agent.py` 在整批质量检查通过前生成草稿；之后 `store.quarantine` 只隔离判定，不同步撤销草稿。
5. `--llm auto` 在无 API key 时会悄悄使用 mock。演示方便，但“真实数据 + mock”绝不能被描述成真实模型效果。
6. README 曾提到 `--resume`，CLI 实际支持 `--no-ingest`。默认时间上限为 900 秒，长期无人值守仍需调度和明确的失败恢复。

## 已完成的第一阶段交付

- `LABELING_GUIDE.md`：四任务、边界例子、证据要求、冲突裁定、指标定义。
- `data/real_gold/manifest.json` + 25 份原始 JSON：四个疾病查询、已发布／未发布结果以及阳性挑战案例，附哈希和记录版本日期。抽样**非随机**，不能估计总体发生率。
- `data/gold_set.json`：逐条初标和证据路径。标注状态为 `single_reviewer_provisional`，**不是独立人类共识 gold**。
- `eval_gold.py`：读取冻结快照，验证哈希、引句和数值路径，输出所有标签的指标、混淆矩阵、拒答率和分歧清单。
- `data/reviewer2_disagreements.csv`（7 条）、`data/reviewer2_priority.csv`（18 条）与 `data/reviewer2_full.csv`（25 条）：不包含初标答案的盲审表。

## 接下来三小时的最短路径

| 时间 | 工作 | 可对外报告的结果 |
|---|---|---|
| 0–45 分钟 | 第二人先独立标 `reviewer2_disagreements.csv` 的 7 条，再尽量完成 `reviewer2_priority.csv` 的其余案例 | 记录分歧，不改动原始快照 |
| 45–90 分钟 | 两人裁定分歧；如果有余力完成剩余 9 条。把最终标签和裁定理由写回 `gold_set.json`，修改 `review_status` | 才可称“人工复核 gold” |
| 90–120 分钟 | `python eval_gold.py --llm mock` 作管线检查；有 Anthropic key 与依赖时再跑 `--llm anthropic` | 真实 LLM 指标必须注明模型、样本数、标签版本 |
| 120–150 分钟 | 看 `gold_eval.md` 的逐项分歧；优先核对假阳性与假阴性。不要在同一 25 条上调 prompt 后又把其分数当独立测试集 | 错误案例与修正计划 |
| 150–180 分钟 | 固定代码、记录模型版本／价格假设、演示最有代表性的正确与错误案例 | 可复现实验与诚实限制 |

`data/gold_eval.md` 当前由 **mock** 后端生成，只证明评估管线可以工作。针对只有 2 条 `STRATIFIED_FOUND` 阳性的样本，任何 100% 都极不稳定。若要展示真正的模型质量，必须运行真实模型，并明确初标或裁定状态。

当前 mock 对单评审初标的逐任务准确率：`sex_restriction` 25/25、`eligibility` 19/25、`enrollment_by_sex` 24/25、`sex_stratified` 25/25；共 7 个判定分歧。`eligibility` 中两条漏检来自 “birth control” 未被触发和超长单行文字在 300 字符处被截断。这些分歧是可行动的错误分析，不是最终临床准确率。
