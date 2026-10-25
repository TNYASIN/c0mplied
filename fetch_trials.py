"""ClinicalTrials.gov API v2 -> normalized trial dicts. Offline mode uses synthetic fixtures.

NOTE: field names below follow the v2 JSON as documented. Print one raw record
(`python fetch_trials.py --raw heart failure`) and confirm before trusting the parsers.
"""
import re, sys, time, requests
import store, fixtures, contacts, pubmed

API = "https://clinicaltrials.gov/api/v2/studies"


def fetch_page(condition, page_size=50, page_token=None):
    params = {"query.cond": condition, "filter.overallStatus": "COMPLETED",
              "aggFilters": "results:with,studyType:int", "pageSize": page_size, "format": "json"}
    if page_token:
        params["pageToken"] = page_token
    for attempt in range(3):
        try:
            r = requests.get(API, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def _titles(items):
    return [i.get("title", "") for i in items or [] if isinstance(i, dict)]


def _int(x):
    try:
        return int(float(str(x).replace(",", "")))
    except (TypeError, ValueError):
        return None


FEMALE = {"female", "females", "women", "woman"}
MALE = {"male", "males", "men", "man"}


def sex_counts(baseline):
    """(female, male) participant counts from the baseline table, or (None, None).

    Uses the 'Total' column when there is one (so arms aren't double-counted), otherwise sums the arms.
    Handles 'Sex: Female, Male' and 'Sex/Gender, Customized'. A single-sex trial that lists only one
    category gets 0 for the other. Structured data only: no LLM touches these numbers.
    """
    groups = baseline.get("groups", []) or []
    total_ids = {g.get("id") for g in groups if (g.get("title") or "").strip().lower() == "total"}
    rows = [m for m in baseline.get("measures", []) or [] if re.search(r"\b(sex|gender)\b", m.get("title", ""), re.I)]
    rows.sort(key=lambda m: "customized" in m.get("title", "").lower())   # standard row first
    for m in rows:
        got = {"f": None, "m": None}
        for cls in m.get("classes", []) or []:
            for cat in cls.get("categories", []) or []:
                label = (cat.get("title") or cls.get("title") or "").strip().lower()
                key = "f" if label in FEMALE else "m" if label in MALE else None
                if not key:
                    continue
                vals = cat.get("measurements", []) or []
                if total_ids:
                    vals = [v for v in vals if v.get("groupId") in total_ids]
                nums = [n for n in (_int(v.get("value")) for v in vals) if n is not None]
                if nums:
                    got[key] = sum(nums)
        if got["f"] is not None or got["m"] is not None:
            return got["f"] or 0, got["m"] or 0
    return None, None


def outcome_sex_values(measure, outcome_index):
    """Return posted outcome values tied to an explicit female/male row or group.

    Denominators and statistical analyses alone are not outcome measurements.
    Paths point back to the unmodified ClinicalTrials.gov v2 record.
    """
    found = {"female": [], "male": []}
    if measure.get("reportingStatus") not in (None, "POSTED"):
        return found
    group_sex = {}
    for group in measure.get("groups", []) or []:
        label = (group.get("title") or "").strip().lower()
        if label in FEMALE | MALE:
            group_sex[group.get("id")] = "female" if label in FEMALE else "male"

    def sex_in(text):
        words = set(re.findall(r"[a-z]+", (text or "").lower()))
        female = bool(words & FEMALE)
        male = bool(words & MALE)
        return "female" if female and not male else "male" if male and not female else None

    for ci, cls in enumerate(measure.get("classes", []) or []):
        for ki, cat in enumerate(cls.get("categories", []) or []):
            row_sex = sex_in(cat.get("title")) or sex_in(cls.get("title"))
            for vi, value in enumerate(cat.get("measurements", []) or []):
                number = value.get("value")
                if number is None or not re.search(r"\d", str(number)):
                    continue
                group = next((g for g in measure.get("groups", []) or [] if g.get("id") == value.get("groupId")), {})
                sex = row_sex or group_sex.get(value.get("groupId"))
                if sex:
                    if row_sex:
                        context = re.sub(r"\b(female|females|women|woman|male|males|men|man)\b", "",
                                         " ".join((cls.get("title") or "", cat.get("title") or "")), flags=re.I)
                        match_key = f"row:{' '.join(context.lower().split())}:{value.get('groupId')}"
                    else:
                        match_key = f"group:{ci}:{ki}"
                    found[sex].append({"value": str(number), "group": group.get("title", ""),
                                       "class": cls.get("title", ""), "category": cat.get("title", ""),
                                       "match_key": match_key,
                                       "path": f"resultsSection.outcomeMeasuresModule.outcomeMeasures[{outcome_index}].classes[{ci}].categories[{ki}].measurements[{vi}].value"})
    return found


def normalize_trial(study, condition=""):
    p = study.get("protocolSection", {}) or {}
    ident, el, st = (p.get(k, {}) or {} for k in ("identificationModule", "eligibilityModule", "statusModule"))
    res = study.get("resultsSection", {}) or {}
    base = []
    for m in (res.get("baselineCharacteristicsModule", {}) or {}).get("measures", []) or []:
        cats = []
        for c in m.get("classes", []) or []:
            cats += [c.get("title", "")] + _titles(c.get("categories"))
        base.append({"title": m.get("title", ""), "categories": [c for c in cats if c]})
    outs = []
    for oi, m in enumerate((res.get("outcomeMeasuresModule", {}) or {}).get("outcomeMeasures", []) or []):
        classes, cats = [], []
        for c in m.get("classes", []) or []:
            classes.append(c.get("title", ""))
            cats += _titles(c.get("categories"))
        analyses = [" ".join(filter(None, [a.get("groupDescription", ""), a.get("statisticalComment", "")]))
                    for a in m.get("analyses", []) or []]
        outs.append({"title": m.get("title", ""), "description": m.get("description", ""),
                     "groups": _titles(m.get("groups")), "classes": [c for c in classes if c],
                     "categories": [c for c in cats if c], "analyses": [a for a in analyses if a],
                     "sex_values": outcome_sex_values(m, oi)})
    t = {"nct_id": ident.get("nctId"), "condition": condition, "title": ident.get("briefTitle", ""),
         "status": st.get("overallStatus", ""), "sex": el.get("sex", "UNKNOWN"),
         "eligibility_text": el.get("eligibilityCriteria", "") or "",
         "has_results": bool(study.get("hasResults", False)),
         "baseline_measures": base, "outcome_measures": outs,
         "contacts": contacts.extract(study),
         "references": [{"pmid": r.get("pmid", ""), "type": r.get("type", ""), "citation": r.get("citation", "")}
                        for r in (p.get("referencesModule", {}) or {}).get("references", []) or [] if r.get("pmid")]}
    t["female_n"], t["male_n"] = sex_counts(res.get("baselineCharacteristicsModule", {}) or {})
    t["results_fingerprint"] = fixtures.fingerprint(t)
    return t


def ingest(condition, n, sup=None, page_size=50, log=print, with_pubmed=True):
    """Queue n trials not seen before, so each run works through new records instead of
    re-fetching ones already audited (those stay in the checkpoint and the gap map)."""
    got, seen, token, linked = 0, 0, None, 0
    while got < n:
        sig = f"fetch|{condition}|{token}"
        if sup:
            sup.check_budget()
            sup.note_fetch(sig)
        data = fetch_page(condition, page_size, token)
        studies = data.get("studies", []) or []
        for s in studies:
            if got >= n:
                break
            t = normalize_trial(s, condition)
            if not t["nct_id"]:
                continue
            if store.q("SELECT 1 FROM queue WHERE nct_id=?", (t["nct_id"],)):
                seen += 1
                continue
            store.save_trial(t, "live")
            store.enqueue(t["nct_id"], condition)
            got += 1
            if with_pubmed:
                linked += pubmed.link_trial(t, sup)[1] > 0
        token = data.get("nextPageToken")
        if not token or not studies:
            break
    log(f"  fetched {got} new completed interventional trials with results for '{condition}'"
        + (f" (skipped {seen} already audited)" if seen else "")
        + (f"; {linked} have linked PubMed publications" if with_pubmed else ""))
    return got


def ingest_offline(n, seed=7, ambiguous=False, log=print):
    trials, _ = fixtures.make_synthetic(n, seed, ambiguous=ambiguous)
    pubs = fixtures.synthetic_publications(trials, seed)
    for t in trials:
        store.save_trial(t, "synthetic")
        store.enqueue(t["nct_id"], t["condition"])
        mine = pubs.get(t["nct_id"], [])
        store.save_publications(t["nct_id"], "OK", [{"pmid": p["pmid"], "link": "synthetic"} for p in mine], mine,
                                source="synthetic")
    log(f"  loaded {len(trials)} SYNTHETIC trials (offline mode); {len(pubs)} with SYNTHETIC publications")
    return len(trials)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--raw":
        import json
        d = fetch_page(" ".join(sys.argv[2:]), 1)
        print(json.dumps(d["studies"][0], indent=1)[:6000])
    else:
        print("usage: python fetch_trials.py --raw <condition>")
