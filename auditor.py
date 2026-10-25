"""Per-trial audit. Rules first; the LLM is only used where rules cannot decide."""
import re
from rules import elig_candidates, strat_payload_lines
from pubmed import find_sex_analysis

NAIVE_RETRY_CAP = 100_000   # the "naive agent" retries forever; the supervisor is the safety net


def V(nct, chk, label, quote, conf, method):
    return {"nct_id": nct, "chk": chk, "label": label, "quote": quote, "confidence": conf,
            "method": method, "verified": 0, "verify_note": ""}


def _llm_json(llm, task, payload):
    for _ in range(NAIVE_RETRY_CAP):
        r = llm.call(task, payload, "primary")
        if r is not None:
            return r
    raise RuntimeError("unreachable in practice")


def audit_trial(trial, llm):
    nct, out = trial["nct_id"], []
    sex = (trial.get("sex") or "UNKNOWN").upper()
    out.append(V(nct, "sex_restriction", sex, f"eligibilityModule.sex = {sex}", 1.0, "rule"))

    # A. eligibility language
    cands = elig_candidates(trial.get("eligibility_text"))
    if not (trial.get("eligibility_text") or "").strip():
        out.append(V(nct, "eligibility_exclusion", "UNCLEAR", "", 0.0, "rule"))
    elif not cands:
        out.append(V(nct, "eligibility_exclusion", "NONE", "", 0.9, "rule"))
    else:
        payload = {"nct_id": nct, "text": (trial.get("eligibility_text") or "")[:6000],
                   "candidates": [f"[{s}] {l}" for s, l in cands]}
        r = _llm_json(llm, "eligibility", payload)
        v = V(nct, "eligibility_exclusion", r["label"], r["evidence_quote"], r["confidence"], "llm")
        v["_task"], v["_payload"] = "eligibility", payload
        out.append(v)

    # B. enrollment reported by sex (structural)
    if not trial.get("has_results"):
        out.append(V(nct, "enrollment_by_sex", "NO_RESULTS_POSTED", "", 1.0, "rule"))
    else:
        if trial.get("female_n") is not None or trial.get("male_n") is not None:
            quote = f"baseline sex counts: female={trial.get('female_n')}, male={trial.get('male_n')}"
            out.append(V(nct, "enrollment_by_sex", "REPORTED", quote, 1.0, "rule"))
        else:
            out.append(V(nct, "enrollment_by_sex", "NOT_REPORTED_IN_RECORD", "", 1.0, "rule"))

    # C. sex-stratified outcome results
    if not trial.get("has_results"):
        out.append(V(nct, "sex_stratified_results", "NO_RESULTS_POSTED", "", 1.0, "rule"))
    elif not trial.get("outcome_measures"):
        out.append(V(nct, "sex_stratified_results", "UNCLEAR", "", 0.0, "rule"))
    else:
        proven = []
        for i, measure in enumerate(trial["outcome_measures"], 1):
            values = measure.get("sex_values") or {}
            for female in values.get("female", []):
                male = next((m for m in values.get("male", []) if m.get("match_key") == female.get("match_key")), None)
                if male:
                    proven.append((i, female, male))
        hits, lines = strat_payload_lines(trial)
        if proven:
            i, female, male = proven[0]
            quote = (f"Outcome {i}: female={female['value']} ({female['path']}); "
                     f"male={male['value']} ({male['path']})")
            v = V(nct, "sex_stratified_results", "STRATIFIED_FOUND", quote, 1.0, "structured_rule")
            v["evidence_paths"] = [female["path"], male["path"]]
            out.append(v)
        elif not hits:
            out.append(V(nct, "sex_stratified_results", "NOT_FOUND_IN_RECORD", "", 0.9, "rule"))
        else:
            payload = {"nct_id": nct, "lines": lines}
            r = _llm_json(llm, "stratified", payload)
            v = V(nct, "sex_stratified_results", r["label"], r["evidence_quote"], r["confidence"], "llm")
            if v["label"] == "STRATIFIED_FOUND":
                v["label"], v["quote"], v["confidence"], v["method"] = "UNCLEAR", "", 0.0, "evidence_gate"
                v["verify_note"] = "sex-specific outcome values absent; human review required"
            v["_task"], v["_payload"] = "stratified", payload
            out.append(v)

    # D. linked publications (PubMed titles/abstracts, attached by the caller). Never overrides check C:
    # the registry gap stays a registry gap; a mention is a lead that changes what the draft asks.
    out.append(publication_check(nct, trial.get("pubmed_status"), trial.get("publications") or []))
    return out


def publication_check(nct, status, pubs):
    if status is None or (status == "ERROR" and not pubs):
        return V(nct, "publication_sex_analysis", "NOT_CHECKED", "", 0.0, "rule")
    if not pubs:
        return V(nct, "publication_sex_analysis", "NO_LINKED_PUBLICATION", "", 1.0, "rule")
    for p in pubs:
        sentence = find_sex_analysis(p)
        if sentence:
            v = V(nct, "publication_sex_analysis", "MENTIONED_IN_PUBLICATION", f'PMID {p["pmid"]}: "{sentence}"',
                  0.7, "rule")
            v["pmid"], v["pub_title"], v["sentence"] = p["pmid"], p.get("title", ""), sentence
            return v
    return V(nct, "publication_sex_analysis", "NOT_FOUND_IN_ABSTRACTS",
             "searched PMID " + ", ".join(p["pmid"] for p in pubs), 0.6, "rule")
