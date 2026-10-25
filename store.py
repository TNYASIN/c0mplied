"""SQLite persistence = the agent's checkpoint. Kill it any time; --resume continues."""
import sqlite3, json, os, time
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials(nct_id TEXT PRIMARY KEY, condition TEXT, json TEXT, source TEXT, fetched_at REAL);
CREATE TABLE IF NOT EXISTS queue(nct_id TEXT PRIMARY KEY, condition TEXT, status TEXT, attempts INTEGER DEFAULT 0, run_id TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS verdicts(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, nct_id TEXT, condition TEXT, chk TEXT, label TEXT, quote TEXT, confidence REAL, method TEXT, verified INTEGER, verify_note TEXT, quarantined INTEGER DEFAULT 0, batch INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, started REAL, ended REAL, scenario TEXT, status TEXT, halt_code TEXT, halt_reason TEXT, state_json TEXT);
CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY AUTOINCREMENT, nct_id TEXT, kind TEXT, subject TEXT, body TEXT, status TEXT, created REAL, updated REAL, to_name TEXT, to_org TEXT, to_email TEXT, to_role TEXT, to_source TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts REAL, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS publications(pmid TEXT PRIMARY KEY, title TEXT, journal TEXT, year TEXT, doi TEXT, abstract TEXT, source TEXT, fetched_at REAL);
CREATE TABLE IF NOT EXISTS trial_publications(nct_id TEXT, pmid TEXT, link TEXT, PRIMARY KEY(nct_id, pmid));
CREATE TABLE IF NOT EXISTS pubmed_checks(nct_id TEXT PRIMARY KEY, status TEXT, checked_at REAL);
"""
# Columns added after the first release; init() adds them to databases created before then.
MIGRATIONS = {"drafts": ("to_name", "to_org", "to_email", "to_role", "to_source")}


def conn():
    path = config.DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _run(sql, args=(), fetch=False):
    c = conn()
    try:
        cur = c.execute(sql, args)
        out = [dict(r) for r in cur.fetchall()] if fetch else cur.lastrowid
        c.commit()
        return out
    finally:
        c.close()


def init():
    c = conn()
    try:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for col in cols:
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        c.commit()
    finally:
        c.close()


def q(sql, args=()):
    return _run(sql, args, True)


def x(sql, args=()):
    return _run(sql, args, False)


def save_trial(t, source):
    x("INSERT OR REPLACE INTO trials VALUES(?,?,?,?,?)",
      (t["nct_id"], t.get("condition", ""), json.dumps(t), source, time.time()))


def get_trial(nct):
    r = q("SELECT json FROM trials WHERE nct_id=?", (nct,))
    return json.loads(r[0]["json"]) if r else None


def enqueue(nct, cond):
    x("INSERT OR IGNORE INTO queue(nct_id,condition,status,attempts,updated) VALUES(?,?,'pending',0,?)",
      (nct, cond, time.time()))


def reset_synthetic():
    """Clear queue, verdicts and drafts for SYNTHETIC trials so each offline demo scenario starts fresh.
    Live (real) trials are untouched, so resuming a live run still works."""
    sub = "(SELECT nct_id FROM trials WHERE source='synthetic')"
    for table in ("queue", "verdicts", "drafts", "trial_publications", "pubmed_checks"):
        x(f"DELETE FROM {table} WHERE nct_id IN {sub}")


def save_publications(nct, status, links, pubs, source):
    """Record one PubMed lookup. On ERROR, keep the previous links rather than erasing them."""
    if status == "OK" or source == "synthetic":
        x("DELETE FROM trial_publications WHERE nct_id=?", (nct,))
        for p in pubs:
            x("INSERT OR REPLACE INTO publications VALUES(?,?,?,?,?,?,?,?)",
              (p["pmid"], p.get("title", ""), p.get("journal", ""), p.get("year", ""), p.get("doi", ""),
               p.get("abstract", ""), source, time.time()))
        for l in links:
            x("INSERT OR REPLACE INTO trial_publications VALUES(?,?,?)", (nct, l["pmid"], l["link"]))
    x("INSERT OR REPLACE INTO pubmed_checks VALUES(?,?,?)", (nct, status, time.time()))


def publications_for(nct):
    """(lookup status or None if never checked, [publication dicts with their link type])."""
    chk = q("SELECT status FROM pubmed_checks WHERE nct_id=?", (nct,))
    pubs = q("SELECT p.*, tp.link FROM trial_publications tp JOIN publications p ON p.pmid=tp.pmid "
             "WHERE tp.nct_id=? ORDER BY p.year DESC, p.pmid", (nct,))
    return (chk[0]["status"] if chk else None), pubs


def next_batch(n, source=None):
    """Pending trials, optionally only 'live' or 'synthetic' ones so the two kinds never mix in one run."""
    if source:
        return [r["nct_id"] for r in q("SELECT q.nct_id FROM queue q JOIN trials t ON t.nct_id=q.nct_id "
                                       "WHERE q.status='pending' AND t.source=? ORDER BY q.rowid LIMIT ?", (source, n))]
    return [r["nct_id"] for r in q("SELECT nct_id FROM queue WHERE status='pending' ORDER BY rowid LIMIT ?", (n,))]


def attempts(nct):
    r = q("SELECT attempts FROM queue WHERE nct_id=?", (nct,))
    return r[0]["attempts"] if r else 0


def set_status(nct, status, run_id=None, inc=False):
    x("UPDATE queue SET status=?, run_id=?, updated=?, attempts=attempts+? WHERE nct_id=?",
      (status, run_id, time.time(), 1 if inc else 0, nct))


def requeue(max_attempts):
    x("UPDATE queue SET status='pending' WHERE status IN ('retry','failed') AND attempts<?", (max_attempts,))


def add_verdict(run_id, batch, v, cond):
    x("INSERT INTO verdicts(run_id,nct_id,condition,chk,label,quote,confidence,method,verified,verify_note,batch,ts) "
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
      (run_id, v["nct_id"], cond, v["chk"], v["label"], v.get("quote", ""), v.get("confidence", 1.0),
       v["method"], int(v.get("verified", 0)), v.get("verify_note", ""), batch, time.time()))


def quarantine(run_id, from_batch):
    ids = [r["nct_id"] for r in q("SELECT DISTINCT nct_id FROM verdicts WHERE run_id=? AND batch>=?", (run_id, from_batch))]
    x("UPDATE verdicts SET quarantined=1 WHERE run_id=? AND batch>=?", (run_id, from_batch))
    started = q("SELECT started FROM runs WHERE run_id=?", (run_id,))
    for n in ids:
        if started:
            x("UPDATE drafts SET status='WITHHELD', updated=? WHERE nct_id=? AND created>=? AND status IN ('DRAFT','APPROVED')",
              (time.time(), n, started[0]["started"]))
    for n in ids:
        set_status(n, "quarantined", run_id)
    return ids


def log_event(run_id, kind, detail=""):
    x("INSERT INTO events(run_id,ts,kind,detail) VALUES(?,?,?,?)", (run_id, time.time(), kind, str(detail)))


def upsert_run(run_id, **f):
    x("INSERT OR IGNORE INTO runs(run_id) VALUES(?)", (run_id,))
    for k, v in f.items():
        x(f"UPDATE runs SET {k}=? WHERE run_id=?", (v, run_id))
