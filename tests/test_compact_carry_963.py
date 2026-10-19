"""V-963: the compaction prompts must name the same previous-handoff marker the platform emits.

The prompts tell the compactor how to treat the first journal row (the previous handoff). If the header
that `AgentSession.compact()` writes or that `db.get_compact_segment()` searches for drifts away from the
marker the prompts mention, the instruction silently stops matching anything. The behaviour itself
(carry-forward, cancellation) is measured by the V-963 stand, not asserted on wording here.
"""

import ast
import inspect
from pathlib import Path

from app import agentic_compact, db
from app import session as session_module
from app.session import _compact_prompt


def _session_preamble() -> str:
    tree = ast.parse(Path(session_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "PREAMBLE" for t in node.targets)
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("PREAMBLE not found in app/session.py")


def test_prompts_name_the_marker_session_and_db_use(tmp_path):
    marker = agentic_compact.PREVIOUS_SUMMARY_MARKER

    assert _session_preamble().startswith(marker)
    assert f"{marker}%" in inspect.getsource(db.get_compact_segment)
    for prompt in (
        agentic_compact.audit_prompt(tmp_path / "journal", tmp_path / "summary.md"),
        agentic_compact.final_prompt(tmp_path / "journal", tmp_path / "summary.md"),
    ):
        assert marker in prompt
    assert marker.lstrip("[") in _compact_prompt("s", "")
