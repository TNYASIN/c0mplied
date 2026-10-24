"""Measured accuracy vs a hand-labeled gold set. THIS is the number to put on your slide.

  python eval_gold.py --template 30            # export cached trials to label by hand
  python eval_gold.py --gold data/gold_set.json
  python eval_gold.py --synthetic 40           # offline: gold from synthetic ground truth
"""
import argparse, csv, json
import store, fixtures
from config import Limits
from supervisor import Supervisor
from llm import AuditLLM, get_backend
from auditor import audit_trial
from rules import elig_candidates, strat_payload_lines

p = argparse.ArgumentParser()
p.add_argument("--template", type=int)
p.add_argument("--gold", default="data/gold_set.json")
p.add_argument("--synthetic", type=int)
p.add_argument("--llm", default="auto")
a = p.parse_args()
store.init()

if a.template:
    rows = store.q("SELECT nct_id FROM trials WHERE source='live' LIMIT ?", (a.template,))
    with open("data/gold_template.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nct_id", "eligibility_lines", "outcome_lines", "eligibility_label", "sex_stratified_label"])
        for r in rows:
            t = store.get_trial(r["nct_id"])
            w.writerow([t["nct_id"], " || ".join(l for _, l in elig_candidates(t["eligibility_text"])),
                        " || ".join(strat_payload_lines(t)[1]), "", ""])
    print("wrote data/gold_template.csv. Fill the label columns using:")
    print("  eligibility: BLANKET_EXCLUSION_CHILDBEARING | PREGNANCY_LACTATION_EXCLUSION | CONDITIONAL | NONE")
    print("  sex_stratified: STRATIFIED_FOUND | NOT_FOUND_IN_RECORD | NO_RESULTS_POSTED  (then save as data/gold_set.json)")
    raise SystemExit

if a.synthetic:
    trials, truth = fixtures.make_synthetic(a.synthetic)
    for t in trials:
        store.save_trial(t, "synthetic")
    gold = [{"nct_id": k, "eligibility": v["eligibility_exclusion"], "sex_stratified": v["sex_stratified_results"]}
            for k, v in truth.items()]
else:
    gold = json.load(open(a.gold))

lim = Limits(emergency_calls=10 ** 9)
llm = AuditLLM(Supervisor(lim, enabled=False), get_backend(a.llm))
hit = {"eligibility": 0, "sex_stratified": 0}
misses = []
for g in gold:
    vs = {v["chk"]: v["label"] for v in audit_trial(store.get_trial(g["nct_id"]), llm)}
    for key, chk in (("eligibility", "eligibility_exclusion"), ("sex_stratified", "sex_stratified_results")):
        if vs[chk] == g[key]:
            hit[key] += 1
        else:
            misses.append({"nct_id": g["nct_id"], "check": chk, "gold": g[key], "got": vs[chk]})
acc = {k: v / len(gold) for k, v in hit.items()}
json.dump({"n": len(gold), "accuracy": acc, "misses": misses}, open("data/gold_eval.json", "w"), indent=1)
print(f"gold n={len(gold)} | " + " | ".join(f"{k}: {v:.1%}" for k, v in acc.items()))
for m in misses[:10]:
    print("  miss:", m)
if a.synthetic:
    print("NOTE: synthetic gold only tests plumbing. Report accuracy on your HAND-LABELED real-trial gold set.")
