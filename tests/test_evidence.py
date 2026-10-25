"""Grounding, filtering, and deterministic explanation tests for the public UI."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import evidence
import store


def add_finding(run_id, nct_id, check, label, *, verified=1, quote="", method="rule", quarantined=0):
    store.add_verdict(run_id, 0, {
        "nct_id": nct_id,
        "chk": check,
        "label": label,
        "quote": quote,
        "confidence": 0.9,
        "method": method,
        "verified": verified,
        "verify_note": "rule-based (deterministic)" if verified else "RECHECK DISAGREES",
    }, "heart failure")
    if quarantined:
        store.x("UPDATE verdicts SET quarantined=1 WHERE nct_id=? AND chk=?", (nct_id, check))


@pytest.fixture
def evidence_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "evidence.db"))
    store.init()
    base = {
        "condition": "heart failure", "title": "Reporting study", "status": "COMPLETED",
        "sex": "ALL", "eligibility_text": "Age 18 or older", "has_results": False,
        "baseline_measures": [], "outcome_measures": [], "female_n": None, "male_n": None,
    }
    for nct_id, source in [
        ("NCT00000001", "live"), ("NCT00000002", "live"), ("NCT00000003", "live"),
        ("SYN0700001", "synthetic"),
    ]:
        store.save_trial({**base, "nct_id": nct_id, "title": f"Study {nct_id}"}, source)
        store.enqueue(nct_id, "heart failure")
    add_finding("run-real", "NCT00000001", "sex_stratified_results", "NO_RESULTS_POSTED")
    add_finding("run-real", "NCT00000001", "enrollment_by_sex", "NO_RESULTS_POSTED")
    add_finding("run-real", "NCT00000002", "sex_stratified_results", "NOT_FOUND_IN_RECORD", verified=0)
    add_finding("run-real", "NCT00000003", "sex_stratified_results", "NOT_FOUND_IN_RECORD", quarantined=1)
    add_finding("run-demo", "SYN0700001", "sex_stratified_results", "NO_RESULTS_POSTED")
    return config.DB_PATH


def test_explanation_distinguishes_results_not_posted(evidence_db):
    detail = evidence.study_detail("NCT00000001")
    finding = next(f for f in detail["findings"] if f["check"] == "sex_stratified_results")
    assert finding["trusted"] is True
    assert finding["label"] == "NO_RESULTS_POSTED"
    assert "Results were not posted" in finding["beginner"]["what"]
    assert finding["researcher"]["source_path"].endswith("outcomeMeasures")
    assert detail["source_url"].endswith("NCT00000001")


def test_unverified_and_quarantined_are_withheld(evidence_db):
    unverified = evidence.study_detail("NCT00000002")["findings"][0]
    quarantined = evidence.study_detail("NCT00000003")["findings"][0]
    assert unverified["trusted"] is False
    assert quarantined["trusted"] is False
    assert "withheld" in unverified["beginner"]["what"].lower()
    assert quarantined["researcher"]["quarantined"] is True


def test_real_answers_exclude_synthetic_and_untrusted_claims(evidence_db):
    result = evidence.answer("Which checked studies don't have posted results?", scope="real")
    assert result["references"] == [{
        "nct_id": "NCT00000001", "title": "Study NCT00000001",
        "url": "https://clinicaltrials.gov/study/NCT00000001", "synthetic": False,
    }]
    assert "SYN" not in result["answer"]
    assert "NCT00000002" not in result["answer"]
    assert "NCT00000003" not in result["answer"]
    assert "does not mean results do not exist elsewhere" in result["answer"]


def test_synthetic_answers_are_explicitly_labelled(evidence_db):
    result = evidence.answer("Which checked studies don't have posted results?", scope="synthetic")
    assert result["synthetic"] is True
    assert "Synthetic demo records" in result["scope_note"]
    assert result["references"][0]["url"] is None
    assert result["references"][0]["synthetic"] is True


def test_selected_study_explanation_uses_that_study(evidence_db):
    result = evidence.answer(
        "Explain a selected study's reporting gap.", nct_id="NCT00000001", scope="real"
    )
    assert result["intent"] == "selected_study_gap"
    assert result["records_checked"] == ["NCT00000001"]
    assert [r["nct_id"] for r in result["references"]] == ["NCT00000001"]
    assert "Results were not posted" in result["answer"]


def test_review_answer_is_not_presented_as_verified_finding(evidence_db):
    result = evidence.answer("Which studies need more review?", scope="real")
    assert "operational review status" in result["answer"]
    assert "not presented as verified clinical findings" in result["scope_note"]
    assert {r["nct_id"] for r in result["references"]} == {"NCT00000002", "NCT00000003"}


def test_unknown_question_has_honest_fallback(evidence_db):
    result = evidence.answer("Tell me whether this treatment works", scope="real")
    assert result["intent"] == "unknown"
    assert "won’t guess" in result["answer"]
    assert result["references"] == []

