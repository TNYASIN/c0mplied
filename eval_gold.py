"""Evaluate all audit labels against frozen real-record or synthetic references.

The included real labels are single-reviewer PROVISIONAL until independently adjudicated.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import fixtures
import pubmed
from auditor import audit_trial
from fetch_trials import normalize_trial
from llm import AuditLLM, get_backend
from supervisor import Supervisor


LABELS = {
    "sex_restriction": ["ALL", "FEMALE", "MALE", "UNKNOWN"],
    "eligibility": ["BLANKET_EXCLUSION_CHILDBEARING", "PREGNANCY_LACTATION_EXCLUSION", "CONDITIONAL", "NONE", "UNCLEAR"],
    "enrollment_by_sex": ["REPORTED", "NOT_REPORTED_IN_RECORD", "NO_RESULTS_POSTED"],
    "sex_stratified": ["STRATIFIED_FOUND", "NOT_FOUND_IN_RECORD", "NO_RESULTS_POSTED", "UNCLEAR"],
}
CHECKS = {"sex_restriction": "sex_restriction", "eligibility": "eligibility_exclusion",
          "enrollment_by_sex": "enrollment_by_sex", "sex_stratified": "sex_stratified_results"}


def value_at(obj, path):
    for name, index in re.findall(r"([^\.\[\]]+)|\[(\d+)\]", path):
        obj = obj[int(index)] if index else obj[name]
    return obj


def validate_evidence(row, raw):
    for check in CHECKS:
        ev = row["evidence"][check]
        path = ev.get("path") or ev.get("reviewed_path")
        if not path:
            raise ValueError(f"{row['nct_id']} {check}: missing evidence path")
        value = value_at(raw, path)
        quote = ev.get("quote", "")
        if quote.lower() == "false":
            if value is not False:
                raise ValueError(f"{row['nct_id']} {check}: expected hasResults=false")
        elif quote and quote not in str(value):
            raise ValueError(f"{row['nct_id']} {check}: quote absent at {path}")
        if "value_path" in ev and str(value_at(raw, ev["value_path"])) != str(ev["example_value"]):
            raise ValueError(f"{row['nct_id']} {check}: value path mismatch")


def load_real(gold_path):
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path("data/real_gold/manifest.json").read_text(encoding="utf-8"))
    meta = {r["nct_id"]: r for r in manifest["records"]}
    rows = []
    for g in gold:
        ident = g["nct_id"]
        m = meta[ident]
        blob = Path(m["path"]).read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != m["sha256"] or digest != g["snapshot_sha256"]:
            raise ValueError(f"{ident}: frozen snapshot hash mismatch")
        raw = json.loads(blob)
        if raw["protocolSection"]["identificationModule"]["nctId"] != ident:
            raise ValueError(f"{ident}: record identity mismatch")
        validate_evidence(g, raw)
        for check, allowed in LABELS.items():
            if g[check] not in allowed:
                raise ValueError(f"{ident}: invalid {check} label {g[check]}")
        trial = normalize_trial(raw, g["condition"])
        trial["pubmed_status"], trial["publications"] = pubmed.load_gold(ident)
        rows.append((g, trial, bool(raw.get("hasResults"))))
    return rows


def load_synthetic(n):
    trials, truth = fixtures.make_synthetic(n)
    rows = []
    for t in trials:
        labels = truth[t["nct_id"]]
        g = {"nct_id": t["nct_id"], "condition": t["condition"],
             "sex_restriction": t["sex"], "eligibility": labels["eligibility_exclusion"],
             "enrollment_by_sex": labels["enrollment_by_sex"],
             "sex_stratified": labels["sex_stratified_results"], "review_status": "synthetic_generator_truth"}
        rows.append((g, t, t["has_results"]))
    return rows


def metric_for_check(gold, pred, labels, abstain_label="UNCLEAR"):
    n = len(gold)
    matrix = {g: {p: sum(a == g and b == p for a, b in zip(gold, pred)) for p in labels} for g in labels}
    per_label = {}
    for label in labels:
        tp = matrix[label][label]
        support = sum(a == label for a in gold)
        predicted = sum(b == label for b in pred)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if precision is not None and recall is not None else None
        per_label[label] = {"support": support, "predicted": predicted,
                            "precision": precision, "recall": recall, "f1": f1}
    abstained = sum(x == abstain_label for x in pred) if abstain_label in labels else 0
    accepted = [(a, b) for a, b in zip(gold, pred) if b != abstain_label] if abstain_label in labels else list(zip(gold, pred))
    return {"n": n, "accuracy": sum(a == b for a, b in zip(gold, pred)) / n if n else None,
            "abstained": abstained, "abstention_rate": abstained / n if n else None,
            "coverage": len(accepted) / n if n else None,
            "accuracy_on_non_abstained": sum(a == b for a, b in accepted) / len(accepted) if accepted else None,
            "labels": per_label, "confusion_matrix": matrix}


def fmt(value):
    return "—" if value is None else f"{value:.1%}"


def markdown_report(result):
    lines = ["# Gold-set evaluation", "", f"- Backend: `{result['backend']}`",
             f"- Records: {result['n']}", f"- Reference status: {result['reference_status']}",
             "- Confusion matrix: rows = reference, columns = prediction.",
             "- Targeted challenge cases are included; this is not a prevalence estimate.", ""]
    for check, m in result["metrics"].items():
        lines += [f"## {check}", "", f"Accuracy: {fmt(m['accuracy'])}; coverage: {fmt(m['coverage'])}; "
                  f"abstention: {fmt(m['abstention_rate'])}; non-abstained accuracy: {fmt(m['accuracy_on_non_abstained'])}", "",
                  "| Label | Support | Predicted | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|---:|"]
        for label, v in m["labels"].items():
            lines.append(f"| {label} | {v['support']} | {v['predicted']} | {fmt(v['precision'])} | {fmt(v['recall'])} | {fmt(v['f1'])} |")
        labels = list(m["labels"])
        lines += ["", "Confusion matrix:", "", "| Reference \\ Prediction | " + " | ".join(labels) + " |",
                  "|---|" + "---:|" * len(labels)]
        for label in labels:
            lines.append("| " + label + " | " + " | ".join(str(m["confusion_matrix"][label][p]) for p in labels) + " |")
        lines.append("")
    lines += ["## Disagreements", ""]
    for miss in result["misses"]:
        lines.append(f"- {miss['nct_id']} `{miss['check']}`: reference `{miss['gold']}`, predicted `{miss['pred']}`")
    lines += ["", "## Publication cross-check (PubMed abstracts)", "",
              "Linked-publication sentences that appear to report a finding by sex. These are unlabeled leads "
              "for a human reader, not scored; a lead on a `NOT_FOUND_IN_RECORD` record means the paper may "
              "hold what the registry lacks.", ""]
    for lead in result.get("publication_leads", []):
        lines.append(f"- {lead['nct_id']} (registry reference `{lead['registry_reference']}`) PMID {lead['pmid']}: "
                     f"\"{lead['sentence']}\"")
    if not result.get("publication_leads"):
        lines.append("- none (or no `data/real_gold/pubmed.json` snapshot; run `python pubmed.py --freeze-gold`)")
    return "\n".join(lines) + "\n"


def evaluate(rows, backend):
    llm = AuditLLM(Supervisor(enabled=False), backend)
    refs, preds = {k: [] for k in CHECKS}, {k: [] for k in CHECKS}
    misses = []
    decisions = []
    strata = Counter()
    publication_leads = []
    for g, trial, has_results in rows:
        full = {v["chk"]: v for v in audit_trial(trial, llm)}
        verdicts = {chk: v["label"] for chk, v in full.items()}
        pub = full.get("publication_sex_analysis")
        if pub and pub["label"] == "MENTIONED_IN_PUBLICATION":
            publication_leads.append({"nct_id": g["nct_id"], "registry_reference": g["sex_stratified"],
                                      "registry_prediction": verdicts["sex_stratified_results"], "pmid": pub["pmid"],
                                      "sentence": pub["sentence"]})
        decisions.append({"nct_id": g["nct_id"], "reference": {k: g[k] for k in CHECKS},
                          "prediction": {k: verdicts[check] for k, check in CHECKS.items()},
                          "snapshot_sha256": g.get("snapshot_sha256")})
        strata[(g["condition"], "results" if has_results else "no_results")] += 1
        for key, check in CHECKS.items():
            gold, pred = g[key], verdicts[check]
            refs[key].append(gold)
            preds[key].append(pred)
            if gold != pred:
                misses.append({"nct_id": g["nct_id"], "check": key, "gold": gold, "pred": pred})
    metrics = {k: metric_for_check(refs[k], preds[k], LABELS[k]) for k in CHECKS}
    reference_digest = hashlib.sha256(json.dumps(
        [{"nct_id": d["nct_id"], "reference": d["reference"], "snapshot_sha256": d["snapshot_sha256"]}
         for d in sorted(decisions, key=lambda x: x["nct_id"])], sort_keys=True).encode()).hexdigest()
    return {"n": len(rows), "backend": backend.name,
            "reference_digest": reference_digest, "decisions": decisions,
            "reference_status": sorted({g["review_status"] for g, _, _ in rows}),
            "accuracy": {k: v["accuracy"] for k, v in metrics.items()},
            "metrics": metrics, "strata_counts": [{"condition": c, "results_status": s, "n": n} for (c, s), n in sorted(strata.items())],
            "misses": misses, "publication_leads": publication_leads}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--template", type=int, help="export cached live trials for additional human labeling")
    p.add_argument("--gold", default="data/gold_set.json")
    p.add_argument("--synthetic", type=int, help="evaluate generator truth rather than frozen real records")
    p.add_argument("--llm", default="mock", choices=["mock", "anthropic", "auto"])
    p.add_argument("--out", default="data/gold_eval.json")
    args = p.parse_args()
    if args.template:
        import store
        from rules import elig_candidates, strat_payload_lines
        store.init()
        ids = store.q("SELECT nct_id FROM trials WHERE source='live' LIMIT ?", (args.template,))
        path = Path("data/gold_template.csv")
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["nct_id", "eligibility_lines", "outcome_lines", "eligibility_label", "sex_stratified_label"])
            for row in ids:
                t = store.get_trial(row["nct_id"])
                w.writerow([t["nct_id"], " || ".join(line for _, line in elig_candidates(t["eligibility_text"])),
                            " || ".join(strat_payload_lines(t)[1]), "", ""])
        print(f"wrote {path}; label using the full source record, not only these candidate lines")
        return
    rows = load_synthetic(args.synthetic) if args.synthetic else load_real(args.gold)
    result = evaluate(rows, get_backend(args.llm))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(markdown_report(result), encoding="utf-8")
    print(f"{result['backend']} | n={result['n']} | reference={result['reference_status']}")
    for k, m in result["metrics"].items():
        print(f"  {k}: accuracy={fmt(m['accuracy'])}, coverage={fmt(m['coverage'])}, abstention={fmt(m['abstention_rate'])}")
    print(f"wrote {path} and {path.with_suffix('.md')}; disagreements={len(result['misses'])}")


if __name__ == "__main__":
    main()
