"""Fail-closed decision gate for candidate auditor branches.

Development data can stop a bad branch. Promotion additionally needs an independent,
adjudicated holdout with enough positive examples. This gate never edits production code.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _risk(report):
    counts = {"strat_false_found": 0, "strat_missed_found": 0,
              "elig_false_restriction": 0, "elig_missed_restriction": 0}
    for row in report["decisions"]:
        ref, pred = row["reference"], row["prediction"]
        a, b = ref["sex_stratified"], pred["sex_stratified"]
        counts["strat_false_found"] += b == "STRATIFIED_FOUND" and a != b
        counts["strat_missed_found"] += a == "STRATIFIED_FOUND" and b != a
        a, b = ref["eligibility"], pred["eligibility"]
        counts["elig_false_restriction"] += a == "NONE" and b not in ("NONE", "UNCLEAR")
        counts["elig_missed_restriction"] += a not in ("NONE", "UNCLEAR") and b == "NONE"
    return counts


def _validate(report, name):
    rows = report.get("decisions") or []
    if not rows or len(rows) != report.get("n") or len({r["nct_id"] for r in rows}) != len(rows):
        return [f"{name}: missing or duplicate record-level decisions"]
    digest = hashlib.sha256(json.dumps(
        [{"nct_id": r["nct_id"], "reference": r["reference"], "snapshot_sha256": r.get("snapshot_sha256")}
         for r in sorted(rows, key=lambda x: x["nct_id"])], sort_keys=True).encode()).hexdigest()
    if digest != report.get("reference_digest"):
        return [f"{name}: reference digest does not match decisions"]
    for check, summary in report.get("metrics", {}).items():
        correct = sum(r["reference"][check] == r["prediction"][check] for r in rows)
        accepted = sum(r["prediction"][check] != "UNCLEAR" for r in rows)
        if abs(summary["accuracy"] - correct / len(rows)) > 1e-9 or abs(summary["coverage"] - accepted / len(rows)) > 1e-9:
            return [f"{name}: {check} summary disagrees with record-level decisions"]
    return []


def compare_pair(baseline, candidate, name):
    blockers = _validate(baseline, f"{name} baseline") + _validate(candidate, f"{name} candidate")
    if not baseline.get("reference_digest") or baseline.get("reference_digest") != candidate.get("reference_digest"):
        blockers.append(f"{name}: reference labels or frozen record versions differ")
    if baseline.get("backend") != candidate.get("backend"):
        blockers.append(f"{name}: backend differs")
    if not baseline.get("decisions") or not candidate.get("decisions"):
        blockers.append(f"{name}: missing record-level decisions")
    if blockers:
        return blockers, {}, 0
    old, new = _risk(baseline), _risk(candidate)
    for key in old:
        if new[key] > old[key]:
            blockers.append(f"{name}: {key} increased {old[key]} -> {new[key]}")
    for check in baseline["metrics"]:
        before = baseline["metrics"][check]
        after = candidate["metrics"][check]
        if after["accuracy"] < before["accuracy"]:
            blockers.append(f"{name}: {check} accuracy fell {before['accuracy']:.3f} -> {after['accuracy']:.3f}")
        if after["coverage"] < before["coverage"] - 0.05:
            blockers.append(f"{name}: {check} coverage fell by more than 5 percentage points")
    gain = sum(candidate["metrics"][c]["accuracy"] - baseline["metrics"][c]["accuracy"]
               for c in baseline["metrics"])
    return blockers, {"baseline": old, "candidate": new}, gain


def decide(baseline_dev, candidate_dev, baseline_holdout=None, candidate_holdout=None):
    blockers, dev_risk, dev_gain = compare_pair(baseline_dev, candidate_dev, "development")
    result = {"decision": "STOP", "reasons": blockers, "development_risk": dev_risk,
              "development_accuracy_gain_sum": dev_gain}
    if blockers:
        return result
    if dev_gain <= 0:
        result["reasons"] = ["development: no measured accuracy gain"]
        return result
    if baseline_holdout is None or candidate_holdout is None:
        result.update(decision="HOLD", reasons=["independent holdout evaluation missing"])
        return result
    if baseline_dev["reference_digest"] == baseline_holdout.get("reference_digest"):
        result["reasons"] = ["holdout is the same reference set as development"]
        return result
    blockers, holdout_risk, holdout_gain = compare_pair(baseline_holdout, candidate_holdout, "holdout")
    result["holdout_risk"] = holdout_risk
    result["holdout_accuracy_gain_sum"] = holdout_gain
    if blockers:
        result["reasons"] = blockers
        return result
    if any("adjudicated" not in s.lower() for s in candidate_holdout["reference_status"]):
        result.update(decision="HOLD", reasons=["holdout labels are not independently adjudicated"])
        return result
    support = candidate_holdout["metrics"]["sex_stratified"]["labels"]["STRATIFIED_FOUND"]["support"]
    if support < 10:
        result.update(decision="HOLD", reasons=[f"holdout has only {support} STRATIFIED_FOUND examples; require 10"])
        return result
    if holdout_gain <= 0:
        result.update(decision="HOLD", reasons=["no measured gain on independent holdout"])
        return result
    result.update(decision="PROMOTE", reasons=["development and independent holdout gates passed"])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline-dev", required=True)
    p.add_argument("--candidate-dev", required=True)
    p.add_argument("--baseline-holdout")
    p.add_argument("--candidate-holdout")
    p.add_argument("--out", default="data/experiment_gate.json")
    args = p.parse_args()
    if bool(args.baseline_holdout) != bool(args.candidate_holdout):
        p.error("both holdout reports are required together")
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    result = decide(read(args.baseline_dev), read(args.candidate_dev),
                    read(args.baseline_holdout), read(args.candidate_holdout))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["decision"] + ": " + "; ".join(result["reasons"]))


if __name__ == "__main__":
    main()
