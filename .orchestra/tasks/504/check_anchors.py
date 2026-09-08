#!/usr/bin/env python3
"""До-реализационная инвентаризация на 1b795300, текущий код не проверяет.

RETRACTED: любые прежние претензии на проверку текущего main отменены #530.
После 264daeb75484bbe9f97e53c654180fca11c8a12a площадки закрыты иначе.
Числа и якоря относятся только к историческому снимку; полнота отдельно
обоснована в source-to-sink.md. Якоря намеренно не обновлены под main.
"""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESEARCH_SNAPSHOT = "1b795300"


def snapshot_lines(relative: str) -> list[str]:
    return subprocess.check_output(
        ["git", "show", f"{RESEARCH_SNAPSHOT}:{relative}"],
        cwd=ROOT,
        text=True,
    ).splitlines()

# Each tuple is (class, path, one-based line, literal substring on that line).
# A/B are the report rows. C is the provenance-checked exclusion inventory.
ROWS = [
    ("A", "app/session.py", 248, '"monthly spend limit"'),
    ("A", "app/session.py", 250, "if any(marker in lowered"),
    ("A", "app/session.py", 284, "return lowered.startswith(_SAFEGUARD_PREFIX)"),
    ("A", "app/session.py", 3013, "and any(pattern in summary_lower"),
    ("A", "app/tool_call_guard.py", 27, "return sum(bool(pattern.search(prose))"),
    ("A", "app/bg_jobs.py", 54, "if _BLIND_REVIEW.search(artifact)"),
    ("A", "app/mcp_stdio.py", 3590, 'pattern.search(str(item.get("text", "")))'),
    ("A", "app/harness/loop.py", 209, 'startswith("[round guard]")'),
    ("A", "app/harness/loop.py", 211, 'startswith("[round guard]")'),
    ("A", "app/static/js/chat.js", 794, "pattern.test(prose)"),
    ("B", "app/turn_markers.py", 8, "value == SILENT_TURN_MARKER"),
    ("B", "app/static/js/app.js", 440, "content === SILENT_TURN_MARKER"),
    ("B", "app/bg_jobs.py", 56, "_REVIEW_VERDICT.search(artifact) is None"),
    ("B", "app/bg_jobs.py", 1022, "re.search(success_pattern, artifact) is None"),
    ("B", "app/codex_review_artifact.py", 73, "match = re.search"),
    ("B", "app/codex_review_artifact.py", 206, "if require_verdict and re.search"),
    ("B", "app/review_coverage.py", 149, "FINDING_RE.finditer(last_round)"),
    ("B", "app/review_coverage.py", 156, "FINDING_HEADING_RE.match(line)"),
    ("B", "app/routes/sessions.py", 968, "task_match = re.match"),
    ("C", "app/session.py", 195, '"locked" in str(error).lower()'),
    ("C", "app/session.py", 2525, '"rate_limit" in event.content'),
    ("C", "app/session_turns.py", 406, 'startswith("[ede_diagnostic]")'),
    ("C", "app/session_turns.py", 409, 'str(error).lower() == "rate_limit"'),
    ("C", "app/backend_claude.py", 1037, "any(marker in detail for marker in markers)"),
    ("C", "app/backend_codex.py", 2523, "any(part in message for part in"),
    ("C", "app/backend_grok.py", 1320, "any(part in message for part in"),
    ("C", "app/bg_jobs.py", 815, "re.search(pattern, raw_output) is None"),
    ("C", "app/bg_jobs.py", 863, "re.search(pattern, text)"),
    ("C", "app/bg_jobs.py", 896, "re.search(pattern, output)"),
    ("C", "app/bg_jobs.py", 920, "re.search(pattern, text)"),
    ("C", "app/harness/llm.py", 381, 'line.startswith("data:")'),
    ("C", "app/harness/llm.py", 386, 'payload == "[DONE]"'),
    ("C", "app/harness/loop.py", 319, 'result.startswith("[")'),
    ("C", "app/harness/tools.py", 257, 'result.startswith("wrote")'),
    ("C", "app/harness/tools.py", 548, 'rendered.startswith("[todo error]")'),
    ("C", "app/merge_test_gate.py", 389, 're.search(r"No module named'),
    ("C", "app/merge_test_gate.py", 396, '"unrecognized arguments" in output'),
    ("C", "app/workspace.py", 1114, '"nothing to commit" in cp_err'),
    ("C", "app/workspace.py", 2862, 'line.startswith("CONFLICT")'),
    ("C", "app/workspace.py", 2864, 're.search(r"Merge conflict in (.+)$"'),
    ("C", "app/fan_barrier.py", 58, "message.startswith(prefix)"),
    ("C", "app/tg_bridge.py", 163, "_ATTENTION_RESULT_RE.search"),
    ("C", "app/tg_bridge.py", 1625, '"type=local_bash" in content'),
    ("C", "app/tg_bridge.py", 2228, '"message is not modified" in str(e).lower()'),
    ("C", "app/tg_bridge.py", 2251, '"message is not modified" in str(e).lower()'),
    ("C", "app/tg_bridge.py", 2273, '"message is not modified" in str(e).lower()'),
    ("C", "app/tg_bridge.py", 2410, '"message is not modified" in str(e).lower()'),
    ("C", "app/tg_bridge.py", 2999, '"TOPIC_NOT_MODIFIED" in str(e).upper()'),
    ("C", "app/tg_bridge.py", 3420, "'type': 'image'"),
    ("C", "app/routes/tm.py", 266, '"not found" in str(e).lower()'),
    ("C", "app/routes/tm.py", 336, '"not found" in str(e).lower()'),
    ("C", "app/merge_operations.py", 574, 'startswith("attestation_")'),
    ("C", "app/merge_operations.py", 1295, '"target working tree is dirty" in lower'),
    ("C", "app/merge_operations.py", 1408, '"working tree is dirty" in message.lower()'),
    ("C", "app/merge_operations.py", 1489, '"rollback" in message.lower()'),
    ("C", "app/limit_wake.py", 63, 'startswith("turn ended")'),
    ("C", "app/limit_wake.py", 76, '"stop_sequence" not in latest["content"]'),
    ("C", "app/limit_wake.py", 87, '"subscription limit — ждём сброса квоты"'),
    ("C", "app/db.py", 871, "_re.search(r'\\$(\\d+\\.?\\d*)'"),
    ("C", "app/static/js/app.js", 283, "/\\b(error|failed|rejected|unknown)\\b/i.test"),
    ("C", "app/static/js/app.js", 3636, "content.match(/rate limited"),
    ("C", "app/static/js/tool-renderers.js", 489, "text.match(/^(.+?):(\\d+):(.*)$/)"),
    ("C", "app/static/js/tool-renderers.js", 491, "text.match(/^(\\d+):(.*)$/)"),
    ("C", "app/static/js/tool-renderers.js", 702, "raw.match(/^_(.*?\\|.*?tokens"),
    ("C", "app/static/js/tool-renderers.js", 703, "raw.match(/^#{1,3}\\s/m)"),
    ("C", "app/static/js/tool-renderers.js", 760, "text.slice(i).match"),
    ("C", "app/static/js/tool-renderers.js", 770, "text.startsWith('{')"),
    ("C", "app/static/js/tool-renderers.js", 783, "text.includes(`'${key}':`)"),
    ("C", "app/static/js/chat.js", 1853, "clean.includes('error')"),
    ("C", "app/static/js/chat.js", 1858, "/error|fail/i.test(clean)"),
    ("C", "app/static/js/chat.js", 1861, "clean.match(/sent to"),
    ("C", "app/static/js/chat.js", 1866, "clean.match(/(\\d+)%/)"),
    ("C", "app/static/js/chat.js", 1882, "clean.includes('error')"),
    ("C", "app/static/js/chat.js", 1891, "clean.match(/tool_name"),
    ("C", "app/static/js/chat.js", 1899, "clean.toLowerCase().includes('error')"),
    ("C", "app/static/js/chat.js", 1941, "content?.startsWith('precompact timer')"),
    ("C", "app/static/js/chat.js", 1942, "/^codex hook .+"),
    ("C", "app/static/js/chat.js", 1943, "/^codex mcp .+"),
    ("C", "app/static/js/chat.js", 1944, "/^compact started"),
    ("C", "app/static/js/chat.js", 1946, "/^grok mcp ready"),
    ("C", "app/static/js/chat.js", 1955, "(content || '').match"),
    ("C", "app/static/js/chat.js", 1959, "content.startsWith('codex reconnecting:')"),
    ("C", "app/static/js/chat.js", 1961, "content.startsWith('model rerouted:')"),
    ("C", "app/static/js/chat.js", 1962, "content.startsWith('codex hook ')"),
    ("C", "app/static/js/chat.js", 1963, "content.startsWith('codex mcp ')"),
    ("C", "app/static/js/chat.js", 1964, "content.includes('codex context compact')"),
    ("C", "app/static/js/chat.js", 2049, "/^\\w+$/.test"),
    ("C", "app/static/js/chat.js", 2957, "content.match(/<tool_use_error>"),
    ("C", "app/static/js/chat.js", 3032, "content.match(/tool_name"),
    ("C", "app/static/js/chat.js", 3047, "content.includes('error')"),
    ("C", "app/static/js/chat.js", 3312, "c.match(/Worker '(.+?)' stopped/)"),
    ("C", "app/static/js/chat.js", 3313, "c.match(/Worker '(.+?)' stopped"),
    ("C", "app/static/js/chat.js", 3314, "c.match(/Worker '(.+?)' renamed"),
    ("C", "app/static/js/chat.js", 3316, "c.match(/Description updated"),
    ("C", "app/static/js/chat.js", 3317, "c.match(/(\\d+) commits? merged"),
    ("C", "app/static/js/chat.js", 3318, "c.match(/sent to"),
    ("C", "app/static/js/chat.js", 3323, "c.match(/Background job created"),
    ("C", "app/static/js/chat.js", 3324, "c.match(/Job (\\S+) cancelled/)"),
    ("C", "app/static/js/chat.js", 3330, "content.includes('failed')"),
    ("C", "app/static/js/chat.js", 3358, "clean.match(/(\\d+)%"),
    ("C", "app/static/js/chat.js", 3908, "content.includes(\"'type': 'image'\")"),
    ("C", "app/static/js/chat.js", 4136, "/rate.?limit/i.test(content)"),
]

# Additional historical anchors cited in research.md/source-to-sink.md outside
# the per-site inventory table.
DOCUMENT_ANCHORS = [
    ("app/backend_claude.py", 1268, 'AgentEvent("text", block.text)'),
    ("app/backend_codex.py", 2178, 'AgentEvent("text", text)'),
    ("app/backend_grok.py", 1117, 'AgentEvent("text", text)'),
    ("app/harness/loop.py", 256, 'AgentEvent("text", content)'),
    ("app/session_turns.py", 43, "get_session_messages"),
    ("app/session_turns.py", 49, 'payload.get("role") == "assistant"'),
    ("app/session_turns.py", 433, "if s._safeguard_refusal and not ok"),
    ("app/session.py", 2488, 'self._log("text", event.content)'),
    ("app/session.py", 2957, "async for event in backend.events()"),
    ("app/session.py", 2959, "summary_parts.append(event.content)"),
    ("app/codex_review_artifact.py", 34, "def _last_agent_message"),
    ("app/codex_review_artifact.py", 197, "review = round_file.read_text"),
    ("app/routes/sessions.py", 1024, '"message": f"[Task #{created'),
    ("app/routes/sessions.py", 1069, "if ("),
    ("app/routes/sessions.py", 1083, "require_drained_scope=req.scope"),
    ("app/acceptance.py", 148, "Never reads DONE text"),
    ("app/fan_barrier.py", 34, "def is_terminal_report"),
]


def main() -> None:
    counts = {"A": 0, "B": 0, "C": 0}
    failures = []
    for category, relative, line_number, anchor in ROWS:
        counts[category] += 1
        lines = snapshot_lines(relative)
        actual = lines[line_number - 1] if line_number <= len(lines) else ""
        if anchor not in actual:
            failures.append(
                f"{category} {relative}:{line_number}: missing {anchor!r}; got {actual!r}"
            )
    document_ok = 0
    for relative, line_number, anchor in DOCUMENT_ANCHORS:
        lines = snapshot_lines(relative)
        actual = lines[line_number - 1] if line_number <= len(lines) else ""
        if anchor not in actual:
            failures.append(
                f"DOC {relative}:{line_number}: missing {anchor!r}; got {actual!r}"
            )
        else:
            document_ok += 1
    print(f"A={counts['A']} B={counts['B']} C={counts['C']} total={len(ROWS)}")
    print(f"research_snapshot={RESEARCH_SNAPSHOT}")
    print("C_groups=runtime_errors:7 external_outputs:14 platform_text:19 browser:43")
    inventory_failures = sum(1 for failure in failures if not failure.startswith("DOC "))
    print(
        f"inventory_anchors_ok={len(ROWS) - inventory_failures} "
        f"document_anchors_ok={document_ok} anchors_failed={len(failures)}"
    )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
