"""V-672 compaction event regression checks, isolated for the merge gate."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

pytest_plugins = (
    "tests.test_frontend",
    "tests.test_logs_sync",
)

from tests.test_frontend import _open_tool_correlation_page
from tests.test_logs_sync import _session


@pytest.fixture
def tb(tmp_path, monkeypatch):
    monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", tmp_path / "tg_bridge.json")
    from app import tg_bridge

    tg_bridge.config = {"group_id": -100123456, "topics": {}, "token": "test"}
    tg_bridge._topic_status = {}
    tg_bridge.bot = None
    tg_bridge._pil_available = None
    for name, value in {
        "_tasks": [], "_stream_tasks": {}, "_topic_status_tasks": {},
        "_topic_status_desired": {}, "_topic_create_tasks": {},
        "_bridge_tasks": {}, "_mirror_outboxes": {}, "_mirror_tasks": {},
        "_mirror_dropped": {}, "_mirror_stopping": set(), "_buffers": {},
        "_tg_delivery_states": {}, "_tg_dispatch_tasks": {},
        "_tg_queue_loops": {}, "_tg_result_tasks": set(),
        "_tg_result_wrappers": {}, "_tg_flood_until": {}, "_tg_last_send": {},
        "_tg_call_sequence": 0,
    }.items():
        monkeypatch.setattr(tg_bridge, name, value, raising=False)
    return tg_bridge


async def _run_tg_logs(tb, monkeypatch, rows):
    class FakeConn:
        def close(self):
            pass

    calls = 0
    sent = []
    mirrored = []

    def get_logs(_session_id, after_id=0, conn=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        if calls == 2:
            return rows
        raise asyncio.CancelledError

    async def no_sleep(_delay):
        return None

    async def tg_send_safe(_chat_id, text, _thread_id, **_kwargs):
        sent.append(text)

    async def mirror_send(_orch_name, text, **_kwargs):
        mirrored.append(text)

    monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
    monkeypatch.setattr("app.db.get_all_sessions", lambda: [
        {"name": "orch", "scope": "/scope", "role": "orchestrator"},
    ])
    monkeypatch.setattr("app.db.get_session_by_name", lambda *_: {"id": "sid"})
    monkeypatch.setattr("app.db.get_logs", get_logs)
    monkeypatch.setattr("app.db._conn", FakeConn)
    monkeypatch.setattr(tb, "_schedule_topic_status", lambda *_: None)
    monkeypatch.setattr(tb, "_any_running_in_scope", lambda *_: False)
    monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
    monkeypatch.setattr(tb, "_mirror_send", mirror_send)
    monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await tb.stream_logs("orch", 42)
    return sent, mirrored


@pytest.mark.asyncio
async def test_compact_events_and_statuses_do_not_reach_telegram_or_mirror(tb, monkeypatch):
    sent, mirrored = await _run_tg_logs(tb, monkeypatch, [
        {"id": 1, "type": "compact_event", "event_id": "compact-1",
         "content": '{"action":"tool","phase":"audit","kind":"tool_result"}'},
        {"id": 2, "type": "status", "content": "compact started (context 95%, pre_session=x)"},
        {"id": 3, "type": "status", "content": "compact done: 95% → 31%"},
        {"id": 90, "type": "status",
         "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
    ])

    assert sent == []
    assert mirrored == []


def test_compact_journal_rows_render_as_one_separate_collapsible_block(
    dashboard_browser: Browser,
):
    fixture_path = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-fixture.json"
    fixture = json.loads(fixture_path.read_text())
    assert fixture["source"]["legacy_tool_result_rows_without_tool_use_id"] == 34
    page = _open_tool_correlation_page(dashboard_browser, compact_mode=False)
    page.evaluate("""fixture => {
        for (const row of fixture.events) {
            addChatEntry('compact_event', JSON.stringify(row.content), null, null, {
                id: row.id,
                event_id: row.event_id,
                tool_use_id: row.content.tool_use_id,
                tool_name: row.content.tool_name,
                tool_is_error: false,
            });
            if (row.id === 4) addChatEntry('text', 'ordinary message stays in the chat flow', null);
        }
        const card = document.querySelector('.compact-event-card');
        return {
            compactCards: document.querySelectorAll('.compact-event-card').length,
            orphanResults: document.querySelectorAll('[data-unmatched-tool-result]').length,
            compactText: card?.innerText || '',
            ordinaryMessageCount: [...document.querySelectorAll('#chat .chat-bot')]
                .filter(node => node.innerText.includes('ordinary message stays')).length,
        };
    }""", fixture)
    card = page.locator(".compact-event-card")
    expect(card).to_contain_text("Context compaction")
    expect(card).to_contain_text("In progress")
    card.evaluate("""card => {
        card.open = true;
        card.querySelector('details[data-phase="audit"]').open = true;
        card.querySelector('details[data-phase="audit"] details').open = true;
    }""")
    assert card.evaluate("card => card.open && card.querySelector('details[data-phase=\"audit\"]').open")
    screenshot = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-card.png"
    page.evaluate("""() => {
        const clone = document.querySelector('.compact-event-card').cloneNode(true);
        clone.id = 'compact-card-screenshot';
        clone.style.cssText = 'position:fixed;top:8px;left:8px;width:900px;max-height:none;overflow:visible;z-index:99999;background:#0b1120';
        document.body.appendChild(clone);
    }""")
    page.locator("#compact-card-screenshot").screenshot(path=str(screenshot))
    page.locator("#compact-card-screenshot").evaluate("node => node.remove()")
    page.evaluate("""() => {
        addChatEntry('compact_event', JSON.stringify({
            action: 'step_done', phase: 'draft', summary: 'Initial draft summary.',
        }), null, null, {id: 96, event_id: 'fixture-compact'});
        addChatEntry('compact_event', JSON.stringify({
            action: 'step_done', phase: 'audit', seconds: 90, cost_usd: 0.47,
        }), null, null, {id: 97, event_id: 'fixture-compact'});
        addChatEntry('compact_event', JSON.stringify({
            action: 'step_done', phase: 'final', seconds: 75, cost_usd: 0.51,
            summary: 'Reviewed summary for the next session.',
        }), null, null, {id: 98, event_id: 'fixture-compact'});
        addChatEntry('compact_event', JSON.stringify({
            action: 'finish', status: 'complete', before_pct: 95, after_pct: 31,
            pre_tokens: 190000, post_tokens: 62000, seconds: 217.4,
            cost_usd: 1.23, summary: 'Reviewed summary for the next session.',
        }), null, null, {id: 99, event_id: 'fixture-compact'});
        addChatEntry('compact_event', JSON.stringify({action: 'start', status: 'running', before_pct: 90}),
            null, null, {id: 100, event_id: 'fixture-fallback'});
        addChatEntry('compact_event', JSON.stringify({action: 'finish', status: 'fallback_draft',
            summary: 'Kept draft summary.'}), null, null, {id: 101, event_id: 'fixture-fallback'});
        window.api = async path => ({
            id: 7, event_id: 'fixture-compact', type: 'compact_event', ts: null,
            content: JSON.stringify({action: 'tool', phase: 'audit', kind: 'tool_result',
                tool_use_id: 'fixture-audit-read', tool_name: 'Read',
                content: 'FULL_RESULT_AFTER_EXPANSION'}),
        });
        addChatEntry('compact_event', JSON.stringify({action: 'tool', phase: 'audit',
            kind: 'tool_result', tool_use_id: 'fixture-audit-read', tool_name: 'Read',
            content: 'PARTIAL_RESULT', content_truncated_bytes: 9000}), null, null,
            {id: 7, event_id: 'fixture-compact'});
    }""")
    compact_card = page.locator('.compact-event-card[data-compact-id="fixture-compact"]')
    compact_card.evaluate("""card => {
        card.querySelector('details[data-phase="audit"]').open = true;
        card.querySelector('details[data-phase="audit"] details').open = true;
        card.querySelector('details[data-phase="final"]').open = true;
    }""")
    compact_card.get_by_role("button", name="load full").click()
    compact_card.evaluate("""card => {
        card.open = true;
        card.querySelectorAll('details').forEach(node => { node.open = true; });
    }""")
    expect(compact_card).to_contain_text("FULL_RESULT_AFTER_EXPANSION")
    rendered = page.evaluate("""() => ({
        compactCards: document.querySelectorAll('.compact-event-card').length,
        orphanResults: document.querySelectorAll('[data-unmatched-tool-result]').length,
        compactText: document.querySelector('.compact-event-card')?.innerText || '',
        fallbackText: document.querySelector('[data-compact-id="fixture-fallback"]')?.innerText || '',
        ordinaryMessageCount: [...document.querySelectorAll('#chat .chat-bot')]
            .filter(node => node.innerText.includes('ordinary message stays in the chat flow')).length,
    })""")
    page.close()

    assert rendered["compactCards"] == 2
    assert rendered["orphanResults"] == 0
    assert "FULL_RESULT_AFTER_EXPANSION" in rendered["compactText"]
    assert "Ready" in rendered["compactText"]
    assert "95% → 31%" in rendered["compactText"]
    assert "Reviewed summary for the next session." in rendered["compactText"]
    assert "Draft restored" in rendered["fallbackText"]
    assert "ordinary message stays in the chat flow" not in rendered["compactText"]
    assert rendered["ordinaryMessageCount"] == 1
    assert screenshot.is_file()


def test_compact_event_cap_preserves_json_pair_and_full_db_payload(db):
    from app.db import add_log, get_log, get_logs_before, save_session

    save_session(_session("s1", "compact"))
    event = {
        "action": "tool", "phase": "audit", "kind": "tool_result",
        "tool_use_id": "audit-read", "tool_name": "Read",
        "content": "строка\n" * 3000,
    }
    row_id = add_log(
        "s1", datetime.now(timezone.utc), "compact_event",
        json.dumps(event, ensure_ascii=False), event_id="compact-1",
        tool_use_id="audit-read", tool_name="Read",
    )
    summary_event = {
        "action": "finish", "status": "complete",
        "summary": "итоговая сводка\n" * 3000,
    }
    summary_id = add_log(
        "s1", datetime.now(timezone.utc), "compact_event",
        json.dumps(summary_event, ensure_ascii=False), event_id="compact-1",
    )

    projected_rows = get_logs_before(
        "s1", 2 ** 31 - 1, limit=10, max_bytes=0, cap=1024,
    )
    projected = next(row for row in projected_rows if row["id"] == row_id)
    projected_summary = next(row for row in projected_rows if row["id"] == summary_id)
    decoded = json.loads(projected["content"])
    decoded_summary = json.loads(projected_summary["content"])
    stored = json.loads(get_log(row_id)["content"])
    stored_summary = json.loads(get_log(summary_id)["content"])

    assert len(projected["content"].encode()) <= 1024
    assert projected["event_id"] == "compact-1"
    assert decoded["tool_use_id"] == "audit-read"
    assert decoded["content"].startswith("строка")
    assert decoded["content_truncated_bytes"] > 0
    assert stored["content"] == event["content"]
    assert len(projected_summary["content"].encode()) <= 1024
    assert projected_summary["event_id"] == "compact-1"
    assert decoded_summary["status"] == "complete"
    assert decoded_summary["summary"].startswith("итоговая сводка")
    assert decoded_summary["content_truncated_bytes"] > 0
    assert stored_summary["summary"] == summary_event["summary"]
