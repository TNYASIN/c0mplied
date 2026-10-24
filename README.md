# HerEvidence: an autonomous auditor that audits itself

**Track: Unsupervised.** An agent audits ClinicalTrials.gov records for gaps in sex-specific reporting,
runs unattended, and *knows when it is stuck, looping, overspending, or unreliable, and stops itself.*
Only reaches a human when it needs approval or has halted. The demo page (`ui_server.py`) is backstage for judges.

## Problem / solution
**Problem:** Women have been under-represented in clinical research, and registry records often do not show whether
results were analyzed by sex. Checking thousands of records by hand is too tedious for anyone to do routinely.
**Solution:** an agent that audits records in the background, backs every finding with a verbatim quote, verifies its own
work, and halts with a handoff report when it can no longer be trusted. Gaps become *approval-gated* draft requests.
**Wording rule:** "not found in the registry record", never "failed to analyze by sex". Pregnancy exclusions are flagged for
review, not labeled discriminatory.

## Criteria -> where it lives
| Track criterion | Implementation | Demo scenario |
|---|---|---|
| Resumable batches | SQLite queue = checkpoint; `--no-ingest` requeues unresolved trials on the next run | `normal` |
| Knows when it's **stuck** | `STUCK`: N batches resolving zero trials | `stuck` |
| Knows when it's **looping** | identical-call fingerprints (per-task skip, then run halt); repeated fetch pages | `loop` |
| Knows when it's **overspending** | token / call / cost / time caps checked before every call | `budget` |
| Knows when to **stop** | Beta-Binomial posterior on measured error rates; halt if P(rate>10%) >= 0.8; quarantine since last clean batch | `sabotage` |
| Hands off cleanly | `reports/handoff_<run>.md` with why, spend, what's quarantined, what to do | all |
| Human-in-the-loop | drafts need approval; nothing is sent automatically | demo page |

**Representation (who is enrolled):** the gap map also reports the share of women among participants, read from each
record's structured baseline table (no LLM), against the share of women among patients from `prevalence.csv`. The ratio
is the participation-to-prevalence ratio (PPR); below 0.8 is usually read as under-representation. Offline runs use
SYNTHETIC patient shares, labeled as such in the report; never quote those numbers.

## Run it (no API key, no internet needed)
```bash
pip install -r requirements.txt
python run_agent.py --scenario normal            # synthetic trials, mock LLM
python run_agent.py --scenario sabotage          # model degrades mid-run -> supervisor halts + quarantines
python run_agent.py --scenario loop              # unparseable replies -> loop detector
python run_agent.py --scenario stuck             # ambiguous trials -> stuck detector
python run_agent.py --scenario budget            # tiny token cap
python compare.py                                # same sabotage, supervisor OFF vs ON (headline numbers)
python followup.py --simulate && python run_agent.py --no-ingest   # gap closes -> draft marked RESOLVED
python ui_server.py                              # the demo page: http://localhost:8501
python -m pytest tests
```
**Real data + real LLM:** `export ANTHROPIC_API_KEY=...` then `python run_agent.py --live --limit 60 --llm anthropic`.
Set `HEREVIDENCE_MODEL` if you want a different model. **Before trusting live mode:** run
`python fetch_trials.py --raw heart failure` and confirm the v2 field names and the `aggFilters` string; this was written
against the live API. The phase-1 frozen JSON records enable parser checks, but the whole live pipeline still needs end-to-end validation.

## Real-record evaluation: phase 1

See [`AGENT_RESEARCH_REVIEW.md`](AGENT_RESEARCH_REVIEW.md) for the DataMaster/AIBuildAI comparison, numeric evidence gate, staged draft behavior, and candidate branch stop rules. `experiment_gate.py` uses version-matched evaluation reports to stop regressions and holds promotion until an independent adjudicated holdout passes. It does not merge or deploy code.

Read `LABELING_GUIDE.md` and `ARCHITECTURE_REVIEW.md`. `data/real_gold/` contains 25 frozen ClinicalTrials.gov v2 JSON records, with SHA-256 and record dates. `data/gold_set.json` contains **single-reviewer provisional labels**, not a two-person adjudicated gold set. The blind review sheets cover 7 model disagreements (`data/reviewer2_disagreements.csv`), 18 priority records (`data/reviewer2_priority.csv`), and all 25 records (`data/reviewer2_full.csv`). A second person should label from the full source records without seeing the first labels. Then run `python compare_reviewers.py data/reviewer2_full.csv`, adjudicate disagreements, and update the gold file and review status.

```bash
python eval_gold.py --llm mock             # pipeline check, not real-LLM accuracy
python eval_gold.py --llm anthropic        # requires the package and ANTHROPIC_API_KEY
python -m pytest tests                     # existing and phase-1 tests
```

`data/gold_eval.json` and `data/gold_eval.md` contain per-label precision, recall, F1, support, confusion matrices, coverage, abstention rate, and disagreements. The sample includes targeted challenge records, so it does not estimate population prevalence. `--template 30` remains available for exporting additional cached live records, but its candidate lines are not sufficient for labeling; read the complete source. `ARCHITECTURE_REVIEW.md` gives the remaining three-hour schedule.

## Demo UI (`python ui_server.py`)
One page, standard library only. Left: the phone of the person running the audit; it stays silent until the agent halts
or finishes, then shows the same message `notify.py` texts. Right: backstage for judges. **Run audit** and the
**Break it** buttons start real `run_agent.py` runs in the background (paced at 0.3 s/trial so they can be watched;
`HEREVIDENCE_UI_PACE` changes it). The supervisor chart is P(error rate > 10%) per batch, the same numbers the halt rule
uses. **Send morning brief** summarizes the gap map. Pick **Real (ClinicalTrials.gov)** in the Data menu for live runs.

## 3-minute demo
1. **Real gap:** live run, open a flagged trial, show the verbatim quote against source text.
2. **Sabotage:** `sabotage` scenario. Posterior climbs, supervisor halts, quarantines, prints the handoff.
3. **Loop + budget:** `loop` (burns 15 calls, not 150) and `budget` (stops mid-run, resumable).
4. **Numbers:** `compare.py` compares wrong verdicts eligible for the gap map in a synthetic sabotage run; its `published` column is a database count, not external publication.
5. **Follow-up:** approve a draft (simulated), simulate new results, watch the gap close and the draft resolve.
6. **Limits slide:** below.

## Honest limits (say them before the judges do)
- Offline numbers come from **synthetic** trials with known ground truth; they test the plumbing and supervisor, not clinical accuracy. The checked-in real-record labels are provisional and the checked-in evaluation uses mock, so neither is a validated real-LLM clinical accuracy result.
- Verification measures *source-grounding and agreement*. An error both passes share is invisible; the sampled recheck can miss errors in
  unsampled verdicts (the supervised run shows 0 wrong published in the demo, but this is not a guarantee).
- Loop detection uses exact call fingerprints; swap in embedding similarity if you have time.
- The registry is not the literature: absent from the record does not mean absent from a paper.
- Check C ("sex-stratified results") definitions with a domain-aware teammate before presenting percentages.

## Files
`agent.py` loop | `supervisor.py` guards + Beta-Binomial | `verifier.py` quote grounding + sampled recheck | `auditor.py` rules-first, LLM-second |
`fetch_trials.py` API + cache + enrollment counts by sex | `prevalence.csv` women's share of patients (sourced) | `store.py` checkpoint DB | `report.py` gap map + handoff | `drafts.py`/`notify.py`/`followup.py` actions |
`mock_llm.py` offline model w/ sabotage modes | `eval_gold.py` | `compare.py` | `ui_server.py` + `ui/index.html` demo page | `tests/`
