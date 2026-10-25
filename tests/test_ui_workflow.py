"""Human-review and synthetic follow-up behavior exposed by ui_server.py."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import drafts
import store
import ui_server


def trial(nct_id):
    return {
        "nct_id": nct_id, "condition": "heart failure", "title": f"Study {nct_id}",
        "status": "COMPLETED", "sex": "ALL", "eligibility_text": "Age 18 or older",
        "has_results": True, "baseline_measures": [], "outcome_measures": [],
        "female_n": None, "male_n": None,
    }


@pytest.fixture
def workflow_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "workflow.db"))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(ui_server, "proc", None)
    store.init()
    return tmp_path


def test_draft_requires_valid_transition(workflow_db):
    item = trial("SYN0700001")
    store.save_trial(item, "synthetic")
    store.enqueue(item["nct_id"], item["condition"])
    draft_id = drafts.create(item, "sex_stratified_results")

    code, result = ui_server.set_draft({"id": draft_id, "status": "APPROVED"})
    assert code == 200 and result["status"] == "APPROVED"
    assert store.q("SELECT status FROM drafts WHERE id=?", (draft_id,))[0]["status"] == "APPROVED"

    code, result = ui_server.set_draft({"id": draft_id, "status": "REJECTED"})
    assert code == 409 and "already APPROVED" in result["error"]


def test_followup_never_rewrites_live_record_as_synthetic(workflow_db, monkeypatch):
    live = trial("NCT00000001")
    store.save_trial(live, "live")
    store.enqueue(live["nct_id"], live["condition"])
    drafts.create(live, "sex_stratified_results")
    code, result = ui_server.follow_up()
    assert code == 409 and "synthetic" in result["error"]

    demo = trial("SYN0700002")
    store.save_trial(demo, "synthetic")
    store.enqueue(demo["nct_id"], demo["condition"])
    drafts.create(demo, "sex_stratified_results")
    monkeypatch.setattr(ui_server, "start", lambda body: (200, {"started": "run_agent.py --no-ingest"}))

    code, result = ui_server.follow_up()
    assert code == 200 and result["nct_id"] == demo["nct_id"]
    updated = store.get_trial(demo["nct_id"])
    assert any("stratified by sex" in outcome["title"] for outcome in updated["outcome_measures"])
    assert store.q("SELECT status FROM queue WHERE nct_id=?", (demo["nct_id"],))[0]["status"] == "pending"


def test_state_includes_workflow_and_handoff(workflow_db):
    item = trial("SYN0700003")
    store.save_trial(item, "synthetic")
    store.enqueue(item["nct_id"], item["condition"])
    drafts.create(item, "enrollment_by_sex")
    store.log_event(None, "test_event", "workflow visible")
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    with open(os.path.join(config.REPORT_DIR, "handoff_test.md"), "w", encoding="utf-8") as f:
        f.write("# Test handoff")

    result = ui_server.state()
    assert result["drafts"][0]["source"] == "synthetic"
    assert result["events"][0]["kind"] == "test_event"
    assert result["handoff"] == "# Test handoff"
    assert "compare" in result["measured"]

