from datetime import datetime, timedelta, timezone
from itertools import permutations
import json
from pathlib import Path
import sqlite3
import subprocess
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import error_watch as watch


@pytest.fixture
def scan_reports(monkeypatch):
    reports = Mock(wraps=watch._brief_output)
    monkeypatch.setattr(watch, "_brief_output", reports)
    return reports


def _event(message, minute=0, source="journalctl", scope=None):
    timestamp = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)
    event = {"source": source, "ts": timestamp.isoformat(), "message": message}
    if scope is not None:
        event["scope"] = scope
    return event


_V1189_CHAIN_LINES = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)
_V1189_IPV4 = "[Errno 111] Connect call failed ('192.0.2.1', 443)"
_V1189_IPV6 = "[Errno 101] Network is unreachable"


def _v1189_connector(*causes):
    return (
        "aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host "
        "upstream.example.invalid:443 ssl:default [Multiple exceptions: "
        + ", ".join(causes) + "]"
    )


def _v1189_legacy_connector_signature():
    # The old normalizer replaced numbers but retained this noncanonical order.
    return (
        "aiohttp.client_exceptions.ClientConnectorError: Cannot connect to host "
        "upstream.example.invalid:<N> ssl:default [Multiple exceptions: "
        "[Errno <N>] Network is unreachable, "
        "[Errno <N>] Connect call failed ('<N>.<N>', <N>)]"
    )


@pytest.mark.parametrize("line", _V1189_CHAIN_LINES)
@pytest.mark.parametrize("prefix", ["", "ERROR:app.transport:"])
@pytest.mark.parametrize("source", ["journalctl", "logs"])
def test_v1189_only_standalone_chaining_lines_are_noise(line, prefix, source):
    message = "  " + prefix + line + "\n"
    events = [_event(message, i, source=source) for i in range(2)]
    before = [dict(event) for event in events]
    signature = watch.normalize_signature(message)
    assert watch.classify_noise(signature) == "traceback chaining line"
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=2)
    assert candidates == []
    assert [(item["noise"], item["count"]) for item in noise] == [("traceback chaining line", 2)]
    started = datetime.fromisoformat(events[0]["ts"])
    assert watch.post_fix_verdict(events, signature, started, 168)["count"] == 0
    assert events == before


@pytest.mark.parametrize("line", _V1189_CHAIN_LINES)
@pytest.mark.parametrize("template", [
    "ValueError: {}", "{} database failed", "{}\nConnectionRefusedError: refused",
    "ConnectionRefusedError: refused\n{}", "{} extra:",
])
def test_v1189_chaining_text_with_an_error_stays_actionable(line, template):
    message = template.format(line)
    signature = watch.normalize_signature(message)
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(signature) is None
    events = [_event(message, i) for i in range(2)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=2)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 2)]
    assert noise == []
    assert watch.post_fix_verdict(
        events, signature, datetime.fromisoformat(events[0]["ts"]), 168,
    )["count"] == 2


def test_v1189_connector_address_order_is_canonical_and_idempotent():
    ipv6_address = "[Errno 111] Connect call failed ('2001:db8::1', 443, 0, 0)"
    messages = [_v1189_connector(*causes) for causes in permutations((
        _V1189_IPV4, _V1189_IPV6, ipv6_address,
    ))]
    signatures = {watch.normalize_signature(message) for message in messages}
    assert len(signatures) == 1
    signature = signatures.pop()
    assert signature.count("[Errno <N>]") == 3
    assert "('" in signature and ", <N>, <N>, <N>)" in signature
    assert watch.normalize_signature(signature) == signature
    assert watch.classify_noise(signature) is None


@pytest.mark.parametrize("source", ["journalctl", "logs"])
def test_v1189_mixed_order_connector_failures_reach_threshold_and_recur(source):
    left = _v1189_connector(_V1189_IPV4, _V1189_IPV6)
    right = _v1189_connector(_V1189_IPV6, _V1189_IPV4)
    events = [_event(message, i, source=source) for i, message in enumerate([left, right] * 2)]
    signature = watch.normalize_signature(left)
    # Either order alone is below threshold; their shared cause is actionable.
    assert watch.aggregate(events[:2], datetime.now(timezone.utc), threshold=4) == ([], [])
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=4)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 4)]
    assert noise == []
    started = datetime.fromisoformat(events[0]["ts"])
    # This is the signature persisted by the old normalizer, with unsorted causes.
    legacy_signature = _v1189_legacy_connector_signature()
    assert legacy_signature != signature
    assert watch.post_fix_verdict(events, legacy_signature, started, 168)["count"] == 4


@pytest.mark.parametrize("replacement", [
    ("upstream.example.invalid", "other.example.invalid"),
    ("ssl:default", "ssl:False"),
    ("Network is unreachable", "Connection refused"),
    ("Connect call failed", "Connection timed out"),
    ("ClientConnectorError", "ClientProxyConnectionError"),
])
def test_v1189_other_connector_causes_remain_separate(replacement):
    original = _v1189_connector(_V1189_IPV4, _V1189_IPV6)
    other = original.replace(*replacement)
    signatures = {watch.normalize_signature(message) for message in [original, other]}
    assert len(signatures) == 2
    events = [_event(message, i) for i, message in enumerate([original, other] * 2)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=2)
    assert {item["signature"] for item in candidates} == signatures
    assert [item["count"] for item in candidates] == [2, 2]
    assert noise == []


@pytest.mark.parametrize("template", [
    "OSError: [Multiple exceptions: {}]",
    "ClientProxyConnectionError: [Multiple exceptions: {}]",
    "ClientConnectorError: [Other errors: {}]",
    "ClientConnectorError: [Multiple exceptions: {}, ValueError: broken]",
])
def test_v1189_only_supported_connector_aggregates_are_reordered(template):
    left = template.format(", ".join((_V1189_IPV4, _V1189_IPV6)))
    right = template.format(", ".join((_V1189_IPV6, _V1189_IPV4)))
    assert watch.normalize_signature(left) != watch.normalize_signature(right)
    assert watch.classify_noise(watch.normalize_signature(left)) is None


def test_v1189_connector_duplicates_and_surrounding_errors_are_preserved():
    message = _v1189_connector(_V1189_IPV6, _V1189_IPV4, _V1189_IPV6)
    signature = watch.normalize_signature(message)
    assert signature.count("Network is unreachable") == 2
    assert signature != watch.normalize_signature(_v1189_connector(_V1189_IPV4, _V1189_IPV6))
    assert signature != watch.normalize_signature(message + "; ValueError: broken")
    assert signature != watch.normalize_signature("connection pool failed: " + message)
    # A logger's repeated copy of one journal record still counts only once.
    reordered = _v1189_connector(_V1189_IPV4, _V1189_IPV6, _V1189_IPV6)
    events = [_event(message), _event("ERROR:app.transport:" + reordered), _event(message, 1)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=2)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 2)]
    assert noise == []


def test_v1189_journal_collection_keeps_real_connector_failure():
    messages = [_V1189_CHAIN_LINES[1], _v1189_connector(_V1189_IPV4, _V1189_IPV6)]
    timestamp = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    runner = Mock(return_value=SimpleNamespace(stdout="\n".join(
        json.dumps({"MESSAGE": message, "__REALTIME_TIMESTAMP": int(timestamp.timestamp() * 1_000_000)})
        for message in messages
    )))
    events = watch.collect_journal_events(timestamp, runner=runner)
    assert [event["message"] for event in events] == messages
    candidates, noise = watch.aggregate(events, timestamp, threshold=1)
    assert [item["signature"] for item in candidates] == [watch.normalize_signature(messages[1])]
    assert [item["noise"] for item in noise] == ["traceback chaining line"]


def test_v1189_real_aiohttp_exception_format_and_python_chain_without_io():
    from aiohttp import ClientConnectorError

    key = SimpleNamespace(host="upstream.example.invalid", port=443, ssl=True)
    messages = []
    for causes in [(_V1189_IPV4, _V1189_IPV6), (_V1189_IPV6, _V1189_IPV4)]:
        try:
            try:
                raise OSError(111, "Multiple exceptions: " + ", ".join(causes))
            except OSError as cause:
                raise ClientConnectorError(key, cause) from cause
        except ClientConnectorError as error:
            rendered = traceback.format_exception(error)
            assert any(line.strip() == _V1189_CHAIN_LINES[1] for line in rendered)
            messages.append(traceback.format_exception_only(error)[0].strip())
    assert messages == [
        _v1189_connector(_V1189_IPV4, _V1189_IPV6),
        _v1189_connector(_V1189_IPV6, _V1189_IPV4),
    ]
    candidates, noise = watch.aggregate(
        [_event(message, i) for i, message in enumerate(messages)],
        datetime.now(timezone.utc), threshold=2,
    )
    assert len(candidates) == 1 and candidates[0]["count"] == 2
    assert noise == []


@pytest.mark.parametrize("already_alerted", [False, True])
def test_v1189_scan_preserves_legacy_fix_and_alert_state(
    already_alerted, tmp_path, monkeypatch, capsys, scan_reports,
):
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    left = _v1189_connector(_V1189_IPV4, _V1189_IPV6)
    right = _v1189_connector(_V1189_IPV6, _V1189_IPV4)
    events = [
        dict(_event(message, source="logs"), ts=(started + timedelta(seconds=i)).isoformat())
        for i, message in enumerate([left, right] * 2 + [_V1189_CHAIN_LINES[1]] * 4)
    ]
    signature = watch.normalize_signature(left)
    legacy = _v1189_legacy_connector_signature()
    fix = dict(task="V-1189", commit="synthetic", started_at=started.isoformat(), window_hours=168)
    state_path = tmp_path / "error_watch.json"
    watch._write_state(state_path, {
        "alerts": {legacy: {"first_alerted": started.isoformat(), "count": 4}} if already_alerted else {},
        "fixes": {legacy: dict(fix), _V1189_CHAIN_LINES[1]: dict(fix)},
    })
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: events)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    args = SimpleNamespace(db=str(tmp_path / "synthetic.db"), window_hours=168, threshold=4, dry_run=False)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [item["signature"] for item in signals] == ([] if already_alerted else [signature])
    if signals:
        assert signals[0]["known"]["task"] == "V-1189"
        assert signals[0]["known"]["commit"] == "synthetic"
    assert [(item["signature"], item["count"]) for item in verdicts] == [(legacy, 4)]
    state = watch._load_state(state_path)
    assert set(state["alerts"]) == {signature}
    assert set(state["fixes"]) == {legacy, _V1189_CHAIN_LINES[1]}
    assert state["fixes"][legacy]["recurrence_reported"] is True
    assert not state["fixes"][_V1189_CHAIN_LINES[1]].get("recurrence_reported")
    # Restart/reload must not produce another finding or recurrence notification.
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


def test_normalization_merges_volatile_values_and_logger_prefixes():
    a = "WARNING:app.manager:task sync failed for [katya-work-orchestrator] /home/kesha/worktrees/a 123"
    b = "task sync failed for [other-work-orchestrator] /srv/orchestra/worktrees/b 998"
    assert watch.normalize_signature(a) == watch.normalize_signature(b)
    assert watch.normalize_signature("[designer] listen task exited") == "[SESSION] listen task exited"


def test_distinct_causes_remain_distinct():
    left = watch.normalize_signature("connect failed: FileNotFoundError: no such file")
    right = watch.normalize_signature("native Codex compact failed: FileNotFoundError: no such file")
    assert left != right


def test_normalization_removes_credentials_urls_and_email_addresses():
    message = "request failed https://example.invalid/path?token=longsecretvalue123 user=owner@example.invalid"
    result = watch.normalize_signature(message)
    assert "longsecretvalue123" not in result
    assert "owner@example.invalid" not in result
    assert "<URL>" in result
    assert "<EMAIL>" in result


def test_threshold_and_quota_noise_classification():
    events = [_event("quota rate_limit blocked", i) for i in range(3)]
    events += [_event("database transaction failed: Locked", i) for i in range(2)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=3)
    assert candidates == []
    assert noise[0]["count"] == 3
    assert noise[0]["noise"] == "quota/rate limit"
    assert watch.classify_noise(watch.normalize_signature("command exited with code 143")) == "expected command termination"
    assert watch.classify_noise(watch.normalize_signature("Merge operation x: FAILED — DIFF TOO LARGE: 2720 insertions (limit 2000).")) == "merge gate refusal"
    assert watch.classify_noise(watch.normalize_signature("Exit code 1")) == "agent command exit code"
    assert watch.classify_noise(watch.normalize_signature("This app tool requires a non-empty string link_id argument")) == "external app tool argument"
    missing = "File does not exist. Note: your current working directory is /home/kesha/x."
    assert watch.classify_noise(watch.normalize_signature(missing)) == "agent read of missing file"


@pytest.mark.parametrize("call", ["t3_thread_wait", "t3_thread_read"])
@pytest.mark.parametrize("cause", [
    "RemoteProtocolError", "ReadError", "ReadTimeout", "ConnectError", "HTTP 503",
])
@pytest.mark.parametrize("delay", [1, 2, 4, 8, "<N>"])
def test_hub_watch_intermediate_retry_is_noise(call, cause, delay):
    message = f"hub {call} failed; retrying in {delay}s: MultiCode MCP request failed: {cause}"
    assert watch.classify_noise(message) == "hub watch read retry"
    assert watch.classify_noise(watch.normalize_signature(message)) == "hub watch read retry"
    logged = "WARNING:app.backend_hub:" + message
    assert watch.classify_noise(watch.normalize_signature(logged)) == "hub watch read retry"


@pytest.mark.parametrize("cause", [
    "RemoteProtocolError", "ReadError", "ReadTimeout", "ConnectError", "HTTP 503",
])
@pytest.mark.parametrize("prefix", ["", "Hub worker turn failed: "])
def test_hub_watch_final_exception_stays_actionable(cause, prefix):
    message = prefix + "MultiCode MCP request failed: " + cause
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(watch.normalize_signature(message)) is None


@pytest.mark.parametrize("message", [
    "hub watch request exceeded 60 seconds",
    "Hub worker turn failed: hub watch request exceeded 60 seconds",
    "hub t3_thread_wait failed: MultiCode MCP request failed: ReadTimeout",
    "hub t3_thread_read failed: MultiCode MCP request failed: ReadTimeout",
    "hub t3_thread_send failed; retrying in 1s: MultiCode MCP request failed: ReadTimeout",
    "hub t3_thread_launch failed; retrying in 1s: MultiCode MCP request failed: ReadTimeout",
])
def test_hub_watch_failures_outside_read_retry_stay_actionable(message):
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(watch.normalize_signature(message)) is None


def test_hub_watch_retries_do_not_hide_final_failure():
    retry = "WARNING:app.backend_hub:hub t3_thread_wait failed; retrying in 8s: MultiCode MCP request failed: ReadTimeout"
    final = "Hub worker turn failed: MultiCode MCP request failed: ReadTimeout"
    events = [_event(retry, i) for i in range(3)]
    events += [_event(final, i, source="logs") for i in range(3)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=3)
    assert [(item["signature"], item["count"]) for item in candidates] == [
        (watch.normalize_signature(final), 3),
    ]
    assert [(item["noise"], item["count"]) for item in noise] == [("hub watch read retry", 3)]


@pytest.mark.parametrize("reset", [
    "5h 2026-10-24T09:30:34Z",
    "7d 2026-10-31T09:30:34.123456Z",
    "5h 2026-10-24T12:30:34+03:00",
    "5h 2026-10-24T09:30:34Z, 7d 2026-10-31T09:30:34Z",
    "5h неизвестно",
    "primary неизвестно, secondary неизвестно",
    "primary 2026-10-24T09:30:34Z, secondary неизвестно",
])
def test_codex_quota_refusal_is_noise_raw_and_normalized(reset):
    message = f"квота Codex исчерпана, сброс {reset}"
    assert watch.classify_noise(message) == "quota/rate limit"
    assert watch.classify_noise(watch.normalize_signature(message)) == "quota/rate limit"
    logged = "ERROR:app.session:" + message
    assert watch.classify_noise(watch.normalize_signature(logged)) == "quota/rate limit"


@pytest.mark.parametrize("message", [
    "квота Codex: ошибка провайдера HTTP 503",
    "квота Codex: ошибка учёта использованных токенов",
    "квота Codex: ошибка парсера resets_at",
    "квота Codex: сервис недоступен",
    "квота другого провайдера исчерпана, сброс 5h 2026-10-24T09:30:34Z",
    "квота Codex исчерпана, сброс 5h: ошибка парсера",
    "квота Codex исчерпана, сброс 5h 2026-10-24T09:30:34Z; ошибка учёта",
    "ошибка провайдера: квота Codex исчерпана, сброс 5h 2026-10-24T09:30:34Z",
])
def test_distinct_russian_quota_failure_stays_actionable(message):
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(watch.normalize_signature(message)) is None
    candidates, noise = watch.aggregate(
        [_event(message, i, source="logs") for i in range(10)],
        datetime.now(timezone.utc),
    )
    assert len(candidates) == 1
    assert candidates[0]["count"] == 10
    assert noise == []


@pytest.mark.parametrize("message", [
    "quota exhausted", "rate_limit exceeded", "rate limited", "rate_limited",
    "subscription limit reached",
])
def test_english_quota_noise_unchanged(message):
    assert watch.classify_noise(message) == "quota/rate limit"
    assert watch.classify_noise(watch.normalize_signature(message)) == "quota/rate limit"


_CAPACITY_REFUSAL = "Selected model is at capacity. Please try a different model."


@pytest.mark.parametrize("message", [
    _CAPACITY_REFUSAL,
    "ERROR:app.session:" + _CAPACITY_REFUSAL,
    "WARNING:app.backend_hub: " + _CAPACITY_REFUSAL,
    " \t" + _CAPACITY_REFUSAL + "\r\n",
    "ERROR:app.session: Selected model is at capacity.\n  Please try a different model.\n",
])
@pytest.mark.parametrize("source", ["logs", "journalctl"])
def test_standalone_provider_capacity_is_noise_without_changing_event(message, source):
    event = dict(_event(message, source=source), type="error")
    original = dict(event)
    assert watch.classify_noise(_CAPACITY_REFUSAL) == "external provider capacity"
    assert watch.normalize_signature(message) == _CAPACITY_REFUSAL
    assert watch.classify_noise(watch.normalize_signature(message)) == "external provider capacity"
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=1)
    assert candidates == []
    assert [(item["signature"], item["noise"], item["count"]) for item in noise] == [
        (_CAPACITY_REFUSAL, "external provider capacity", 1),
    ]
    assert event == original


@pytest.mark.parametrize("message", [
    "Hub worker turn failed: " + _CAPACITY_REFUSAL,
    "Hub worker turn failed: hub thread ended with status failed; " + _CAPACITY_REFUSAL,
    "Hub worker turn failed: RuntimeError: " + _CAPACITY_REFUSAL,
    "RuntimeError: " + _CAPACITY_REFUSAL,
    "Data loss detected; " + _CAPACITY_REFUSAL,
    _CAPACITY_REFUSAL + " Data loss detected.",
    _CAPACITY_REFUSAL + "\nTraceback (most recent call last): RuntimeError: delivery failed",
    "ERROR:app.session:" + _CAPACITY_REFUSAL + " DatabaseError: transaction failed",
    'Parser failed while reading "' + _CAPACITY_REFUSAL + '"',
    '"' + _CAPACITY_REFUSAL + '"',
    "Other failure: " + _CAPACITY_REFUSAL,
    "Selected model is at capacity.",
    "Please try a different model.",
    _CAPACITY_REFUSAL.lower(),
    _CAPACITY_REFUSAL[:-1],
    "database capacity exceeded",
    "worker capacity accounting failed",
])
def test_other_capacity_messages_stay_actionable_raw_and_normalized(message):
    signature = watch.normalize_signature(message)
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(signature) is None
    events = [_event(message, i, source="logs") for i in range(10)]
    assert watch.aggregate(events[:9], datetime.now(timezone.utc)) == ([], [])
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc))
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 10)]
    assert noise == []
    started = datetime.fromisoformat(events[0]["ts"])
    assert watch.post_fix_verdict(events, signature, started, 168)["count"] == 10


@pytest.mark.parametrize("failure", [
    _CAPACITY_REFUSAL + " Data loss detected.",
    "ERROR:app.session:" + _CAPACITY_REFUSAL + "\nRuntimeError: delivery failed",
    "Hub worker turn failed: " + _CAPACITY_REFUSAL,
    "Hub worker turn failed: hub thread ended with status failed; " + _CAPACITY_REFUSAL,
    'Parser failed while reading "' + _CAPACITY_REFUSAL + '"',
])
def test_capacity_scan_groups_expected_refusal_but_reports_real_errors(
    failure, hub_finish_db, monkeypatch, capsys, scan_reports,
):
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    stamp = started + timedelta(seconds=1)
    raw = "ERROR:app.session: Selected model is at capacity.\n  Please try a different model.\n"
    _insert_error_rows(hub_finish_db, [("error", _CAPACITY_REFUSAL, None, 1)] * 5 + [
        ("error", raw, None, 1),
    ] * 4, stamp)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    args = SimpleNamespace(db=str(hub_finish_db), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_events"] == 0

    _insert_error_rows(hub_finish_db, [("error", raw, None, 1)], stamp)
    original_events = watch.collect_db_events(hub_finish_db, started)
    assert [event["message"] for event in original_events] == [_CAPACITY_REFUSAL] * 5 + [raw] * 5
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_count"] == 1
    assert output["noise_events"] == 10
    assert output["noise_by_class"] == {"external provider capacity": 10}

    assert watch.record_fix(SimpleNamespace(
        db=str(hub_finish_db), signature=_CAPACITY_REFUSAL, task="legacy-capacity-control",
        commit="example", started_at=started.isoformat(), window_hours=168,
    )) == 0
    capsys.readouterr()
    state_path = hub_finish_db.parent / "error_watch.json"
    fixes = watch._load_state(state_path)["fixes"]
    args.dry_run = False
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    state = watch._load_state(state_path)
    assert state["alerts"] == {}
    assert state["fixes"] == fixes
    assert watch.collect_db_events(hub_finish_db, started) == original_events

    _insert_error_rows(hub_finish_db, [("error", failure, None, 1)] * 9, stamp)
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    _insert_error_rows(hub_finish_db, [("error", failure, None, 1)], stamp)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    signature = watch.normalize_signature(failure)
    assert [(item["signature"], item["count"]) for item in signals] == [(signature, 10)]
    assert verdicts == []
    state = watch._load_state(state_path)
    assert set(state["alerts"]) == {signature}
    assert state["fixes"] == fixes
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


def test_capacity_refusal_fix_observation_completes_without_recurrence():
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    event = dict(_event(_CAPACITY_REFUSAL, source="logs"), ts=started.isoformat())
    result = watch.post_fix_verdict([event], _CAPACITY_REFUSAL, started, 1)
    assert result["count"] == 0
    assert result["complete"] is True


def test_repeated_codex_quota_refusals_are_aggregated_without_alert(tmp_path, monkeypatch, capsys, scan_reports):
    events = [
        _event(f"квота Codex исчерпана, сброс 5h 2026-10-24T09:{30 + i}:34Z", i, source="logs")
        for i in range(10)
    ]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc))
    assert candidates == []
    assert len(noise) == 1
    assert noise[0]["count"] == 10
    assert noise[0]["noise"] == "quota/rate limit"

    monkeypatch.setattr(watch, "collect_db_events", lambda *_: events)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: [])
    args = SimpleNamespace(db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_events"] == 10
    assert output["noise_by_class"] == {"quota/rate limit": 10}

    args.dry_run = False
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    assert watch._load_state(tmp_path / "error_watch.json")["alerts"] == {}

    failure = "квота Codex: ошибка учёта использованных токенов"
    events.extend(_event(failure, i, source="logs") for i in range(10))
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [(item["signature"], item["count"]) for item in signals] == [(failure, 10)]
    assert verdicts == []
    assert set(watch._load_state(tmp_path / "error_watch.json")["alerts"]) == {failure}
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert set(watch._load_state(tmp_path / "error_watch.json")["alerts"]) == {failure}


@pytest.mark.parametrize("reset", ["5h 2026-10-24T09:30:34Z", "primary неизвестно, secondary неизвестно"])
def test_record_fix_then_scan_ignores_codex_refusal_but_reports_real_recurrence(
    reset, tmp_path, monkeypatch, capsys, scan_reports,
):
    expected = f"квота Codex исчерпана, сброс {reset}"
    failure = expected + "; ошибка учёта"
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_path = tmp_path / "orchestra.db"
    for message, task in ((expected, "V-1068"), (failure, "real-failure-control")):
        assert watch.record_fix(SimpleNamespace(
            db=str(db_path), signature=message, task=task, commit="example",
            started_at=started.isoformat(), window_hours=168,
        )) == 0
        capsys.readouterr()
        assert watch._load_state(tmp_path / "error_watch.json")["fixes"][watch.normalize_signature(message)] == {
            "task": task, "commit": "example", "started_at": started.isoformat(), "window_hours": 168,
        }
    expected_signature = watch.normalize_signature(expected)
    failure_signature = watch.normalize_signature(failure)
    state_path = tmp_path / "error_watch.json"
    assert set(watch._load_state(state_path)["fixes"]) == {expected_signature, failure_signature}

    events = [
        dict(_event(expected, source="logs"), ts=(started + timedelta(seconds=i + 1)).isoformat())
        for i in range(10)
    ]
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: events)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: [])
    args = SimpleNamespace(db=str(db_path), window_hours=168, threshold=10, dry_run=False)
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    state = watch._load_state(state_path)
    assert not state["fixes"][expected_signature].get("recurrence_reported")
    assert state["alerts"] == {}

    events.append(dict(_event(failure, source="logs"), ts=(started + timedelta(seconds=30)).isoformat()))
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert signals == []
    assert [(item["signature"], item["task"], item["count"], item["complete"]) for item in verdicts] == [
        (failure_signature, "real-failure-control", 1, False),
    ]
    state = watch._load_state(state_path)
    assert set(state["fixes"]) == {expected_signature, failure_signature}
    assert not state["fixes"][expected_signature].get("recurrence_reported")
    assert state["fixes"][failure_signature]["recurrence_reported"] is True
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


@pytest.mark.parametrize("message", ["quota rate_limit blocked", "PreToolUse: policy refusal"])
def test_other_noise_still_counts_as_registered_fix_recurrence(message):
    event = _event(message, source="logs")
    assert watch.classify_noise(watch.normalize_signature(message)) is not None
    result = watch.post_fix_verdict(
        [event], watch.normalize_signature(message), datetime.fromisoformat(event["ts"]), 168,
    )
    assert result["count"] == 1


def test_codex_refusal_fix_observation_can_complete_without_recurrence():
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    message = "квота Codex исчерпана, сброс 5h неизвестно"
    event = dict(_event(message, source="logs"), ts=(started + timedelta(minutes=1)).isoformat())
    result = watch.post_fix_verdict([event], watch.normalize_signature(message), started, 1)
    assert result["count"] == 0
    assert result["complete"] is True


def test_normal_listener_end_is_noise_but_running_failure_is_actionable():
    idle = "WARNING:app.session:[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"
    waiting = "[session-b] listen task exited without exception (silent death), status=AgentStatus.WAITING"
    assert watch.classify_noise(watch.normalize_signature(idle)) == "normal per-turn listener completion"
    assert watch.classify_noise(watch.normalize_signature(waiting)) == "normal per-turn listener completion"
    event = _event("listen task exited unexpectedly while RUNNING")
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=10)
    assert len(candidates) == 1
    assert candidates[0]["count"] == 1
    assert noise == []


def test_successful_http_access_lines_triggered_by_error_words_are_noise():
    events = [
        _event(
            f'INFO:     127.0.0.1:{52000 + i} - "GET /api/logs/search?query=failed-{i} '
            'HTTP/1.1" 200 OK',
            i,
        )
        for i in range(12)
    ]

    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=10)

    assert candidates == []
    assert [(item["count"], item["noise"]) for item in noise] == [(12, "successful HTTP access log")]


def test_http_failures_and_access_lines_with_traceback_stay_actionable():
    messages = [
        'INFO:     127.0.0.1:52000 - "GET /api/logs/search?query=failed HTTP/1.1" 404 Not Found',
        'INFO:     127.0.0.1:52001 - "GET /api/logs/search?query=failed HTTP/1.1" 500 Internal Server Error',
        'INFO:     127.0.0.1:52002 - "GET /api/logs/search?query=failed HTTP/1.1" 200 OK\n'
        'Traceback (most recent call last):\nRuntimeError: downstream request failed',
    ]
    events = [_event(message, i) for i, message in enumerate(messages)]

    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=1)

    assert len(candidates) == 3
    assert noise == []
    assert any("Not Found" in item["signature"] for item in candidates)
    assert any("Internal Server Error" in item["signature"] for item in candidates)
    assert any("Traceback" in item["signature"] and "RuntimeError" in item["signature"] for item in candidates)


_V1191_HTTP_ACCESS = 'INFO:     192.0.2.1:52000 - "GET /api/search?query=failed HTTP/1.1" 200 OK'
_V1191_HTTP_SIGNATURE = 'INFO: <N>.<N>:<N> - "GET <PATH> HTTP/<N>" <N> OK'


@pytest.fixture
def v1191_journal_scan(hub_finish_db, monkeypatch):
    # Exercise real journal JSON parsing, filtering, normalization and scan. Only
    # the subprocess boundary is replaced; DB and state are synthetic local files.
    rows = []
    collect = watch.collect_journal_events
    runner = Mock(side_effect=lambda *args, **kwargs: SimpleNamespace(
        stdout="\n".join(json.dumps(row) for row in rows),
    ))
    monkeypatch.setattr(watch, "collect_journal_events", lambda since, scopes: collect(
        since, scopes, runner=runner,
    ))
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    return hub_finish_db, rows, runner


def _v1191_access_rows(message, started, count=10):
    return [
        {
            "MESSAGE": message,
            "__REALTIME_TIMESTAMP": str(int((started + timedelta(seconds=i + 1)).timestamp() * 1_000_000)),
        }
        for i in range(count)
    ]


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("already_reported", [False, True])
def test_v1191_successful_access_scan_with_legacy_fix_state(
    complete, already_reported, v1191_journal_scan, capsys, scan_reports,
):
    db_path, rows, runner = v1191_journal_scan
    started = datetime.now(timezone.utc) - timedelta(hours=2 if complete else 1)
    rows.extend(_v1191_access_rows(_V1191_HTTP_ACCESS, started))
    assert watch.normalize_signature(_V1191_HTTP_ACCESS) == _V1191_HTTP_SIGNATURE
    # A normalized signature has lost the HTTP status. It cannot by itself prove success.
    assert watch.classify_noise(_V1191_HTTP_SIGNATURE) is None
    fix = {
        "task": "V-1174", "commit": "example", "started_at": started.isoformat(),
        "window_hours": 1 if complete else 168,
    }
    if already_reported:
        fix["recurrence_reported"] = True
    state_path = db_path.parent / "error_watch.json"
    legacy = {"alerts": {_V1191_HTTP_SIGNATURE: {"count": 12}}, "fixes": {_V1191_HTTP_SIGNATURE: fix}}
    watch._write_state(state_path, legacy)
    args = SimpleNamespace(db=str(db_path), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["events_by_source"] == {"journalctl": 10, "logs": 0}
    assert output["noise_by_class"] == {"successful HTTP access log": 10}
    assert watch._load_state(state_path) == legacy

    args.dry_run = False
    assert watch.scan(args) == 0
    output = capsys.readouterr().out
    if complete:
        signals, verdicts = scan_reports.call_args.args
        assert signals == []
        assert [(v["signature"], v["task"], v["count"], v["complete"]) for v in verdicts] == [
            (_V1191_HTTP_SIGNATURE, "V-1174", 0, True),
        ]
        assert "не повторилась за окно 1 ч" in output
    else:
        assert not scan_reports.called
        assert output.strip() == "No new error-watch findings"
    state = watch._load_state(state_path)
    assert state["fixes"] == {
        _V1191_HTTP_SIGNATURE: {**fix, **({"completion_reported": True} if complete else {})},
    }
    # Reload the persisted flags, then lose the access records from the window.
    # Neither case should re-alert, reset old flags or remove the fix metadata.
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert watch._load_state(state_path) == state
    rows.clear()
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert watch._load_state(state_path)["fixes"] == state["fixes"]
    assert scan_reports.call_count == int(complete)
    assert runner.call_count == 4


@pytest.mark.parametrize("source,message", [
    ("logs", _V1191_HTTP_ACCESS),
    ("logs", _V1191_HTTP_SIGNATURE),
    # Even an inconsistent status/reason line must not be accepted from its
    # normalized key: 500 OK and 200 OK produce exactly the same signature.
    ("journalctl", _V1191_HTTP_ACCESS.replace("200 OK", "500 OK")),
])
def test_v1191_successful_access_does_not_hide_errors_with_identical_signature(
    source, message, v1191_journal_scan, capsys, scan_reports,
):
    db_path, rows, _ = v1191_journal_scan
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    stamp = started + timedelta(seconds=1)
    rows.extend(_v1191_access_rows(_V1191_HTTP_ACCESS, started))
    assert watch.record_fix(SimpleNamespace(
        db=str(db_path), signature=_V1191_HTTP_ACCESS, task="V-1174", commit="example",
        started_at=started.isoformat(), window_hours=168,
    )) == 0
    capsys.readouterr()
    args = SimpleNamespace(db=str(db_path), window_hours=168, threshold=10, dry_run=False)
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called

    # Same normalized key, but a failed HTTP status or explicitly flagged DB
    # error must still count without counting the ten successful access records.
    assert watch.normalize_signature(message) == _V1191_HTTP_SIGNATURE

    def insert_errors(count):
        if source == "journalctl":
            rows.extend(_v1191_access_rows(message, started + timedelta(seconds=len(rows) + 1), count))
        else:
            _insert_error_rows(db_path, [("error", message, None, 1)] * count, stamp)

    insert_errors(1)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert signals == []
    assert [(v["signature"], v["count"]) for v in verdicts] == [(_V1191_HTTP_SIGNATURE, 1)]
    state_path = db_path.parent / "error_watch.json"
    assert watch._load_state(state_path)["fixes"][_V1191_HTTP_SIGNATURE]["recurrence_reported"] is True
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1

    insert_errors(9)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [(s["signature"], s["count"]) for s in signals] == [(_V1191_HTTP_SIGNATURE, 10)]
    assert verdicts == []


@pytest.mark.parametrize("message", [
    _V1191_HTTP_ACCESS.replace("200 OK", "404 Not Found"),
    _V1191_HTTP_ACCESS.replace("200 OK", "500 Internal Server Error"),
    _V1191_HTTP_ACCESS + "\nTraceback (most recent call last):\nRuntimeError: downstream failed",
    "ERROR: request failed while parsing " + _V1191_HTTP_ACCESS,
    _V1191_HTTP_ACCESS + "; request refused: policy error: denied",
    _V1191_HTTP_ACCESS.replace("INFO:", "ERROR:"),
    "request refused: authentication failed",
])
def test_v1191_real_http_errors_and_refusals_scan_and_recur(
    message, v1191_journal_scan, capsys, scan_reports,
):
    db_path, rows, _ = v1191_journal_scan
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    rows.extend(_v1191_access_rows(message, started))
    assert watch.record_fix(SimpleNamespace(
        db=str(db_path), signature=message, task="http-error-control", commit="example",
        started_at=started.isoformat(), window_hours=168,
    )) == 0
    capsys.readouterr()
    signature = watch.normalize_signature(message)
    args = SimpleNamespace(db=str(db_path), window_hours=168, threshold=10, dry_run=False)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [(s["signature"], s["count"]) for s in signals] == [(signature, 10)]
    assert [(v["signature"], v["count"], v["complete"]) for v in verdicts] == [(signature, 10, False)]
    state_path = db_path.parent / "error_watch.json"
    state = watch._load_state(state_path)
    assert state["alerts"][signature]["count"] == 10
    assert state["fixes"][signature]["recurrence_reported"] is True
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


def test_journal_logger_and_root_handler_lines_count_as_one_event():
    stamp = "2026-09-27T12:00:00+00:00"
    events = [
        {"source": "journalctl", "ts": stamp, "message": "[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
        {"source": "journalctl", "ts": stamp, "message": "WARNING:app.session:[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
        {"source": "journalctl", "ts": stamp, "message": "[session-b] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
    ]
    _candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=1)
    assert noise[0]["count"] == 2


def test_post_fix_count_uses_deduplicated_logger_events():
    stamp = "2026-09-27T12:00:00+00:00"
    message = "task sync failed for [session-a]"
    events = [
        {"source": "journalctl", "ts": stamp, "message": message},
        {"source": "journalctl", "ts": stamp, "message": "WARNING:app.manager:" + message},
    ]
    signature = watch.normalize_signature(message)
    result = watch.post_fix_verdict(
        watch.deduplicate_events(events), signature,
        datetime.fromisoformat("2026-09-27T11:00:00+00:00"), 24,
    )
    assert result["count"] == 1


def test_scan_deduplicates_repeated_runs_without_new_events(tmp_path, monkeypatch, capsys, scan_reports):
    events = [_event("database transaction failed: Locked", i) for i in range(3)]
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: events)
    monkeypatch.setattr(watch, "_existing_refs", lambda _signature: [])
    args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=3,
        dry_run=False,
    )
    watch.scan(args)
    capsys.readouterr()
    signature = watch.normalize_signature(events[0]["message"])
    signals, verdicts = scan_reports.call_args.args
    assert [(item["signature"], item["count"]) for item in signals] == [(signature, 3)]
    assert verdicts == []
    state_path = tmp_path / "error_watch.json"
    state = watch._load_state(state_path)
    assert state["alerts"][signature]["count"] == 3
    watch.scan(args)
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


def test_known_error_series_suppress_baseline_and_alert_on_new_growth(tmp_path, monkeypatch, capsys, scan_reports):
    series = [
        ("/usr/bin/python: No module named pytest", ("V-783",)),
        ("transport_timeout: Message delivery outcome is ambiguous: ReadTimeout", ("V-778", "V-782")),
    ]
    current = {"events": []}
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: current["events"])

    for index, (message, tasks) in enumerate(series):
        scan_reports.reset_mock()
        signature = watch.normalize_signature(message)
        args = SimpleNamespace(
            db=str(tmp_path / f"{index}.db"), window_hours=168, threshold=10,
            dry_run=False,
        )
        scope = str(Path(watch.__file__).resolve().parents[1]) if "No module named pytest" in message else None
        current["events"] = [_event(message, i, scope=scope) for i in range(10)]
        watch.scan(args)
        capsys.readouterr()
        assert not scan_reports.called

        current["events"] = [_event(message, i, scope=scope) for i in range(11)]
        watch.scan(args)
        capsys.readouterr()
        signals, verdicts = scan_reports.call_args.args
        assert [(item["signature"], item["count"]) for item in signals] == [(signature, 11)]
        assert signals[0]["known"]["known"]["tasks"] == list(tasks)
        assert verdicts == []

        watch.scan(args)
        capsys.readouterr()
        assert scan_reports.call_count == 1

        current["events"] = [_event(message, i, scope=scope) for i in range(9)]
        watch.scan(args)
        capsys.readouterr()
        assert scan_reports.call_count == 1

        current["events"] = [_event(message, i, scope=scope) for i in range(11)]
        watch.scan(args)
        capsys.readouterr()
        assert scan_reports.call_count == 2
        signals, verdicts = scan_reports.call_args.args
        assert [(item["signature"], item["count"]) for item in signals] == [(signature, 11)]
        assert signals[0]["known"]["known"]["tasks"] == list(tasks)
        assert verdicts == []


def test_post_fix_verdict_reports_recurrence_and_open_window():
    start = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
    events = [_event("ImportError: cannot import name '_fire_sync'", 30)]
    assert watch.post_fix_verdict(events, watch.normalize_signature(events[0]["message"]), start, 24)["count"] == 1
    empty = watch.post_fix_verdict([], "some error", datetime.now(timezone.utc), 24)
    assert empty["count"] == 0
    assert empty["complete"] is False


def test_pytest_known_series_is_scoped_to_orchestra_for_noise_and_post_fix(tmp_path, monkeypatch, capsys):
    message = "/usr/bin/python: No module named pytest"
    signature = watch.normalize_signature(message)
    orchestra_scope = str(Path(watch.__file__).resolve().parents[1])
    foreign_scope = str(tmp_path / "seedon")
    assert watch._ORCHESTRA_SCOPE == orchestra_scope
    events = [
        _event(message, scope=orchestra_scope),
        _event(message, minute=1, scope=foreign_scope),
    ]

    assert watch._known_series_counts(events)[signature] == 1
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=1)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 1)]
    assert [(item["noise"], item["count"]) for item in noise] == [
        ("pytest missing outside Orchestra scope", 1),
    ]

    started = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
    assert watch.post_fix_verdict(events, signature, started, 24)["count"] == 1

    current = {"events": events}
    watch_args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=1, dry_run=True,
    )
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: current["events"])
    watch.scan(watch_args)
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_by_class"] == {"pytest missing outside Orchestra scope": 1}


def test_collect_db_events_keeps_session_scope(tmp_path):
    db_path = tmp_path / "orchestra.db"
    stamp = "2026-10-10T08:45:59+00:00"
    foreign_scope = str(tmp_path / "seedon")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT);"
            "CREATE TABLE logs (ts TEXT, type TEXT, content TEXT, tool_is_error INTEGER, session_id TEXT, tool_name TEXT);"
        )
        connection.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            [
                ("orchestra-worker", "worker", str(Path(watch.__file__).resolve().parents[1])),
                ("seedon-worker", "tender-triage", foreign_scope),
            ],
        )
        connection.executemany(
            "INSERT INTO logs VALUES (?, 'error', '/usr/bin/python: No module named pytest', 1, ?, NULL)",
            [(stamp, "orchestra-worker"), (stamp, "seedon-worker")],
        )

    events = watch.collect_db_events(
        db_path, datetime(2026, 10, 10, tzinfo=timezone.utc),
    )
    assert {event["scope"] for event in events} == {
        str(Path(watch.__file__).resolve().parents[1]), foreign_scope,
    }


def test_completed_post_fix_window_reports_absence():
    start = datetime.now(timezone.utc) - timedelta(hours=25)
    result = watch.post_fix_verdict([], "some error", start, 24)
    assert result["complete"] is True
    assert result["count"] == 0


def test_record_fix_persists_task_commit_and_process_start(tmp_path, capsys):
    args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), signature="ImportError: path /tmp/x 42",
        task="V-636", commit="9035836a", started_at="2026-09-27T04:49:07+00:00",
        window_hours=168,
    )
    watch.record_fix(args)
    capsys.readouterr()
    state = watch._load_state(tmp_path / "error_watch.json")
    entry = state["fixes"][watch.normalize_signature(args.signature)]
    assert entry == {
        "task": "V-636", "commit": "9035836a",
        "started_at": "2026-09-27T04:49:07+00:00", "window_hours": 168,
    }


def test_v952_merge_refused_for_busy_worker_is_expected_noise():
    message = "Merge operation x: FAILED — Worker is waiting; wait until it is idle, then start a new merge operation."
    assert watch.classify_noise(watch.normalize_signature(message)) == "merge refused: worker not idle"


_MERGE_SHA_REFUSAL = (
    "Merge operation 12345678-abcd-4321-abcd-123456789abc: FAILED — "
    "expected_head must be the full 40-character SHA from worker_wip. "
    "Inspect worker_wip and supply its full SHA and a meaningful acceptance_note, "
    "then start a new operation."
)


@pytest.mark.parametrize("message", [
    _MERGE_SHA_REFUSAL,
    _MERGE_SHA_REFUSAL.replace("40-character", "64-character"),
    _MERGE_SHA_REFUSAL.replace("12345678-abcd-4321-abcd-123456789abc", "<ID>").replace("40-character", "<N>-character"),
])
def test_merge_full_sha_refusal_is_noise_raw_and_normalized(message):
    assert watch.classify_noise(message) == "merge refused: full expected_head required"
    assert watch.classify_noise(watch.normalize_signature(message)) == "merge refused: full expected_head required"
    assert watch.classify_noise(watch.normalize_signature("ERROR:app.merge:" + message)) == "merge refused: full expected_head required"


@pytest.mark.parametrize("message", [
    "Merge operation x: FAILED — expected_head does not match worker_wip HEAD.",
    "Merge operation x: FAILED — merge conflict in app/example.py",
    "Merge operation x: FAILED — acceptance gate failed: tests did not pass",
    "Merge operation x: FAILED — expected_head validation failed unexpectedly",
    _MERGE_SHA_REFUSAL + " Gate failed unexpectedly.",
    "Unexpected merge failure: " + _MERGE_SHA_REFUSAL,
])
def test_other_merge_failures_stay_actionable(message):
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(watch.normalize_signature(message)) is None
    candidates, noise = watch.aggregate(
        [_event(message, i, source="logs") for i in range(12)], datetime.now(timezone.utc),
    )
    assert [(item["signature"], item["count"]) for item in candidates] == [(watch.normalize_signature(message), 12)]
    assert noise == []


def test_merge_full_sha_refusal_scan_and_old_fix_keep_real_failure_visible(
    tmp_path, monkeypatch, capsys, scan_reports,
):
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    events = [
        dict(_event(_MERGE_SHA_REFUSAL, source="logs"), ts=(started + timedelta(seconds=i)).isoformat())
        for i in range(12)
    ]
    signature = watch.normalize_signature(_MERGE_SHA_REFUSAL)
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc))
    assert candidates == []
    assert [(item["signature"], item["count"], item["noise"]) for item in noise] == [
        (signature, 12, "merge refused: full expected_head required"),
    ]

    db_path = tmp_path / "orchestra.db"
    assert watch.record_fix(SimpleNamespace(
        db=str(db_path), signature=_MERGE_SHA_REFUSAL, task="V-1103", commit="example",
        started_at=started.isoformat(), window_hours=168,
    )) == 0
    capsys.readouterr()
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: events)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: [])
    args = SimpleNamespace(db=str(db_path), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_by_class"] == {"merge refused: full expected_head required": 12}
    args.dry_run = False
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    assert watch.post_fix_verdict(events, signature, started, 168)["count"] == 0

    failure = "Merge operation x: FAILED — expected_head does not match worker_wip HEAD."
    failure_events = [
        dict(_event(failure, source="logs"), ts=(started + timedelta(seconds=i)).isoformat())
        for i in range(12)
    ]
    events.extend(failure_events)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [(item["signature"], item["count"]) for item in signals] == [(failure, 12)]
    assert verdicts == []
    state = watch._load_state(tmp_path / "error_watch.json")
    assert set(state["alerts"]) == {failure}
    assert not state["fixes"][signature].get("recurrence_reported")
    assert watch.post_fix_verdict(events, failure, started, 168)["count"] == 12
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(tmp_path / "error_watch.json") == state


def test_hub_turn_failure_signatures_preserve_error_class_and_http_status():
    causes = [
        ("ReadError('connection reset')", "ReadError"),
        ("httpx.RemoteProtocolError: peer disconnected", "RemoteProtocolError"),
        ("MultiCode MCP returned HTTP 400 for request 123", "HTTP 400"),
        ("MultiCode MCP returned HTTP 503 for request 456", "HTTP 503"),
        ("hub thread ended with status failed (thread 789)", "hub thread ended with status failed"),
    ]
    signatures = []
    for cause, expected in causes:
        message = f"WARNING:app.session:[worker-a] turn FAILED: (no output)\nHub worker turn failed: {cause}"
        signature = watch.normalize_signature(message)
        assert signature == f"Hub worker turn failed: {expected}"
        assert watch.normalize_signature(signature) == signature
        signatures.append(signature)
    assert len(set(signatures)) == len(causes)


def test_hub_turn_failure_signatures_drop_volatile_details():
    pairs = [
        (
            "ReadError('request 123 /home/worker/a 0123456789abcdef')",
            "httpx.ReadError: request 456 /srv/work/b fedcba9876543210",
        ),
        (
            "MultiCode MCP returned HTTP 400: request 123 /home/worker/a",
            "MultiCode MCP returned HTTP 400: thread 456 /srv/work/b",
        ),
        (
            "hub thread ended with status failed: id=123 /home/worker/a",
            "hub thread ended with status failed: id=456 /srv/work/b",
        ),
        (
            "unknown hub failure: /home/worker/a 123 0123456789abcdef",
            "unknown hub failure: /srv/work/b 456 fedcba9876543210",
        ),
    ]
    for left, right in pairs:
        a = watch.normalize_signature("Hub worker turn failed: " + left)
        b = watch.normalize_signature("Hub worker turn failed: " + right)
        assert a == b
        assert "123" not in a and "/home/worker/a" not in a


@pytest.mark.parametrize("prefix", [
    "", "Hub worker turn failed: ",
    "ERROR:app.backend_hub:Hub worker turn failed: ",
])
def test_hub_missing_owned_dirs_refusal_is_expected_noise(prefix):
    message = prefix + (
        "this hub worker has no owned_dirs, and only projects marked persistent in data/hub-projects.json "
        "go to the hub whole. Nothing was uploaded. The orchestrator must set owned_dirs: call "
        "set_worker_owned_dirs for this worker with the directories (or files) the task touches; "
        "repo-level files such as CLAUDE.md and pyproject.toml always go along."
    )
    signature = watch.normalize_signature(message)
    assert watch.classify_noise(message) == "hub owned_dirs guard refusal"
    assert watch.classify_noise(signature) == "hub owned_dirs guard refusal"
    events = [_event(message, i, source="logs") for i in range(10)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=10)
    assert candidates == []
    assert [(item["signature"], item["noise"], item["count"]) for item in noise] == [
        (signature, "hub owned_dirs guard refusal", 10),
    ]
    started = datetime.fromisoformat(events[0]["ts"])
    assert watch.post_fix_verdict(events, signature, started, 24)["count"] == 0


@pytest.mark.parametrize("message", [
    "hub sync FAILED: hub workspace download exceeds the size limit",
    "Hub worker turn failed: hub sync FAILED: hub workspace download exceeds the size limit",
    "Hub worker turn failed: something else went wrong",
    "Hub worker turn failed: this hub worker has no owned_dirs: unexpected configuration failure",
])
def test_hub_failures_outside_owned_dirs_guard_stay_actionable(message):
    signature = watch.normalize_signature(message)
    assert watch.classify_noise(message) is None
    assert watch.classify_noise(signature) is None
    events = [_event(message, i, source="logs") for i in range(10)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=10)
    assert noise == []
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 10)]
    started = datetime.fromisoformat(events[0]["ts"])
    assert watch.post_fix_verdict(events, signature, started, 24)["count"] == 10


def _expected_hub_failures():
    return [
        "Hub worker turn failed: Hub claude usage limit; use model='hubsol'",
        "Hub worker turn failed: RuntimeError: (no output); stop_reason=hub_provider_limit",
        "hub_provider_limit",
        "usage limit",
        "the task prompt contains a credential-shaped string; refusing to send it to the hub",
        "Hub worker turn failed: RuntimeError: the task prompt contains a credential-shaped string; refusing to send it to the hub",
    ]


def test_expected_hub_failures_never_become_recurring_findings():
    for message in _expected_hub_failures():
        events = [_event(message, i, source="logs") for i in range(10)]
        candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=10)
        assert candidates == [], message
        assert sum(item["count"] for item in noise) == 10
        assert {item["noise"] for item in noise} <= {
            "hub provider limit", "hub credential guard refusal",
        }


def test_expected_hub_failures_never_count_as_post_fix_recurrences():
    started = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
    for message in _expected_hub_failures():
        events = [_event(message, i, source="logs") for i in range(10)]
        signature = watch.normalize_signature(message)
        assert watch.post_fix_verdict(events, signature, started, 24)["count"] == 0, message
        # Older state may still contain the mixed, empty-output bucket.
        assert watch.post_fix_verdict(events, "(no output)", started, 24)["count"] == 0


def test_real_hub_transport_error_reaches_threshold_and_recurs_after_fix():
    messages = [
        "Hub worker turn failed: ReadError('connection reset for request 123 /home/worker/a')",
        "Hub worker turn failed: httpx.ReadError: peer closed connection 456 /srv/work/b",
        "Hub worker turn failed: ReadError('broken stream, thread 789')",
    ]
    now = datetime.now(timezone.utc)
    events = [_event(message, i, source="logs") for i, message in enumerate(messages)]
    assert watch.aggregate(events[:2], now, threshold=3) == ([], [])
    candidates, noise = watch.aggregate(events, now, threshold=3)
    assert noise == []
    assert [(item["signature"], item["count"]) for item in candidates] == [
        ("Hub worker turn failed: ReadError", 3),
    ]
    started = datetime(2026, 9, 27, 12, 1, tzinfo=timezone.utc)
    assert watch.post_fix_verdict(events, candidates[0]["signature"], started, 24)["count"] == 2


def test_expected_hub_outcome_beyond_output_wrapper_is_still_excluded():
    for message in _expected_hub_failures():
        wrapped = "Hub worker turn failed: RuntimeError: " + "(no output) " * 100 + message
        signature = watch.normalize_signature(wrapped)
        candidates, noise = watch.aggregate([_event(wrapped)], datetime.now(timezone.utc), threshold=1)
        assert candidates == []
        assert len(noise) == 1
        started = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
        assert watch.post_fix_verdict([_event(wrapped)], signature, started, 24)["count"] == 0


def test_hub_scan_keeps_legacy_fix_state_and_only_reports_real_recurrence(tmp_path, monkeypatch, capsys, scan_reports):
    transport = "Hub worker turn failed: ReadError('connection reset')"
    signature = watch.normalize_signature(transport)
    fixes = {
        key: {
            "task": "V-1040", "commit": "example", "started_at": datetime.now(timezone.utc).isoformat(),
            "window_hours": 168,
        }
        for key in ["(no output)", signature] + [watch.normalize_signature(m) for m in _expected_hub_failures()]
    }
    state_path = tmp_path / "error_watch.json"
    watch._write_state(state_path, {"alerts": {"(no output)": {"count": 12}}, "fixes": fixes})
    current = {"events": []}
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: current["events"])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    args = SimpleNamespace(db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=3, dry_run=False)
    stamp = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    current["events"] = [dict(_event(m, source="logs"), ts=stamp) for m in _expected_hub_failures()]
    watch.scan(args)
    capsys.readouterr()
    assert not scan_reports.called
    state = watch._load_state(state_path)
    assert state["alerts"] == {}
    assert all(not fix.get("recurrence_reported") for fix in state["fixes"].values())

    current["events"].append(dict(_event(transport, source="logs"), ts=stamp))
    watch.scan(args)
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert signals == []
    assert [(item["signature"], item["count"]) for item in verdicts] == [(signature, 1)]
    state = watch._load_state(state_path)
    assert set(state["fixes"]) == set(fixes)
    assert {key for key, fix in state["fixes"].items() if fix.get("recurrence_reported")} == {signature}
    watch.scan(args)
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state


@pytest.fixture
def hub_finish_db(tmp_path):
    path = tmp_path / "orchestra.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT);"
            "CREATE TABLE logs (ts TEXT, type TEXT, content TEXT, tool_name TEXT, "
            "tool_is_error INTEGER, session_id TEXT);"
        )
    return path


@pytest.fixture
def hub_finish_row():
    from app.hub_activity import HubActivityStream

    stream = HubActivityStream("run")
    stream.feed([{
        "itemId": "command", "runId": "run", "position": 1,
        "type": "command_execution", "status": "running", "text": "$ false",
    }])
    result, = stream.finish("")
    return (result.type, result.content, result.metadata["tool_name"], int(result.metadata["is_error"]))


def _insert_error_rows(path, rows, stamp):
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO logs (ts, type, content, tool_name, tool_is_error) VALUES (?, ?, ?, ?, ?)",
            [(stamp.isoformat(), *row) for row in rows],
        )


@pytest.mark.parametrize("message", ["Terminated", "Terminated ", "Terminated\n", " \tTerminated\r\n"])
def test_bash_terminated_result_is_noise(message):
    event = dict(_event(message, source="logs"), type="tool_result", tool_name="Bash")
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=1)
    assert candidates == []
    assert [(item["signature"], item["count"], item["noise"]) for item in noise] == [
        ("Terminated", 1, "bash child process termination"),
    ]


@pytest.mark.parametrize("overrides", [
    {"tool_name": "Read"},
    {"tool_name": "hub"},
    {"tool_name": "bash"},
    {"tool_name": None},
    {"type": "error"},
    {"type": "tool_use"},
    {"type": None},
    {"source": "journalctl"},
    {"source": None},
    {"message": "Traceback (most recent call last):\nRuntimeError: Terminated"},
    {"message": "Terminated\nTraceback (most recent call last):\nRuntimeError: failed"},
    {"message": "Terminated unexpectedly"},
    {"message": "terminated"},
])
def test_other_terminated_events_stay_actionable(overrides):
    event = dict(_event("Terminated", source="logs"), type="tool_result", tool_name="Bash")
    event.update(overrides)
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=1)
    assert [(item["signature"], item["count"]) for item in candidates] == [
        (watch.normalize_signature(event["message"]), 1),
    ]
    assert noise == []


def test_bash_terminated_scan_reports_noise_separately_from_other_tool(
    hub_finish_db, monkeypatch, capsys,
):
    now = datetime.now(timezone.utc)
    _insert_error_rows(hub_finish_db, [("tool_result", "Terminated\n", "Bash", 1)] * 10, now)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    args = SimpleNamespace(db=str(hub_finish_db), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_by_class"] == {"bash child process termination": 10}
    assert output["noise_events"] == 10

    _insert_error_rows(hub_finish_db, [("tool_result", "Terminated", "Read", 1)] * 10, now)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert [(item["signature"], item["count"]) for item in output["signals"]] == [("Terminated", 10)]
    assert output["noise_by_class"] == {"bash child process termination": 10}


def test_hub_finish_db_provenance_separates_identical_command_errors_at_threshold(hub_finish_db, hub_finish_row):
    now = datetime.now(timezone.utc)
    assert hub_finish_row == ("tool_result", "(not finished)", "hub", 1)
    command_error = ("tool_result", "(not finished)", "Bash", 1)
    _insert_error_rows(hub_finish_db, [hub_finish_row] * 10 + [command_error] * 9 + [
        ("end_turn", "", None, 0), ("tool_result", "(not finished)", "Bash", 0),
    ], now)
    events = watch.collect_db_events(hub_finish_db, now - timedelta(minutes=1))
    assert len(events) == 19
    assert {(e["type"], e["tool_name"]) for e in events} == {("tool_result", "hub"), ("tool_result", "Bash")}
    candidates, noise = watch.aggregate(events, now)
    assert candidates == []
    assert [(item["signature"], item["count"], item["noise"]) for item in noise] == [
        ("(not finished)", 10, "hub unfinished tool closure"),
    ]

    _insert_error_rows(hub_finish_db, [command_error], now)
    events = watch.collect_db_events(hub_finish_db, now - timedelta(minutes=1))
    candidates, noise = watch.aggregate(events, now)
    assert [(item["signature"], item["count"], item["noise"]) for item in candidates] == [
        ("(not finished)", 10, None),
    ]
    assert [item["count"] for item in noise] == [10]
    assert watch.post_fix_verdict(events, "(not finished)", now, 168)["count"] == 10


@pytest.mark.parametrize("row", [
    ("error", "(not finished)", "hub", 1),
    ("error", "(not finished)", None, 0),
    ("tool_result", "(not finished)", "Bash", 1),
    ("tool_result", "(not finished)", None, 1),
    ("tool_result", "(not finished)", "Hub", 1),
    ("tool_use", "(not finished)", "hub", 1),
    ("tool_result", " (not finished)", "hub", 1),
    ("tool_result", "(not finished)\n", "hub", 1),
    ("tool_result", "(not  finished)", "hub", 1),
    ("tool_result", "command failed: (not finished)", "hub", 1),
    ("error", "Hub worker turn failed: (not finished)", "hub", 1),
    ("error", "Hub worker turn failed: hub thread ended with status failed", "hub", 1),
    ("tool_result", "fatal: command failed", "Bash", 1),
])
def test_only_exact_synthetic_hub_finish_row_is_noise(hub_finish_db, hub_finish_row, row):
    now = datetime.now(timezone.utc)
    _insert_error_rows(hub_finish_db, [hub_finish_row] * 10 + [row] * 10, now)
    events = watch.collect_db_events(hub_finish_db, now - timedelta(minutes=1))
    signature = watch.normalize_signature(row[1])
    candidates, noise = watch.aggregate(events, now)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 10)]
    assert [(item["noise"], item["count"]) for item in noise] == [("hub unfinished tool closure", 10)]
    assert watch.post_fix_verdict(events, signature, now, 168)["count"] == 10


@pytest.mark.parametrize("provenance", [
    {}, {"type": "tool_result"}, {"tool_name": "hub"},
    {"source": "journalctl", "type": "tool_result", "tool_name": "hub"},
])
def test_marker_without_db_hub_provenance_remains_actionable(provenance):
    event = dict(_event("(not finished)", source="logs"), **provenance)
    assert watch.classify_noise("(not finished)") is None
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=1)
    assert [(item["signature"], item["count"]) for item in candidates] == [("(not finished)", 1)]
    assert noise == []
    assert watch.post_fix_verdict([event], "(not finished)", datetime.fromisoformat(event["ts"]), 168)["count"] == 1


def test_hub_finish_scan_reports_noise_and_preserves_real_post_fix_recurrence(
    hub_finish_db, hub_finish_row, monkeypatch, capsys, scan_reports,
):
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    stamp = started + timedelta(seconds=1)
    _insert_error_rows(hub_finish_db, [hub_finish_row] * 10, stamp)
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    monkeypatch.setattr(watch, "_existing_refs", lambda _: {"tasks": []})
    args = SimpleNamespace(db=str(hub_finish_db), window_hours=168, threshold=10, dry_run=True)
    assert watch.scan(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_count"] == 1
    assert output["noise_events"] == 10
    assert output["noise_by_class"] == {"hub unfinished tool closure": 10}
    assert output["events_by_source"] == {"logs": 10, "journalctl": 0}

    signature = "(not finished)"
    state_path = hub_finish_db.parent / "error_watch.json"
    fix = {"task": "V-1094", "commit": "example", "started_at": started.isoformat(), "window_hours": 168}
    watch._write_state(state_path, {"alerts": {}, "fixes": {signature: fix}})
    args.dry_run = False
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert not scan_reports.called
    state = watch._load_state(state_path)
    assert state["fixes"] == {signature: fix}
    assert state["alerts"] == {}

    _insert_error_rows(hub_finish_db, [("tool_result", signature, "Bash", 1)], stamp)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert signals == []
    assert [(item["signature"], item["count"], item["complete"]) for item in verdicts] == [(signature, 1, False)]
    state = watch._load_state(state_path)
    assert state["fixes"][signature]["recurrence_reported"] is True
    assert watch.scan(args) == 0
    capsys.readouterr()
    assert scan_reports.call_count == 1
    assert watch._load_state(state_path) == state

    _insert_error_rows(hub_finish_db, [("tool_result", signature, "Bash", 1)] * 9, stamp)
    assert watch.scan(args) == 0
    capsys.readouterr()
    signals, verdicts = scan_reports.call_args.args
    assert [(item["signature"], item["count"]) for item in signals] == [(signature, 10)]
    assert verdicts == []
    assert scan_reports.call_count == 2
    assert watch._load_state(state_path)["alerts"][signature]["count"] == 10


def test_hub_finish_post_fix_observation_completes_without_false_recurrence():
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    event = dict(_event("(not finished)", source="logs"), type="tool_result", tool_name="hub", ts=started.isoformat())
    result = watch.post_fix_verdict([event], "(not finished)", started, 1)
    assert result["count"] == 0
    assert result["complete"] is True


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired(["journalctl"], 45),
    OSError(28, "No space left on device"),
])
def test_ops_scan_failure_wakes_the_orchestrator_instead_of_staying_silent(
    failure, tmp_path, monkeypatch, capsys,
):
    def broken(*_args):
        raise failure

    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", broken)
    assert watch.main(["scan", "--db", str(tmp_path / "synthetic.db")]) == 1
    captured = capsys.readouterr()
    # bg_jobs matches the pattern against stdout + stderr and sends the last 3000 chars:
    # the wake line must be the very last line, after the traceback.
    assert captured.err.rstrip().splitlines()[-1].startswith(
        f"ERROR-WATCH: scan failed, recurring errors were not checked: {type(failure).__name__}"
    )
    assert "Traceback" in captured.err


def test_ops_successful_scan_and_record_fix_are_unchanged(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: [])
    assert watch.main(["scan", "--db", str(tmp_path / "synthetic.db")]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "No new error-watch findings"
    assert "ERROR-WATCH" not in captured.out + captured.err

    def full(*_args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(watch, "_write_state", full)
    with pytest.raises(OSError):
        watch.main([
            "record-fix", "--db", str(tmp_path / "synthetic.db"), "--signature", "x",
            "--task", "V-1", "--commit", "abc", "--started-at", "2026-11-02T00:00:00+00:00",
        ])
