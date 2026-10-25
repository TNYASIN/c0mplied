"""LLM access. Every call goes through the supervisor guard first."""
import os, json, random, re, time
import config, prompts
from rules import ELIG_LABELS, STRAT_LABELS
from mock_llm import MockBackend


class AnthropicBackend:
    name = "anthropic"

    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()

    def complete(self, task, payload, variant, quality):
        system, user = prompts.build(task, payload, variant, quality)
        try:
            # Short JSON labels need little reasoning. Current models think by default, and thinking can
            # use up max_tokens and leave no answer (which then looks like a loop): keep effort low and
            # leave room to finish.
            r = self.client.messages.create(model=config.MODEL, max_tokens=2048, system=system,
                                            messages=[{"role": "user", "content": user}],
                                            output_config={"effort": "low"})
            if r.stop_reason != "end_turn":
                print(f"  [llm] stop_reason={r.stop_reason} for {payload.get('nct_id')}", flush=True)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")   # skip thinking blocks
            return text, r.usage.input_tokens, r.usage.output_tokens
        except self.anthropic.APIError as e:
            print(f"  [llm] API error: {type(e).__name__}: {str(e)[:300]}", flush=True)
            time.sleep(2)               # transient failure -> counted as an invalid reply;
            return "", 0, 0             # repeated identical failures get caught as a loop


def get_backend(mode="auto"):
    if mode == "mock":
        return MockBackend()
    if mode == "anthropic" or (mode == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        try:
            return AnthropicBackend()
        except ImportError:
            if mode == "anthropic":
                raise
    return MockBackend()


def parse_result(task, text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    allowed = ELIG_LABELS if task == "eligibility" else STRAT_LABELS
    if d.get("label") not in allowed:
        return None
    d["evidence_quote"] = str(d.get("evidence_quote") or "")
    try:
        d["confidence"] = float(d.get("confidence", 0.5))
    except (TypeError, ValueError):
        d["confidence"] = 0.5
    return d


FAULT_P = 0.6   # same rate as mock_llm.DEGRADE_P
FAKE_QUOTE = {"eligibility": "Pregnant women and women of childbearing potential are not eligible for enrollment.",
              "stratified": "Efficacy outcomes were analyzed separately for female and male participants."}
FAKE_LABEL = {"eligibility": "BLANKET_EXCLUSION_CHILDBEARING", "stratified": "STRATIFIED_FOUND"}


def inject_fault(task, text, quality, rng):
    """Demo fault injection for a real model: corrupt its answer the way a failing model would.
    Asking Claude to misbehave in the prompt is unreliable (it keeps quoting verbatim), so the
    'Break it' scenarios inject faults deterministically here instead. The supervisor sees only the result."""
    if quality == "garbage":
        return "Sure! Having looked through the record carefully, I think this trial is mostly fine overall."
    if quality == "unclear":
        return json.dumps({"label": "UNCLEAR", "evidence_quote": "", "confidence": 0.2})
    if quality == "degraded" and rng.random() < FAULT_P:
        return json.dumps({"label": FAKE_LABEL[task], "evidence_quote": FAKE_QUOTE[task], "confidence": 0.9})
    return text


class AuditLLM:
    def __init__(self, sup, backend):
        self.sup, self.backend, self.quality = sup, backend, "normal"
        self.rng = random.Random(7)

    def call(self, task, payload, variant="primary"):
        self.sup.pre_call(f"{task}|{variant}|{payload['nct_id']}")
        injected = self.backend.name != "mock" and self.quality != "normal" and variant == "primary"
        text, tin, tout = self.backend.complete(task, payload, variant, "normal" if injected else self.quality)
        self.sup.post_call(tin, tout)
        if injected:
            text = inject_fault(task, text, self.quality, self.rng)
        return parse_result(task, text)
