"""Delivery check for the two public review claims changed by #513."""

from pathlib import Path


root = Path(__file__).resolve().parents[3]
text = (root / "README.md").read_text(encoding="utf-8")
comparison = text.split('<a id="comparison"></a>', 1)[1].split("## Features", 1)[0]

required = "An orchestrator can review a target worker's exact snapshot without waking that worker"
old_limit = (
    "the receipt is matched by the worker's own session id, so an orchestrator cannot "
    "certify a review on the worker's behalf"
)
stale_enforcement = "is not yet enforced by the merge code"

missing = []
if required not in comparison:
    missing.append("target-worker review capability is absent from the comparison row")
if old_limit in comparison:
    missing.append("closed target-worker limitation is still published")
if stale_enforcement in text:
    missing.append("README still says the merge gate is not enforced")

if missing:
    raise SystemExit("README #513 delivery failed: " + "; ".join(missing))

print("README #513 delivery OK: target review and enforced merge gate are current")
