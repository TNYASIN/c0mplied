"""Write the v1 single-reviewer labels after manual inspection of frozen records.

Run once with `python seed_gold_labels.py`. It refuses to replace edited labels.
This is NOT a substitute for a second, independent human annotator.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path("data/real_gold")
TARGET = Path("data/gold_set.json")

# Explicit decisions made after reading the frozen eligibility text, not model output.
ELIG = {
    "NCT01187407": ("CONDITIONAL", "Using a reliable method of birth control", "Birth-control condition omitted by current keyword trigger"),
    "NCT00003299": ("PREGNANCY_LACTATION_EXCLUSION", "Not pregnant or nursing", "Restriction appears beyond the current 300-character line truncation"),
    "NCT00547729": ("CONDITIONAL", "Female subjects of childbearing potential must have a negative pregnancy test", "Pregnancy test condition; no blanket exclusion"),
    "NCT00340379": ("PREGNANCY_LACTATION_EXCLUSION", "A positive pregnancy test", "Also has contraception condition"),
    "NCT00042562": ("PREGNANCY_LACTATION_EXCLUSION", "You are a woman and are pregnant or breastfeeding.", "Explicit exclusion"),
    "NCT00162266": ("PREGNANCY_LACTATION_EXCLUSION", "not nursing and not pregnant", "Also permits WOCBP with contraception"),
    "NCT00233363": ("PREGNANCY_LACTATION_EXCLUSION", "Patients who are pregnant, possibly pregnant, or lactating", "Explicit exclusion"),
    "NCT00001731": ("CONDITIONAL", "Female patients of childbearing potential must use reliable forms of contraception", "Contraception condition"),
    "NCT01317797": ("PREGNANCY_LACTATION_EXCLUSION", "Pregnant or lactating female patients have to be excluded.", "Also has contraception condition"),
    "NCT00182689": ("PREGNANCY_LACTATION_EXCLUSION", "patients must not be pregnant or nursing", "Also has contraception condition"),
    "NCT00365053": ("PREGNANCY_LACTATION_EXCLUSION", "Not pregnant or nursing", "Also has contraception condition"),
    "NCT00385996": ("CONDITIONAL", "Women of child-bearing potential must be taking adequate contraceptive precautions", "Contraception condition"),
    "NCT00381303": ("PREGNANCY_LACTATION_EXCLUSION", "Not pregnant or breastfeeding", "Explicit exclusion"),
    "NCT01541852": ("BLANKET_EXCLUSION_CHILDBEARING", "Women of childbearing potential are excluded from this trial.", "Whole-trial exclusion"),
    "NCT01094717": ("UNCLEAR", "Women of childbearing potential are excluded from the actretin arm of the study.", "Arm-specific exclusion; another arm explicitly permits enrollment"),
    "NCT04680273": ("BLANKET_EXCLUSION_CHILDBEARING", "Women of childbearing potential, women who are pregnant or breastfeeding", "Whole-trial exclusion; female-only trial"),
}
STRAT_FOUND = {"NCT00381303": 0, "NCT03844321": 17}
BASELINE_MISSING_DATA = {"NCT00074724"}


def first_measurement_path(measure, prefix):
    for ci, cl in enumerate(measure.get("classes", [])):
        for cat_i, cat in enumerate(cl.get("categories", [])):
            for mi, item in enumerate(cat.get("measurements", [])):
                if item.get("value") not in (None, ""):
                    return f"{prefix}.classes[{ci}].categories[{cat_i}].measurements[{mi}].value", str(item["value"])
    return None, None


def main():
    if TARGET.exists():
        raise SystemExit(f"Refusing to replace {TARGET}; preserve reviewer edits")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for meta in manifest["records"]:
        ident = meta["nct_id"]
        raw = (ROOT / f"{ident}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {ident}")
        d = json.loads(raw)
        p = d["protocolSection"]
        criteria = p.get("eligibilityModule", {}).get("eligibilityCriteria", "")
        sex = p.get("eligibilityModule", {}).get("sex", "UNKNOWN")
        has_results = bool(d.get("hasResults"))
        e_label, quote, note = ELIG.get(ident, ("NONE", "", "Full eligibilityCriteria reviewed; no qualifying restriction found"))
        if quote and quote not in criteria:
            raise ValueError(f"Evidence quote absent: {ident}: {quote}")
        evidence = {"sex_restriction": {"path": "protocolSection.eligibilityModule.sex", "quote": sex},
                    "eligibility": {"path": "protocolSection.eligibilityModule.eligibilityCriteria",
                                    "quote": quote, "note": note}}
        if not has_results:
            baseline_label = outcome_label = "NO_RESULTS_POSTED"
            evidence["enrollment_by_sex"] = {"path": "hasResults", "quote": "false"}
            evidence["sex_stratified"] = {"path": "hasResults", "quote": "false"}
        else:
            bases = d.get("resultsSection", {}).get("baselineCharacteristicsModule", {}).get("measures", [])
            base_path = "resultsSection.baselineCharacteristicsModule.measures"
            sex_bases = [(i, m) for i, m in enumerate(bases)
                         if re.search(r"\b(sex|gender)\b", m.get("title", ""), re.I)]
            with_values = [(i, m, *first_measurement_path(m, f"{base_path}[{i}]")) for i, m in sex_bases]
            with_values = [v for v in with_values if v[2]]
            if with_values and ident not in BASELINE_MISSING_DATA:
                i, m, value_path, value = with_values[0]
                baseline_label = "REPORTED"
                evidence["enrollment_by_sex"] = {"path": f"{base_path}[{i}].title",
                    "quote": m["title"], "value_path": value_path, "example_value": value}
            else:
                baseline_label = "NOT_REPORTED_IN_RECORD"
                evidence["enrollment_by_sex"] = {"reviewed_path": base_path,
                    "note": "Sex measure title has no posted numeric measurement" if sex_bases else "No sex/gender baseline measure with numeric values"}
            outs = d.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
            out_path = "resultsSection.outcomeMeasuresModule.outcomeMeasures"
            if ident in STRAT_FOUND:
                idx = STRAT_FOUND[ident]
                m = outs[idx]
                value_path, value = first_measurement_path(m, f"{out_path}[{idx}]")
                if not value_path:
                    raise ValueError(f"No outcome value for stratified positive: {ident}")
                outcome_label = "STRATIFIED_FOUND"
                evidence["sex_stratified"] = {"path": f"{out_path}[{idx}].title", "quote": m["title"],
                    "sex_groups": [g.get("title", "") for g in m.get("groups", []) if re.fullmatch(r"Female|Male", g.get("title", ""), re.I)],
                    "sex_classes": [c.get("title", "") for c in m.get("classes", []) if re.search(r"\b(female|male)\b", c.get("title", ""), re.I)],
                    "value_path": value_path, "example_value": value,
                    "note": "Outcome values map to sex-named groups/classes; inspect full outcome for mapping"}
            else:
                outcome_label = "NOT_FOUND_IN_RECORD"
                evidence["sex_stratified"] = {"reviewed_path": out_path, "outcomes_reviewed": len(outs),
                    "note": "No outcome values mapped to sex/gender groups in the frozen result module"}
        out.append({"nct_id": ident, "condition": meta["condition_query"], "source_url": f"https://clinicaltrials.gov/study/{ident}",
            "snapshot_sha256": meta["sha256"], "last_update_posted": meta["last_update_posted"],
            "review_status": "single_reviewer_provisional", "reviewer": "Codex", "sex_restriction": sex,
            "eligibility": e_label, "enrollment_by_sex": baseline_label, "sex_stratified": outcome_label,
            "evidence": evidence})
    TARGET.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", len(out), "provisional labels to", TARGET)


if __name__ == "__main__":
    main()
