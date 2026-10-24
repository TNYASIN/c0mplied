"""Central configuration. Every number here is an editable assumption."""
import os
from dataclasses import dataclass

DB_PATH = os.environ.get("HEREVIDENCE_DB", "data/herevidence.db")
REPORT_DIR = os.environ.get("HEREVIDENCE_REPORTS", "reports")
MODEL = os.environ.get("HEREVIDENCE_MODEL", "claude-sonnet-5-5")
# Price assumptions for the spend gauge only. Check current pricing and edit.
PRICE_IN = float(os.environ.get("PRICE_IN_PER_MTOK", 3.0))
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_MTOK", 15.0))


@dataclass
class Limits:
    # budgets (overspend detector)
    max_tokens: int = 150_000
    max_calls: int = 300
    max_cost_usd: float = 2.00
    max_seconds: int = 900
    # batching / verification
    batch_size: int = 5
    rechecks_per_batch: int = 3
    # statistical stopping rule (Beta-Binomial)
    error_threshold: float = 0.10     # tolerated error rate
    halt_probability: float = 0.80    # halt if P(rate > threshold) >= this
    prior_alpha: float = 1.0          # Beta(1, 9): expect ~10% errors, weakly
    prior_beta: float = 9.0
    min_observations: int = 6
    # loop / stuck detectors
    loop_repeat: int = 3              # identical call this many times = loop
    max_task_loops: int = 3           # this many looped tasks halts the run
    stuck_batches: int = 3            # batches with zero resolved trials
    # retries / safety
    max_attempts_per_trial: int = 3
    emergency_calls: int = 150        # only used when supervisor is DISABLED
