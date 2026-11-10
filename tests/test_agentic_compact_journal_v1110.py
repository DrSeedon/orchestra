"""Compaction journal keeps who said what, the tail of long messages and recall aids.

V-643 measured that the journal + AUDIT/FINAL scheme lifts recall from 0.55 to 0.85;
these contracts keep the journal itself from dropping what AUDIT is told to verify:
the source of every USER row, the end of a long brief, and the bans/ids/numbers.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from app import agentic_compact
from app import db as dbmod
from app.events import MessageProvenance


def _row(row_id, content, *, kind="user_message", origin=None, detail=None, tool=None):
    row = {
        "id": row_id, "ts": "2026-11-10T10:00:00Z", "type": kind, "content": content,
        "tool_name": tool, "tool_is_error": False,
    }
    if origin is not None:
        row["origin"] = origin
        row["origin_detail"] = json.dumps(detail or {"senders": ["unknown"]})
    return row


def _journal(tmp_path, rows):
    agentic_compact.write_journal(rows, tmp_path / "audit")
    journal = tmp_path / "audit" / "journal"
    events = [json.loads(line) for line in (journal / "journal.jsonl").read_text().splitlines()]
    chunk = (journal / "chunk_001.md").read_text()
    return journal, events, chunk


def test_user_rows_name_their_source_in_chunks_and_jsonl(tmp_path):
    rows = [
        _row(1, "owner says", origin="user", detail={"senders": ["user"], "subtype": "telegram"}),
        _row(2, "worker says", origin="agent",
             detail={"senders": ["tender-scout"], "subtype": "direct_message", "ref": "x"}),
        _row(3, "server says", origin="platform",
             detail={"senders": ["Orchestra"], "subtype": "silence_signal"}),
        _row(4, "legacy row without provenance"),
    ]

    _journal_dir, events, chunk = _journal(tmp_path, rows)

    assert "[#1 2026-11-10T10:00] USER [origin=user, from=owner, via=telegram]:\nowner says" in chunk
    assert "USER [origin=agent, from=tender-scout, via=direct_message]:\nworker says" in chunk
    assert "USER [origin=platform, from=Orchestra, via=silence_signal]:\nserver says" in chunk
    assert "USER:\nlegacy row without provenance" in chunk
    assert events[0]["origin"] == "user" and events[0]["senders"] == ["user"]
    assert events[1]["origin"] == "agent" and events[1]["senders"] == ["tender-scout"]
    assert events[3]["origin"] is None and events[3]["senders"] == []


def test_redelivered_role_prompt_collapses_and_message_survives(tmp_path):
    prompt = "ROLE " * 15000 + "\n<identity>Worker name: w</identity>"
    for reason in ("your role instructions were updated.", "refreshed context (worker list, etc.)."):
        # Exactly the shape `AgentSession.send` builds for a re-delivered prompt.
        text = (f"[Orchestra platform note: {reason} This is from the server, not another agent.]"
                f"\n{prompt}\n\n---\n\nnever push to main")
        stripped = agentic_compact._strip_platform_prompt_prefix(text)
        assert stripped == agentic_compact.PLATFORM_PROMPT_NOTE + "never push to main"

    facts = ("[Orchestra platform note: пока тебя не было, до тебя не дошло 2 событий.]\n"
             "- 10:00 x\n---\nreal message")
    assert agentic_compact._strip_platform_prompt_prefix(facts) == facts
    assert agentic_compact._strip_platform_prompt_prefix("plain") == "plain"

    _journal_dir, events, chunk = _journal(tmp_path, [_row(1, text, origin="user",
                                                           detail={"senders": ["user"]})])
    assert "ROLE ROLE" not in chunk and "never push to main" in chunk
    assert events[0]["content"].endswith("never push to main")


def test_long_message_keeps_head_and_tail_everywhere(tmp_path):
    text = "HEAD-START " + "x" * 40000 + " FINAL-INSTRUCTION: do not merge V-77"
    journal, events, chunk = _journal(tmp_path, [_row(5, text, origin="user",
                                                       detail={"senders": ["user"]})])

    content = events[0]["content"]
    assert content.startswith("HEAD-START")
    assert content.endswith("FINAL-INSTRUCTION: do not merge V-77")
    assert agentic_compact.MIDDLE_MARK in content
    assert len(content) == (agentic_compact.HEAD_CHARS + agentic_compact.TAIL_CHARS
                            + len(agentic_compact.MIDDLE_MARK))
    assert "FINAL-INSTRUCTION" in chunk and "HEAD-START" in chunk
    # USER_MESSAGES.md is the complete source: nothing of the owner's text is cut there.
    assert text in (journal / "USER_MESSAGES.md").read_text()


def test_short_rows_and_tool_rows_are_unchanged(tmp_path):
    rows = [
        _row(1, "do not push commit abc123"),
        _row(2, "x" * 25000, kind="tool_result", tool="Read"),
    ]
    _journal_dir, events, _chunk = _journal(tmp_path, rows)

    assert events[0]["content"] == "do not push commit abc123"
    assert events[1]["content"] == "x" * agentic_compact.CONTENT_CAP


def test_user_messages_file_lists_every_user_message_in_order(tmp_path):
    rows = [
        _row(10, "first ask", origin="user", detail={"senders": ["user"], "subtype": "dashboard"}),
        _row(11, "assistant reply", kind="text"),
        _row(12, "second ask from worker", origin="agent", detail={"senders": ["w1"]}),
    ]
    journal, _events, _chunk = _journal(tmp_path, rows)
    text = (journal / "USER_MESSAGES.md").read_text()

    assert text.index("first ask") < text.index("second ask from worker")
    assert "[#10 2026-11-10T10:00:00 user user dashboard]" in text
    assert "[#12 2026-11-10T10:00:00 agent w1]" in text
    assert "assistant reply" not in text
    assert "USER_MESSAGES.md" in (journal / "INDEX.md").read_text()


def test_extracted_candidates_collect_bans_ids_commits_paths_urls_numbers(tmp_path):
    rows = [
        _row(1, "Никогда не пушь в main без тестов.\nСделай V-693 и #V-12, см. #4021\n"
                "Бюджет 22 000 ₽, диск 85%, лимит 680 часов",
             origin="user", detail={"senders": ["user"]}),
        _row(2, "Merged 52417d43116048e83e010fa381f91badcda4164e into /home/kesha/orchestra/app/db.py "
                "and tests/test_x.py; see https://user:pa55@github.com/DrSeedon/orchestra/actions/runs/42",
             kind="text"),
        _row(3, "Read app/session.py", kind="tool", tool="Read"),
    ]
    journal, _events, _chunk = _journal(tmp_path, rows)
    text = (journal / "EXTRACTED_CANDIDATES.md").read_text()

    bans = text.split("## BANS AND INVARIANTS")[1].split("##")[0]
    assert "Никогда не пушь в main без тестов." in bans and "origin=user, from=owner" in bans
    for value in ("V-693", "#V-12", "#4021", "52417d43116048e83e010fa381f91badcda4164e",
                  "/home/kesha/orchestra/app/db.py", "tests/test_x.py", "app/session.py",
                  "22 000 ₽", "85%", "680 часов"):
        assert value in text, value
    assert "https://<secret>@github.com/DrSeedon/orchestra/actions/runs/42" in text
    assert "pa55" not in text


def test_candidate_lists_keep_late_ids_long_bans_and_tool_measurements(tmp_path):
    rows = [_row(i, f"task V-{i}", kind="text") for i in range(1, 406)]
    ban = "Никогда " + "x" * 500 + " do not restart telegram-bot-api"
    rows += [_row(406, ban), _row(407, "Measured 123 ms, 88%", kind="tool_result")]
    journal, _events, _chunk = _journal(tmp_path, rows)
    text = (journal / "EXTRACTED_CANDIDATES.md").read_text()
    assert "V-405" in text and ban in text
    assert "123 ms" in text and "88%" in text
    assert "more not listed" not in text


def test_dynamic_rule_updates_are_not_stripped_as_a_static_prompt():
    message = ("[Orchestra platform note: your role instructions were updated. Only the "
               "temporary-rules blocks changed: they replace the earlier blocks; everything "
               "else stays as delivered. This is from the server, not another agent.]\n"
               "<temporary-rules>NEVER delete the archive</temporary-rules>\n\n---\n\nContinue")
    assert agentic_compact._strip_platform_prompt_prefix(message) == message


def test_audit_prompt_points_to_the_recall_aids(tmp_path):
    prompt = agentic_compact.audit_prompt(tmp_path / "journal", tmp_path / "summary.md")

    assert "USER_MESSAGES.md" in prompt and "EXTRACTED_CANDIDATES.md" in prompt
    assert agentic_compact.PREVIOUS_SUMMARY_MARKER in prompt
    assert "pass 1 — AUDIT" in prompt


def test_compact_segment_returns_provenance_from_the_database(tmp_path, monkeypatch):
    db_path = tmp_path / "compact.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, name, scope, cwd, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", "w", "/s", "/s", "claude-opus-5-5[1m]", datetime.now(timezone.utc).isoformat()),
        )
    dbmod.add_log(
        "s1", datetime.now(timezone.utc), "user_message", "owner brief",
        provenance=MessageProvenance(origin="user", senders=("user",), subtype="telegram"),
    )

    rows = dbmod.get_compact_segment("s1")
    journal = asyncio.run(agentic_compact.prepare_journal("s1", tmp_path / "audit"))

    assert rows[0]["origin"] == "user"
    assert json.loads(rows[0]["origin_detail"])["senders"] == ["user"]
    assert "USER [origin=user, from=owner, via=telegram]:" in (journal / "chunk_001.md").read_text()
