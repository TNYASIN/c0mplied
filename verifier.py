"""Two-level verification. Level A: quote grounding. Level B: independent sampled re-check."""
from rules import norm, NEEDS_QUOTE, results_text


def source_text(chk, trial):
    return trial.get("eligibility_text") or "" if chk == "eligibility_exclusion" else results_text(trial)


def verify(v, trial, llm, do_recheck, sup):
    if v["method"] != "llm":
        v["verified"], v["verify_note"] = 1, "rule-based (deterministic)"
        return v
    notes, grounded = [], True
    if v["label"] in NEEDS_QUOTE:
        q = norm(v["quote"])
        grounded = bool(q) and q in norm(source_text(v["chk"], trial))
        sup.observe("grounding", not grounded)
        notes.append("quote found in source" if grounded else "QUOTE NOT IN SOURCE (fabricated or paraphrased)")
    else:
        notes.append("no quote required")
    agree = None
    if v["label"] == "UNCLEAR":
        notes.append("abstained (UNCLEAR): sent to retry/human review, not counted as an error")
    elif do_recheck and grounded:
        r = llm.call(v["_task"], v["_payload"], "recheck")
        if r is None:
            notes.append("recheck inconclusive")
        else:
            agree = r["label"] == v["label"]
            sup.observe("recheck", not agree)
            notes.append("independent recheck agrees" if agree else
                         f"RECHECK DISAGREES (primary={v['label']}, recheck={r['label']})")
    v["verified"] = int(grounded and agree is not False)
    v["verify_note"] = "; ".join(notes)
    return v
