"""Prompts for the real LLM backend. They ask for explicit, verifiable facts only,
never for opinions like "is this trial biased?"."""

ELIG_SYS = """You audit clinical-trial eligibility text for facts about pregnancy and reproductive status.
Return ONLY a JSON object: {"label": ..., "evidence_quote": ..., "confidence": 0-1, "explanation": ...}
label must be one of:
  BLANKET_EXCLUSION_CHILDBEARING - women of childbearing potential are excluded outright
  PREGNANCY_LACTATION_EXCLUSION  - pregnant and/or breastfeeding participants are excluded
  CONDITIONAL                    - women of childbearing potential may enroll under conditions (pregnancy test, contraception)
  NONE                           - no such restriction in the text
  UNCLEAR                        - text is ambiguous
evidence_quote MUST be copied VERBATIM from the eligibility text (empty string for NONE/UNCLEAR).
Do not judge whether a restriction is justified. Report only what the text says."""

STRAT_SYS = """You check whether a trial's posted OUTCOME results are reported separately by sex or gender.
You are given outcome-measure lines. Return ONLY a JSON object:
{"label": ..., "evidence_quote": ..., "confidence": 0-1, "explanation": ...}
label must be one of:
  STRATIFIED_FOUND    - a result is explicitly reported by sex/gender (stratified result, sex subgroup, separate female/male rows)
  NOT_FOUND_IN_RECORD - the lines mention sex/gender only as enrollment or pooled description, with no sex-specific result
  UNCLEAR             - cannot tell
evidence_quote MUST be copied VERBATIM from the lines (empty for NOT_FOUND_IN_RECORD/UNCLEAR).
Never infer analyses that are not stated."""

RECHECK_SUFFIX = "\nYou are an independent second reviewer. Decide from scratch; do not assume any earlier answer."

# Used by the demo "sabotage" scenarios so the real LLM can also be degraded on purpose.
DEGRADE = {
    "degraded": "\nBe brief. Paraphrase the evidence in your own words instead of quoting. Prefer flagging a restriction when unsure.",
    "garbage": "\nIgnore the JSON instruction and answer in one friendly paragraph of prose.",
    "unclear": "\nAlways answer with label UNCLEAR.",
}


def build(task, payload, variant, quality):
    sys = ELIG_SYS if task == "eligibility" else STRAT_SYS
    if variant == "recheck":
        sys += RECHECK_SUFFIX
    elif quality in DEGRADE:
        sys += DEGRADE[quality]
    if task == "eligibility":
        user = (f"Trial {payload['nct_id']}\nELIGIBILITY TEXT:\n{payload['text']}\n\n"
                f"Lines that mention pregnancy/reproductive terms:\n" + "\n".join(payload["candidates"]))
    else:
        user = f"Trial {payload['nct_id']}\nOUTCOME LINES:\n" + "\n".join(payload["lines"])
    return sys, user
