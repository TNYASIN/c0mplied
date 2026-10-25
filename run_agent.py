import argparse
import agent

p = argparse.ArgumentParser(description="HerEvidence autonomous audit agent")
p.add_argument("--scenario", default="normal", choices=list(agent.SCENARIOS))
p.add_argument("--live", action="store_true", help="fetch real trials from ClinicalTrials.gov (default: synthetic offline)")
p.add_argument("--limit", type=int, default=40)
p.add_argument("--conditions", default="", help="comma-separated, live mode only")
p.add_argument("--llm", default="auto", choices=["auto", "mock", "anthropic"])
p.add_argument("--no-supervisor", action="store_true", help="baseline: agent with no verification or guards")
p.add_argument("--no-ingest", action="store_true", help="resume/re-audit the existing queue only")
p.add_argument("--seed", type=int, default=7)
p.add_argument("--max-tokens", type=int)
p.add_argument("--max-cost", type=float)
p.add_argument("--pace", type=float, default=0.0, help="seconds to pause after each trial (to watch a demo run)")
p.add_argument("--no-pubmed", action="store_true", help="live mode: skip the PubMed cross-check of linked publications")
a = p.parse_args()
ov = {k: v for k, v in (("max_tokens", a.max_tokens), ("max_cost_usd", a.max_cost)) if v is not None}
agent.run(a.scenario, [c.strip() for c in a.conditions.split(",") if c.strip()] or None, a.limit,
          offline=not a.live, supervised=not a.no_supervisor, ingest_data=not a.no_ingest,
          seed=a.seed, llm_mode=a.llm, overrides=ov, pace=a.pace, with_pubmed=not a.no_pubmed)
