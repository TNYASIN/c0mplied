"""Compare completed blind second-review CSV with provisional reference labels.

Usage: python compare_reviewers.py data/reviewer2_full.csv
Only filled cells count as reviewed. This never silently overwrites gold labels.
"""
import argparse
import csv
import json
from pathlib import Path

from eval_gold import LABELS


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path")
    args = p.parse_args()
    first = {r["nct_id"]: r for r in json.loads(Path("data/gold_set.json").read_text(encoding="utf-8"))}
    disagreements = []
    counts = {k: {"reviewed": 0, "agreed": 0} for k in LABELS}
    with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ident = row["nct_id"]
            if ident not in first:
                raise ValueError(f"Unknown NCT ID: {ident}")
            for check, allowed in LABELS.items():
                second = row.get(check, "").strip()
                if not second:
                    continue
                if second not in allowed:
                    raise ValueError(f"{ident}: invalid {check} label {second}")
                counts[check]["reviewed"] += 1
                initial = first[ident][check]
                if second == initial:
                    counts[check]["agreed"] += 1
                else:
                    disagreements.append({"nct_id": ident, "check": check, "first_label": initial,
                                          "second_label": second, "final_label": "", "adjudication_reason": "",
                                          "source_url": first[ident]["source_url"]})
    output = Path("data/adjudication_queue.csv")
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["nct_id", "check", "first_label", "second_label", "final_label", "adjudication_reason", "source_url"])
        w.writeheader()
        w.writerows(disagreements)
    print("reviewed/agreed by check:", counts)
    print("disagreements:", len(disagreements), "->", output)
    print("Resolve every disagreement against the same frozen JSON before changing data/gold_set.json.")


if __name__ == "__main__":
    main()
