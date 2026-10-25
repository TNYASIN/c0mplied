"""Primary HerEvidence web UI, standard library only (no Streamlit needed).

    python ui_server.py            # then open http://localhost:8501

GET  /                  main page (ui/index.html)
GET  /agent-demo.html    teammate's original judge/phone demo (ui/agent-demo.html)
GET  /api/trial?id=X    trial verdicts for the original demo
GET  /api/state           live state read from the agent's SQLite checkpoint
GET  /api/studies         read-only summaries of stored audit records
GET  /api/studies/<id>    one study and deterministic finding explanations
POST /api/ask             grounded, read-only answers from stored evidence
POST /api/run             starts run_agent.py in the background
POST /api/draft           approves or rejects a pending follow-up draft
POST /api/followup        simulates a synthetic record update and re-audits it
"""
import json, mimetypes, os, subprocess, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlsplit

import config, drafts, evidence, followup, notify, store, report
from config import Limits
from supervisor import BetaTracker
from agent import SCENARIOS

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("HEREVIDENCE_UI_PORT", 8501))
PACE = float(os.environ.get("HEREVIDENCE_UI_PACE", 0.3))   # seconds per trial, so judges can watch
proc = None


def running():
    return proc is not None and proc.poll() is None


def history(run_id, limits):
    """Per-batch posterior P(error rate > threshold), rebuilt from stored verification notes."""
    trk = {"grounding": BetaTracker(limits.prior_alpha, limits.prior_beta),
           "recheck": BetaTracker(limits.prior_alpha, limits.prior_beta)}
    out, cur = [], None

    def point(b):
        out.append({"batch": b, **{k: round(t.p_exceeds(limits.error_threshold), 3) for k, t in trk.items()}})

    for r in store.q("SELECT batch, verify_note FROM verdicts WHERE run_id=? ORDER BY id", (run_id,)):
        if cur is not None and r["batch"] != cur:
            point(cur)
        cur, note = r["batch"], r["verify_note"] or ""
        if "quote found in source" in note:
            trk["grounding"].update(False)
        elif "QUOTE NOT IN SOURCE" in note:
            trk["grounding"].update(True)
        if "independent recheck agrees" in note:
            trk["recheck"].update(False)
        elif "RECHECK DISAGREES" in note:
            trk["recheck"].update(True)
    if cur is not None:
        point(cur)
    return out


GAP_KEYS = {
    "condition": "condition", "trials_audited": "trials",
    "% women among participants (mixed-sex trials)": "women_trials", "% women among patients": "women_patients",
    "PPR (participants / patients)": "ppr", "patient share source": "source",
    "% blanket childbearing exclusion": "blanket", "% pregnancy/lactation exclusion": "pregnancy",
    "% results-posted with NO sex-stratified result in record": "no_strat",
    "% enrollment-by-sex reported (of results-posted)": "enroll_reported",
}


def recent(run_id, n=8):
    rows = store.q("SELECT v.nct_id, v.condition, v.chk, v.label, v.verified, v.quarantined, v.method, q.status "
                   "FROM verdicts v LEFT JOIN queue q ON q.nct_id=v.nct_id WHERE v.run_id=? ORDER BY v.id DESC LIMIT 80",
                   (run_id,))
    by = {}
    for r in rows:
        t = by.setdefault(r["nct_id"], {"nct_id": r["nct_id"], "condition": r["condition"], "status": r["status"],
                                         "checks": {}, "rejected": 0, "quarantined": 0})
        t["checks"].setdefault(r["chk"], r["label"])
        t["rejected"] += r["verified"] == 0
        t["quarantined"] = max(t["quarantined"], r["quarantined"])
    return list(by.values())[:n]


def handoff():
    """Return the newest handoff report written by a completed or halted run."""
    directory = config.REPORT_DIR
    files = [os.path.join(directory, name) for name in os.listdir(directory)
             if name.startswith("handoff_")] if os.path.isdir(directory) else []
    if not files:
        return None
    with open(max(files, key=os.path.getmtime), encoding="utf-8") as f:
        return f.read()


def measured():
    """Load optional evaluation artifacts without making them prerequisites for the UI."""
    out = {}
    for key, path in (("compare", "data/compare.json"), ("gold", "data/gold_eval.json")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[key] = json.load(f)
    return out


def trial(nct):
    t = store.get_trial(nct)
    if not t:
        return 404, {"error": f"No trial {nct!r}"}
    vs = store.q("SELECT chk, label, quote, method, verified, quarantined, verify_note, run_id FROM verdicts "
                 "WHERE nct_id=? ORDER BY id DESC LIMIT 12", (nct,))
    return 200, {"nct_id": nct, "title": t.get("title"), "condition": t.get("condition"), "sex": t.get("sex"),
                 "has_results": t.get("has_results"), "eligibility_text": t.get("eligibility_text", ""),
                 "link": drafts.link(t), "verdicts": vs}


def state():
    store.init()
    runs = store.q("SELECT * FROM runs ORDER BY started DESC LIMIT 1")
    run = runs[0] if runs else None
    snap = json.loads(run["state_json"]) if run and run.get("state_json") else None
    limits = Limits(**snap["limits"]) if snap else Limits()
    rid = run["run_id"] if run else None
    one = lambda sql: store.q(sql, (rid,))[0]["n"] if rid else 0
    trials = store.q("SELECT nct_id FROM trials")
    return {
        "running": running(),
        "run": run and {k: run[k] for k in ("run_id", "scenario", "status", "halt_code", "halt_reason", "started", "ended")},
        "advice": report.ADVICE.get(run["halt_code"], "") if run and run.get("halt_code") else "",
        "snapshot": snap,
        "history": history(rid, limits) if rid else [],
        "counts": {
            "audited": one("SELECT COUNT(DISTINCT nct_id) n FROM verdicts WHERE run_id=?"),
            "rejected": one("SELECT COUNT(*) n FROM verdicts WHERE run_id=? AND verified=0"),
            "quarantined": one("SELECT COUNT(DISTINCT nct_id) n FROM verdicts WHERE run_id=? AND quarantined=1"),
            "drafts": store.q("SELECT COUNT(*) n FROM drafts WHERE status='DRAFT'")[0]["n"],
            "queue": report.queue_counts(),
        },
        "synthetic": bool(trials) and all(t["nct_id"].startswith("SYN") for t in trials),
        "gap": [{GAP_KEYS[k]: v for k, v in r.items() if k in GAP_KEYS} for r in report.gap_map()],
        "recent": recent(rid) if rid else [],
        "scenarios": list(SCENARIOS),
        "data_available": {
            "real": store.q("SELECT COUNT(*) n FROM trials WHERE source!='synthetic'")[0]["n"],
            "synthetic": store.q("SELECT COUNT(*) n FROM trials WHERE source='synthetic'")[0]["n"],
        },
        "drafts": store.q(
            "SELECT d.id,d.nct_id,d.kind,d.subject,d.body,d.status,t.source "
            "FROM drafts d LEFT JOIN trials t ON t.nct_id=d.nct_id "
            "ORDER BY d.updated DESC,d.id DESC LIMIT 25"
        ),
        "events": store.q("SELECT id,ts,kind,detail FROM events ORDER BY id DESC LIMIT 12"),
        "handoff": handoff(),
        "measured": measured(),
    }


def set_draft(body):
    status = body.get("status")
    if status not in ("APPROVED", "REJECTED"):
        return 400, {"error": "status must be APPROVED or REJECTED"}
    try:
        draft_id = int(body.get("id"))
    except (TypeError, ValueError):
        return 400, {"error": "draft id must be an integer"}
    rows = store.q("SELECT status FROM drafts WHERE id=?", (draft_id,))
    if not rows:
        return 404, {"error": "No such draft"}
    if rows[0]["status"] != "DRAFT":
        return 409, {"error": f"Draft is already {rows[0]['status']}"}
    drafts.set_status(draft_id, status)
    return 200, {"ok": True, "id": draft_id, "status": status}


def follow_up():
    """Simulate a demo registry update and resume the saved queue.

    This endpoint intentionally accepts synthetic trials only. A live NCT record must
    never be rewritten into demo data merely to demonstrate the follow-up lifecycle.
    """
    if running():
        return 409, {"error": "A run is already in progress. Wait for it to finish."}
    rows = store.q(
        "SELECT d.nct_id FROM drafts d JOIN trials t ON t.nct_id=d.nct_id "
        "WHERE t.source='synthetic' AND d.kind='sex_stratified_results' "
        "AND d.status IN ('DRAFT','APPROVED') ORDER BY d.id LIMIT 1"
    )
    if not rows:
        return 409, {"error": "No open synthetic result-reporting draft is available. Run a synthetic audit first."}
    nct_id = rows[0]["nct_id"]
    followup.simulate_new_results(nct_id)
    code, out = start({"scenario": "normal", "resume": True})
    return code, {**out, "nct_id": nct_id}


def start(body):
    global proc
    if running():
        return 409, {"error": "A run is already in progress. Wait for it to finish."}
    scen = body.get("scenario", "normal")
    if scen not in SCENARIOS:
        return 400, {"error": f"Unknown scenario {scen!r}"}
    cmd = [sys.executable, "run_agent.py", "--scenario", scen, "--pace", str(PACE)]
    if body.get("live"):
        cmd += ["--live", "--limit", str(int(body.get("limit", 40)))]
    if body.get("resume"):
        cmd += ["--no-ingest"]
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    log = open(os.path.join(config.REPORT_DIR, "ui_run.log"), "w")
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
    return 200, {"started": " ".join(cmd[1:])}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in ("/", "/index.html", "/agent-demo.html", "/ui/agent-demo.html"):
            # Serve both UIs: redesigned homepage and teammate's original judge demo.
            # ui/*.html files are document fragments, wrapped in a small HTML shell.
            filename = "index.html" if path in ("/", "/index.html") else "agent-demo.html"
            try:
                f = open(os.path.join(HERE, "ui", filename), "rb")
            except FileNotFoundError:
                return self._send(404, {"error": "not found"})
            with f:
                page = (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                        b'</head><body>' + f.read() + b'</body></html>')
            return self._send(200, page, "text/html; charset=utf-8")
        if path in ("/ui/styles.css", "/ui/app.js"):
            target = os.path.join(HERE, path.lstrip("/"))
            try:
                with open(target, "rb") as f:
                    return self._send(200, f.read(), mimetypes.guess_type(target)[0] or "application/octet-stream")
            except FileNotFoundError:
                return self._send(404, {"error": "not found"})
        if path == "/api/state":
            try:
                return self._send(200, state())
            except Exception as e:   # e.g. DB busy mid-write: the page just polls again
                return self._send(503, {"error": str(e)})
        if path == "/api/trial":
            # Compatibility endpoint for the team's judge/phone demo.
            nct_id = parse_qs(parsed.query).get("id", [""])[0]
            if not nct_id or len(nct_id) > 40:
                return self._send(400, {"error": "invalid study identifier"})
            try:
                return self._send(*trial(nct_id))
            except Exception as e:
                return self._send(503, {"error": str(e)})
        if path == "/api/studies":
            scope = parse_qs(parsed.query).get("scope", ["real"])[0]
            if scope not in ("real", "synthetic"):
                return self._send(400, {"error": "scope must be real or synthetic"})
            try:
                return self._send(200, {"studies": evidence.studies(scope), "overview": evidence.overview(scope)})
            except Exception as e:
                return self._send(503, {"error": str(e)})
        if path.startswith("/api/studies/"):
            nct_id = unquote(path[len("/api/studies/"):]).strip()
            if not nct_id or "/" in nct_id or len(nct_id) > 40:
                return self._send(400, {"error": "invalid study identifier"})
            try:
                detail = evidence.study_detail(nct_id)
                return self._send(200, detail) if detail else self._send(404, {"error": "study not found"})
            except Exception as e:
                return self._send(503, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/run", "/api/ask", "/api/draft", "/api/followup"):
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000:
            return self._send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "Body must be JSON"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "Body must be a JSON object"})
        if path == "/api/ask":
            question = str(body.get("question") or "").strip()
            scope = body.get("scope", "real")
            nct_id = body.get("nct_id")
            if not question:
                return self._send(400, {"error": "Ask a question first"})
            if len(question) > 2_000:
                return self._send(400, {"error": "Question is too long"})
            if scope not in ("real", "synthetic"):
                return self._send(400, {"error": "scope must be real or synthetic"})
            try:
                return self._send(200, evidence.answer(question, nct_id=nct_id, scope=scope))
            except Exception as e:
                return self._send(503, {"error": str(e)})
        if path == "/api/draft":
            return self._send(*set_draft(body))
        if path == "/api/followup":
            return self._send(*follow_up())
        self._send(*start(body))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(HERE)
    print(f"HerEvidence UI on http://localhost:{PORT}  (Ctrl+C to stop)")
    print(f"Team agent demo: http://localhost:{PORT}/agent-demo.html")
    print("Phone notifications:", ", ".join(notify.channels()) or "OFF (set NTFY_TOPIC to turn on)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
