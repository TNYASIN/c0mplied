"""ClinicalTrials.gov API v2 -> normalized trial dicts. Offline mode uses synthetic fixtures.

NOTE: field names below follow the v2 JSON as documented. Print one raw record
(`python fetch_trials.py --raw heart failure`) and confirm before trusting the parsers.
"""
import re, sys, time, requests
import store, fixtures

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
                label = (cat.get("title") or "").strip().lower()
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
    for m in (res.get("outcomeMeasuresModule", {}) or {}).get("outcomeMeasures", []) or []:
        classes, cats = [], []
        for c in m.get("classes", []) or []:
            classes.append(c.get("title", ""))
            cats += _titles(c.get("categories"))
        analyses = [" ".join(filter(None, [a.get("groupDescription", ""), a.get("statisticalComment", "")]))
                    for a in m.get("analyses", []) or []]
        outs.append({"title": m.get("title", ""), "description": m.get("description", ""),
                     "groups": _titles(m.get("groups")), "classes": [c for c in classes if c],
                     "categories": [c for c in cats if c], "analyses": [a for a in analyses if a]})
    t = {"nct_id": ident.get("nctId"), "condition": condition, "title": ident.get("briefTitle", ""),
         "status": st.get("overallStatus", ""), "sex": el.get("sex", "UNKNOWN"),
         "eligibility_text": el.get("eligibilityCriteria", "") or "",
         "has_results": bool(study.get("hasResults", False)),
         "baseline_measures": base, "outcome_measures": outs}
    t["female_n"], t["male_n"] = sex_counts(res.get("baselineCharacteristicsModule", {}) or {})
    t["results_fingerprint"] = fixtures.fingerprint(t)
    return t


def ingest(condition, n, sup=None, page_size=50, log=print):
    got, token = 0, None
    while got < n:
        sig = f"fetch|{condition}|{token}"
        if sup:
            sup.check_budget()
            sup.note_fetch(sig)
        data = fetch_page(condition, min(page_size, max(n - got, 1)), token)
        studies = data.get("studies", []) or []
        for s in studies:
            if got >= n:
                break
            t = normalize_trial(s, condition)
            if t["nct_id"]:
                store.save_trial(t, "live")
                store.enqueue(t["nct_id"], condition)
                got += 1
        token = data.get("nextPageToken")
        if not token or not studies:
            break
    log(f"  fetched {got} completed interventional trials with results for '{condition}'")
    return got


def ingest_offline(n, seed=7, ambiguous=False, log=print):
    trials, _ = fixtures.make_synthetic(n, seed, ambiguous=ambiguous)
    for t in trials:
        store.save_trial(t, "synthetic")
        store.enqueue(t["nct_id"], t["condition"])
    log(f"  loaded {len(trials)} SYNTHETIC trials (offline mode)")
    return len(trials)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--raw":
        import json
        d = fetch_page(" ".join(sys.argv[2:]), 1)
        print(json.dumps(d["studies"][0], indent=1)[:6000])
    else:
        print("usage: python fetch_trials.py --raw <condition>")
