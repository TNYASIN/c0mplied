# HerEvidence: an autonomous auditor that audits itself

**Track: Unsupervised.** An agent audits ClinicalTrials.gov records for gaps in sex-specific reporting,
runs unattended, and *knows when it is stuck, looping, overspending, or unreliable, and stops itself.*
It reaches a human only when it needs approval or has halted. The demo page (`ui_server.py`) is backstage for judges.

## Problem / solution
**Problem:** Women have been under-represented in clinical research, and registry records often do not show whether
results were analyzed by sex. Checking thousands of records by hand is too tedious for anyone to do routinely.
**Solution:** an agent that audits records in the background, backs every finding with a verbatim quote or a JSON path,
verifies its own work, cross-checks the trial's own publications, and halts with a handoff report when it can no longer
be trusted. Gaps become *approval-gated* draft requests addressed to the contact the record names.
**Wording rule:** "not found in the registry record", never "failed to analyze by sex". Pregnancy exclusions are flagged for
review, not labeled discriminatory.

## How a trial is audited
1. **Ingest** (`fetch_trials.py`): a ClinicalTrials.gov v2 record (or a synthetic `SYN…` trial offline) is normalized.
   Sex counts come from the baseline table, outcome values keep their JSON paths, and contacts and the record's own
   publication references are kept. Live ingest also looks up linked PubMed papers (`pubmed.py`).
2. **Audit** (`auditor.py`): rules first, the LLM only where rules cannot decide. There are five checks:

   | Check | How | Labels |
   |---|---|---|
   | `sex_restriction` | rule: `eligibilityModule.sex` | ALL / FEMALE / MALE / UNKNOWN |
   | `eligibility_exclusion` | LLM, only when pregnancy/contraception wording appears; quote must exist in the text | BLANKET_EXCLUSION_CHILDBEARING / PREGNANCY_LACTATION_EXCLUSION / CONDITIONAL / NONE / UNCLEAR |
   | `enrollment_by_sex` | rule: female/male counts in the baseline table | REPORTED / NOT_REPORTED_IN_RECORD / NO_RESULTS_POSTED |
   | `sex_stratified_results` | rule: numeric female *and* male outcome values in the same arm and time point; an LLM "found" without numbers becomes UNCLEAR | STRATIFIED_FOUND / NOT_FOUND_IN_RECORD / UNCLEAR / NO_RESULTS_POSTED |
   | `publication_sex_analysis` | rule: sentence match over linked PubMed titles/abstracts (a lead, never overrides the registry verdict) | MENTIONED_IN_PUBLICATION / NOT_FOUND_IN_ABSTRACTS / NO_LINKED_PUBLICATION / NOT_CHECKED |
3. **Verify** (`verifier.py`): LLM quotes must appear in the source text, and 3 trials per batch get an independent recheck.
4. **Supervise** (`supervisor.py`): budget, loop, stuck and error-rate guards. Queue decisions and drafts are committed only
   after the whole batch passes.
5. **Act** (`report.py`, `drafts.py`, `notify.py`): writes the gap map, the handoff report and drafts, and sends a phone notification.

## Criteria -> where it lives
| Track criterion | Implementation | Demo scenario |
|---|---|---|
| Resumable batches | SQLite queue = checkpoint; `--no-ingest` requeues unresolved trials on the next run | `normal` |
| Knows when it's **stuck** | `STUCK`: 3 consecutive batches resolving zero trials | `stuck` |
| Knows when it's **looping** | identical-call fingerprints (per-task skip, then run halt); repeated fetch pages | `loop` |
| Knows when it's **overspending** | token / call / cost / time caps checked before every call | `budget` |
| Knows when to **stop** | Beta-Binomial posterior on measured error rates; halt if P(rate>10%) >= 0.8; quarantine since last clean batch | `sabotage` |
| Hands off cleanly | `reports/handoff_<run>.md` with why, spend, what's quarantined, what to do | all |
| Human-in-the-loop | drafts need approval; nothing is sent automatically | demo page |

**Representation (who is enrolled):** the gap map also reports the share of women among participants, read from each
record's structured baseline table (no LLM), against the share of women among patients from `prevalence.csv`. The ratio
is the participation-to-prevalence ratio (PPR); below 0.8 is usually read as under-representation. Offline runs use
SYNTHETIC patient shares, labeled as such in the report; never quote those numbers. `prevalence.csv` has sourced figures
only for chronic kidney disease and dementia; the four default live conditions (heart failure, major depressive
disorder, rheumatoid arthritis, lung cancer) are still blank, so live PPR shows as missing until someone adds cited figures.

## Who to contact (`contacts.py`)
Every draft is addressed to the best contact the record itself names, in this order:
1. **Results point of contact** (`resultsSection.moreInfoModule.pointOfContact`): the registry's named contact for results questions.
2. Central contacts (usually removed once a trial completes).
3. The responsible-party investigator.
4. Overall officials (PI, study director).
5. The lead sponsor (organization only).

Only the first two can carry an email, and emails are only ever copied from the record, never guessed. In the 25 frozen
records, 20 have a results point of contact and 16 of those include an email; none has central contacts. A draft with no
email still says who to reach, so the human approving it can find one. Synthetic emails use the reserved `.invalid`
domain, so they can never be delivered. `python drafts.py list` prints each draft's "To:" line. The demo page shows it on
each draft and lists all of a trial's contacts in the trial panel.

## PubMed cross-check (`pubmed.py`)
A registry gap may be filled in the trial's own papers. Linked papers are the record's RESULT/DERIVED references plus a
PubMed search on the NCT ID (`NCTxxxxxxxx[si]`); BACKGROUND references are skipped. The matcher reads titles and
abstracts deterministically (no LLM). It skips sex used as a covariate, matching factor or randomization stratum,
enrollment counts, and aims/methods sentences, and it ranks findings with numbers first.

A match is a **lead, not proof**. It never changes the registry verdict. It changes the draft from "did you analyze by
sex?" to "your paper PMID X appears to report this; would you add it to the registry?", quoting the sentence verbatim.

- Live ingest runs the lookup; `--no-pubmed` skips it.
- `followup.py` requeues watched trials when a new paper gets linked.
- The gap map reports, among registry gaps, the share with a linked paper and the share with a by-sex lead.
- Set `NCBI_API_KEY` for 10 requests/s instead of 3, and `NCBI_EMAIL` per NCBI's usage policy.
- `data/real_gold/pubmed.json` is a frozen snapshot of the papers linked to the 25 gold records: 36 papers across 14
  trials, fetched 2026-10-24. `python pubmed.py --freeze-gold` refreshes it; `python pubmed.py NCT…` checks one trial.
- On that snapshot, the one lead on a registry gap is **NCT00043550**: the record has no by-sex outcome, but PMID
  22152401 reports *"Gender and minority status moderated outcome (P = .014)…"*.

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
python drafts.py list                            # drafts with who they are addressed to
python ui_server.py                              # the demo page: http://localhost:8501
python -m pytest tests                           # 29 tests
```
**Real data + real LLM:** `export ANTHROPIC_API_KEY=...` then `python run_agent.py --live --limit 60 --llm anthropic`.
The default model is `claude-sonnet-5-5`; set `HEREVIDENCE_MODEL` to change it. The prices in `config.py` only drive the
spend gauge; check current pricing. Live mode needs internet for both ClinicalTrials.gov and PubMed. A live smoke test
(8 trials, mock LLM) ran end to end on 2026-10-24. The real-LLM live pipeline has **not** been validated end to end.

### Measured offline results (synthetic, mock LLM, 40 trials, 2026-10-24)
| Scenario | Outcome | Calls | Tokens |
|---|---|---:|---:|
| `normal` | COMPLETED | 62 | 30,023 |
| `sabotage` | HALTED_ERROR_RATE (grounding 4/19 failures, P = 0.86); 15 trials quarantined | 39 | 19,244 |
| `loop` | HALTED_LOOP after 3 looping tasks | 14 | 7,077 |
| `stuck` | HALTED_STUCK after 3 batches with no progress | 17 | 7,750 |
| `budget` | HALTED_TOKEN_BUDGET (9,079 of 9,000) | 18 | 9,079 |

`compare.py` (written to `data/compare.json`). "Published" means eligible for the gap map (a database count, not
external publication). "Wrong" means it disagrees with synthetic ground truth on the eligibility or sex-stratified checks.

| Scenario | Supervisor | Status | Calls | Published | Wrong | Withheld |
|---|---|---|---:|---:|---:|---:|
| sabotage | off | COMPLETED | 39 | 80 | 19 | 0 |
| sabotage | **on** | HALTED_ERROR_RATE | 39 | 30 | **1** | 30 |
| loop | off | HALTED_EMERGENCY_CAP | 150 | 10 | 0 | 0 |
| loop | **on** | HALTED_LOOP | **14** | 10 | 0 | 2 |

The supervisor cuts wrong published verdicts from 19 to 1 and loop spend from 150 calls to 14. The remaining 1 is
SYN0700012: the degraded model claimed by-sex results, and the evidence gate downgraded the claim to `UNCLEAR`.
`compare.py` counts that abstention as published and wrong (truth is `NOT_FOUND_IN_RECORD`). So no false finding
reached the gap map in this run, but the gap map's denominators still include one abstention.

## Real-record evaluation: phase 1
See [`AGENT_RESEARCH_REVIEW.md`](AGENT_RESEARCH_REVIEW.md) for the DataMaster/AIBuildAI comparison, the numeric evidence
gate, staged draft behavior, and candidate branch stop rules. `experiment_gate.py` uses version-matched evaluation
reports to stop regressions and holds promotion until an independent adjudicated holdout passes. It does not merge or
deploy code.

Read [`LABELING_GUIDE.md`](LABELING_GUIDE.md). `data/real_gold/` contains 25 frozen ClinicalTrials.gov v2 JSON records,
with SHA-256 and record dates, plus the PubMed snapshot above. `data/gold_set.json` contains **single-reviewer
provisional labels**, not a two-person adjudicated gold set. The blind review sheets cover 7 model disagreements
(`data/reviewer2_disagreements.csv`), 18 priority records (`data/reviewer2_priority.csv`), and all 25 records
(`data/reviewer2_full.csv`). A second person should label from the full source records without seeing the first labels.
Then run `python compare_reviewers.py data/reviewer2_full.csv`, adjudicate disagreements, and update the gold file and
review status.

```bash
python eval_gold.py --llm mock             # pipeline check, not real-LLM accuracy
python eval_gold.py --llm anthropic        # requires the package and ANTHROPIC_API_KEY
```

`data/gold_eval.json` and `data/gold_eval.md` contain per-label precision, recall, F1, support, confusion matrices,
coverage, abstention rate and disagreements. Each run now also adds a **publication cross-check** section listing
PubMed leads; these are unscored. With mock, all four scored checks are 100% on these 25 records, with 4% eligibility
abstention. That is in-sample feedback on provisional labels with only two positive sex-outcome cases, not a validated
accuracy. The sample includes targeted challenge records, so it does not estimate population prevalence.
`--template 30` remains available for exporting additional cached live records, but its candidate lines are not
sufficient for labeling; read the complete source.

## Demo UI (`python ui_server.py`)
One page, standard library only. Left: the phone of the person running the audit; it stays silent until the agent halts
or finishes, then shows the same message `notify.py` sends. Right: backstage for judges. **Run audit** and the
**Break it** buttons start real `run_agent.py` runs in the background (paced at 0.3 s/trial so they can be watched;
`HEREVIDENCE_UI_PACE` changes it). The supervisor chart is P(error rate > 10%) per batch, the same numbers the halt rule
uses. **Send morning brief** summarizes the gap map. Pick **Real (ClinicalTrials.gov)** in the Data menu for live runs.
Drafts show who they are addressed to. Clicking a trial shows each verdict and its quote, the eligibility text, the
record's contacts, and its linked PubMed papers.

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
1. **Real gap:** live run, open a flagged trial, show the verbatim quote against source text, then show who the draft is addressed to.
2. **Paper vs registry:** show NCT00043550: no by-sex result in the registry, but its paper reports gender moderated outcome, so the draft asks them to post it.
3. **Sabotage:** `sabotage` scenario. Posterior climbs, supervisor halts, quarantines, prints the handoff.
4. **Loop + budget:** `loop` (burns 14 calls, not 150) and `budget` (stops mid-run, resumable).
5. **Numbers:** `compare.py`: wrong published verdicts 19 -> 1 with the supervisor on (the 1 is an `UNCLEAR` abstention, not a false finding).
6. **Follow-up:** approve a draft (simulated), simulate new results, watch the gap close and the draft resolve.
7. **Limits slide:** below.

## Honest limits (say them before the judges do)
- Offline numbers come from **synthetic** trials with known ground truth; they test the plumbing and supervisor, not
  clinical accuracy. The real-record labels are provisional and the checked-in evaluation uses mock, so neither is a
  validated real-LLM clinical accuracy result.
- Verification measures *source-grounding and agreement*. An error both passes share is invisible, and the sampled
  recheck can miss errors in unsampled verdicts. In this synthetic run no false finding got through, but that is one
  seeded run, not a guarantee.
- Loop detection uses exact call fingerprints; swap in embedding similarity if you have time.
- The registry is not the literature: absent from the record does not mean absent from a paper. The PubMed check reads
  only titles and abstracts of papers linked to the NCT ID, so unlinked papers and full-text-only subgroup tables are
  missed. Its matcher was reviewed by hand on 36 linked abstracts (3 hits, no false positives seen); it has no labeled evaluation.
- Contacts are only as current as the registry record; a results contact may have moved on. A human checks before sending.
- Trials saved to the database before contact extraction existed have no stored contacts until they are fetched again.
- Check C ("sex-stratified results") definitions with a domain-aware teammate before presenting percentages.

## Files
`agent.py` loop | `supervisor.py` guards + Beta-Binomial | `verifier.py` quote grounding + sampled recheck | `auditor.py` rules-first, LLM-second |
`fetch_trials.py` API + cache + enrollment counts by sex | `contacts.py` who to contact | `pubmed.py` linked-publication cross-check |
`prevalence.csv` women's share of patients (sourced) | `store.py` checkpoint DB | `report.py` gap map + handoff | `drafts.py`/`notify.py`/`followup.py` actions |
`mock_llm.py` offline model w/ sabotage modes | `fixtures.py` synthetic trials, contacts, papers | `eval_gold.py` | `compare.py` | `experiment_gate.py` |
`ui_server.py` + `ui/index.html` demo page | `tests/`
