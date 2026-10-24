"""Synthetic trials for offline development and repeatable demos.

IDs start with SYN so nobody mistakes them for real registry records. Ground truth is
returned separately and is NEVER visible to the auditor; it is only used by the
evaluation harness (gold eval, compare.py).
"""
import random, json, hashlib

CONDITIONS = ["heart failure", "major depressive disorder", "rheumatoid arthritis", "lung cancer"]
# SYNTHETIC placeholders for the offline demo only. They are NOT real estimates and are never used for
# real (NCT) trials; real runs read patient shares from prevalence.csv, which needs a source per row.
SYNTHETIC_TRIAL_WOMEN = {"heart failure": 0.26, "major depressive disorder": 0.64,
                         "rheumatoid arthritis": 0.74, "lung cancer": 0.38}
SYNTHETIC_PATIENT_WOMEN = {"heart failure": 0.45, "major depressive disorder": 0.62,
                           "rheumatoid arthritis": 0.70, "lung cancer": 0.46}
INCL = ["Age 18 years or older", "Diagnosis confirmed by a physician",
        "Able to provide written informed consent", "Stable medication for at least 4 weeks"]
EXCL = ["Prior stroke within 6 months", "Severe renal impairment",
        "Participation in another interventional trial", "Known hypersensitivity to study drug",
        "Life expectancy under 12 months"]


def _elig(label, rng, ambiguous):
    inc, exc = rng.sample(INCL, 3), rng.sample(EXCL, 2)
    if label == "CONDITIONAL":
        inc.append("Women of childbearing potential must have a negative pregnancy test "
                   "and agree to use effective contraception")
    elif label == "PREGNANCY_LACTATION_EXCLUSION":
        exc.insert(0, rng.choice(["Pregnant or breastfeeding women", "Pregnancy or lactation"]))
    elif label == "BLANKET_EXCLUSION_CHILDBEARING":
        exc.insert(0, "Women of childbearing potential")
    elif ambiguous or rng.random() < 0.15:
        exc.append("Residents of nursing homes")  # decoy: trigger word, not an exclusion
    fmt = lambda xs: "\n".join("* " + x for x in xs)
    return f"Inclusion Criteria:\n\n{fmt(inc)}\n\nExclusion Criteria:\n\n{fmt(exc)}"


def _outcomes(strat, rng):
    m0 = {"title": rng.choice(["Change from baseline in 6-minute walk distance",
                               "Change in disease activity score", "Overall survival at 24 months",
                               "Change in depression rating scale score"]),
          "description": "Mean change at week 24 compared with baseline.",
          "groups": ["Treatment", "Placebo"], "classes": [], "categories": [], "analyses": []}
    ms = [m0]
    if strat == "STRATIFIED_FOUND":
        if rng.random() < 0.5:
            ms.append({"title": "Primary endpoint, stratified by sex",
                       "description": "Treatment effect reported separately for each sex.",
                       "groups": ["Female", "Male"], "classes": [], "categories": [], "analyses": [],
                       "sex_values": {"female": [{"value": "12", "path": "synthetic.outcome.female"}],
                                      "male": [{"value": "9", "path": "synthetic.outcome.male"}]}})
        else:
            ms.append({"title": "Primary endpoint by subgroup", "description": "Subgroup results.",
                       "groups": [], "classes": ["Female", "Male"], "categories": [], "analyses": [],
                       "sex_values": {"female": [{"value": "12", "path": "synthetic.outcome.female"}],
                                      "male": [{"value": "9", "path": "synthetic.outcome.male"}]}})
    else:
        if rng.random() < 0.3:
            m0["description"] = "Enrolled men and women aged 18 or older; analysis pooled across all participants."
        if rng.random() < 0.15:
            ms.append({"title": "Participants with sexual dysfunction adverse events",
                       "description": "Count of events.", "groups": [], "classes": [],
                       "categories": [], "analyses": []})
    return ms


def fingerprint(t):
    blob = json.dumps([t.get("outcome_measures"), t.get("baseline_measures")], sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()


def make_synthetic(n=40, seed=7, conditions=None, ambiguous=False):
    rng = random.Random(seed)
    conditions = conditions or CONDITIONS
    labels = ["NONE", "CONDITIONAL", "PREGNANCY_LACTATION_EXCLUSION", "BLANKET_EXCLUSION_CHILDBEARING"]
    weights = [0.40, 0.20, 0.25, 0.15]
    trials, truth = [], {}
    for i in range(n):
        lab = "NONE" if ambiguous else rng.choices(labels, weights)[0]
        has_res = rng.random() < 0.75
        strat = "STRATIFIED_FOUND" if rng.random() < 0.30 else "NOT_FOUND_IN_RECORD"
        has_sex_measure = has_res and rng.random() < 0.80
        base = []
        if has_res:
            base.append({"title": "Age, continuous", "categories": []})
            if has_sex_measure:
                base.append({"title": "Sex: Female, Male", "categories": ["Female", "Male"]})
        t = {"nct_id": f"SYN{seed:02d}{i:05d}", "condition": conditions[i % len(conditions)],
             "title": f"Synthetic trial {i}", "status": "COMPLETED",
             "sex": rng.choices(["ALL", "FEMALE", "MALE"], [0.88, 0.06, 0.06])[0],
             "eligibility_text": _elig(lab, rng, ambiguous), "has_results": has_res,
             "baseline_measures": base,
             "outcome_measures": _outcomes(strat, rng) if has_res else []}
        # Enrollment counts use their OWN random stream so the sequence above (and every existing
        # synthetic trial, ground truth and compare.py number) is unchanged.
        t["female_n"] = t["male_n"] = None
        if has_sex_measure:
            r2 = random.Random(f"{seed}-{i}-enrollment")
            n_enrolled = r2.randint(80, 900)
            share = {"FEMALE": 1.0, "MALE": 0.0}.get(
                t["sex"], min(0.97, max(0.03, r2.gauss(SYNTHETIC_TRIAL_WOMEN.get(t["condition"], 0.5), 0.10))))
            t["female_n"] = round(n_enrolled * share)
            t["male_n"] = n_enrolled - t["female_n"]
        t["results_fingerprint"] = fingerprint(t)
        trials.append(t)
        truth[t["nct_id"]] = {
            "eligibility_exclusion": lab,
            "sex_stratified_results": strat if has_res else "NO_RESULTS_POSTED",
            "enrollment_by_sex": ("REPORTED" if has_sex_measure else "NOT_REPORTED_IN_RECORD")
                                 if has_res else "NO_RESULTS_POSTED"}
    return trials, truth
