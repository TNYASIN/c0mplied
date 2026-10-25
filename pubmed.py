"""PubMed cross-check: a registry gap may be answered in the trial's own publications.

Linked papers come from two places: PMIDs the registry lists as RESULT/DERIVED references, and a PubMed
search for the NCT ID in the Secondary Source ID field ([si]), where NLM indexes ClinicalTrials.gov IDs.
BACKGROUND references are other people's work and are ignored. Only titles and abstracts are read
(full text is not available for most papers), so a miss means "not in the abstract", nothing more.

Detection is a deterministic sentence match, never an LLM. A match is a LEAD for a human to read,
not proof that sex-specific results exist: abstracts summarize, and the sentence is shown verbatim.

    python pubmed.py NCT00381303       # linked papers and any sex-analysis sentence for one trial
    python pubmed.py --freeze-gold     # snapshot PubMed data for data/real_gold/ into data/real_gold/pubmed.json

Set NCBI_API_KEY for 10 requests/s instead of 3, and NCBI_EMAIL so NCBI can reach you about heavy use.
"""
import json, os, re, sys, time
import xml.etree.ElementTree as ET
import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
LINK_TYPES = ("RESULT", "DERIVED")
_last = [0.0]

SEX_ANALYSIS = re.compile(
    r"\b(sex|gender)[- ](specific|stratified|based|related|differen\w*|subgroups?|interaction)\b|"
    r"\b(by|according to|across|between)\s+(sex|gender|sexes)\b|"
    r"\b(sex|gender)\s+(differences?|subgroups?|interactions?)\b|"
    r"\bsubgroups?\b[^.;]{0,60}\b(sex|gender)\b|"
    r"\b(sex|gender)\b[^.;]{0,40}\b(moderat\w*|modif\w*|interact\w*)\b|"
    r"\b(regardless|irrespective) of (sex|gender)\b|"
    r"\b(women|females?)\b[^.;]{0,80}\bcompared (with|to)\s+(men|males?)\b|"
    r"\b(women|females?|men|males?)\s+than\s+(women|females?|men|males?)\b|"
    r"\b(in|among|for)\s+(women and men|men and women|females and males|males and females)\b[^.;]{0,80}\d|"
    r"\bdiffer\w*\s+between\s+(women and men|men and women|females and males|males and females)\b", re.I)
# Sex as a covariate, matching factor or randomization stratum is not a sex-specific result; nor is a plan.
NOT_ANALYSIS = re.compile(
    r"adjust\w*\s+for[^.;]{0,60}\b(sex|gender)\b|\b(sex|gender)[- ]matched\b|matched\s+(for|by|on)[^.;]{0,30}\b(sex|gender)\b|"
    r"randomi[sz]ation\s+(was\s+)?stratified\s+by[^.;]{0,30}\b(sex|gender)\b|"
    r"\b(is|was|were) designed to\b|\bwe (aim|aimed|sought|plan|planned|will)\b|\bwill be (analy|assess|evaluat|examin)", re.I)
# Structured-abstract sections that state aims and methods, not findings.
INTENT_SECTIONS = {"BACKGROUND", "INTRODUCTION", "OBJECTIVE", "OBJECTIVES", "AIM", "AIMS", "PURPOSE", "CONTEXT",
                   "IMPORTANCE", "DESIGN", "METHOD", "METHODS", "SETTING", "PATIENTS", "PARTICIPANTS"}


def _get(path, **params):
    params.update(tool="herevidence", **{k: v for k, v in (("email", os.environ.get("NCBI_EMAIL")),
                                                           ("api_key", os.environ.get("NCBI_API_KEY"))) if v})
    gap = 0.11 if params.get("api_key") else 0.34      # NCBI rate limit: 10/s with a key, 3/s without
    time.sleep(max(0.0, _last[0] + gap - time.monotonic()))
    for attempt in range(3):
        try:
            _last[0] = time.monotonic()
            r = requests.get(f"{EUTILS}/{path}", params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def search_pmids(nct):
    r = _get("esearch.fcgi", db="pubmed", term=f"{nct}[si]", retmode="json", retmax=50)
    return r.json().get("esearchresult", {}).get("idlist", [])


def _text(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def parse(xml):
    out = []
    for a in ET.fromstring(xml).iter("PubmedArticle"):
        mc = a.find("MedlineCitation")
        art = mc.find("Article")
        parts = []
        for t in art.findall("Abstract/AbstractText"):
            label, body = t.get("Label"), _text(t)
            parts.append(f"{label}: {body}" if label else body)
        date = art.find("Journal/JournalIssue/PubDate")
        year = _text(date.find("Year")) if date is not None and date.find("Year") is not None else _text(
            date.find("MedlineDate") if date is not None else None)[:4]
        doi = next((_text(e) for e in art.findall("ELocationID") if e.get("EIdType") == "doi"), "")
        out.append({"pmid": _text(mc.find("PMID")), "title": _text(art.find("ArticleTitle")),
                    "journal": _text(art.find("Journal/Title")), "year": year, "doi": doi,
                    "abstract": "\n".join(parts)})
    return out


def fetch(pmids):
    out = []
    for i in range(0, len(pmids), 50):
        out += parse(_get("efetch.fcgi", db="pubmed", id=",".join(pmids[i:i + 50]), retmode="xml").content)
    return out


def lookup(trial, sup=None):
    """(status, links, publications) for one trial. status: OK, or ERROR if PubMed could not be reached."""
    nct = trial["nct_id"]
    links = {r["pmid"]: f"registry {r['type']} reference" for r in trial.get("references") or []
             if r.get("pmid") and r.get("type") in LINK_TYPES}
    try:
        if sup:
            sup.check_budget()
            sup.note_fetch(f"pubmed|{nct}")
        for pmid in search_pmids(nct):
            links.setdefault(pmid, "PubMed [si] NCT link")
        pubs = fetch(list(links)) if links else []
    except (requests.RequestException, ET.ParseError):
        return "ERROR", [], []
    return "OK", [{"pmid": p, "link": l} for p, l in links.items()], pubs


def link_trial(trial, sup=None):
    import store
    status, links, pubs = lookup(trial, sup)
    store.save_publications(trial["nct_id"], status, links, pubs, source="pubmed")
    return status, len(pubs)


def sentences(pub):
    """[(section, sentence)]: section is TITLE, a structured-abstract label such as RESULTS, or '' if unlabeled."""
    out = [("TITLE", pub["title"])] if pub.get("title") else []
    for part in (pub.get("abstract") or "").split("\n"):
        m = re.match(r"([A-Z][A-Z ,&/-]{2,40}):\s+", part)
        section, body = (m.group(1).strip(), part[m.end():]) if m else ("", part)
        out += [(section, s.strip()) for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", body) if s.strip()]
    return out


def find_sex_analysis(pub):
    """The best title/abstract sentence that reports a finding by sex, verbatim; '' if none.

    Sentences from aim/method sections and statements of intent are skipped (a plan to analyze by sex is not
    a result). Findings with numbers rank first, then other findings, then the title.
    """
    hits = [(sec, s) for sec, s in sentences(pub)
            if sec not in INTENT_SECTIONS and SEX_ANALYSIS.search(s) and not NOT_ANALYSIS.search(s)]
    hits.sort(key=lambda h: (h[0] == "TITLE", not re.search(r"\d", h[1])))
    return hits[0][1] if hits else ""


GOLD_SNAPSHOT = "data/real_gold/pubmed.json"


def freeze_gold(path=GOLD_SNAPSHOT):
    """Snapshot linked-publication data for the frozen gold records, so evaluation and tests run offline."""
    from fetch_trials import normalize_trial
    manifest = json.load(open("data/real_gold/manifest.json", encoding="utf-8"))
    snap = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "query": "RESULT/DERIVED refs + {nct}[si]",
            "trials": {}, "publications": {}}
    for rec in manifest["records"]:
        t = normalize_trial(json.load(open(rec["path"], encoding="utf-8")))
        status, links, pubs = lookup(t)
        snap["trials"][t["nct_id"]] = {"status": status, "links": links}
        snap["publications"].update({p["pmid"]: p for p in pubs})
        print(f"{t['nct_id']}: {status}, {len(pubs)} linked publication(s)")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1, ensure_ascii=False)
    print(f"wrote {path}")


def load_gold(nct, path=GOLD_SNAPSHOT):
    """(status, publications) for a frozen gold record, or (None, []) if no snapshot exists."""
    if not os.path.exists(path):
        return None, []
    snap = json.load(open(path, encoding="utf-8"))
    t = snap["trials"].get(nct)
    if not t:
        return None, []
    return t["status"], [{**snap["publications"][l["pmid"]], "link": l["link"]}
                         for l in t["links"] if l["pmid"] in snap["publications"]]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--freeze-gold":
        freeze_gold()
    elif len(sys.argv) > 1:
        status, links, pubs = lookup({"nct_id": sys.argv[1]})
        print(status, links)
        for p in pubs:
            print(f"- PMID {p['pmid']} ({p['year']}) {p['title']}\n    sex analysis: {find_sex_analysis(p) or '(none in title/abstract)'}")
    else:
        print(__doc__)
