"""Gap map + handoff report. Wording is deliberately 'not found in the registry record'."""
import os, csv, json
import config, store

ELIG_FLAGS = ("BLANKET_EXCLUSION_CHILDBEARING", "PREGNANCY_LACTATION_EXCLUSION", "CONDITIONAL")


def latest_trusted():
    rows = store.q("SELECT v.* FROM verdicts v JOIN (SELECT nct_id,chk,MAX(id) mid FROM verdicts GROUP BY nct_id,chk) m "
                   "ON v.id=m.mid WHERE v.quarantined=0 AND v.verified=1")
    by = {}
    for r in rows:
        by.setdefault((r["condition"], r["nct_id"]), {})[r["chk"]] = r["label"]
    return by


PREVALENCE_CSV = "prevalence.csv"


def load_prevalence(path=PREVALENCE_CSV):
    """condition -> (share of women among patients, source). Rows without a number are skipped."""
    out = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                v = (row.get("female_share_of_patients") or "").strip()
                if v:
                    out[row["condition"].strip().lower()] = (float(v), row.get("source", ""))
    return out


def representation(cond, ncts, prevalence):
    """Share of women among participants in trials open to all sexes, vs share among patients.

    Counts come from structured baseline tables (no LLM). PPR = participants share / patients share;
    below 0.8 is the usual reading of under-representation.
    """
    f = m = 0
    for nct in ncts:
        t = store.get_trial(nct) or {}
        if (t.get("sex") or "").upper() == "ALL" and t.get("female_n") is not None and t.get("male_n") is not None:
            f, m = f + t["female_n"], m + t["male_n"]
    share = f / (f + m) if f + m else None
    if ncts and all(n.startswith("SYN") for n in ncts):
        import fixtures
        pat, src = fixtures.SYNTHETIC_PATIENT_WOMEN.get(cond), "SYNTHETIC placeholder (offline demo)"
    else:
        pat, src = prevalence.get(cond.lower(), (None, "missing: add to prevalence.csv"))
    return {
        "% women among participants (mixed-sex trials)": round(100 * share, 1) if share is not None else None,
        "% women among patients": round(100 * pat, 1) if pat else None,
        "PPR (participants / patients)": round(share / pat, 2) if share is not None and pat else None,
        "patient share source": src,
    }


def gap_map():
    per = {}
    for (cond, nct), c in latest_trusted().items():
        per.setdefault(cond, []).append((nct, c))
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    prevalence = load_prevalence()
    out = []
    for cond, pairs in sorted(per.items()):
        ts = [c for _, c in pairs]
        n = len(ts)
        res = [t for t in ts if t.get("sex_stratified_results") not in (None, "NO_RESULTS_POSTED")]
        el = [t for t in ts if "eligibility_exclusion" in t]
        out.append({
            "condition": cond, "trials_audited": n, "with_results_posted": len(res),
            **representation(cond, [nct for nct, _ in pairs], prevalence),
            "% restricted to one sex": pct(sum(t.get("sex_restriction") in ("FEMALE", "MALE") for t in ts), n),
            "% blanket childbearing exclusion": pct(sum(t.get("eligibility_exclusion") == "BLANKET_EXCLUSION_CHILDBEARING" for t in el), len(el)),
            "% pregnancy/lactation exclusion": pct(sum(t.get("eligibility_exclusion") == "PREGNANCY_LACTATION_EXCLUSION" for t in el), len(el)),
            "% enrollment-by-sex reported (of results-posted)": pct(sum(t.get("enrollment_by_sex") == "REPORTED" for t in res), len(res)),
            "% sex-stratified results found (of results-posted)": pct(sum(t.get("sex_stratified_results") == "STRATIFIED_FOUND" for t in res), len(res)),
            "% results-posted with NO sex-stratified result in record": pct(sum(t.get("sex_stratified_results") == "NOT_FOUND_IN_RECORD" for t in res), len(res)),
        })
    return out


def queue_counts():
    return {r["status"]: r["n"] for r in store.q("SELECT status, COUNT(*) n FROM queue GROUP BY status")}


def write_reports():
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    gm = gap_map()
    if gm:
        with open(os.path.join(config.REPORT_DIR, "gap_map.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(gm[0].keys()))
            w.writeheader()
            w.writerows(gm)
    acc = ""
    if os.path.exists("data/gold_eval.json"):
        g = json.load(open("data/gold_eval.json"))
        acc = f"\nEvaluation vs {g.get('reference_status', 'unspecified')} references using {g.get('backend', 'unspecified')} backend (n={g['n']}): " + \
              ", ".join(f"{k}: {v:.0%}" for k, v in g["accuracy"].items()) + "\n"
    lines = ["# HerEvidence gap map", "",
             "Findings mean **not found in the registry record**, not 'was not done'. Papers may report analyses the "
             "registry lacks, and some pregnancy exclusions have legitimate safety reasons. Quarantined and unverified "
             "verdicts are excluded.", acc, f"Queue status: {queue_counts()}", ""]
    for r in gm:
        lines.append(f"## {r['condition']}")
        lines += [f"- {k}: {v}" for k, v in r.items() if k != "condition"]
        lines.append("")
    open(os.path.join(config.REPORT_DIR, "gap_report.md"), "w").write("\n".join(lines))
    return gm


ADVICE = {
    "ERROR_RATE": "Measured error rate became unacceptable. Batches since the last clean batch were quarantined. Inspect prompts/model, rerun on the quarantined trials, and compare against the gold set before trusting new output.",
    "LOOP": "The agent kept repeating identical calls. Check for malformed model output or a failing endpoint, then `--resume`.",
    "STUCK": "Several batches produced no resolved trials. The remaining trials are likely ambiguous for the current prompt; a human should review them.",
    "TOKEN_BUDGET": "Token budget reached. Raise the cap deliberately or narrow scope, then `--resume`.",
    "COST_BUDGET": "Cost budget reached. Raise the cap deliberately or narrow scope, then `--resume`.",
    "CALL_BUDGET": "Call budget reached. Raise the cap deliberately, then `--resume`.",
    "TIME_LIMIT": "Time limit reached. `--resume` continues from the checkpoint.",
    "EMERGENCY_CAP": "No supervisor was active; only a hard emergency cap stopped this run.",
    "CRASH": "The agent hit an unexpected error. The unfinished batch was quarantined; see reports/ui_run.log for the traceback, fix it, then resume with `--no-ingest`.",
}


def write_handoff(run_id, status, halt, snap):
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    qc = queue_counts()
    nver = store.q("SELECT COUNT(*) n FROM verdicts WHERE run_id=? AND verified=1 AND quarantined=0", (run_id,))[0]["n"]
    nbad = store.q("SELECT COUNT(*) n FROM verdicts WHERE run_id=? AND verified=0", (run_id,))[0]["n"]
    nq = store.q("SELECT COUNT(*) n FROM verdicts WHERE run_id=? AND quarantined=1", (run_id,))[0]["n"]
    nd = store.q("SELECT COUNT(*) n FROM drafts WHERE status='DRAFT'")[0]["n"]
    md = [f"# Handoff report: {run_id}", "", f"**Status:** {status}"]
    if halt:
        md += [f"**Why it stopped:** `{halt.code}`: {halt.reason}", "", f"**What to do:** {ADVICE.get(halt.code, '')}"]
    md += ["", "## Work completed", f"- Verified, trusted verdicts: {nver}", f"- Unverified (rejected by verifier): {nbad}",
           f"- Quarantined (withheld from the gap map): {nq}", f"- Queue: {qc}", f"- Draft requests awaiting human approval: {nd}",
           "", "## Spend and health",
           f"- Tokens: {snap['tokens']:,} | calls: {snap['calls']} | est. cost: ${snap['cost']:.3f} | elapsed: {snap['elapsed']}s",
           f"- Task loops: {snap['task_loops']} | batches with no progress: {snap['no_progress']}"]
    for k, t in snap["trackers"].items():
        md.append(f"- {k} check: {t['errors']}/{t['n']} failures, posterior mean error {t['mean']:.1%}, P(rate>10%) = {t['p_exceeds']:.2f}")
    md += ["", "## Honest limits",
           "- Verification measures agreement and source-grounding; errors shared by both passes are invisible. Use the gold-set accuracy as the real number.",
           "- Registry records can be incomplete relative to published papers."]
    path = os.path.join(config.REPORT_DIR, f"handoff_{run_id}.md")
    open(path, "w").write("\n".join(md))
    return path
