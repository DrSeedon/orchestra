"""Text is payload; only runtime events may change execution state."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events import AgentEvent


@pytest.fixture
def session(tmp_path, monkeypatch):
    from app.session import AgentSession
    monkeypatch.setattr('app.session.save_session', MagicMock())
    monkeypatch.setattr('app.session.add_log', MagicMock(return_value=1))
    monkeypatch.setattr('app.bg_jobs.bg_manager', None)
    s = AgentSession(id='text-control', name='test', scope='/test', cwd=str(tmp_path),
                     model='claude-sonnet-5[1m]', system_prompt='test',
                     created_at=datetime.now(timezone.utc))
    s._log = MagicMock()
    s._spawn_bg = lambda coro: coro.close()
    return s


@pytest.mark.parametrize('text', [
    'We fixed the session limit and monthly spend limit classifiers.',
    'API Error: safeguards flagged this message',
    '[round guard] an example from the source',
    '<function_calls><invoke name="Bash">pwd</invoke>',
])
def test_prose_never_sets_runtime_failure(session, text):
    session._handle_event(AgentEvent('text', text))
    assert not session._session_limit_hit
    assert not getattr(session, '_safeguard_refusal', '')
    assert session._last_text_output == text


@pytest.mark.parametrize('status,blocked', [('allowed', False), ('allowed_warning', False), ('rejected', True)])
def test_provider_limit_uses_primary_status(session, status, blocked):
    session._handle_event(AgentEvent('provider_limit', metadata={
        'status': status, 'rate_limit_type': 'seven_day', 'overage_status': 'rejected',
    }))
    assert session._session_limit_hit is blocked


@pytest.mark.asyncio
async def test_late_subscription_rejection_cancels_scheduled_retry(session):
    session.send = AsyncMock()
    session._session_limit_hit = True
    await session._rate_limit_retry(0, session._turn_gen)
    session.send.assert_not_called()


@pytest.mark.asyncio
async def test_quoted_failure_survives_failed_turn_without_fork(session, monkeypatch):
    import claude_agent_sdk
    fork = MagicMock()
    monkeypatch.setattr(claude_agent_sdk, 'fork_session', fork)
    session.session_id = 'unchanged'
    session._handle_event(AgentEvent('text', 'API Error: safeguards flagged this message'))
    session._handle_event(AgentEvent('turn_end', metadata={
        'ok': False, 'stop_reason': 'refusal', 'model_error': 'invalid_request',
    }))
    assert session.session_id == 'unchanged'
    fork.assert_not_called()


@pytest.mark.asyncio
async def test_round_guard_quote_preserved_and_runtime_hint_ephemeral(tmp_path):
    from app.harness.loop import AgentLoop
    class LLM:
        seen = []
        async def stream(self, history, tool_schemas, **kwargs):
            self.seen.append(list(history))
            yield type('E', (), {'kind': 'text_delta', 'text': '[round guard] assistant quote'})()
    llm = LLM()
    history = [{'role': 'user', 'content': '[round guard] saved user quote'}]
    loop = AgentLoop(llm, None, str(tmp_path), history, [], max_context=100_000, max_rounds=12)
    # Exercise the warning round directly with a short-lived initial cap.
    import app.harness.loop as mod
    old = mod.WIND_DOWN_AT
    try:
        mod.WIND_DOWN_AT = (12, 3)
        loop.max_rounds = 13
        # First round must request a tool to reach the warning at 12.
        original = llm.stream
        async def stream(history, schemas, **kwargs):
            if not llm.seen:
                llm.seen.append(list(history))
                yield type('E', (), {'kind': 'tool_call_done', 'tool_id': 'one',
                    'tool_name': 'read', 'arguments': '{"path":"missing"}'})()
            else:
                async for event in original(history, schemas, **kwargs):
                    yield event
        llm.stream = stream
        _ = [e async for e in loop.run('go')]
    finally:
        mod.WIND_DOWN_AT = old
    assert any('rounds remain' in str(m.get('content')) for m in llm.seen[-1])
    assert not any('rounds remain' in str(m.get('content')) for m in loop.history + loop.new_messages)
    assert history[0]['content'] == '[round guard] saved user quote'
    assert history[-1]['content'] == '[round guard] assistant quote'


def test_review_quotes_do_not_mean_execution_failed():
    from app.codex_review_artifact import review_result_error
    assert review_result_error('## Findings\nFix bwrap: failed rtm_newaddr\n## Verdict\nNEEDS WORK') == ''


def test_limit_wake_does_not_read_model_prose():
    from app.limit_wake import _latest_limit_turn
    rows = [
        {'id': 1, 'type': 'text', 'content': 'We fixed a monthly spend limit bug'},
        {'id': 2, 'type': 'provider_limit', 'content': json.dumps({'status': 'rejected', 'rate_limit_type': 'seven_day'})},
        {'id': 3, 'type': 'status', 'content': 'turn ended (stop_sequence, 1 turns)'},
    ]
    assert _latest_limit_turn(rows) == ('timed', 3)


@pytest.mark.parametrize('events,expected', [
    ([{'type': 'turn.completed'}, {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'bwrap: Unable to perform'}}], ''),
    ([{'type': 'turn.failed'}], 'failure'),
    ([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'APPROVED'}}], 'no completed turn'),
    ([{'type': 'turn.completed'}], 'no final response'),
    ([{'type': 'turn.completed'}, {'type': 'turn.started'}], 'no completed turn'),
])
def test_review_runtime_status_is_independent_of_prose(tmp_path, events, expected):
    from app.codex_review_artifact import review_execution_error
    path = tmp_path / 'runtime.jsonl'
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    error = review_execution_error(path)
    assert expected in error if expected else not error


@pytest.mark.parametrize('verdict,expected', [
    ('APPROVED', ''), ('NEEDS WORK', ''), ('INCOMPLETE\nCannot read the requested files', 'INCOMPLETE'),
    ('', 'nonempty'),
])
def test_explicit_review_result(tmp_path, verdict, expected):
    from app.codex_review_artifact import review_result_error
    error = review_result_error('## Findings\nWe discuss INCOMPLETE and bwrap: here\n## Verdict\n' + verdict)
    assert expected in error if expected else not error


def test_resumed_review_uses_latest_result_only():
    from app.codex_review_artifact import review_result_error
    prior = '## Verdict\nINCOMPLETE\n'
    current = '\n## Round (today)\n## Findings\nNo findings\n## Verdict\nAPPROVED\n'
    assert review_result_error(prior + current) == ''
    assert 'nonempty' in review_result_error(prior + '\n## Round (today)\nNo result')


@pytest.mark.parametrize('failure', ['runtime', 'incomplete'])
def test_unsuccessful_review_preserves_findings_and_failed_receipt(tmp_path, monkeypatch, failure):
    from app import codex_review_artifact as artifact
    receipt = MagicMock()
    monkeypatch.setattr(artifact, '_record_terminal_receipt', receipt)
    path = tmp_path / 'run.jsonl'
    events = [{'type': 'thread.started', 'thread_id': 'review-thread'},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Partial finding'}},
              {'type': 'turn.failed' if failure == 'runtime' else 'turn.completed'}]
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    output = tmp_path / 'review.md'
    output.write_text('Prior findings\n')
    draft = tmp_path / 'review.round'
    draft.write_text('## Findings\nPartial finding\n## Verdict\n' + ('INCOMPLETE' if failure == 'incomplete' else 'APPROVED'))
    with pytest.raises(artifact.ReviewResultError):
        artifact.finalize_review_artifact(output=output, round_file=draft,
            sessions_file=tmp_path / 'sessions.json', slug='review', jsonl_file=path,
            resume=False, require_verdict=True, receipt_id='receipt')
    assert 'Prior findings' in output.read_text()
    assert 'Partial finding' in output.read_text()
    assert receipt.call_count == 1
    assert receipt.call_args.kwargs['status'] == 'failed'
    assert receipt.call_args.kwargs['return_code'] == 0  # runtime failure differs from process exit


@pytest.mark.parametrize('status', ['allowed', 'allowed_warning', 'rejected'])
def test_claude_adapter_keeps_primary_limit_signal(status):
    from claude_agent_sdk.types import RateLimitEvent, RateLimitInfo
    from app.backend_claude import ClaudeBackend
    backend = ClaudeBackend(model='claude-sonnet-5[1m]', cwd='/tmp')
    converted = backend._convert(RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, rate_limit_type='seven_day',
                                     overage_status='rejected', resets_at=2000000000),
        uuid='signal-id', session_id='session'))
    event = next(e for e in converted if e.type == 'provider_limit')
    assert event.metadata == {'status': status, 'rate_limit_type': 'seven_day',
                             'resets_at': 2000000000, 'overage_status': 'rejected', 'event_id': 'signal-id'}


@pytest.mark.asyncio
async def test_limit_arriving_during_admission_stops_retry_before_submit(session):
    from app.events import MessageProvenance
    entered = asyncio.Event()
    release = asyncio.Event()
    async def admission(_model):
        entered.set()
        await release.wait()
        return object()  # Rejection must be checked before this decision is consumed.
    session._worker_admission = admission
    session._ensure_backend = AsyncMock()
    task = asyncio.create_task(session.send('retry',
        provenance=MessageProvenance(origin='system', senders=('system',), subtype='rate_limit_retry'),
        retry_generation=(session._turn_gen, session._turn_start_cancel_gen)))
    await asyncio.wait_for(entered.wait(), 2)
    session._handle_event(AgentEvent('provider_limit', metadata={'status': 'rejected'}))
    release.set()
    await asyncio.wait_for(task, 2)
    session._ensure_backend.assert_not_awaited()
    assert session._session_limit_hit
    assert not any(call.args[0] == 'user_message' for call in session._log.call_args_list)


def test_typed_transient_rate_limit_can_retry(session):
    session._handle_event(AgentEvent('error', 'A localized provider message', metadata={'model_error': 'rate_limit'}))
    assert session._rate_limit_retries == 1
    assert not session._session_limit_hit
