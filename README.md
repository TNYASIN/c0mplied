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
| Runs for hours unsupervised | SQLite queue = checkpoint; `--resume`/`--no-ingest`; unresolved trials auto-retried next run | `normal` |
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
from the documented schema but could not be tested against the live API from the build environment.

## Do these in your 5 hours (the code is the skeleton, the evidence is yours)
1. **0:00-0:30** Run offline scenarios; confirm everyone's environment works. Run `--live` once, fix any field-name issues in `fetch_trials.normalize_trial`.
   Also fill `prevalence.csv`: the share of women among patients for each condition, **with a source per row**.
   Without it, real runs still report the share of women among participants, but no PPR.
2. **0:30-1:30** Pull ~60 real trials. `python eval_gold.py --template 30` and **hand-label 30** (split across the team). Save as `data/gold_set.json`:
   `[{"nct_id":..., "eligibility":..., "sex_stratified":...}]`.
3. **1:30-2:30** `python eval_gold.py` with the real LLM. Read the misses; tune `prompts.py`. Your accuracy number is *this*, not the synthetic one.
4. **2:30-3:30** Real-LLM sabotage run (`--scenario sabotage --llm anthropic`); tune `Limits` in `config.py` so the halt triggers cleanly on stage but not on a normal run.
5. **3:30-4:15** `python compare.py` (offline numbers) plus a recorded backup video. Freeze code at 4:15.
6. **4:15-5:00** Rehearse x3. Optional: set Twilio env vars (`notify.py`) so a real phone buzzes at halt/approval time.

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
4. **Numbers:** `compare.py`: unsupervised agent published N wrong findings; supervised published 0 and withheld the rest.
5. **Follow-up:** approve a draft (simulated), simulate new results, watch the gap close and the draft resolve.
6. **Limits slide:** below.

## Honest limits (say them before the judges do)
- Offline numbers come from **synthetic** trials with known ground truth; they test the plumbing and supervisor, not clinical accuracy.
  Report accuracy on your hand-labeled real gold set only.
- Verification measures *source-grounding and agreement*. An error both passes share is invisible; the sampled recheck can miss errors in
  unsampled verdicts (the supervised run shows 0 wrong published in the demo, but this is not a guarantee).
- Loop detection uses exact call fingerprints; swap in embedding similarity if you have time.
- The registry is not the literature: absent from the record does not mean absent from a paper.
- Check C ("sex-stratified results") definitions with a domain-aware teammate before presenting percentages.

## Files
`agent.py` loop | `supervisor.py` guards + Beta-Binomial | `verifier.py` quote grounding + sampled recheck | `auditor.py` rules-first, LLM-second |
`fetch_trials.py` API + cache + enrollment counts by sex | `prevalence.csv` women's share of patients (sourced) | `store.py` checkpoint DB | `report.py` gap map + handoff | `drafts.py`/`notify.py`/`followup.py` actions |
`mock_llm.py` offline model w/ sabotage modes | `eval_gold.py` | `compare.py` | `ui_server.py` + `ui/index.html` demo page | `tests/`
