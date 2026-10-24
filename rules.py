"""Deterministic text rules shared by the auditor, the mock LLM and the verifier."""
import re

ELIG_LABELS = {"BLANKET_EXCLUSION_CHILDBEARING", "PREGNANCY_LACTATION_EXCLUSION",
               "CONDITIONAL", "NONE", "UNCLEAR"}
STRAT_LABELS = {"STRATIFIED_FOUND", "NOT_FOUND_IN_RECORD", "UNCLEAR"}
# Labels that assert something about the text and therefore MUST carry a quote.
NEEDS_QUOTE = {"BLANKET_EXCLUSION_CHILDBEARING", "PREGNANCY_LACTATION_EXCLUSION",
               "CONDITIONAL", "STRATIFIED_FOUND"}

TRIG = re.compile(r"pregnan|lactat|breast-?\s?feed|nursing|child-?bearing|"
                  r"reproductive potential|contracept|women of|woman of", re.I)
SEXWORD = re.compile(r"\b(sex|gender|female|females|male|males|women|woman|men)\b", re.I)
HEAD_EX = re.compile(r"^\s*(key\s+)?exclusion criteria\s*:?\s*", re.I)
HEAD_IN = re.compile(r"^\s*(key\s+)?inclusion criteria\s*:?\s*", re.I)


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[*\u2022\"'`]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def elig_lines(text):
    sec = "inclusion"
    for raw in (text or "").splitlines():
        line = raw.strip(" \t-\u2022*")
        if not line:
            continue
        m = HEAD_EX.match(line)
        if m:
            sec, line = "exclusion", line[m.end():].strip()
        else:
            m = HEAD_IN.match(line)
            if m:
                sec, line = "inclusion", line[m.end():].strip()
        if line:
            yield sec, line[:300]


def elig_candidates(text):
    return [(s, l) for s, l in elig_lines(text) if TRIG.search(l)]


def results_lines(trial):
    out = []
    for i, m in enumerate(trial.get("outcome_measures") or [], 1):
        for kind in ("title", "description"):
            if m.get(kind):
                out.append((i, kind, m[kind][:400]))
        for kind, key in (("group", "groups"), ("class", "classes"),
                          ("category", "categories"), ("analysis", "analyses")):
            for t in m.get(key) or []:
                out.append((i, kind, str(t)[:400]))
    return out


def line_str(t):
    return f"Outcome {t[0]} {t[1]}: {t[2]}"


def strat_payload_lines(trial):
    """Outcomes that mention sex/gender words at all -> only these go to the LLM."""
    lines = results_lines(trial)
    hit = {i for i, _, t in lines if SEXWORD.search(t)}
    return hit, [line_str(l) for l in lines if l[0] in hit]


def results_text(trial):
    return "\n".join(line_str(l) for l in results_lines(trial))
