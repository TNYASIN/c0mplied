"""Enrollment-by-sex counts (from structured baseline tables) and the participation-to-prevalence ratio."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config, store, report
from fetch_trials import sex_counts, normalize_trial

ARMS_TOTAL = [{"id": "BG000", "title": "Drug"}, {"id": "BG001", "title": "Placebo"}, {"id": "BG002", "title": "Total"}]


def row(title, cats, groups=("BG000", "BG001", "BG002")):
    return {"title": title, "classes": [{"categories": [
        {"title": name, "measurements": [{"groupId": g, "value": str(v)} for g, v in zip(groups, vals)]}
        for name, vals in cats]}]}


def test_total_column_not_double_counted():
    b = {"groups": ARMS_TOTAL, "measures": [row("Sex: Female, Male", [("Female", [60, 70, 130]), ("Male", [90, 80, 170])])]}
    assert sex_counts(b) == (130, 170)


def test_no_total_column_sums_arms():
    b = {"groups": [{"id": "A", "title": "A"}, {"id": "B", "title": "B"}],
         "measures": [row("Sex: Female, Male", [("Female", [10, 15]), ("Male", [5, 20])], groups=("A", "B"))]}
    assert sex_counts(b) == (25, 25)


def test_customized_row_and_single_sex():
    b = {"groups": ARMS_TOTAL, "measures": [row("Sex/Gender, Customized", [("Women", [1, 2, 3]), ("Men", [4, 5, 9])])]}
    assert sex_counts(b) == (3, 9)
    only_f = {"groups": ARMS_TOTAL, "measures": [row("Sex: Female, Male", [("Female", [50, 50, 100])])]}
    assert sex_counts(only_f) == (100, 0)


def test_missing_table():
    assert sex_counts({}) == (None, None)
    t = normalize_trial({"protocolSection": {"identificationModule": {"nctId": "NCT1"}}})
    assert (t["female_n"], t["male_n"]) == (None, None)


def test_ppr_uses_mixed_sex_trials_and_prevalence_csv():
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    store.init()
    for nct, sex, f, m in [("NCT1", "ALL", 30, 70), ("NCT2", "ALL", 20, 80), ("NCT3", "FEMALE", 100, 0)]:
        store.save_trial({"nct_id": nct, "condition": "dementia", "sex": sex, "female_n": f, "male_n": m}, "live")
    r = report.representation("dementia", ["NCT1", "NCT2", "NCT3"], {"dementia": (0.5, "test")})
    assert r["% women among participants (mixed-sex trials)"] == 25.0   # single-sex NCT3 excluded
    assert r["PPR (participants / patients)"] == 0.5
    missing = report.representation("asthma", ["NCT1"], {})
    assert missing["PPR (participants / patients)"] is None and "missing" in missing["patient share source"]
