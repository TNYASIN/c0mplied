"""LLM access. Every call goes through the supervisor guard first."""
import os, json, re, time
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
            r = self.client.messages.create(model=config.MODEL, max_tokens=400, system=system,
                                            messages=[{"role": "user", "content": user}])
            return r.content[0].text, r.usage.input_tokens, r.usage.output_tokens
        except self.anthropic.APIError:
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


class AuditLLM:
    def __init__(self, sup, backend):
        self.sup, self.backend, self.quality = sup, backend, "normal"

    def call(self, task, payload, variant="primary"):
        self.sup.pre_call(f"{task}|{variant}|{payload['nct_id']}")
        text, tin, tout = self.backend.complete(task, payload, variant, self.quality)
        self.sup.post_call(tin, tout)
        return parse_result(task, text)
