"""Exercise upstream support-desk tools directly; no model, no Orchestra runtime."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

TASK = Path(__file__).resolve().parents[1]
KIT = TASK / "upstream/kit"
sys.path.insert(0, str(KIT / "examples/support-desk"))
sys.path.insert(1, str(KIT))
os.environ["KIT_MODEL"] = "fake"

from app.backend import Backend
from single_loop.agent import Conversation, checked_response


class NoModel:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise AssertionError("This exemplar must never call a model")


def show(label, value):
    print(json.dumps({"case": label, "output": value}, sort_keys=True))


def conversation(backend, customer, approve):
    return Conversation(backend, customer_id=customer, client=NoModel(), approve=approve)


backend = Backend()
conv = conversation(backend, "C-1001", lambda name, args: True)
lookup = conv.rt.backend.get_order("5002")
assert "eta" not in lookup
show("lookup alone has no carrier ETA", {"status": lookup["status"], "has_eta": "eta" in lookup})
tracked = conv.agent.tools["track_order"].run({"order_id": "5002"})
assert tracked["shipment"]["eta"] == "2026-10-03"
show("real track_order composes two backend reads", {"eta": tracked["shipment"]["eta"]})
show("foreign record refused", conv.agent.tools["track_order"].run({"order_id": "5003"}))
assert "error" in conv.agent.tools["track_order"].run({"order_id": "5003"})

for customer, order in [("C-1002", "5003"), ("C-1004", "5008")]:
    b = Backend()
    c = conversation(b, customer, lambda name, args: True)
    result = c.agent.tools["start_return"].run({"order_id": order, "reason": "other"})
    assert result["created"] is False and b.actions == []
    show("return refused by real tool", result)

call = SimpleNamespace(name="start_return", id="demo-call", input={"order_id": "5001", "reason": "other"})
b = Backend()
c = conversation(b, "C-1001", lambda name, args: False)
result = c.agent._execute(call)
assert "declined" in result["content"] and b.actions == []
show("write gate declines eligible return", result)
c = conversation(b, "C-1001", lambda name, args: True)
result = c.agent._execute(call)
assert len(b.actions) == 1 and json.loads(result["content"])["created"] is True
show("write gate permits eligible return", {"actions": b.actions, "result": json.loads(result["content"])})

missing = conv.agent.tools["diagnose_device"].run({})
assert "error" in missing
show("required serial refused before any model", missing)
malformed = checked_response("Demo specialist returned prose")
assert malformed["confidence"] == "low" and malformed["caveats"]
show("malformed specialist response flagged", malformed)
try:
    checked_response(" ")
except ValueError as exc:
    show("empty specialist response refused", str(exc))
else:
    raise AssertionError("Empty result was accepted")
print("MANUAL SAMPLE OK; model calls=0; network calls=0; backend is an in-memory public fixture")
