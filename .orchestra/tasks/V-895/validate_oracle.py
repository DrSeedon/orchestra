"""Frozen-oracle validation: closed tests must FAIL on pre-fix snapshot and PASS on the real fix; open rules
must accept a reference answer and reject decoys. Run before any model run."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from oracle import score
from tasks import TASKS
OUT = Path("/home/kesha/bench895")
REF = {
 "O1": "ROOT CAUSE: app.js _showAgentContextMenu calls PATCH /api/sessions/{name}/tg-topic, a duplicate handler toggle_tg_topic in routes/sessions.py that calls save_session(found.to_dict()) without session_id and returns HTTP 500; the working POST /tg_topic handler uses manager.update_session_fields.",
 "O2": "ROOT CAUSE: in WorkflowEngine.agent current_prompt starts as the bare prompt, the schema is added only after a schema_invalid retry, so the first answer is not JSON. Budget.exhausted() merges spent_usd>=maximum_usd with dispatched_calls>=maximum_calls (max_calls=3) and the retry branch writes 'budget' for both, so retries are deferred.",
 "O3": "ROOT CAUSE: mcp_stdio.get_worker_logs requests /logs with after_id=0 and no limit, then slices logs[-limit:] client-side; the route get_session_logs accepts limit but does not pass it to get_logs, so up to 5000 rows are returned.",
 "O4": "ROOT CAUSE: routes/system.py get_file_raw returns 404 when target.is_file() is false; the link points into the worker worktree which was removed on archival, and there is no fallback to the project checkout.",
}
DECOY = {
 "O1": "ROOT CAUSE: the CSS hides the menu item in app.js so clicks never register.",
 "O2": "ROOT CAUSE: the model returns bad JSON because the temperature is too high in wf_adapters.py.",
 "O3": "ROOT CAUSE: the SQLite logs table has no index so the query is slow in db.py.",
 "O4": "ROOT CAUSE: the browser caches the 404 response for the download link.",
}
ok = True
for t, spec in TASKS.items():
    if spec["kind"] == "open":
        a = score(t, REF[t], None)[0]; b = score(t, DECOY[t], None)[0]
        print(t, "ref accepted:", a, "decoy accepted:", b); ok &= a and not b
    else:
        pre, pl = score(t, "", OUT / "fx" / t); post, ql = score(t, "", OUT / "ref" / t)
        print(t, "pre-fix passes:", pre, "(want False)  fix passes:", post, "(want True)")
        if pre or not post: print(pl if pre else ql)
        ok &= (not pre) and post
print("VALID" if ok else "INVALID")
