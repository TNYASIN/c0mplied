"""Create blind review sheets for the second annotator (no first-review labels)."""
import csv
import json
from pathlib import Path


FIELDS = ["nct_id", "source_url", "snapshot_path", "condition", "has_results",
          "sex_restriction", "eligibility", "enrollment_by_sex", "sex_stratified",
          "eligibility_quote", "sex_outcome_path_and_values", "notes"]


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    gold = json.loads(Path("data/gold_set.json").read_text(encoding="utf-8"))
    meta = {r["nct_id"]: r for r in json.loads(Path("data/real_gold/manifest.json").read_text(encoding="utf-8"))["records"]}
    evaluation = json.loads(Path("data/gold_eval.json").read_text(encoding="utf-8"))
    misses = {m["nct_id"] for m in evaluation["misses"]}
    priority = set(misses)
    for g in gold:
        if g["eligibility"] not in ("NONE",) or g["sex_stratified"] == "STRATIFIED_FOUND":
            priority.add(g["nct_id"])
    rows = [{"nct_id": g["nct_id"], "source_url": g["source_url"],
             "snapshot_path": meta[g["nct_id"]]["path"], "condition": g["condition"],
             "has_results": meta[g["nct_id"]]["has_results"]} for g in gold]
    write(Path("data/reviewer2_full.csv"), rows)
    write(Path("data/reviewer2_priority.csv"), [r for r in rows if r["nct_id"] in priority])
    write(Path("data/reviewer2_disagreements.csv"), [r for r in rows if r["nct_id"] in misses])
    print("full", len(rows), "priority", len(priority), "model disagreements", len(misses), "(blind sheets)")


if __name__ == "__main__":
    main()
