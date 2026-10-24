"""Backstage dashboard for judges. The agent itself needs no screen: it runs unattended,
and only reaches a human (SMS/notify) when it needs approval or has halted."""
import json, os, subprocess, sys, time
import pandas as pd
import streamlit as st
import config, store, report, drafts, followup

st.set_page_config(page_title="HerEvidence", layout="wide")
store.init()
st.title("HerEvidence")
st.caption("Autonomous, self-supervising audit of sex-specific reporting in clinical-trial registry records. "
           "Findings mean 'not found in the registry record', not 'not done'.")

with st.sidebar:
    st.header("Launch a run")
    scenario = st.selectbox("Scenario", ["normal", "sabotage", "loop", "stuck", "budget"])
    live = st.checkbox("Live ClinicalTrials.gov (else synthetic)", value=False)
    limit = st.slider("Trials", 10, 120, 40, 5)
    no_sup = st.checkbox("Disable supervisor (baseline)", value=False)
    if st.button("Start run", type="primary"):
        cmd = [sys.executable, "run_agent.py", "--scenario", scenario, "--limit", str(limit)]
        cmd += (["--live"] if live else []) + (["--no-supervisor"] if no_sup else [])
        st.session_state["proc"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if st.button("Resume queue (no new fetch)"):
        st.session_state["proc"] = subprocess.Popen([sys.executable, "run_agent.py", "--no-ingest"],
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if st.button("Simulate: new results published"):
        rows = store.q("SELECT nct_id FROM drafts WHERE kind='sex_stratified_results' AND status IN ('DRAFT','APPROVED') ORDER BY id LIMIT 1")
        if rows:
            followup.simulate_new_results(rows[0]["nct_id"])
            st.success(f"Simulated registry update for {rows[0]['nct_id']}. Click 'Resume queue' to re-audit.")
        else:
            st.warning("No open draft yet.")
    auto = st.checkbox("Auto-refresh while running", value=True)

proc = st.session_state.get("proc")
running = proc is not None and proc.poll() is None
runs = store.q("SELECT * FROM runs ORDER BY started DESC LIMIT 1")

t1, t2, t3, t4, t5, t6 = st.tabs(["Supervisor", "Gap map", "Findings & evidence", "Draft requests", "Handoff report", "Measured results"])

with t1:
    if not runs:
        st.info("No runs yet. Start one from the sidebar.")
    else:
        r = runs[0]
        s = json.loads(r["state_json"]) if r["state_json"] else None
        st.subheader(f"{r['run_id']}: {r['status']}")
        if r["halt_code"]:
            st.error(f"Supervisor halted the agent [{r['halt_code']}]: {r['halt_reason']}")
        if s:
            L = s["limits"]
            c = st.columns(4)
            c[0].metric("Tokens", f"{s['tokens']:,}", f"cap {L['max_tokens']:,}")
            c[0].progress(min(1.0, s["tokens"] / L["max_tokens"]))
            c[1].metric("Est. cost", f"${s['cost']:.3f}", f"cap ${L['max_cost_usd']:.2f}")
            c[1].progress(min(1.0, s["cost"] / L["max_cost_usd"]))
            c[2].metric("LLM calls", s["calls"], f"cap {L['max_calls']}")
            c[2].progress(min(1.0, s["calls"] / L["max_calls"]))
            c[3].metric("Task loops", s["task_loops"], f"halt at {L['max_task_loops']}")
            c = st.columns(3)
            for col, (name, t) in zip(c, s["trackers"].items()):
                col.metric(f"{name} check: P(error > {L['error_threshold']:.0%})", f"{t['p_exceeds']:.2f}",
                           f"{t['errors']}/{t['n']} failed; halt at {L['halt_probability']:.2f}")
                col.progress(min(1.0, t["p_exceeds"]))
            c[2].metric("Batches with no progress", s["no_progress"], f"halt at {L['stuck_batches']}")
        st.write("Queue:", report.queue_counts())
        ev = store.q("SELECT datetime(ts,'unixepoch','localtime') time, kind, detail FROM events ORDER BY id DESC LIMIT 15")
        if ev:
            st.dataframe(pd.DataFrame(ev))

with t2:
    gm = report.gap_map()
    if gm:
        df = pd.DataFrame(gm).set_index("condition")
        st.dataframe(df)
        col = "% results-posted with NO sex-stratified result in record"
        st.bar_chart(df[[col]].fillna(0))
        st.caption("Only verified, non-quarantined verdicts are counted. Women's share of participants comes from "
                   "structured baseline tables (no LLM), over trials open to all sexes. PPR below 0.8 is usually read "
                   "as under-representation; check 'patient share source' before quoting any PPR.")
    else:
        st.info("No trusted verdicts yet.")

with t3:
    rows = store.q("SELECT nct_id FROM queue ORDER BY rowid")
    if rows:
        pick = st.selectbox("Trial", [r["nct_id"] for r in rows])
        tr = store.get_trial(pick)
        st.write(f"**{tr['title']}** | condition: {tr['condition']} | sex field: {tr['sex']} | results posted: {tr['has_results']}")
        vs = store.q("SELECT chk,label,quote,method,verified,quarantined,verify_note FROM verdicts WHERE nct_id=? ORDER BY id DESC", (pick,))
        st.dataframe(pd.DataFrame(vs))
        with st.expander("Source eligibility text"):
            st.text(tr["eligibility_text"])

with t4:
    st.write("Nothing is ever sent automatically. Approval here is simulated.")
    for d in store.q("SELECT * FROM drafts ORDER BY id DESC LIMIT 25"):
        with st.expander(f"#{d['id']} [{d['status']}] {d['subject']}"):
            st.text(d["body"])
            if d["status"] == "DRAFT":
                a, b = st.columns(2)
                if a.button("Approve", key=f"a{d['id']}"):
                    drafts.set_status(d["id"], "APPROVED"); st.rerun()
                if b.button("Reject", key=f"r{d['id']}"):
                    drafts.set_status(d["id"], "REJECTED"); st.rerun()

with t5:
    files = sorted(f for f in os.listdir(config.REPORT_DIR) if f.startswith("handoff_")) if os.path.isdir(config.REPORT_DIR) else []
    if files:
        st.markdown(open(os.path.join(config.REPORT_DIR, files[-1])).read())
    else:
        st.info("A handoff report is written whenever a run ends or halts.")

with t6:
    if os.path.exists("data/compare.json"):
        st.subheader("Supervised vs unsupervised (same sabotage)")
        st.dataframe(pd.DataFrame(json.load(open("data/compare.json"))))
    if os.path.exists("data/gold_eval.json"):
        g = json.load(open("data/gold_eval.json"))
        st.subheader(f"Accuracy vs gold set (n={g['n']})")
        st.json(g["accuracy"])
    st.caption("Run `python compare.py` and `python eval_gold.py` to refresh. Synthetic numbers test plumbing only.")

if running and auto:
    time.sleep(2)
    st.rerun()
