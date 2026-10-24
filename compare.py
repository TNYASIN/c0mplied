"""Same sabotage, with and without the supervisor. Produces the headline numbers for the pitch."""
import json, os, tempfile
import config, store, fixtures, agent

LIMIT = 40


def one(scenario, supervised):
    config.DB_PATH = os.path.join(tempfile.mkdtemp(), "cmp.db")
    config.REPORT_DIR = tempfile.mkdtemp()
    res = agent.run(scenario, limit=LIMIT, offline=True, supervised=supervised, llm_mode="mock", verbose=False)
    _, truth = fixtures.make_synthetic(LIMIT, 7)
    rows = store.q("SELECT v.* FROM verdicts v JOIN (SELECT nct_id,chk,MAX(id) mid FROM verdicts GROUP BY nct_id,chk) m ON v.id=m.mid "
                   "WHERE v.chk IN ('eligibility_exclusion','sex_stratified_results')")
    pub = [r for r in rows if r["verified"] == 1 and r["quarantined"] == 0]
    wrong = [r for r in pub if r["label"] != truth[r["nct_id"]][r["chk"]]]
    s = res["snapshot"]
    return {"scenario": scenario, "supervisor": supervised, "status": res["status"], "calls": s["calls"],
            "tokens": s["tokens"], "cost_usd": s["cost"], "published": len(pub), "wrong_published": len(wrong),
            "withheld": len(rows) - len(pub)}


if __name__ == "__main__":
    out = [one(sc, sup) for sc in ("sabotage", "loop") for sup in (False, True)]
    json.dump(out, open("data/compare.json", "w"), indent=1)
    print(f"{'scenario':9} {'supervisor':10} {'status':20} {'calls':>6} {'tokens':>9} {'cost':>7} {'published':>9} {'WRONG':>6} {'withheld':>8}")
    for r in out:
        print(f"{r['scenario']:9} {str(r['supervisor']):10} {r['status']:20} {r['calls']:>6} {r['tokens']:>9,} "
              f"${r['cost_usd']:>6.3f} {r['published']:>9} {r['wrong_published']:>6} {r['withheld']:>8}")
