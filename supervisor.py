"""The supervisor: the part of this project the Unsupervised track actually judges.

Detects and acts on: OVERSPEND (tokens/calls/cost/time), LOOPS (identical calls, repeated
fetch pages), STUCK (batches with no resolved trials), and UNRELIABILITY (Beta-Binomial
posterior on measured error rates). Every halt carries a code, a reason and a handoff report.
"""
import time, math
from collections import Counter
from dataclasses import asdict
from config import Limits, PRICE_IN, PRICE_OUT


class HaltRun(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code, self.reason = code, reason


class TaskLoop(Exception):
    """Non-fatal: this one task is looping. Skip it. Too many of these -> HaltRun(LOOP)."""


class BetaTracker:
    """Error-rate posterior. Prior Beta(a0,b0); failures raise alpha, passes raise beta."""

    def __init__(self, a0, b0):
        self.a0, self.b0, self.errors, self.passes = a0, b0, 0, 0

    n = property(lambda s: s.errors + s.passes)
    alpha = property(lambda s: s.a0 + s.errors)
    beta = property(lambda s: s.b0 + s.passes)
    mean = property(lambda s: s.alpha / (s.alpha + s.beta))

    def update(self, failed):
        if failed:
            self.errors += 1
        else:
            self.passes += 1

    def p_exceeds(self, thr, steps=2000):
        """P(error_rate > thr) by midpoint integration of the Beta pdf (no scipy needed)."""
        a, b = self.alpha, self.beta
        lg = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        h = (1 - thr) / steps
        tot = 0.0
        for i in range(steps):
            x = thr + (i + 0.5) * h
            tot += math.exp(lg + (a - 1) * math.log(x) + (b - 1) * math.log(1 - x))
        return min(1.0, tot * h)


class Supervisor:
    def __init__(self, limits=None, enabled=True):
        self.l = limits or Limits()
        self.enabled = enabled
        self.t0 = time.monotonic()
        self.tok_in = self.tok_out = self.calls = 0
        self.sigs = Counter()
        self.task_loops = 0
        self.trackers = {k: BetaTracker(self.l.prior_alpha, self.l.prior_beta)
                         for k in ("grounding", "recheck")}
        self.batches = []          # [{"idx", "fails", "resolved"}]
        self.last_clean = -1
        self.no_progress = 0
        self.halt = None

    # ---- accounting -------------------------------------------------------
    @property
    def tokens(self):
        return self.tok_in + self.tok_out

    @property
    def cost(self):
        return self.tok_in / 1e6 * PRICE_IN + self.tok_out / 1e6 * PRICE_OUT

    @property
    def elapsed(self):
        return time.monotonic() - self.t0

    def post_call(self, tin, tout):
        self.calls += 1
        self.tok_in += tin
        self.tok_out += tout

    # ---- guards (called BEFORE every external action) ----------------------
    def check_budget(self):
        if not self.enabled:
            if self.calls >= self.l.emergency_calls:  # so the demo baseline terminates
                raise HaltRun("EMERGENCY_CAP", f"{self.calls} calls with no supervisor; emergency cap hit")
            return
        l = self.l
        if self.tokens >= l.max_tokens:
            raise HaltRun("TOKEN_BUDGET", f"{self.tokens:,} tokens used (cap {l.max_tokens:,})")
        if self.calls >= l.max_calls:
            raise HaltRun("CALL_BUDGET", f"{self.calls} LLM calls (cap {l.max_calls})")
        if self.cost >= l.max_cost_usd:
            raise HaltRun("COST_BUDGET", f"~${self.cost:.2f} spent (cap ${l.max_cost_usd:.2f})")
        if self.elapsed >= l.max_seconds:
            raise HaltRun("TIME_LIMIT", f"{self.elapsed:.0f}s elapsed (cap {l.max_seconds}s)")

    check_time = check_budget

    def pre_call(self, sig):
        self.check_budget()
        self.sigs[sig] += 1
        if self.enabled and self.sigs[sig] >= self.l.loop_repeat:
            self.task_loops += 1
            if self.task_loops >= self.l.max_task_loops:
                raise HaltRun("LOOP", f"{self.task_loops} tasks stuck repeating identical calls (last: {sig})")
            raise TaskLoop(sig)

    def note_fetch(self, sig):
        self.sigs[sig] += 1
        if self.enabled and self.sigs[sig] >= self.l.loop_repeat:
            raise HaltRun("LOOP", f"same fetch repeated {self.sigs[sig]}x ({sig})")

    # ---- verification observations ----------------------------------------
    def observe(self, tracker, failed):
        self.trackers[tracker].update(failed)
        self._batch_fails = getattr(self, "_batch_fails", 0) + (1 if failed else 0)

    def after_batch(self, idx, resolved):
        fails = getattr(self, "_batch_fails", 0)
        self._batch_fails = 0
        self.batches.append({"idx": idx, "fails": fails, "resolved": resolved})
        if fails == 0:
            self.last_clean = idx
        self.no_progress = 0 if resolved > 0 else self.no_progress + 1
        if not self.enabled:
            return
        for name, t in self.trackers.items():
            if t.n >= self.l.min_observations:
                p = t.p_exceeds(self.l.error_threshold)
                if p >= self.l.halt_probability:
                    raise HaltRun("ERROR_RATE",
                                  f"{name} check: {t.errors}/{t.n} failures; P(error rate > "
                                  f"{self.l.error_threshold:.0%}) = {p:.2f} >= {self.l.halt_probability:.2f}")
        if self.no_progress >= self.l.stuck_batches:
            raise HaltRun("STUCK", f"{self.no_progress} consecutive batches resolved zero trials")
        self.check_budget()

    # ---- observability -----------------------------------------------------
    def snapshot(self):
        tr = {}
        for k, t in self.trackers.items():
            tr[k] = {"n": t.n, "errors": t.errors, "mean": round(t.mean, 3),
                     "p_exceeds": round(t.p_exceeds(self.l.error_threshold), 3)}
        return {"enabled": self.enabled, "elapsed": round(self.elapsed, 1), "tokens": self.tokens,
                "calls": self.calls, "cost": round(self.cost, 4), "limits": asdict(self.l),
                "trackers": tr, "task_loops": self.task_loops, "no_progress": self.no_progress,
                "batches": len(self.batches), "last_clean_batch": self.last_clean,
                "halt": self.halt}
