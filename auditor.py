"""Per-trial audit. Rules first; the LLM is only used where rules cannot decide."""
import re
from rules import elig_candidates, strat_payload_lines

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
    if not cands:
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
        hit = [b for b in trial.get("baseline_measures") or [] if re.search(r"\b(sex|gender)\b", b.get("title", ""), re.I)]
        if hit:
            out.append(V(nct, "enrollment_by_sex", "REPORTED", hit[0]["title"], 1.0, "rule"))
        else:
            out.append(V(nct, "enrollment_by_sex", "NOT_REPORTED_IN_RECORD", "", 1.0, "rule"))

    # C. sex-stratified outcome results
    if not trial.get("has_results"):
        out.append(V(nct, "sex_stratified_results", "NO_RESULTS_POSTED", "", 1.0, "rule"))
    else:
        hits, lines = strat_payload_lines(trial)
        if not hits:
            out.append(V(nct, "sex_stratified_results", "NOT_FOUND_IN_RECORD", "", 0.9, "rule"))
        else:
            payload = {"nct_id": nct, "lines": lines}
            r = _llm_json(llm, "stratified", payload)
            v = V(nct, "sex_stratified_results", r["label"], r["evidence_quote"], r["confidence"], "llm")
            v["_task"], v["_payload"] = "stratified", payload
            out.append(v)
    return out
