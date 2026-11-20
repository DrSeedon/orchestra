"""Export only allowlisted structural observations, keeping private logs intact."""

import json
from dataclasses import dataclass

from app import db
from app.secret_mask import mask_secrets
from .abi import NAME, canonical


@dataclass(frozen=True)
class TraceProjection:
    arguments: frozenset[str]
    result_fields: frozenset[str]


def _project(value, allowed, symbols):
    if not isinstance(value, dict) or not set(value) <= allowed:
        raise ValueError("unknown_trace_shape")
    projection = {}
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            raise ValueError("unprojectable_trace_field")
        encoded = canonical(item)
        # Equality is scoped to a single observation. No raw scalar leaves here.
        projection[key] = symbols.setdefault(encoded, f"${len(symbols) + 1}")
    return projection


def observe(invocation_id, *, skill, request_shape, projections, success, record=False):
    """Return a private compiler projection, or an explicit ineligible reason.

    The caller owns the canonical skill and trusted per-tool projection definitions.
    success checks the subject-specific outcome on the private journal rows.
    record stores source pointers for an eligible trace in the capsule registry.
    """
    if not isinstance(skill, str) or not NAME.fullmatch(skill):
        return {"eligible": False, "reason": "unknown_skill"}
    with db._conn() as conn:
        conn.execute("BEGIN")
        turn = conn.execute(
            "SELECT * FROM turn_usage WHERE invocation_id=?", (invocation_id,),
        ).fetchone()
        if turn is None:
            return {"eligible": False, "reason": "no_terminal_lineage"}
        rows = conn.execute(
            "SELECT * FROM logs WHERE invocation_id=? ORDER BY invocation_seq", (invocation_id,),
        ).fetchall()
        usage = conn.execute(
            "SELECT normalized_json FROM turn_usage_measurements WHERE event_id=?", (turn["event_id"],),
        ).fetchone()
        try:
            actions = _actions(turn, rows, projections)
            if not actions or not success(rows):
                raise ValueError("unverified_outcome")
            shape = _project(request_shape, frozenset({"intent", "window", "source"}), {})
        except (ValueError, TypeError, KeyError):
            return {"eligible": False, "reason": turn["invocation_exclusion"] or "ineligible_trace"}
    if record:
        _record(turn, rows, skill)
    result = {
        "eligible": True, "skill_ref": skill, "request_shape": shape, "actions": actions,
        "agent_observations": [], "outcome": "verified", "usage_ref": turn["event_id"],
        "usage": json.loads(usage[0]) if usage else None,
    }
    return json.loads(mask_secrets(canonical(result)))


def _record(turn, rows, skill):
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        identity = turn["invocation_id"]
        conn.execute(
            """INSERT INTO sc_invocation(id,scope,origin,session_ref,usage_ref,skill,eligible)
               VALUES (?,?,'orchestra',?,?,?,1)
               ON CONFLICT(id) DO UPDATE SET usage_ref=excluded.usage_ref, eligible=1
               WHERE sc_invocation.scope=excluded.scope AND sc_invocation.origin=excluded.origin
                 AND sc_invocation.session_ref=excluded.session_ref AND sc_invocation.skill=excluded.skill""",
            (identity, turn["scope"], f"orchestra:{turn['session_id']}", turn["event_id"], skill),
        )
        found = conn.execute(
            "SELECT usage_ref, eligible, skill FROM sc_invocation WHERE id=?", (identity,),
        ).fetchone()
        if tuple(found) == (turn["event_id"], 1, skill):
            conn.executemany(
                "INSERT OR IGNORE INTO sc_event(invocation_id,seq,source_ref) VALUES (?,?,?)",
                [(identity, row["invocation_seq"], str(row["id"])) for row in rows],
            )


def _actions(turn, rows, projections):
    if (turn["invocation_exclusion"] or not turn["ok"] or turn["stop_reason"] != "end_turn" or len(rows) != turn["invocation_events"]
            or not rows or len(rows) > 2048):
        raise ValueError("incomplete_turn")
    symbols = {}
    pending = {}
    actions = []
    for seq, row in enumerate(rows, 1):
        needed = row["tool_use_id"]
        if row["session_id"] != turn["session_id"] or row["invocation_seq"] != seq or not needed:
            raise ValueError("ambiguous_lineage")
        if row["type"] == "tool":
            if pending or any(needed == action[0] for action in actions):
                raise ValueError("overlapping_tools")
            name = row["tool_name"]
            schema = projections[name]
            raw = row["tool_raw_input_json"]
            if raw is None:
                prefix = name + ": "
                if not row["content"].startswith(prefix):
                    raise ValueError("missing_arguments")
                arguments = json.loads(row["content"][len(prefix):])
                if isinstance(arguments, dict) and arguments.get("_codex_item_id") == needed:
                    arguments.pop("_codex_item_id")
            else:
                arguments = json.loads(raw)
            args = _project(arguments, schema.arguments, symbols)
            pending[needed] = (seq, name, args)
        elif row["type"] == "tool_update":
            if needed not in pending:
                raise ValueError("orphan_update")
        elif row["type"] == "tool_result":
            start, name, args = pending.pop(needed)
            if row["tool_is_error"] != 0:
                raise ValueError("failed_tool")
            result = _project(json.loads(row["content"]), projections[name].result_fields, symbols)
            actions.append((needed, {"seq": start, "tool": name, "args": args, "result": result, "error": False}))
        else:
            raise ValueError("unknown_event")
    if pending:
        raise ValueError("missing_result")
    return [action for _, action in actions]

