"""Read-only, grounded explanations and question answering for stored audits.

This module deliberately does not call an LLM.  The SQLite checkpoint remains the
source of truth and every study-specific answer is assembled from stored trial and
verdict fields.  Synthetic records are opt-in and are always labelled as demo data.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import store


CHECK_NAMES = {
    "sex_restriction": "Who the study says can enroll",
    "eligibility_exclusion": "Pregnancy and childbearing eligibility wording",
    "enrollment_by_sex": "Enrollment reported by sex",
    "sex_stratified_results": "Results reported by sex",
}

SOURCE_PATHS = {
    "sex_restriction": "protocolSection.eligibilityModule.sex",
    "eligibility_exclusion": "protocolSection.eligibilityModule.eligibilityCriteria",
    "enrollment_by_sex": "resultsSection.baselineCharacteristicsModule.measures",
    "sex_stratified_results": "resultsSection.outcomeMeasuresModule.outcomeMeasures",
}

LABEL_NAMES = {
    "ALL": "Open to all sexes",
    "FEMALE": "Female eligibility field",
    "MALE": "Male eligibility field",
    "UNKNOWN": "Eligibility field unavailable",
    "NONE": "No relevant exclusion identified",
    "CONDITIONAL": "Conditional participation wording",
    "PREGNANCY_LACTATION_EXCLUSION": "Pregnancy or lactation exclusion",
    "BLANKET_EXCLUSION_CHILDBEARING": "Possible broad childbearing exclusion",
    "REPORTED": "Reported in the registry record",
    "NOT_REPORTED_IN_RECORD": "Not identified in the registry record checked",
    "STRATIFIED_FOUND": "Sex-stratified result identified",
    "NOT_FOUND_IN_RECORD": "Not identified in the registry record checked",
    "NO_RESULTS_POSTED": "Results not posted",
    "UNCLEAR": "Not assessable automatically",
}


def _iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat().replace("+00:00", "Z")


def _is_synthetic(source, nct_id):
    return source == "synthetic" or str(nct_id).upper().startswith("SYN")


def _source_url(nct_id, synthetic=False):
    if not synthetic and re.fullmatch(r"NCT\d{8}", str(nct_id).upper()):
        return f"https://clinicaltrials.gov/study/{str(nct_id).upper()}"
    return None


def _latest_verdicts(nct_id):
    return store.q(
        "SELECT v.* FROM verdicts v "
        "JOIN (SELECT chk, MAX(id) mid FROM verdicts WHERE nct_id=? GROUP BY chk) m ON v.id=m.mid "
        "ORDER BY v.id",
        (nct_id,),
    )


def _scope_clause(scope):
    if scope == "synthetic":
        return "t.source='synthetic'"
    if scope == "all":
        return "1=1"
    return "t.source!='synthetic'"


def _template(check, label, trial):
    counts = None
    female, male = trial.get("female_n"), trial.get("male_n")
    if female is not None and male is not None:
        counts = f"{female} women/female participants and {male} men/male participants"

    templates = {
        ("sex_restriction", "ALL"): (
            "The registry eligibility field says the study was open to all sexes.",
            "This field helps describe who could enter the study, but it does not show who ultimately enrolled.",
            "Compare this eligibility field with the baseline participant counts when those counts are available.",
        ),
        ("sex_restriction", "FEMALE"): (
            "The registry eligibility field lists female participants.",
            "A single-sex eligibility field changes how representation should be interpreted.",
            "Review the study purpose and protocol before deciding whether the restriction was appropriate.",
        ),
        ("sex_restriction", "MALE"): (
            "The registry eligibility field lists male participants.",
            "A single-sex eligibility field changes how representation should be interpreted.",
            "Review the study purpose and protocol before deciding whether the restriction was appropriate.",
        ),
        ("sex_restriction", "UNKNOWN"): (
            "The enrollment eligibility field was not assessable from the stored record.",
            "Without that field, this audit cannot describe who the registry says could enroll.",
            "Check the current registry record and the full study protocol.",
        ),
        ("eligibility_exclusion", "NONE"): (
            "The audit did not identify pregnancy- or childbearing-related exclusion wording in the registry text checked.",
            "This means the targeted wording was not identified here; it does not prove that no restriction exists elsewhere.",
            "Review the complete eligibility criteria and protocol if this question is important to a decision.",
        ),
        ("eligibility_exclusion", "CONDITIONAL"): (
            "The registry text describes conditions for participation related to pregnancy prevention or testing.",
            "Conditions can affect who is able to participate, but the registry text alone does not show their clinical justification.",
            "A reviewer should compare the wording with the intervention risks and the full protocol.",
        ),
        ("eligibility_exclusion", "PREGNANCY_LACTATION_EXCLUSION"): (
            "The registry text appears to exclude people who are pregnant or breastfeeding.",
            "This may affect participation and can also reflect legitimate safety concerns; this audit does not decide which applies.",
            "A reviewer should inspect the intervention risks, rationale, and full protocol.",
        ),
        ("eligibility_exclusion", "BLANKET_EXCLUSION_CHILDBEARING"): (
            "The audit identified a possible broad exclusion related to childbearing potential.",
            "Broad wording may affect access to a study, but this is a finding for human review—not a judgment of bias or safety.",
            "A reviewer should confirm the exact wording, rationale, and whether narrower safeguards were possible.",
        ),
        ("eligibility_exclusion", "UNCLEAR"): (
            "The eligibility wording was not assessable automatically.",
            "Ambiguous wording should not be converted into a definite claim.",
            "A human reviewer should read the full eligibility section and protocol.",
        ),
        ("enrollment_by_sex", "REPORTED"): (
            "The registry baseline information includes enrollment reported by sex" + (f": {counts}." if counts else "."),
            "Participant counts help readers understand who took part; they are not treatment outcomes.",
            "Compare the counts with the eligible population and inspect whether outcomes were also reported by sex.",
        ),
        ("enrollment_by_sex", "NOT_REPORTED_IN_RECORD"): (
            "Enrollment by sex was not identified in the baseline registry fields checked.",
            "Without these counts, readers cannot assess participant distribution from this record alone.",
            "Check the full results record, protocol, and publications for participant details.",
        ),
        ("enrollment_by_sex", "NO_RESULTS_POSTED"): (
            "Results were not posted in the registry information checked, so baseline enrollment by sex was not available there.",
            "This is different from saying the study had no results or that sex was not recorded elsewhere.",
            "Check the current registry record and linked publications for newly posted results.",
        ),
        ("sex_stratified_results", "STRATIFIED_FOUND"): (
            "The audit identified a posted outcome reported separately by sex.",
            "Separate reporting can help researchers inspect whether observed outcomes differ across groups; it does not by itself establish a meaningful difference.",
            "Review the outcome definition, group sizes, uncertainty, and statistical analysis.",
        ),
        ("sex_stratified_results", "NOT_FOUND_IN_RECORD"): (
            "Posted results were present, but a result reported separately by sex was not identified in the registry fields checked.",
            "This limits what can be learned from the registry record. It does not mean the analysis was never done or published elsewhere.",
            "Check linked publications and the protocol, then ask whether a prespecified subgroup analysis exists.",
        ),
        ("sex_stratified_results", "NO_RESULTS_POSTED"): (
            "Results were not posted in the registry information checked.",
            "Without posted results, this audit cannot assess whether outcomes were reported separately by sex.",
            "Check the current registry record and linked publications, and review reporting timelines.",
        ),
        ("sex_stratified_results", "UNCLEAR"): (
            "The available result wording was not assessable automatically.",
            "Ambiguous evidence should not be presented as a confirmed reporting gap or confirmed result.",
            "A human reviewer should inspect the full outcome tables and analyses.",
        ),
    }
    return templates.get(
        (check, label),
        (
            "This stored classification does not yet have a plain-language template.",
            "The original audit metadata remains available for review.",
            "A human reviewer should inspect the source record before drawing a conclusion.",
        ),
    )


def explain_verdict(verdict, trial):
    check, label = verdict["chk"], verdict["label"]
    trusted = bool(verdict["verified"]) and not bool(verdict["quarantined"])
    what, why, next_step = _template(check, label, trial)
    if not trusted:
        what = "This automated finding was withheld and should not be treated as a verified finding. " + what
    quote = verdict.get("quote") or ""
    if quote:
        support = "The stored audit cites the source excerpt shown below."
    elif label == "NO_RESULTS_POSTED":
        support = "The finding comes from the stored structured results-availability field; no excerpt is available."
    elif label in ("NOT_FOUND_IN_RECORD", "NOT_REPORTED_IN_RECORD", "NONE"):
        support = "This is an absence finding from the registry fields checked, so there is no positive excerpt to quote."
    else:
        support = "No source excerpt was stored for this finding."
    if not trusted:
        support += " Verification did not clear this finding for use as trusted evidence."

    return {
        "check": check,
        "check_name": CHECK_NAMES.get(check, check.replace("_", " ").title()),
        "label": label,
        "label_name": LABEL_NAMES.get(label, label.replace("_", " ").title()),
        "trusted": trusted,
        "beginner": {
            "what": what,
            "why": why,
            "evidence": support,
            "next": next_step,
        },
        "researcher": {
            "classification": label,
            "source_path": SOURCE_PATHS.get(check, "Stored normalized trial record"),
            "original_excerpt": quote,
            "method": verdict.get("method"),
            "confidence": verdict.get("confidence"),
            "run_id": verdict.get("run_id"),
            "batch": verdict.get("batch"),
            "verified": bool(verdict.get("verified")),
            "verification_outcome": verdict.get("verify_note") or "No verification note stored",
            "quarantined": bool(verdict.get("quarantined")),
            "recorded_at": _iso(verdict.get("ts")),
        },
    }


def study_detail(nct_id):
    rows = store.q("SELECT json, source FROM trials WHERE nct_id=?", (nct_id,))
    if not rows:
        return None
    import json

    trial = json.loads(rows[0]["json"])
    source = rows[0]["source"]
    synthetic = _is_synthetic(source, nct_id)
    findings = [explain_verdict(v, trial) for v in _latest_verdicts(nct_id)]
    female, male = trial.get("female_n"), trial.get("male_n")
    distribution = None
    if female is not None and male is not None and female + male > 0:
        distribution = {
            "female": female,
            "male": male,
            "denominator": female + male,
            "note": "Structured baseline enrollment counts; these are participants, not treatment outcomes.",
        }
    queue = store.q("SELECT status, attempts, run_id, updated FROM queue WHERE nct_id=?", (nct_id,))
    return {
        "nct_id": nct_id,
        "title": trial.get("title") or "Untitled study",
        "condition": trial.get("condition") or "Condition not recorded",
        "study_status": trial.get("status") or "Unknown",
        "sex": trial.get("sex") or "UNKNOWN",
        "has_results": bool(trial.get("has_results")),
        "eligibility_text": trial.get("eligibility_text") or "",
        "source": source,
        "synthetic": synthetic,
        "source_url": _source_url(nct_id, synthetic),
        "data_notice": (
            "Synthetic demo record. It is not a real clinical study and must not be cited as research."
            if synthetic
            else "Stored ClinicalTrials.gov record. Confirm time-sensitive details at the source link."
        ),
        "distribution": distribution,
        "queue": queue[0] if queue else None,
        "findings": findings,
    }


def _study_summary(row):
    detail = study_detail(row["nct_id"])
    if not detail or not detail["findings"]:
        return None
    findings = {f["check"]: f for f in detail["findings"]}
    trusted = [f for f in detail["findings"] if f["trusted"]]
    needs_review = any(not f["trusted"] for f in detail["findings"])
    needs_review = needs_review or (detail.get("queue") or {}).get("status") in ("review", "quarantined", "failed", "retry")
    return {
        "nct_id": detail["nct_id"],
        "title": detail["title"],
        "condition": detail["condition"],
        "study_status": detail["study_status"],
        "source": detail["source"],
        "synthetic": detail["synthetic"],
        "source_url": detail["source_url"],
        "data_notice": detail["data_notice"],
        "trusted_findings": len(trusted),
        "total_findings": len(detail["findings"]),
        "needs_review": needs_review,
        "queue_status": (detail.get("queue") or {}).get("status"),
        "has_participant_distribution": detail["distribution"] is not None,
        "findings": {
            key: {"label": value["label"], "label_name": value["label_name"], "trusted": value["trusted"]}
            for key, value in findings.items()
        },
    }


def studies(scope="real"):
    store.init()
    rows = store.q(
        f"SELECT t.nct_id FROM trials t WHERE {_scope_clause(scope)} "
        "AND EXISTS (SELECT 1 FROM verdicts v WHERE v.nct_id=t.nct_id) ORDER BY t.fetched_at DESC, t.nct_id"
    )
    return [s for s in (_study_summary(r) for r in rows) if s]


def _trusted_label(study, check):
    finding = study["findings"].get(check)
    return finding["label"] if finding and finding["trusted"] else None


def overview(scope="real"):
    items = studies(scope)
    conditions = {}
    for study in items:
        trusted_any = bool(study["trusted_findings"])
        cond = conditions.setdefault(
            study["condition"],
            {"condition": study["condition"], "checked": 0, "results_not_posted": 0, "reporting_gaps": 0,
             "enrollment_reported": 0, "participant_distributions": 0},
        )
        if trusted_any:
            cond["checked"] += 1
        strat = _trusted_label(study, "sex_stratified_results")
        enroll = _trusted_label(study, "enrollment_by_sex")
        cond["results_not_posted"] += strat == "NO_RESULTS_POSTED"
        cond["reporting_gaps"] += strat == "NOT_FOUND_IN_RECORD"
        cond["enrollment_reported"] += enroll == "REPORTED"
        cond["participant_distributions"] += study["has_participant_distribution"] and enroll == "REPORTED"
    return {
        "scope": scope,
        "synthetic": scope == "synthetic",
        "records": len(items),
        "trusted_records": sum(bool(s["trusted_findings"]) for s in items),
        "results_not_posted": sum(_trusted_label(s, "sex_stratified_results") == "NO_RESULTS_POSTED" for s in items),
        "reporting_gaps": sum(_trusted_label(s, "sex_stratified_results") == "NOT_FOUND_IN_RECORD" for s in items),
        "needs_review": sum(s["needs_review"] for s in items),
        "participant_distributions": sum(s["has_participant_distribution"] for s in items),
        "conditions": sorted(conditions.values(), key=lambda x: (-x["reporting_gaps"], -x["results_not_posted"], x["condition"])),
        "denominator_note": "Counts use the verified, non-quarantined study findings in this view.",
    }


def _reference(study):
    return {
        "nct_id": study["nct_id"],
        "title": study["title"],
        "url": study["source_url"],
        "synthetic": study["synthetic"],
    }


def _answer_result(answer, checked, refs, intent, synthetic, scope_note=None):
    return {
        "answer": answer,
        "intent": intent,
        "records_checked": [s["nct_id"] for s in checked],
        "references": [_reference(s) for s in refs],
        "synthetic": synthetic,
        "scope_note": scope_note or (
            "Synthetic demo records were checked; these are not real clinical studies."
            if synthetic
            else "Only verified, non-quarantined findings from stored real registry records were used for factual claims."
        ),
    }


def _join_ids(items, limit=8):
    ids = [s["nct_id"] for s in items]
    shown = ", ".join(ids[:limit])
    if len(ids) > limit:
        shown += f", and {len(ids) - limit} more"
    return shown


def answer(question, nct_id=None, scope="real"):
    """Answer the supported question set using only stored, structured evidence."""
    q = " ".join((question or "").lower().split())
    synthetic = scope == "synthetic"
    items = studies(scope)
    selected = next((s for s in items if s["nct_id"] == nct_id), None)

    if nct_id and not selected:
        detail = study_detail(nct_id)
        if detail and detail["synthetic"] != synthetic:
            return _answer_result(
                "That selected study is outside the current data view. Switch to the matching real or synthetic view and try again.",
                [], [], "scope_mismatch", synthetic,
            )

    if "more review" in q or "need review" in q:
        hits = [s for s in items if s["needs_review"]]
        if hits:
            answer_text = (
                f"{len(hits)} record{'s' if len(hits) != 1 else ''} need human or workflow review: {_join_ids(hits)}. "
                "This is an operational review status, not a verified claim that a study is biased, discriminatory, or unsafe."
            )
        else:
            answer_text = "No records in this view currently carry a human-review, retry, failed, quarantined, or unverified status."
        return _answer_result(
            answer_text, items, hits, "needs_review", synthetic,
            ("Synthetic demo workflow statuses were checked; these are not real clinical studies."
             if synthetic else
             "Operational queue and verification statuses were checked. Listed records are not presented as verified clinical findings."),
        )

    if ("posted results" in q and ("don't" in q or "do not" in q or "no " in q or "without" in q)) or "results not posted" in q:
        hits = [s for s in items if _trusted_label(s, "sex_stratified_results") == "NO_RESULTS_POSTED"]
        if hits:
            answer_text = (
                f"Results were not posted in the registry information checked for {len(hits)} verified record"
                f"{'s' if len(hits) != 1 else ''}: {_join_ids(hits)}. This does not mean results do not exist elsewhere."
            )
        else:
            answer_text = "No verified record in this view is classified as ‘results not posted.’"
        return _answer_result(answer_text, items, hits, "results_not_posted", synthetic)

    if "enrollment" in q and ("sex" in q or "women" in q or "female" in q):
        reported = [s for s in items if _trusted_label(s, "enrollment_by_sex") == "REPORTED"]
        missing = [s for s in items if _trusted_label(s, "enrollment_by_sex") == "NOT_REPORTED_IN_RECORD"]
        no_results = [s for s in items if _trusted_label(s, "enrollment_by_sex") == "NO_RESULTS_POSTED"]
        answer_text = (
            f"Among the verified records checked, {len(reported)} report enrollment by sex, "
            f"{len(missing)} do not have it identified in the baseline registry fields checked, and "
            f"{len(no_results)} have no posted results in the registry information checked. "
            "These are reporting categories, not treatment outcomes."
        )
        return _answer_result(answer_text, items, reported + missing + no_results, "enrollment_by_sex", synthetic)

    if ("explain" in q and ("gap" in q or "study" in q or "finding" in q)) or (selected and "reporting" in q):
        if not selected:
            return _answer_result(
                "Select a study first so I can explain its stored reporting finding without guessing.",
                items, [], "selected_study_gap", synthetic,
            )
        detail = study_detail(selected["nct_id"])
        candidates = [f for f in detail["findings"] if f["check"] in ("sex_stratified_results", "enrollment_by_sex") and f["trusted"]]
        if not candidates:
            answer_text = "This study does not have a verified, non-quarantined reporting finding available to explain."
            refs = []
        else:
            finding = next((f for f in candidates if f["check"] == "sex_stratified_results"), candidates[0])
            b = finding["beginner"]
            answer_text = f"{b['what']} {b['why']} Next: {b['next']}"
            refs = [selected]
        return _answer_result(answer_text, [selected], refs, "selected_study_gap", synthetic)

    if "why" in q and ("reporting" in q or "question matter" in q or "matter" in q):
        return _answer_result(
            "Clear reporting helps readers see who participated and whether results were presented separately by sex. "
            "A registry gap limits what can be assessed from that record, but it is not proof that an analysis was never done, "
            "nor is it a judgment that a study was biased or unsafe.",
            [], [], "why_reporting_matters", synthetic,
            "This educational answer does not make a factual claim about a particular study record.",
        )

    if "investigate next" in q or "what should" in q and "next" in q:
        target = [selected] if selected else [
            s for s in items if _trusted_label(s, "sex_stratified_results") in ("NOT_FOUND_IN_RECORD", "NO_RESULTS_POSTED")
            or _trusted_label(s, "enrollment_by_sex") == "NOT_REPORTED_IN_RECORD"
        ]
        if target:
            answer_text = (
                f"For {_join_ids(target)}, researchers could check the current registry record, linked publications, and the full protocol; "
                "confirm participant counts and denominators; and determine whether sex-specific analyses were prespecified or reported elsewhere. "
                "Any clinical interpretation still requires domain review."
            )
        else:
            answer_text = "No verified reporting-gap record is available in this view. Select a study or run an audit before planning follow-up."
        return _answer_result(answer_text, items if not selected else [selected], target, "investigate_next", synthetic)

    return _answer_result(
        "I can answer questions about records needing review, missing posted results, enrollment reporting by sex, a selected study’s reporting gap, "
        "why the reporting question matters, and what to investigate next. I could not map this question to stored evidence, so I won’t guess.",
        items, [], "unknown", synthetic,
    )

