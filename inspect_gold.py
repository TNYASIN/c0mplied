"""Print a compact, source-path-aware review sheet for frozen API records."""
import json
import re
from pathlib import Path

from rules import elig_candidates

ROOT = Path("data/real_gold")
SEX = re.compile(r"\b(sex|gender|female|male|women|men|pregnan|lactat|breastfeed|childbearing|contracept)\b", re.I)


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for row in manifest["records"]:
        d = json.loads((ROOT / (row["nct_id"] + ".json")).read_text(encoding="utf-8"))
        p = d["protocolSection"]
        e = p.get("eligibilityModule", {}).get("eligibilityCriteria", "")
        res = d.get("resultsSection", {})
        outcomes = res.get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
        bases = res.get("baselineCharacteristicsModule", {}).get("measures", [])
        print("\n###", row["nct_id"], row["condition_query"], "results=", row["has_results"],
              "outcomes=", len(outcomes), "baseline=", len(bases), "score=", row["outcome_sex_term_score"])
        print("title:", p.get("identificationModule", {}).get("briefTitle", "")[:120])
        print("elig candidates:")
        for section, line in elig_candidates(e):
            print(" ", section, repr(line[:220]))
        print("baseline sex measures:")
        for i, m in enumerate(bases):
            if SEX.search(m.get("title", "")):
                print(" ", i, repr(m.get("title")), "classes=", len(m.get("classes", [])),
                      "data=", any(cat.get("measurements") for c in m.get("classes", []) for cat in c.get("categories", [])))
        print("outcome sex signals:")
        for i, m in enumerate(outcomes):
            parts = [(f"{k}", str(m.get(k, ""))) for k in ("title", "description", "reportingStatus")]
            parts += [(f"groups[{j}].title", g.get("title", "")) for j, g in enumerate(m.get("groups", []))]
            parts += [(f"classes[{j}].title", c.get("title", "")) for j, c in enumerate(m.get("classes", []))]
            parts += [(f"classes[{j}].categories[{k}].title", cat.get("title", ""))
                      for j, c in enumerate(m.get("classes", [])) for k, cat in enumerate(c.get("categories", []))]
            parts += [(f"analyses[{j}].groupDescription", a.get("groupDescription", ""))
                      for j, a in enumerate(m.get("analyses", []))]
            found = [(k, v[:220]) for k, v in parts if SEX.search(v)]
            if found:
                print(" ", i, repr(m.get("title", "")[:100]), "hits=", found,
                      "groups=", [(g.get("id"), g.get("title")) for g in m.get("groups", [])],
                      "measurements=", sum(len(cat.get("measurements", [])) for c in m.get("classes", []) for cat in c.get("categories", [])))


if __name__ == "__main__":
    main()
