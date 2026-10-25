"""The autonomous audit loop, wrapped end-to-end by the supervisor."""
import json, random, time
import config, store, drafts, report, notify, fetch_trials, pubmed
from config import Limits
from supervisor import Supervisor, HaltRun, TaskLoop
from llm import AuditLLM, get_backend
from auditor import audit_trial
from verifier import verify

# quality_from = (first batch index, quality). 'ambiguous' makes every trial need the LLM.
SCENARIOS = {
    "normal": {},
    "sabotage": {"quality_from": (2, "degraded")},   # model silently degrades mid-run
    "loop": {"quality_from": (1, "garbage")},        # model starts returning unparseable text
    "stuck": {"quality_from": (0, "unclear"), "ambiguous": True},
    "budget": {"limits": {"max_tokens": 9000}},      # tiny budget
}


def decide(verdicts, attempts_so_far, max_attempts):
    if any((not v["verified"]) or v["label"] == "UNCLEAR" for v in verdicts):
        return "review" if attempts_so_far + 1 >= max_attempts else "retry"
    strat = next(v for v in verdicts if v["chk"] == "sex_stratified_results")
    return "watch" if strat["label"] == "NOT_FOUND_IN_RECORD" else "done"


def run(scenario="normal", conditions=None, limit=40, offline=True, supervised=True, ingest_data=True,
        seed=7, llm_mode="auto", overrides=None, verbose=True, pace=0.0, with_pubmed=True):
    """pace: seconds to wait after each trial, so the mock run is slow enough to watch on stage (UI uses it).
    with_pubmed: look up linked publications for real (NCT) trials; synthetic trials bring their own."""
    cfg = SCENARIOS[scenario]
    limits = Limits(**{**cfg.get("limits", {}), **(overrides or {})})
    store.init()
    run_id = f"run-{int(time.time() * 1000)}-{scenario}" + ("" if supervised else "-nosup")
    sup = Supervisor(limits, enabled=supervised)
    llm = AuditLLM(sup, get_backend(llm_mode))
    rng = random.Random(seed)
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    store.upsert_run(run_id, started=time.time(), scenario=scenario, status="RUNNING")
    log(f"\n=== {run_id} | supervisor={'ON' if supervised else 'OFF'} | llm={llm.backend.name} | scenario={scenario}")
    status, halt, batch_idx = "COMPLETED", None, 0
    try:
        if ingest_data:
            if offline:
                # Without this, a second scenario finds every synthetic trial already 'done' and makes 0 calls.
                store.reset_synthetic()
                fetch_trials.ingest_offline(limit, seed, ambiguous=cfg.get("ambiguous", False), log=log)
            else:
                conds = conditions or ["heart failure", "major depressive disorder", "rheumatoid arthritis", "lung cancer"]
                for c in conds:
                    fetch_trials.ingest(c, max(1, limit // len(conds)), sup, log=log, with_pubmed=with_pubmed)
        store.requeue(limits.max_attempts_per_trial)
        while True:
            sup.check_budget()
            ids = store.next_batch(limits.batch_size, "synthetic" if offline else "live")
            if not ids:
                break
            qf = cfg.get("quality_from")
            llm.quality = qf[1] if qf and batch_idx >= qf[0] else "normal"
            rechecks = set(rng.sample(ids, min(len(ids), limits.rechecks_per_batch)))
            resolved = 0
            pending = []
            for nct in ids:
                trial = store.get_trial(nct)
                trial["pubmed_status"], trial["publications"] = store.publications_for(nct)
                if with_pubmed and nct.startswith("NCT") and trial["pubmed_status"] is None:
                    pubmed.link_trial(trial, sup)   # queued before PubMed lookups existed
                    trial["pubmed_status"], trial["publications"] = store.publications_for(nct)
                try:
                    verdicts = audit_trial(trial, llm)
                    for v in verdicts:
                        if supervised:
                            verify(v, trial, llm, nct in rechecks, sup)
                        else:
                            v["verified"], v["verify_note"] = 1, "UNVERIFIED (no supervisor)"
                except TaskLoop as e:
                    store.set_status(nct, "failed", run_id, inc=True)
                    store.log_event(run_id, "task_loop", f"{nct} skipped after repeated identical calls ({e})")
                    log(f"  [loop] {nct}: identical call repeated; skipping task")
                    continue
                for v in verdicts:
                    store.add_verdict(run_id, batch_idx, v, trial["condition"])
                outcome = decide(verdicts, store.attempts(nct), limits.max_attempts_per_trial)
                pending.append((nct, trial, verdicts, outcome))
                resolved += outcome in ("done", "watch")
                bad = [v for v in verdicts if not v["verified"]]
                log(f"  {nct}: {outcome:<6} " + (f"REJECTED {len(bad)} verdict(s): {bad[0]['verify_note']}" if bad else ""))
                store.upsert_run(run_id, state_json=json.dumps(sup.snapshot()))
                if pace:
                    time.sleep(pace)
            sup.after_batch(batch_idx, resolved)
            # Commit decisions and external-facing drafts only after the whole batch passes supervision.
            for nct, trial, verdicts, outcome in pending:
                store.set_status(nct, outcome, run_id, inc=outcome in ("retry", "review"))
                if outcome == "watch":
                    pub = next((v for v in verdicts if v["chk"] == "publication_sex_analysis"
                                and v["label"] == "MENTIONED_IN_PUBLICATION"), None)
                    drafts.create(trial, "sex_stratified_results", publication=pub)
                if outcome in ("done", "watch") and any(
                        v["chk"] == "enrollment_by_sex" and v["label"] == "NOT_REPORTED_IN_RECORD" and v["verified"]
                        for v in verdicts):
                    drafts.create(trial, "enrollment_by_sex")
                if any(v["chk"] == "sex_stratified_results" and v["label"] == "STRATIFIED_FOUND" and v["verified"] for v in verdicts):
                    drafts.resolve(nct, "sex_stratified_results", run_id)
            s = sup.snapshot()["trackers"]
            log(f" batch {batch_idx}: resolved {resolved}/{len(ids)} | grounding {s['grounding']['errors']}/{s['grounding']['n']} "
                f"P>10%={s['grounding']['p_exceeds']:.2f} | recheck {s['recheck']['errors']}/{s['recheck']['n']} "
                f"P>10%={s['recheck']['p_exceeds']:.2f} | tokens {sup.tokens:,} | ${sup.cost:.3f}")
            batch_idx += 1
    except HaltRun as h:
        halt, status = h, f"HALTED_{h.code}"
        sup.halt = {"code": h.code, "reason": h.reason}
        log(f"\n*** SUPERVISOR HALT [{h.code}]: {h.reason}")
        if h.code == "ERROR_RATE":
            ids = store.quarantine(run_id, min(sup.last_clean + 1, batch_idx))
            log(f"*** QUARANTINED {len(ids)} trials from batches after the last clean batch ({sup.last_clean}); excluded from the gap map")
            store.log_event(run_id, "quarantine", f"{len(ids)} trials quarantined")
        else:
            ids = store.quarantine(run_id, batch_idx)
            if ids:
                store.log_event(run_id, "quarantine", f"{len(ids)} unfinished-batch trials quarantined")
    except Exception as e:   # unattended: never die silently; halt with a handoff and a phone alert instead
        import traceback
        log(traceback.format_exc())
        halt = HaltRun("CRASH", f"unexpected error: {type(e).__name__}: {str(e)[:200]}")
        status = "HALTED_CRASH"
        sup.halt = {"code": halt.code, "reason": halt.reason}
        log(f"\n*** HALT [CRASH]: {halt.reason}")
        ids = store.quarantine(run_id, batch_idx)
        if ids:
            store.log_event(run_id, "quarantine", f"{len(ids)} unfinished-batch trials quarantined after a crash")
    snap = sup.snapshot()
    gm = report.write_reports()
    path = report.write_handoff(run_id, status, halt, snap)
    store.upsert_run(run_id, ended=time.time(), status=status, halt_code=halt.code if halt else None,
                     halt_reason=halt.reason if halt else None, state_json=json.dumps(snap))
    n_draft = store.q("SELECT COUNT(*) n FROM drafts WHERE status='DRAFT'")[0]["n"]
    if halt:
        notify.send(f"HerEvidence HALTED: {halt.reason}. Recent work set aside; handoff report written. "
                    f"{n_draft} draft(s) need your approval.")
    else:
        notify.send(f"HerEvidence COMPLETED. {sum(report.queue_counts().values())} trials audited. "
                    f"{n_draft} draft(s) need your approval. Nothing is sent without you.")
    log(f"\n{status} | tokens {sup.tokens:,} | calls {sup.calls} | ~${sup.cost:.3f} | handoff: {path}")
    return {"run_id": run_id, "status": status, "halt": halt, "snapshot": snap, "gap_map": gm}
