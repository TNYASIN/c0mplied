"""Approval-gated draft requests. NOTHING is ever sent without a human approving it."""
import sys, time
import store, notify

TEMPLATES = {
    "sex_stratified_results": (
        "Clarification request: sex-specific outcome reporting ({nct})",
        "Dear Research Team,\n\nWe are reviewing publicly available registry records to understand how "
        "completely sex-specific outcomes are reported. In the registry results for {nct} ({title}) we could "
        "not identify an outcome analysis reported separately by sex.\n\nCould you clarify whether such an "
        "analysis was conducted and, if so, where it is available?\n\nRecord: {link}\n\n"
        "Note: this reflects only what is visible in the registry record; analyses may exist elsewhere.\n\n"
        "Thank you,\nHerEvidence Research Audit (draft pending human approval)"),
    "enrollment_by_sex": (
        "Clarification request: enrollment by sex ({nct})",
        "Dear Research Team,\n\nIn the registry results for {nct} ({title}) we could not find baseline "
        "enrollment broken down by sex. Could you clarify whether this information exists and where it can "
        "be found?\n\nRecord: {link}\n\nThank you,\nHerEvidence Research Audit (draft pending human approval)"),
}


def link(trial):
    n = trial["nct_id"]
    return f"https://clinicaltrials.gov/study/{n}" if n.startswith("NCT") else f"(synthetic record {n}, no public page)"


def recipient(trial):
    """The record's results point of contact, with the email shown by domain only (safe to project on stage)."""
    if not trial or not trial["nct_id"].startswith("NCT"):
        return {"status": "synthetic", "label": "Synthetic record: no real recipient"}
    c = trial.get("contact")
    if c is None and "contact" not in trial:
        return {"status": "unknown", "label": "Re-fetch this trial to look up its contact"}
    who = ", ".join(x for x in ((c or {}).get("title"), (c or {}).get("organization")) if x)
    email = (c or {}).get("email", "").strip()
    if not email:
        return {"status": "no_email", "label": f"{who or 'No contact listed'}: no email in record, contact via the sponsor"}
    return {"status": "ok", "label": f"{who} <…@{email.rsplit('@', 1)[-1]}>" if who else f"<…@{email.rsplit('@', 1)[-1]}>"}


def create(trial, kind):
    if store.q("SELECT 1 FROM drafts WHERE nct_id=? AND kind=? AND status IN ('DRAFT','APPROVED')", (trial["nct_id"], kind)):
        return None
    subj, body = TEMPLATES[kind]
    f = dict(nct=trial["nct_id"], title=trial.get("title", ""), link=link(trial))
    return store.x("INSERT INTO drafts(nct_id,kind,subject,body,status,created,updated) VALUES(?,?,?,?,?,?,?)",
                   (trial["nct_id"], kind, subj.format(**f), body.format(**f), "DRAFT", time.time(), time.time()))


def resolve(nct, kind, run_id=None):
    rows = store.q("SELECT id FROM drafts WHERE nct_id=? AND kind=? AND status IN ('DRAFT','APPROVED')", (nct, kind))
    for r in rows:
        store.x("UPDATE drafts SET status='RESOLVED', updated=? WHERE id=?", (time.time(), r["id"]))
        store.log_event(run_id, "gap_closed", f"{nct}: {kind} now found in the registry record; draft marked RESOLVED")
    return len(rows)


def set_status(draft_id, status):
    store.x("UPDATE drafts SET status=?, updated=? WHERE id=?", (status, time.time(), draft_id))
    if status == "APPROVED":
        notify.send(f"Draft {draft_id} approved (SIMULATED send: no email leaves this system in the demo).")


if __name__ == "__main__":
    store.init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for d in store.q("SELECT id,nct_id,kind,status FROM drafts ORDER BY id"):
            print(d)
    elif cmd in ("approve", "reject"):
        set_status(int(sys.argv[2]), "APPROVED" if cmd == "approve" else "REJECTED")
        print(cmd, "ok")
