import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Limits
from supervisor import Supervisor, BetaTracker, HaltRun, TaskLoop
from rules import norm


def test_beta_prior_tail():
    assert abs(BetaTracker(1, 9).p_exceeds(0.10) - 0.9 ** 9) < 1e-3   # closed form for Beta(1,9)


def test_posterior_moves_correctly():
    good, bad = BetaTracker(1, 9), BetaTracker(1, 9)
    for _ in range(20):
        good.update(False)
    for i in range(10):
        bad.update(i % 2 == 0)
    assert good.p_exceeds(0.10) < 0.1 < 0.8 < bad.p_exceeds(0.10)


def test_loop_is_task_then_run_fatal():
    s = Supervisor(Limits(loop_repeat=3, max_task_loops=2))
    s.pre_call("a"); s.pre_call("a")
    with pytest.raises(TaskLoop):
        s.pre_call("a")
    s.pre_call("b"); s.pre_call("b")
    with pytest.raises(HaltRun) as e:
        s.pre_call("b")
    assert e.value.code == "LOOP"


def test_budget_halts_and_disabled_supervisor_only_has_emergency_cap():
    s = Supervisor(Limits(max_tokens=100))
    s.post_call(80, 40)
    with pytest.raises(HaltRun) as e:
        s.pre_call("x")
    assert e.value.code == "TOKEN_BUDGET"
    off = Supervisor(Limits(max_tokens=1, emergency_calls=3), enabled=False)
    off.post_call(500, 500)
    off.pre_call("x")
    for _ in range(3):
        off.post_call(1, 1)
    with pytest.raises(HaltRun) as e2:
        off.pre_call("y")
    assert e2.value.code == "EMERGENCY_CAP"


def test_stuck_detector():
    s = Supervisor(Limits(stuck_batches=2))
    s.after_batch(0, 0)
    with pytest.raises(HaltRun) as e:
        s.after_batch(1, 0)
    assert e.value.code == "STUCK"


def test_quote_grounding_normalization():
    assert norm("* Pregnant  or\nbreastfeeding women") == norm("Pregnant or breastfeeding women")
