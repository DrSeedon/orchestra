"""Synthetic offline checks; no installed Codex or account data is read."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "codex_reset.py"
spec = importlib.util.spec_from_file_location("codex_reset", SCRIPT)
resetter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resetter)

NOW = 2_000_000_000


def credit(name="synthetic-bonus-one", *, expires_in=3600, status="available"):
    return {"id": name, "expiresAt": NOW + expires_in, "status": status}


def snapshot(*, slot="primary", used=95, credits=None):
    weekly = {"usedPercent": used, "windowDurationMins": 10080,
              "resetsAt": NOW + 10_000}
    limits = {"primary": weekly, "secondary": None}
    if slot == "secondary":
        limits = {"primary": {"usedPercent": 100, "windowDurationMins": 300,
                              "resetsAt": NOW + 200}, "secondary": weekly}
    return {"rateLimits": limits,
            "rateLimitResetCredits": {"credits": [credit()] if credits is None else credits}}


class FakeRPC:
    def __init__(self, before, *, after=None, outcome="reset", fail_method=None):
        self.before = before
        self.after = snapshot(used=0) if after is None else after
        self.outcome = outcome
        self.fail_method = fail_method
        self.calls = []
        self.reads = 0

    def request(self, method, params):
        self.calls.append((method, params))
        if method == self.fail_method:
            raise resetter.ResetError("synthetic RPC failure")
        if method == "initialize":
            return {}
        if method == "account/rateLimits/read":
            self.reads += 1
            return self.before if self.reads == 1 else self.after
        if method == resetter.CONSUME_METHOD:
            return {"outcome": self.outcome}
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, method, params):
        self.calls.append((method, params))

    @property
    def consumes(self):
        return [params for method, params in self.calls if method == resetter.CONSUME_METHOD]


def run(rpc):
    output = []
    resetter.reset(rpc, now=lambda: NOW, emit=output.append)
    return output


@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_weekly_window_in_either_slot_and_successful_readback(slot):
    rpc = FakeRPC(snapshot(slot=slot), after=snapshot(slot=slot, used=0))
    output = run(rpc)
    assert rpc.calls[:3] == [
        ("initialize", {"clientInfo": {"name": "orchestra", "title": "Orchestra", "version": "1"}}),
        ("initialized", {}), ("account/rateLimits/read", {}),
    ]
    assert len(rpc.consumes) == 1
    assert rpc.calls[3] == ("account/rateLimitResetCredit/consume", {
        "creditId": "synthetic-bonus-one",
        "idempotencyKey": "orchestra-synthetic-bonus-one",
    })
    assert "REDEEMED" in output
    assert output[-1] == f"week_after 0 {NOW + 10_000}"
    assert rpc.reads == 2


@pytest.mark.parametrize("slot", ["primary", "secondary"])
@pytest.mark.parametrize(("used", "expires_in", "redeem"), [
    (94.999, 540, False), (95, 540, True), (95.001, 3600, True),
    (24, 539.999, True), (24, 540, False), (24, 540.001, False),
    (0, -1, True),
])
def test_exact_policy_boundaries(slot, used, expires_in, redeem):
    rpc = FakeRPC(snapshot(slot=slot, used=used, credits=[credit(expires_in=expires_in)]))
    output = run(rpc)
    assert bool(rpc.consumes) is redeem
    assert ("REDEEMED" in output) is redeem
    assert rpc.reads == (2 if redeem else 1)


def test_earliest_available_bonus_only_and_stable_key_across_runs():
    credits = [credit("synthetic-late", expires_in=5000),
               credit("synthetic-spent", expires_in=1, status="consumed"),
               credit("synthetic-next", expires_in=4000)]
    calls = []
    for _ in range(2):
        rpc = FakeRPC(snapshot(credits=credits))
        run(rpc)
        calls.append(rpc.consumes)
    assert calls == [[{"creditId": "synthetic-next",
                       "idempotencyKey": "orchestra-synthetic-next"}]] * 2


@pytest.mark.parametrize("limits", [None, {}, {"primary": None, "secondary": None},
    {"primary": {"windowDurationMins": 300, "usedPercent": 100}, "secondary": None},
    {"primary": {"windowDurationMins": 20160, "usedPercent": 100}},
    {slot: {"windowDurationMins": 10080, "usedPercent": 100, "resetsAt": NOW}
     for slot in ("primary", "secondary")},
])
def test_no_unambiguous_week_never_consumes_even_when_bonus_expires(limits):
    before = snapshot(credits=[credit(expires_in=1)])
    before["rateLimits"] = limits
    rpc = FakeRPC(before)
    with pytest.raises(resetter.ResetError, match="weekly"):
        run(rpc)
    assert rpc.consumes == []


@pytest.mark.parametrize("credits", [[], [credit(status="consumed")],
                                     [credit(status="expired")]])
def test_no_available_credits_does_not_require_weekly_data(credits):
    rpc = FakeRPC({"rateLimitResetCredits": {"credits": credits}})
    assert run(rpc)[-1] == "no action: no available reset credits"
    assert rpc.consumes == []


@pytest.mark.parametrize(("field", "value"), [
    ("usedPercent", None), ("usedPercent", True), ("usedPercent", float("nan")),
    ("usedPercent", -1), ("resetsAt", None), ("resetsAt", float("inf")),
])
def test_invalid_weekly_values_fail_closed(field, value):
    before = snapshot()
    before["rateLimits"]["primary"][field] = value
    rpc = FakeRPC(before)
    with pytest.raises(resetter.ResetError):
        run(rpc)
    assert rpc.consumes == []


@pytest.mark.parametrize("before", [{}, {"rateLimitResetCredits": None},
    {"rateLimitResetCredits": {"availableCount": 2}},
    snapshot(credits=[credit(), {"status": "available", "id": "synthetic-invalid"}]),
    snapshot(credits=[credit(), {"status": "available", "expiresAt": NOW}]),
])
def test_malformed_credits_never_redeem_an_arbitrary_bonus(before):
    rpc = FakeRPC(before)
    with pytest.raises(resetter.ResetError):
        run(rpc)
    assert rpc.consumes == []


def test_actual_wire_matches_supplied_legacy_contract():
    # Literal strings on purpose: the expectation must not import CONSUME_METHOD.
    responses = [{"id": 1, "result": {}},
                 {"id": 2, "result": snapshot()},
                 {"id": 3, "result": {"outcome": "reset"}},
                 {"id": 4, "result": snapshot(used=0)}]
    rpc, _ = pipe_client(b"".join(json.dumps(m).encode() + b"\n" for m in responses))
    try:
        output = run(rpc)
        sent = [json.loads(line) for line in rpc.process.stdin.getvalue().splitlines()]
    finally:
        rpc.close()
        rpc.process.stdin.close()
    legacy = {"creditId": "synthetic-bonus-one", "idempotencyKey": "orchestra-synthetic-bonus-one"}
    assert sent == [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "orchestra", "title": "Orchestra", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "account/rateLimitResetCredit/consume", "params": legacy},
        {"jsonrpc": "2.0", "id": 4, "method": "account/rateLimits/read", "params": {}},
    ]
    assert "REDEEMED" in output


@pytest.mark.parametrize("outcome", ["already_consumed", "failed", None])
def test_non_reset_outcome_is_failure_and_never_retried(outcome):
    rpc = FakeRPC(snapshot(), outcome=outcome)
    with pytest.raises(resetter.ResetError, match="outcome"):
        run(rpc)
    assert len(rpc.consumes) == 1
    assert rpc.reads == 1


def pipe_client(data=b"", *, keep_open=False):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    if not keep_open:
        os.close(write_fd)
    process = SimpleNamespace(stdin=io.StringIO(), stdout=os.fdopen(read_fd))
    return resetter.AppServer(process, timeout=0.01), write_fd


def test_rpc_matches_ids_skips_notifications_and_preserves_buffered_lines():
    messages = [{"method": "account/updated", "params": {}},
                {"id": 99, "result": {}},
                {"id": 1, "result": {"first": True}},
                {"id": 2, "result": {"second": True}}]
    rpc, _ = pipe_client(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
    try:
        rpc.notify("initialized", {})
        assert rpc.request("synthetic/first", {}) == {"first": True}
        assert rpc.request("synthetic/second", {}) == {"second": True}
        sent = [json.loads(line) for line in rpc.process.stdin.getvalue().splitlines()]
        assert sent == [{"jsonrpc": "2.0", "method": "initialized", "params": {}},
                        {"jsonrpc": "2.0", "id": 1, "method": "synthetic/first", "params": {}},
                        {"jsonrpc": "2.0", "id": 2, "method": "synthetic/second", "params": {}}]
    finally:
        rpc.close()
        rpc.process.stdin.close()
        rpc.process.stdout.close()


@pytest.mark.parametrize(("data", "message"), [
    (b"", "EOF"), (b"garbage\n", "invalid JSON"), (b"[]\n", "invalid RPC response"),
    (b'{"id":1,"result":null}\n', "invalid RPC result"),
    (b'{"id":1,"error":{"message":"synthetic-private-detail"}}\n', "RPC error"),
])
def test_rpc_errors_are_actionable_without_echoing_payload(data, message):
    rpc, _ = pipe_client(data)
    try:
        with pytest.raises(resetter.ResetError, match=message) as exc:
            rpc.request("synthetic/read", {})
        assert "synthetic-private-detail" not in str(exc.value)
    finally:
        rpc.close()
        rpc.process.stdin.close()
        rpc.process.stdout.close()


def test_rpc_timeout_is_bounded():
    rpc, write_fd = pipe_client(keep_open=True)
    try:
        with pytest.raises(resetter.ResetError, match="timed out"):
            rpc.request("synthetic/read", {})
    finally:
        os.close(write_fd)
        rpc.close()
        rpc.process.stdin.close()
        rpc.process.stdout.close()


class FakeProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.actions = []

    def poll(self):
        return None

    def kill(self):
        self.actions.append("kill")

    def wait(self, *, timeout):
        assert timeout == 5
        self.actions.append("wait")


@pytest.mark.parametrize("scenario", ["success", "no_credits", "no_week", "initialize_error",
                                      "consume_error", "non_reset", "readback_error", "client_error"])
def test_main_reports_cron_markers_and_reaps_child(monkeypatch, capsys, scenario):
    process = FakeProcess()
    before = snapshot(credits=[] if scenario == "no_credits" else None)
    if scenario == "no_week":
        before["rateLimits"] = {}
    fail_method = {"initialize_error": "initialize",
                   "consume_error": resetter.CONSUME_METHOD}.get(scenario)
    rpc = FakeRPC(before, fail_method=fail_method,
                  outcome="failed" if scenario == "non_reset" else "reset",
                  after={} if scenario == "readback_error" else None)

    def popen(argv, **kwargs):
        assert argv == ["codex", "app-server"]
        assert kwargs == {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                          "stderr": subprocess.DEVNULL, "text": True, "cwd": "/tmp"}
        return process

    closed = []

    def app_server(child):
        assert child is process
        if scenario == "client_error":
            raise OSError("synthetic initialization failure")
        rpc.close = lambda: closed.append(True)
        return rpc

    monkeypatch.setattr(resetter.subprocess, "Popen", popen)
    monkeypatch.setattr(resetter, "AppServer", app_server)
    result = resetter.main()
    output = capsys.readouterr().out
    failed = scenario not in ("success", "no_credits")
    assert result == int(failed)
    assert ("REDEEM_FAILED" in output) is failed
    assert ("REDEEMED" in output) is (scenario in ("success", "readback_error"))
    assert process.actions == ["kill", "wait"]
    assert process.stdin.closed and process.stdout.closed
    assert closed == ([] if scenario == "client_error" else [True])
    assert len(rpc.consumes) == int(scenario in (
        "success", "consume_error", "non_reset", "readback_error",
    ))


def test_missing_codex_is_visible_to_cron(monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError("synthetic missing binary")

    monkeypatch.setattr(resetter.subprocess, "Popen", missing)
    assert resetter.main() == 1
    assert "REDEEM_FAILED FileNotFoundError" in capsys.readouterr().out


def test_cleanup_reaps_already_exited_child_and_closes_pipes():
    process = FakeProcess()
    process.poll = lambda: 0
    resetter.cleanup(process)
    assert process.actions == ["wait"]
    assert process.stdin.closed and process.stdout.closed


def test_cleanup_closes_pipes_even_if_wait_fails():
    process = FakeProcess()

    def fail_wait(**kwargs):
        raise subprocess.TimeoutExpired("synthetic", 5)

    process.wait = fail_wait
    with pytest.raises(subprocess.TimeoutExpired):
        resetter.cleanup(process)
    assert process.stdin.closed and process.stdout.closed


def test_cleanup_handles_exit_racing_with_kill():
    process = FakeProcess()

    def exited():
        process.actions.append("kill")
        raise ProcessLookupError

    process.kill = exited
    resetter.cleanup(process)
    assert process.actions == ["kill", "wait"]
    assert process.stdin.closed and process.stdout.closed


def test_main_still_reaps_child_when_rpc_cleanup_fails(monkeypatch, capsys):
    process = FakeProcess()
    rpc = FakeRPC(snapshot(credits=[]))

    def fail_close():
        raise OSError("synthetic selector close failure")

    rpc.close = fail_close
    monkeypatch.setattr(resetter.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(resetter, "AppServer", lambda child: rpc)
    assert resetter.main() == 1
    assert "REDEEM_FAILED RPC cleanup: OSError" in capsys.readouterr().out
    assert process.actions == ["kill", "wait"]
    assert process.stdin.closed and process.stdout.closed


def test_main_cleanup_failure_is_visible_to_cron(monkeypatch, capsys):
    process = FakeProcess()
    rpc = FakeRPC(snapshot(credits=[]))
    rpc.close = lambda: None

    def fail_wait(**kwargs):
        raise subprocess.TimeoutExpired("synthetic", 5)

    process.wait = fail_wait
    monkeypatch.setattr(resetter.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(resetter, "AppServer", lambda child: rpc)
    assert resetter.main() == 1
    assert "REDEEM_FAILED cleanup: TimeoutExpired" in capsys.readouterr().out
    assert process.stdin.closed and process.stdout.closed
