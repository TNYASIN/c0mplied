"""Backstage UI for judges, standard library only (no Streamlit needed).

    python ui_server.py            # then open http://localhost:8501

GET  /             the page (ui/index.html)
GET  /api/state    live state read from the agent's SQLite checkpoint
POST /api/run      {"scenario": "sabotage", "live": false, "resume": false} starts run_agent.py in the background
"""
import json, os, subprocess, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import config, store, report
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
    }


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
        if self.path in ("/", "/index.html"):
            # ui/index.html is a page fragment so the same file also publishes as a claude.ai artifact
            # (where it runs a built-in simulation). Here it gets a full document and finds /api/state.
            with open(os.path.join(HERE, "ui", "index.html"), "rb") as f:
                page = (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                        b'</head><body>' + f.read() + b'</body></html>')
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path.startswith("/api/state"):
            try:
                return self._send(200, state())
            except Exception as e:   # e.g. DB busy mid-write: the page just polls again
                return self._send(503, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/run":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "Body must be JSON"})
        self._send(*start(body))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(HERE)
    print(f"HerEvidence UI on http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
