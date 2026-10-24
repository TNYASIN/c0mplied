# Research-to-architecture review (2026-10-24)

## First, identify the papers correctly

The supplied [arXiv:2605.10906](https://arxiv.org/abs/2605.10906) is **DataMaster** by Yaxin Du et al., not Pengtao Xie's AIBuildAI. The relevant AIBuildAI sequence is [AIBuildAI](https://arxiv.org/abs/2604.14455), [AIBuildAI-2](https://arxiv.org/abs/2605.27873), and [AIBuildAI-2.5](https://arxiv.org/abs/2609.25047). These are research reports by their authors, not external validation of HerEvidence.

| System | Agent searches over | Feedback and stop signal | Transfer to HerEvidence |
|---|---|---|---|
| DataMaster | Data sources, selection, transformations in a DataTree; shared Data Pool and Global Memory | Downstream model score and budget | Freeze source records; retain branch outcomes and failure examples. External data discovery is less relevant because our target is one registry record version. |
| AIBuildAI | Candidate modeling strategies and code, coordinated by manager, designer, coder, tuner | Empirical benchmark score | Compare isolated candidate code against a fixed reference and stop regressing branches. Four agents per record would add cost and correlated errors. |
| AIBuildAI-2 | Same model-building task plus retrieved external development knowledge | Task-specific retrieved guidance | Version the label manual, parser assumptions and adjudicated errors; retrieve guidance at development time. Do not treat generated memory as ground truth. |
| AIBuildAI-2.5 | Budgeted candidate tree with judge/selector and model routing | Expected improvement, grounding, feasibility, measured score | Use a small explicit experiment gate before promotion; prioritize improvements where errors occur. Model routing can wait until real-LLM performance and cost are measured. |
| HerEvidence now | Records in a fixed ClinicalTrials.gov v2 schema; each record gets four judgments | Quote grounding, sampled recheck, budget and loop guards, 25 provisional reference records | Keep rule-first extraction, add source-linked numeric evidence, hold drafts until batch pass, and stop unsafe code branches. |

The 2026 [agent-scaling study](https://arxiv.org/abs/2512.08296) found architecture benefit depends on task and coordination; tool-heavy workflows can pay multi-agent overhead, and central verification can reduce propagation. [AstaBench](https://arxiv.org/abs/2510.21652) emphasizes reproducible tools, cost and access in agent evaluation. Thus this implementation uses a central deterministic evidence gate and version-matched evaluation before adding more reviewer agents.

## Why the old pipeline could be confidently wrong

`fetch_trials.normalize_trial` previously retained sex group names but discarded `measurements[].value`. `auditor` could therefore say `STRATIFIED_FOUND` from a title or group name alone, contrary to `LABELING_GUIDE.md`. A sex baseline title alone could yield `REPORTED` without any participant count. The LLM recheck could repeat the same semantic error, while the quote verifier only checked that a phrase existed. `agent.py` could make a draft before `Supervisor.after_batch` raised an error-rate halt. None of those guards measured real clinical correctness.

## Implemented branch and runtime controls

1. Preserve female and male numeric outcome values with original JSON paths. Mark `STRATIFIED_FOUND` by structured rule only when one posted outcome has values for both in the same time point and treatment arm. A model claim lacking numeric support becomes `UNCLEAR` and enters retry or review. Missing outcome tables with `hasResults=true` also become `UNCLEAR`.
2. Require parsed participant counts for `enrollment_by_sex=REPORTED`; retain eligibility lines past 300 characters and include `birth control`. Missing eligibility text becomes `UNCLEAR`.
3. Stage queue decisions and draft actions until the whole batch passes supervision. Quarantining a run also withholds its still-open drafts from affected records. This is an execution safety gate; it cannot prove the labels are correct.
4. `eval_gold.py` now emits record-level predictions and a digest of record versions plus reference labels. `experiment_gate.py` compares the same backend and reference versions, rejects increases in critical false findings/misses, accuracy regressions or large coverage losses. It **stops** a regressing branch. It **holds** a promising branch without a separate adjudicated holdout, and only permits `PROMOTE` when that holdout also passes with at least 10 positive sex-outcome examples. `PROMOTE` is an evaluation decision, not an automatic Git merge or deployment.

The current 25-record set has only **two** positive sex-outcome cases and provisional single-reviewer labels. Improvements measured here are development feedback, not a validated clinical accuracy estimate or promotion evidence. Mock mode tests code plumbing, not a real LLM. See `data/gold_eval.md` for per-label precision, recall, confusion and abstention; re-run it after any parser or prompt change. To run the branch gate:

On these same 25 provisional records, the frozen pre-change mock report had eligibility accuracy **76%** and enrollment-by-sex accuracy **96%**. The current mock report has **100%** for both, with **4%** eligibility abstention; sex restriction and sex-outcome classification were already **100%** on this small set. This is in-sample development feedback, and the positive sex-outcome support of two makes that 100% especially weak evidence. The gate returns `HOLD` because no independent holdout exists. The code suite passed 20 tests, including a sabotage run that halted with no open drafts for quarantined trials.

```bash
python eval_gold.py --llm mock --out data/candidate_dev.json
python experiment_gate.py --baseline-dev data/baseline_dev.json --candidate-dev data/candidate_dev.json
# For promotion, also pass --baseline-holdout and --candidate-holdout from a separate adjudicated set.
```

## Next MLE work, in order

1. Have a second human label the frozen snapshots blind to both first labels and model output, adjudicate differences, and collect an untouched holdout with enough `STRATIFIED_FOUND` and difficult negative cases. Freeze versions and stratify by disease, results availability, and record format. Do not tune against this holdout.
2. Run the **real LLM** and parser end to end on the same frozen records. Inspect all false `STRATIFIED_FOUND`, false `NOT_FOUND_IN_RECORD`, eligibility misses, and abstentions with original JSON paths; measure precision, recall, coverage, cost and latency. The current mock result cannot answer those questions.
3. Add schema-level provenance to persisted verdicts (source SHA-256, field paths, rule/model/prompt versions and searched paths for negative calls), then invalidate all verdicts and drafts when a source record version changes.
4. Calibrate confidence and any stop threshold on adjudicated development data. Sample verified successes for human audit, because agreement and quote presence do not estimate common-mode failures. Decide whether a second model adds value by comparing cost and error reduction on this sample.

The agent is autonomous in its **bounded audit loop**: it can fetch or read records, classify, retry, halt, quarantine and hand off. It cannot autonomously determine that its scientific interpretation is correct, publish a clinical claim, or promote code from the provisional reference. That boundary is intentional until independent validation exists.
