"""Approval-gated draft requests. NOTHING is ever sent without a human approving it.

Each draft is addressed to the best contact the registry record names (contacts.py). Emails are only
ever copied from the record; a draft with no email still names who to reach, for the human to look up.
"""
import sys, time
import store, notify, contacts

TEMPLATES = {
    "sex_stratified_results": (
        "Clarification request: sex-specific outcome reporting ({nct})",
        "Dear Research Team,\n\nWe are reviewing publicly available registry records to understand how "
        "completely sex-specific outcomes are reported. In the registry results for {nct} ({title}) we could "
        "not identify an outcome analysis reported separately by sex.\n\nCould you clarify whether such an "
        "analysis was conducted and, if so, where it is available?\n\nRecord: {link}\n\n"
        "Note: this reflects only what is visible in the registry record; analyses may exist elsewhere.\n\n"
        "Thank you,\nHerEvidence Research Audit (draft pending human approval)"),
    # Used instead of the above when a linked publication's abstract appears to report results by sex.
    "sex_stratified_results_published": (
        "Request: sex-specific results in the registry record ({nct})",
        "Dear Research Team,\n\nWe are reviewing publicly available registry records to understand how "
        "completely sex-specific outcomes are reported. In the registry results for {nct} ({title}) we could "
        "not identify an outcome analysis reported separately by sex. The linked publication PMID {pmid} "
        "({pub_title}) appears to report one:\n\n  \"{sentence}\"\n\nWould you consider adding these results "
        "to the registry record, so that readers of the registry can find them?\n\nRecord: {link}\n"
        "Publication: https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n\n"
        "Note: we read only the publication's abstract; please correct us if we have misread it.\n\n"
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


def create(trial, kind, publication=None):
    """publication: a MENTIONED_IN_PUBLICATION verdict, which switches to the 'please post it' template."""
    if store.q("SELECT 1 FROM drafts WHERE nct_id=? AND kind=? AND status IN ('DRAFT','APPROVED')", (trial["nct_id"], kind)):
        return None
    f = dict(nct=trial["nct_id"], title=trial.get("title", ""), link=link(trial))
    template = kind
    if publication and kind == "sex_stratified_results":
        template = kind + "_published"
        f.update(pmid=publication["pmid"], pub_title=publication.get("pub_title", ""),
                 sentence=publication["sentence"])
    subj, body = TEMPLATES[template]
    to = contacts.recipient(trial.get("contacts")) or {}
    return store.x("INSERT INTO drafts(nct_id,kind,subject,body,status,created,updated,to_name,to_org,to_email,to_role,to_source) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (trial["nct_id"], kind, subj.format(**f), body.format(**f), "DRAFT", time.time(), time.time(),
                    to.get("name", ""), to.get("organization", ""), to.get("email", ""), to.get("role", ""),
                    to.get("source_path", "")))


def recipient_line(d):
    """One line for a human: who this draft goes to, or why there is no address yet."""
    who = ", ".join(filter(None, [d.get("to_name"), d.get("to_org")])) or "no contact named in the record"
    role = f" ({d['to_role']})" if d.get("to_role") else ""
    if d.get("to_email"):
        return f"To: {who}{role} <{d['to_email']}>"
    return f"To: {who}{role}. No email in the registry record; find one before sending."


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
        for d in store.q("SELECT * FROM drafts ORDER BY id"):
            print(f"{d['id']:>4} {d['nct_id']} {d['kind']:<24} {d['status']:<9} {recipient_line(d)}")
    elif cmd in ("approve", "reject"):
        set_status(int(sys.argv[2]), "APPROVED" if cmd == "approve" else "REJECTED")
        print(cmd, "ok")
