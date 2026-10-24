"""The key error modes are missing numeric evidence and premature draft creation."""
import json
from pathlib import Path

from auditor import audit_trial
from experiment_gate import decide
from fetch_trials import normalize_trial
from llm import AuditLLM, get_backend
from supervisor import Supervisor


def _audit(raw):
    trial = normalize_trial(raw)
    return {v["chk"]: v for v in audit_trial(trial, AuditLLM(Supervisor(enabled=False), get_backend("mock")))}


def test_numeric_sex_outcome_is_required():
    raw = json.loads(Path("data/real_gold/NCT00381303.json").read_text(encoding="utf-8"))
    found = _audit(raw)["sex_stratified_results"]
    assert found["label"] == "STRATIFIED_FOUND"
    assert len(found["evidence_paths"]) == 2
    for outcome in raw["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]:
        for cls in outcome.get("classes", []):
            for cat in cls.get("categories", []):
                cat["measurements"] = []
    assert _audit(raw)["sex_stratified_results"]["label"] != "STRATIFIED_FOUND"


def test_sex_values_must_share_timepoint_and_arm():
    raw = {"hasResults": True, "protocolSection": {"identificationModule": {"nctId": "SYN-CONTEXT"}},
           "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [{
               "title": "Outcome stratified by sex", "reportingStatus": "POSTED",
               "groups": [{"id": "OG0", "title": "Treatment"}],
               "classes": [{"title": sex, "categories": [{"measurements": [{"groupId": "OG0", "value": "1"}]}]}
                           for sex in ("Week 1 Male", "Week 2 Female")] }]}}}
    assert _audit(raw)["sex_stratified_results"]["label"] != "STRATIFIED_FOUND"


def test_baseline_title_without_counts_is_not_reported():
    raw = json.loads(Path("data/real_gold/NCT00074724.json").read_text(encoding="utf-8"))
    assert _audit(raw)["enrollment_by_sex"]["label"] == "NOT_REPORTED_IN_RECORD"


def test_customized_baseline_class_counts_are_reported():
    raw = json.loads(Path("data/real_gold/NCT03844321.json").read_text(encoding="utf-8"))
    assert _audit(raw)["enrollment_by_sex"]["label"] == "REPORTED"


def test_branch_gate_stops_a_false_found_and_holds_without_holdout():
    from eval_gold import evaluate, load_synthetic
    report = evaluate(load_synthetic(10), get_backend("mock"))
    candidate = json.loads(json.dumps(report))
    row = next(d for d in candidate["decisions"] if d["reference"]["sex_stratified"] != "STRATIFIED_FOUND")
    row["prediction"]["sex_stratified"] = "STRATIFIED_FOUND"
    candidate["metrics"]["sex_stratified"]["accuracy"] -= 0.1
    decision = decide(report, candidate)
    assert decision["decision"] == "STOP"
    assert any("strat_false_found" in reason for reason in decision["reasons"])


def test_halted_batch_has_no_open_drafts(tmp_path, monkeypatch):
    import agent
    import config
    import notify
    import store
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(notify, "send", lambda message: None)
    result = agent.run("sabotage", limit=40, llm_mode="mock", verbose=False)
    assert result["status"] == "HALTED_ERROR_RATE"
    assert store.q("SELECT COUNT(*) n FROM queue WHERE status='quarantined'")[0]["n"] > 0
    assert store.q("SELECT COUNT(*) n FROM drafts d JOIN queue q ON q.nct_id=d.nct_id "
                   "WHERE q.status='quarantined' AND d.status IN ('DRAFT','APPROVED')")[0]["n"] == 0
