"""Freeze a small, reviewable ClinicalTrials.gov v2 sample for manual labeling.

This is a convenience/challenge sample, not a prevalence estimate. Run with
`python build_gold_sample.py`; existing snapshots are never silently replaced.
"""
import hashlib
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


API = "https://clinicaltrials.gov/api/v2/studies"
CONDITIONS = ["heart failure", "major depressive disorder", "rheumatoid arthritis", "lung cancer"]
OUT = Path("data/real_gold")
SEX_RESULT = re.compile(r"\b(sex|gender|female|male|women|men)\b", re.I)
BY_SEX = re.compile(r"(by|per|stratified by)\s+(sex|gender)|sex[- ]specific|sex subgroup", re.I)


def fetch_pool(condition):
    response = requests.get(API, params={"query.cond": condition,
        "filter.overallStatus": "COMPLETED", "aggFilters": "studyType:int",
        "pageSize": 100, "format": "json"}, timeout=45)
    response.raise_for_status()
    return response.json().get("studies", [])


def nct(study):
    return study["protocolSection"]["identificationModule"]["nctId"]


def score(study):
    measures = study.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
    text = json.dumps(measures, ensure_ascii=False)
    return 2 * len(BY_SEX.findall(text)) + len(SEX_RESULT.findall(text))


def choose(studies):
    posted = sorted((s for s in studies if s.get("hasResults")), key=nct)
    unposted = sorted((s for s in studies if not s.get("hasResults")), key=nct)
    selected = posted[:3] + unposted[:1]
    candidates = sorted((s for s in posted if s not in selected), key=lambda s: (-score(s), nct(s)))
    if candidates:
        selected.append(candidates[0])
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--add-id", action="append", default=[], help="append a targeted challenge NCT ID to an existing snapshot")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists() and not args.add_id:
        raise SystemExit(f"Snapshot exists: {manifest_path}; move it explicitly before refreshing")
    manifest = {"source": API, "sample_type": "convenience + sex-term challenge",
                "selection": "first three NCT IDs with results, first without results, and highest sex-term outcome candidate per condition among first 100 API matches",
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "records": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = []
    if args.add_id:
        for ident in args.add_id:
            response = requests.get(f"{API}/{ident}", timeout=45)
            response.raise_for_status()
            groups.append(("targeted challenge", [response.json()]))
    else:
        for condition in CONDITIONS:
            pool = fetch_pool(condition)
            chosen = choose(pool)
            print(condition, "pool", len(pool), "selected", [nct(s) for s in chosen], flush=True)
            groups.append((condition, chosen))
    existing = {r["nct_id"] for r in manifest["records"]}
    for condition, chosen in groups:
        for study in chosen:
            ident = nct(study)
            if ident in existing:
                continue
            raw = json.dumps(study, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            path = OUT / f"{ident}.json"
            path.write_bytes(raw.encode("utf-8"))
            status = study.get("protocolSection", {}).get("statusModule", {})
            manifest["records"].append({"nct_id": ident, "condition_query": condition,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "has_results": study.get("hasResults"),
                "last_update_posted": status.get("studyFirstPostDateStruct", {}).get("date") if not status.get("lastUpdatePostDateStruct") else status["lastUpdatePostDateStruct"].get("date"),
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "path": str(path).replace("\\", "/"), "outcome_sex_term_score": score(study)})
            existing.add(ident)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", len(manifest["records"]), "frozen records to", OUT)


if __name__ == "__main__":
    main()
