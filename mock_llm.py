"""Offline stand-in for the LLM so the whole system runs, and demos reliably, without an API key.

Primary and recheck use DIFFERENT logic on purpose (so the recheck is a genuine second
opinion). `quality` lets scenarios sabotage the primary on demand:
  degraded -> fabricated quotes, flipped labels, wrong categories
  garbage  -> non-JSON prose (forces the naive retry loop the supervisor must catch)
  unclear  -> always UNCLEAR (forces the 'stuck' condition)
"""
import re, json, random
from rules import elig_candidates, NEEDS_QUOTE

DEGRADE_P = 0.6
FLAGS = ["BLANKET_EXCLUSION_CHILDBEARING", "PREGNANCY_LACTATION_EXCLUSION", "CONDITIONAL"]
RANK = {"BLANKET_EXCLUSION_CHILDBEARING": 3, "PREGNANCY_LACTATION_EXCLUSION": 2, "CONDITIONAL": 1}
FAB_ELIG = "Pregnant women and women of childbearing potential are not eligible for enrollment."
FAB_STRAT = "Efficacy outcomes were analyzed separately for female and male participants."
BYSEX = re.compile(r"\b(by|per|according to|stratified by)\s+(sex|gender)\b|"
                   r"\b(sex|gender)[- ](specific|subgroup|stratified)|\b(sex|gender)\s+subgroup", re.I)
ALT = re.compile(r"(sex|gender)[^.]{0,30}(subgroup|stratif|separately|specific)|"
                 r"(subgroup|stratif|separately)[^.]{0,30}(sex|gender)", re.I)


def _best(found):
    return max(found, key=lambda f: RANK[f[0]]) if found else ("NONE", "")


def primary_elig(text):
    found = []
    for sec, line in elig_candidates(text):
        l = line.lower()
        cond = re.search(r"contracept|must|agree|negative|willing|use of|effective", l)
        if re.search(r"child-?bearing|reproductive potential", l):
            found.append(("CONDITIONAL" if (cond or sec == "inclusion") else "BLANKET_EXCLUSION_CHILDBEARING", line))
        elif re.search(r"pregnan|lactat|breast-?\s?feed|nursing (mother|women)", l):
            found.append(("CONDITIONAL" if (cond or sec == "inclusion") else "PREGNANCY_LACTATION_EXCLUSION", line))
        elif "contracept" in l:
            found.append(("CONDITIONAL", line))
    return _best(found)


def recheck_elig(text):
    found = []
    for sec, line in elig_candidates(text):
        l = line.lower()
        restrictive = sec == "exclusion" or bool(re.search(r"exclud|not eligible|ineligible", l))
        conditional = bool(re.search(r"must|agree|contracept|negative|willing|effective", l))
        child = bool(re.search(r"child-?bearing|reproductive potential", l))
        preg = bool(re.search(r"pregnan|lactat|breast|nursing (mother|women)", l))
        if not (child or preg):
            continue
        if restrictive and not conditional:
            found.append(("BLANKET_EXCLUSION_CHILDBEARING" if child else "PREGNANCY_LACTATION_EXCLUSION", line))
        else:
            found.append(("CONDITIONAL", line))
    return _best(found)


def _parse(lines):
    out = []
    for s in lines:
        m = re.match(r"Outcome (\d+) (\w+): (.*)$", s)
        if m:
            out.append((int(m[1]), m[2], m[3]))
    return out


def primary_strat(lines):
    items = _parse(lines)
    for i, k, t in items:
        if k in ("title", "description", "analysis") and BYSEX.search(t):
            return "STRATIFIED_FOUND", t
    cats = {}
    for i, k, t in items:
        if k in ("class", "category"):
            cats.setdefault(i, set()).add(t.lower())
    for i, s in cats.items():
        if any("female" in x or "women" in x for x in s) and any(re.fullmatch(r"male|men|man", x) for x in s):
            title = [t for j, k, t in items if j == i and k == "title"]
            return "STRATIFIED_FOUND", title[0] if title else ""
    return "NOT_FOUND_IN_RECORD", ""


def recheck_strat(lines):
    items = _parse(lines)
    for idx in sorted({i for i, _, _ in items}):
        mine = [(k, t) for i, k, t in items if i == idx]
        cat = [t.lower() for k, t in mine if k in ("class", "category")]
        title = next((t for k, t in mine if k == "title"), "")
        if any(re.search(r"\bfemale|\bwomen", c) for c in cat) and any(re.fullmatch(r"male|men", c) for c in cat):
            return "STRATIFIED_FOUND", title
        for k, t in mine:
            if k in ("title", "description", "analysis") and ALT.search(t):
                return "STRATIFIED_FOUND", t
    return "NOT_FOUND_IN_RECORD", ""


def degrade(kind, label, quote, rng):
    mode = rng.choice(["fabricate", "flip", "wrongcat"])
    needs = label in NEEDS_QUOTE
    if kind == "eligibility":
        if mode == "fabricate":
            return rng.choice(FLAGS), FAB_ELIG
        if mode == "flip":
            return ("NONE", "") if needs else ("BLANKET_EXCLUSION_CHILDBEARING", FAB_ELIG)
        other = [f for f in FLAGS if f != label]
        return (rng.choice(other), quote) if needs else ("CONDITIONAL", FAB_ELIG)
    if mode == "fabricate":
        return "STRATIFIED_FOUND", FAB_STRAT
    if mode == "flip":
        return ("NOT_FOUND_IN_RECORD", "") if needs else ("STRATIFIED_FOUND", FAB_STRAT)
    return "UNCLEAR", ""


class MockBackend:
    name = "mock"

    def complete(self, task, payload, variant, quality):
        rng = random.Random(f"{payload['nct_id']}|{task}|{variant}")
        if quality == "garbage" and variant == "primary":
            text = "Sure! I took a careful look at this trial and, overall, it looks fine to me."
        elif quality == "unclear" and variant == "primary":
            text = json.dumps({"label": "UNCLEAR", "evidence_quote": "", "confidence": 0.3})
        else:
            if task == "eligibility":
                fn = primary_elig if variant == "primary" else recheck_elig
                label, quote = fn(payload["text"])
            else:
                fn = primary_strat if variant == "primary" else recheck_strat
                label, quote = fn(payload["lines"])
            if quality == "degraded" and variant == "primary" and rng.random() < DEGRADE_P:
                label, quote = degrade(task, label, quote, rng)
            text = json.dumps({"label": label, "evidence_quote": quote, "confidence": 0.9,
                               "explanation": "mock"})
        tin = len(json.dumps(payload)) // 4 + 350
        return text, tin, len(text) // 4 + 5
