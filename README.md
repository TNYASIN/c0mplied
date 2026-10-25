# HerEvidence: an autonomous auditor that audits itself

**Track: Unsupervised.** An agent audits ClinicalTrials.gov records for gaps in sex-specific reporting,
runs unattended, and *knows when it is stuck, looping, overspending, or unreliable, and stops itself.*
Only reaches a human when it needs approval or has halted. The public-facing web UI explains trusted findings, while the Agent Monitor provides a backstage view of the autonomous run and supervisor for judges and operators. The interface is served by `ui_server.py`.

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

## Web UI (`python ui_server.py`)
The standard-library server and `ui/` frontend are the primary interface. It has five connected areas: **Home**,
**Explore Research**, **Study Findings**, **Ask HerEvidence**, and **Agent Monitor**. The monitor still starts the real
`run_agent.py` process, resumes its SQLite queue, and exposes every failure scenario. `HEREVIDENCE_UI_PACE` controls
how quickly a run advances when it is watched in the UI.

**Explain This Finding** builds beginner and researcher views from the same stored verdict. Researcher mode exposes the
classification label, normalized source field path, original excerpt, run/batch metadata, and verification outcome.
**Ask HerEvidence** is read-only and works without an API key: supported questions are answered deterministically from
verified, non-quarantined SQLite records. Real and synthetic records are separate data views; demo answers are always
labelled synthetic. Real NCT references link to the original ClinicalTrials.gov study page.

The Agent Monitor also keeps the original human-in-the-loop workflow available: operators can approve or reject
follow-up drafts, inspect lifecycle events and the latest supervisor handoff, and review measured supervisor/gold
evaluation results. Gap-closure simulation is deliberately limited to synthetic demo records, so it cannot rewrite a
real NCT record.

Read-only API routes used by the frontend:

- `GET /api/studies?scope=real|synthetic` — reporting overview and study cards
- `GET /api/studies/<id>` — stored study metadata and deterministic finding explanations
- `POST /api/ask` — grounded answers with the exact records checked and source references
- `POST /api/draft` — approve or reject a pending follow-up draft
- `POST /api/followup` — simulate gap closure for an approved synthetic demo record

The existing `GET /api/state` and `POST /api/run` routes continue to power the autonomous Agent Monitor.

## Phone notifications
The agent pushes to a real phone when a run finishes or the supervisor halts it (halts arrive as high priority).
It uses [ntfy](https://ntfy.sh): free, no account, works on iPhone and Android. Without setup it just prints `[notify:stub]`.

1. Install the **ntfy** app (App Store / Google Play). On iPhone, tap **Allow** when it asks to send notifications.
2. In the app, tap **+** and subscribe to the team topic (ask Tanya for the name; anyone who knows it can read it, so don't post it publicly). Leave the server as ntfy.sh.
3. Start the server with the topic set; it should print `Phone notifications: ntfy`:
   ```bash
   NTFY_TOPIC=<team-topic> python ui_server.py
   ```
4. Test: lock the phone, then run `NTFY_TOPIC=<team-topic> python notify.py`. The phone should buzz.

**Troubleshooting (iPhone):** if messages show inside the app but never on the lock screen, notifications weren't registered.
Delete the app, reinstall, tap **Allow**, re-add the topic. Also check Settings → Notifications → ntfy and turn off Focus.
A failed send prints `[notify:ntfy] FAILED ...` in the terminal.

SMS via Twilio also works: set `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM`, `NOTIFY_TO` (trial accounts can only text
verified numbers; some countries require sender registration first, so test early).

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
<<<<<<< HEAD
`mock_llm.py` offline model w/ sabotage modes | `eval_gold.py` | `compare.py` | `ui_server.py` + `ui/index.html` demo page | `tests/`
=======
`mock_llm.py` offline model w/ sabotage modes | `evidence.py` read-only explanations + Q&A | `ui_server.py` + `ui/` primary web UI |
`eval_gold.py` | `compare.py` | `app.py` legacy dashboard | `tests/`
>>>>>>> 8c0c28b (Add HerEvidence frontend assets, evidence handling, and tests)
