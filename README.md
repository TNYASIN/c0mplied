# HerEvidence

**An autonomous AI research auditor that finds missing sex-specific evidence in clinical trials, checks its own work, and stops itself when it can no longer be trusted.**

*Invisible Interfaces hackathon · Track: Unsupervised*

---

## Why this exists

For decades, medical research has often treated the male body as the default, even though women and men can respond differently to medications.

Historically, women were excluded from many early-stage drug trials, partly because of concerns about pregnancy and hormonal changes. This contributed to gaps in our understanding of how certain medications affect women.

Those differences can have serious consequences. For example, research has found that women experience a higher incidence of accidental awareness during general anesthesia, meaning some patients may become conscious and later remember parts of a surgical procedure (the UK's 5th National Audit Project on accidental awareness, NAP5, listed female sex among the factors associated with higher risk; Pandit et al., *Anaesthesia*, October 2014). That is an observational audit, and it shows why understanding sex-related differences in drug response matters. It does not establish that exclusion from clinical trials caused any individual patient's experience.

**The problem isn't simply whether women are included in clinical trials. It's whether researchers actually study and report how treatments affect women differently.**

Checking that by hand means reading thousands of registry records, so almost nobody does it routinely. That is the job we gave to an agent.

## What HerEvidence does

HerEvidence audits completed trials on ClinicalTrials.gov, runs without anyone watching, and for each trial answers three questions:

1. **Who was allowed in?** Does the eligibility text exclude pregnant or breastfeeding women, or women of childbearing potential? These are flagged for review, never labeled discriminatory, because some have legitimate safety reasons.
2. **Was enrollment reported by sex?** Read from the record's structured baseline table.
3. **Were results reported by sex?** Is there any outcome result broken out for women and men?
4. **Do the trial's own papers report it?** Linked PubMed titles and abstracts are checked for a by-sex analysis the registry lacks (a lead, never a verdict).

It also reports the share of women enrolled against the share of women among patients with the condition (participation-to-prevalence ratio, below 0.8 is usually read as under-representation). Patient shares and their sources are in `prevalence.csv`.

Every AI finding comes with a **verbatim quote from the source record**. When results are posted but nothing is reported by sex, the agent drafts a polite clarification request addressed to the best contact the registry record names (see [Who to contact](#who-to-contact-contactspy)). **Nothing is ever sent without a human approving it** (in the demo, approval is simulated and nothing is sent). When a trial's results change, the agent can re-check it and close the gap (`followup.py`; simulated in the demo).

**Wording rule:** a finding means *"not found in the registry record,"* never *"the researchers failed to analyze by sex."* Papers may contain analyses the registry lacks.

## Why it fits the Unsupervised track

The agent is the vehicle. The supervisor is the point: **does the agent know when to stop?**

| Track criterion | How HerEvidence handles it | Demo scenario |
|---|---|---|
| Runs without constant supervision | Work lives in a SQLite queue, so a halted run resumes from its checkpoint (`--no-ingest`) | `normal` |
| Knows when it is **unreliable** | Beta-Binomial posterior on its own measured error rate; halts when P(error rate > 10%) reaches 0.8, then quarantines every batch since the last clean one | `sabotage` |
| Knows when it is **looping** | Fingerprints identical calls and repeated fetch pages; skips the looping task, halts the run if it keeps happening | `loop` |
| Knows when it is **overspending** | Token, call, cost and time caps checked before every call | `budget` |
| Knows when it is **stuck** | Halts after N batches that resolve zero trials | `stuck` |
| Hands off cleanly | `reports/handoff_<run>.md`: why it stopped, spend, what is quarantined, what a human should do next | all |
| Human stays in control | Draft requests need approval; the phone is buzzed only on a halt, a finish, or a draft approval | demo page |

## How it works

```
ClinicalTrials.gov -> queue (SQLite checkpoint)
        |
        v   5 trials per batch; supervisor checks budget before every call
  rules first (free)  ->  LLM only for ambiguous text, must quote the source
        |
        v
  verifier:  A) is the quote really in the record?  (every AI answer that cites evidence)
             B) does an independent second pass agree?  (sampled)
        |
        v
  supervisor: updates error-rate posterior, loop / budget / stuck detectors
        |            \
        v             v  halt -> quarantine -> handoff report -> phone alert
  gap map + approval-gated draft requests + follow-up re-checks
```

Rule-based answers (such as enrollment counts by sex) are read directly from structured fields, so they need no quote check. Rejected or quarantined answers never reach the gap map.

## Who to contact (`contacts.py`)

Every draft is addressed to the best contact the record itself names, in this order:

1. **Results point of contact** (`resultsSection.moreInfoModule.pointOfContact`): the registry's named contact for results questions.
2. Central contacts (usually removed once a trial completes).
3. The responsible-party investigator.
4. Overall officials (PI, study director).
5. The lead sponsor (organization only).

Only the first two can carry an email, and emails are only ever copied from the record, never guessed. In the 25 frozen records, 20 have a results point of contact and 16 of those include an email; none has central contacts. A draft with no email still says who to reach, so the human approving it can find one. Synthetic emails use the reserved `.invalid` domain, so they can never be delivered. `python drafts.py list` prints each draft's "To:" line. The demo page shows it on each draft and lists all of a trial's contacts in the trial panel.

## PubMed cross-check (`pubmed.py`)

A registry gap may be filled in the trial's own papers. Linked papers are the record's RESULT/DERIVED references plus a PubMed search on the NCT ID (`NCTxxxxxxxx[si]`); BACKGROUND references are skipped. The matcher reads titles and abstracts deterministically (no LLM). It skips sex used as a covariate, matching factor or randomization stratum, enrollment counts, and aims/methods sentences, and it ranks findings with numbers first.

A match is a **lead, not proof**. It never changes the registry verdict. It changes the draft from "did you analyze by sex?" to "your paper PMID X appears to report this; would you add it to the registry?", quoting the sentence verbatim.

- Live ingest runs the lookup; `--no-pubmed` skips it.
- `followup.py` requeues watched trials when a new paper gets linked.
- The gap map reports, among registry gaps, the share with a linked paper and the share with a by-sex lead.
- Set `NCBI_API_KEY` for 10 requests/s instead of 3, and `NCBI_EMAIL` per NCBI's usage policy.
- `data/real_gold/pubmed.json` is a frozen snapshot of the papers linked to the 25 gold records: 36 papers across 14 trials, fetched 2026-10-24. `python pubmed.py --freeze-gold` refreshes it; `python pubmed.py NCT…` checks one trial.
- On that snapshot, the one lead on a registry gap is **NCT00043550**: the record has no by-sex outcome, but PMID 22152401 reports *"Gender and minority status moderated outcome (P = .014)…"*.

## Run it (no internet needed)

```bash
pip install -r requirements.txt
python run_agent.py --scenario normal      # synthetic trials, mock LLM
python run_agent.py --scenario sabotage    # model degrades mid-run -> halt + quarantine
python run_agent.py --scenario loop
python run_agent.py --scenario budget
python run_agent.py --scenario stuck
python compare.py                          # same sabotage, supervisor OFF vs ON
python followup.py --simulate && python run_agent.py --no-ingest   # gap closes -> draft marked RESOLVED
python drafts.py list                      # drafts with who they are addressed to
python ui_server.py                        # demo page at http://localhost:8501
python -m pytest tests
```

**If `ANTHROPIC_API_KEY` is set, these use the real model and spend credits.** Add `--llm mock` to force the offline model.

**Real data and a real model:**

```bash
export ANTHROPIC_API_KEY=...
python run_agent.py --live --limit 60 --llm anthropic
```

Set `HEREVIDENCE_MODEL` to use a different model. Live mode needs internet for both ClinicalTrials.gov and PubMed.

## Demo page (`python ui_server.py`)

One page, standard library only. Left: the phone of the person running the audit; it stays silent until the agent halts or finishes. Right: backstage for judges. **Run audit** and the **Break it** buttons start real `run_agent.py` runs in the background (paced at 0.3 s/trial so they can be watched; `HEREVIDENCE_UI_PACE` changes it). Pick **Real (ClinicalTrials.gov)** in the Data menu for live records. Drafts show who they are addressed to. Clicking a trial shows each verdict and its quote, the eligibility text, the record's contacts, and its linked PubMed papers.

**How Break it works with the real model:** asking Claude to misbehave in the prompt is unreliable (it keeps quoting verbatim), so the scenarios use fault injection: the real model answers normally, then `llm.inject_fault` corrupts the answer the way a failing model would (a quote not in the record, unusable prose, or UNCLEAR) before the agent sees it. The supervisor has to catch the failure from the output alone. Any unexpected error halts the run as `CRASH` with a handoff report instead of dying silently.

Below: the supervisor chart (P(error rate > 10%) per batch, the same numbers the halt rule uses), the gap map, the latest trials (click an ID for its evidence and quotes), draft requests with Approve / Reject and the follow-up button, the latest handoff report, and measured results.

## Phone notifications

The agent pushes to a real phone when a run finishes or the supervisor halts it (halts arrive as high priority). It uses [ntfy](https://ntfy.sh): free, no account, works on iPhone and Android. Without setup it just prints `[notify:stub]`.

1. Install the **ntfy** app (App Store / Google Play). On iPhone, tap **Allow** when it asks to send notifications.
2. In the app, tap **+** and subscribe to the team topic (ask Tanya for the name; anyone who knows it can read it, so don't post it publicly). Leave the server as ntfy.sh.
3. Start the server with the topic set; it should print `Phone notifications: ntfy`:
   ```bash
   NTFY_TOPIC=<team-topic> python ui_server.py
   ```
4. Test: lock the phone, then run `NTFY_TOPIC=<team-topic> python notify.py`. The phone should buzz.

**Troubleshooting (iPhone):** if messages show inside the app but never on the lock screen, notifications weren't registered. Delete the app, reinstall, tap **Allow**, re-add the topic. Also check Settings → Notifications → ntfy and turn off Focus. A failed send prints `[notify:ntfy] FAILED ...` in the terminal.

SMS via Twilio also works: set `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM`, `NOTIFY_TO` (trial accounts can only text verified numbers; some countries require sender registration first, so test early).

## Results

Every number HerEvidence reports is generated by the code and written to a file, so nothing in this README can drift out of date.

| What it shows | How to produce it | Output | Data |
|---|---|---|---|
| Supervisor ON vs OFF under the same model sabotage: wrong verdicts that reach the gap map, calls and tokens spent, verdicts withheld | `python compare.py` | `data/compare.json` | Synthetic trials with known ground truth |
| Halts: why the run stopped, spend, what was quarantined, what a human should do next | any `run_agent.py` run | `reports/handoff_<run>.md` | Whatever the run used |
| Classification agreement per label: precision, recall, F1, support, confusion matrices, abstention rate, disagreements, plus an unscored publication cross-check section listing PubMed leads | `python eval_gold.py --llm anthropic` | `data/gold_eval.json`, `data/gold_eval.md` | 25 frozen real ClinicalTrials.gov records, provisional labels from one AI reviewer, not yet human-checked |
| Gap map by condition, including participation-to-prevalence ratio | any run with `--live` | `reports/gap_map.csv`, `reports/gap_report.md` | Live ClinicalTrials.gov records |

Read the data column before quoting a number. Synthetic runs show that the supervisor works. They say nothing about clinical accuracy, and offline prevalence shares are synthetic and labeled as such in the report.

## Real-record evaluation

`data/real_gold/` holds 25 frozen ClinicalTrials.gov v2 records with SHA-256 fingerprints and record dates, plus the PubMed snapshot above (`.gitattributes` keeps git from changing their line endings, which would break the fingerprints). `data/gold_set.json` holds **provisional labels from one AI reviewer** (Codex), not a human or two-person adjudicated gold set. Label definitions are in `LABELING_GUIDE.md`; see also `ARCHITECTURE_REVIEW.md` and `AGENT_RESEARCH_REVIEW.md`.

To make it human-checked: a person labels `data/reviewer2_disagreements.csv` (7 records), `data/reviewer2_priority.csv` (18) or `data/reviewer2_full.csv` (25) from the full source records, without looking at `gold_set.json`. Then run `python compare_reviewers.py <sheet>`, adjudicate the disagreements in `data/adjudication_queue.csv`, and update the gold file and its review status.

```bash
python eval_gold.py --llm mock             # pipeline check, not real-LLM accuracy
python eval_gold.py --llm anthropic        # requires the package and ANTHROPIC_API_KEY
```

The sample includes targeted challenge records, so it does not estimate population prevalence. `experiment_gate.py` holds promotion until an independent adjudicated holdout passes; it currently says HOLD.

## 3-minute demo

1. **Real gap:** live run, show the gap map (heart failure PPR), open a flagged trial, show the verbatim quote against the source text.
2. **Paper vs registry:** show NCT00043550: no by-sex result in the registry, but its paper reports gender moderated outcome, so the draft asks them to post it.
3. **Sabotage:** **Model degrades**. The posterior climbs, the supervisor halts and quarantines, the phone buzzes, the handoff report appears.
4. **Loop and budget:** **Model loops** (burns 15 calls, not 150) and **Tiny budget** (stops mid-run, resumable).
5. **Numbers:** measured results compare wrong verdicts reaching the gap map in a synthetic sabotage run, supervisor off vs on. Its `published` column is a database count, not external publication.
6. **Follow-up:** show a draft's recipient, approve it (simulated), click **A trial publishes results by sex**, watch the draft close.
7. **Limits:** below.

## Honest limits

- Offline numbers come from synthetic trials with known ground truth. The real-record labels are provisional and come from one AI reviewer (not human-checked or adjudicated), and the checked-in evaluation uses the mock model, so none of this is validated real-LLM clinical accuracy yet.
- Verification measures source-grounding and agreement. An error both passes share is invisible, and the sampled recheck can miss errors in unsampled verdicts.
- Loop detection matches exact repeated calls, not similar ones.
- The registry is not the literature: absent from the record does not mean absent from a paper. The PubMed check reads only titles and abstracts of papers linked to the NCT ID, so unlinked papers and full-text-only subgroup tables are missed. Its matcher was reviewed by hand on 36 linked abstracts (3 hits, no false positives seen); it has no labeled evaluation.
- Pregnancy exclusions are flagged for human review, not judged.
- Patient shares in `prevalence.csv` are worldwide estimates, while many audited trials are US-based. Rheumatoid arthritis is approximated from a female-to-male prevalence ratio, and lung cancer uses new cases (incidence), not prevalence.
- Live runs sample about 10 trials per condition, so the gap map is a small sample, not a field-wide estimate.
- Draft requests are addressed to each trial's registry contact but never sent. Contacts are only as current as the record; a results contact may have moved on, so a human checks before sending.
- Trials saved to the database before contact extraction existed have no stored contacts until they are fetched again.

## Repository map

`agent.py` main loop · `supervisor.py` guards and Beta-Binomial · `verifier.py` quote grounding and recheck · `auditor.py` rules first, LLM second · `fetch_trials.py` API, caching and enrollment by sex · `contacts.py` who to contact · `pubmed.py` linked-publication cross-check · `prevalence.csv` sourced patient shares · `store.py` checkpoint DB · `report.py` gap map and handoff · `drafts.py`, `notify.py`, `followup.py` actions · `mock_llm.py` offline model with sabotage modes · `fixtures.py` synthetic trials, contacts, papers · `eval_gold.py` · `compare.py` · `ui_server.py` + `ui/index.html` demo page · `tests/`
