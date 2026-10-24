# HerEvidence 真实记录标注手册（v1，hackathon）

## 标注对象和边界

单位是一条 ClinicalTrials.gov v2 **登记记录的冻结 JSON 版本**，不是论文、研究方案或研究者实际做过的全部分析。每条记录在 `data/real_gold/manifest.json` 中有 NCT ID、抓取时间、最后更新日期和 SHA-256。标签只表示这份 JSON 可见的内容。官方将已发布的 summary results 分为 participant flow、baseline characteristics、outcome measures、adverse events 等模块；本项目的“按性别结局”仅评估 **outcomeMeasuresModule**，不把基线人数或不良事件表当作结局分析。

官方定义参考：[Study Basics](https://clinicaltrials.gov/study-basics)、[Outcome Measure Data Preparation Checklist](https://cdn.clinicaltrials.gov/documents/data-prep-checklist-om-sa.pdf)、[Results Data Element Definitions](https://clinicaltrials.gov/policy/results-definitions)。以下分类阈值是**项目的研究操作定义**，不是 ClinicalTrials.gov 官方评级。

## 四个检查项

### 1. `sex_restriction`

读 `protocolSection.eligibilityModule.sex`，照原值标 `ALL`、`FEMALE`、`MALE` 或 `UNKNOWN`。它只表示登记的招募性别字段，不推断公平性。必须保存该字段路径和值。

### 2. `eligibility_exclusion`

完整阅读 `protocolSection.eligibilityModule.eligibilityCriteria` 的 inclusion 和 exclusion，按**研究整体**标一个主标签：

| 标签 | 判据 | 不能据此标注的情况 |
|---|---|---|
| `BLANKET_EXCLUSION_CHILDBEARING` | 明确排除所有有生育能力的女性，且没有另一研究臂允许她们参加；也包括仅招募无生育能力女性的明确限制 | 只排除已怀孕者；只要求避孕；只在某一治疗臂排除但另一臂允许 |
| `PREGNANCY_LACTATION_EXCLUSION` | 已怀孕、哺乳、妊娠试验阳性者不得参加，即使写在 inclusion 中作为 “not pregnant” 条件 | 仅要求进行妊娠检测，未说明阳性者不能参加且上下文无法推断 |
| `CONDITIONAL` | 有生育能力者可在避孕、妊娠检测等条件下参加，且没有更强的整体排除 | 所有人一律排除 |
| `NONE` | 通读完整字段后，没有上述限制 | 字段缺失、无法读懂或只看了关键词片段 |
| `UNCLEAR` | 字段缺失、含糊、互相矛盾，或现有单标签体系无法表达某一研究臂的专属排除 | 单纯没有结果发布 |

若同一记录有明确的整体妊娠／哺乳排除和避孕条件，主标签取 `PREGNANCY_LACTATION_EXCLUSION`，并在备注记录共存条件。整体 blanket 排除优先于其他标签。**只限制一个研究臂**而其他臂仍允许有生育能力女性的记录先标 `UNCLEAR` 并保留两个冲突证据；下一版可改为多标签和 arm-level 标注。这里的标签不评价限制的医学合理性。

正向标签必须给出原文短引句和 JSON 路径。`NONE` 必须记录已通读的整个字段路径。

### 3. `enrollment_by_sex`

如果顶层 `hasResults=false`，标 `NO_RESULTS_POSTED`。否则审查 `resultsSection.baselineCharacteristicsModule.measures`：只有看到性别／性别认同对应的基线类别**以及至少一个实际人数值**时才标 `REPORTED`。只有 “Sex: Female, Male” 标题、却没有 `measurements[].value`，标 `NOT_REPORTED_IN_RECORD`。不把 outcome 或 participant flow 的人数算进来。记录 measure 路径、类别和一个实际数值。单一性别试验也可以 `REPORTED`，只要数值确实可见。

### 4. `sex_stratified_results`

如果 `hasResults=false`，标 `NO_RESULTS_POSTED`。否则审查**所有** `resultsSection.outcomeMeasuresModule.outcomeMeasures`，包括每个 outcome 的 title、description、groups、classes/categories/measurements、analyses：

| 标签 | 判据 |
|---|---|
| `STRATIFIED_FOUND` | 至少一个已发布 outcome 的结果数值能明确对应女性和男性／其他明确的 sex/gender 子群；可以是 sex-named outcome groups，也可以是 sex-named classes/categories 加数值。需保存 outcome 索引、分组名称和对应值。仅有分析计划或“将按性别分析”的文字不够。 |
| `NOT_FOUND_IN_RECORD` | 已发布结果，但逐个审查 outcome 模块后未见上述结构。只提到男女参与者、性功能量表、基线人数、按性别随机分层或没有数值的分组名称都不够。 |
| `UNCLEAR` | 结构残缺或文本与数值关系无法判断。 |
| `NO_RESULTS_POSTED` | `hasResults=false`。 |

这一定义回答了关键问题：**只有男女分组名称不够，必须有对应的结局数值**。`STRATIFIED_FOUND` 不代表有正式的性别交互作用统计检验，也不意味着研究证明了男女疗效不同。

## 双人标注和冲突裁定

两名标注者独立查看冻结 JSON，不看模型预测。每人填写四个标签、证据路径、短引句、结局数值或“搜索范围”、备注。先计算逐项一致率和 Cohen's kappa；不一致时一起回看同一 SHA-256 版本并依据上表裁定。仍不一致时由第三人裁定；裁定前保留两人的原始标签与理由，不能静默覆盖。若标签体系本身表达不了记录，保留 `UNCLEAR` 并登记为规则修订案例。

当前 `data/gold_set.json` 是 **Codex 单评审初标，尚未经第二名人类标注者复核**。它能用于发现代码问题和演示指标计算，不能在对外展示中称为“人工共识 gold”或真实准确率。三小时内可让团队第二人优先复核所有阳性、`UNCLEAR` 和模型与初标不一致的记录。

## 评估口径

混淆矩阵行是真值、列是预测。每个标签的 precision = TP/(TP+FP)，recall = TP/(TP+FN)；分母为零显示 `null`，不能伪装为 0。`UNCLEAR` 是主动拒答，拒答率 = 预测 `UNCLEAR` / 该检查项全部记录数；`NO_RESULTS_POSTED` 是有效标签，不算拒答。报告全部记录准确率、非拒答准确率、覆盖率及各标签 support。挑战样本被刻意补入，本集合不能估计某类缺口在总体试验中的真实发生率。
