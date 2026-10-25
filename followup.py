"""Re-evaluation of unresolved gaps. In the demo we SIMULATE a registry update;
live mode compares fingerprints of re-fetched records."""
import sys, json
import store, fixtures, requests
from fetch_trials import normalize_trial, API


def simulate_new_results(nct):
    t = store.get_trial(nct)
    t["outcome_measures"].append({"title": "Primary endpoint, stratified by sex",
                                  "description": "Added in a (simulated) registry update.",
                                  "groups": [], "classes": ["Female", "Male"], "categories": [], "analyses": [],
                                  # The evidence gate needs actual values tied to each sex, as a real update would post
                                  "sex_values": {"female": [{"value": "14.2", "match_key": "simulated", "path": "simulated.update.female"}],
                                                 "male": [{"value": "11.8", "match_key": "simulated", "path": "simulated.update.male"}]}})
    t["has_results"] = True
    t["results_fingerprint"] = fixtures.fingerprint(t)
    src = store.q("SELECT source FROM trials WHERE nct_id=?", (nct,))
    store.save_trial(t, src[0]["source"] if src else "synthetic")   # keep a real trial in the real-data queue
    store.set_status(nct, "pending", None)
    store.log_event(None, "new_results", f"{nct}: simulated registry update; queued for re-audit")
    return t


def check_live_updates():
    """For each 'watch' trial, re-fetch and requeue if the results section changed."""
    changed = []
    for r in store.q("SELECT nct_id FROM queue WHERE status='watch'"):
        old = store.get_trial(r["nct_id"])
        if not old["nct_id"].startswith("NCT"):
            continue
        try:
            d = requests.get(f"{API}/{r['nct_id']}", timeout=30).json()
        except requests.RequestException:
            continue
        new = normalize_trial(d, old.get("condition", ""))
        if new["results_fingerprint"] != old.get("results_fingerprint"):
            store.save_trial(new, "live")
            store.set_status(r["nct_id"], "pending")
            changed.append(r["nct_id"])
    return changed


if __name__ == "__main__":
    store.init()
    if len(sys.argv) > 1 and sys.argv[1] == "--simulate":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        if not target:
            rows = store.q("SELECT nct_id FROM drafts WHERE kind='sex_stratified_results' AND status IN ('DRAFT','APPROVED') ORDER BY id LIMIT 1")
            target = rows[0]["nct_id"] if rows else None
        if not target:
            sys.exit("no open draft to follow up on; run an audit first")
        simulate_new_results(target)
        print("simulated new results for", target, "-> now run: python run_agent.py --no-ingest")
    else:
        print("changed:", check_live_updates())
