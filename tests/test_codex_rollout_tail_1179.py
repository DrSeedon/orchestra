"""V-1179: rollout usage is read from the end of the file, not by parsing all of it.

The first turn after (re)connect and every turn end without a `tokenUsage` notification
read the thread rollout synchronously on the shared event loop; a long thread's rollout
holds tens of MB of tool output. The reader must return the same latest token_count as a
forward scan while touching only the tail.
"""

import json
import random

import pytest

import app.backend_codex as backend_codex
from app.backend_codex import CodexBackend, _read_rollout_context, _read_rollout_totals


@pytest.fixture(autouse=True)
def isolate_managed_codex_home(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backend_codex._CODEX_HOME_ROOT", tmp_path / "managed-codex")


def _forward_latest(path, extract):
    """Reference: the pre-V-1179 forward scan, keeping the last row that qualifies."""
    latest = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            info = backend_codex._token_count_info(row) if isinstance(row, dict) else None
            found = extract(info) if info is not None else None
            if found is not None:
                latest = found
    return latest


def _token_count(i, *, window=258400, last=True, total=True):
    info = {}
    if total:
        info["total_token_usage"] = {
            "input_tokens": 1000 * i, "cached_input_tokens": 500 * i,
            "cache_write_input_tokens": i, "output_tokens": 10 * i, "reasoning_tokens": i,
        }
    if last:
        info["last_token_usage"] = {"input_tokens": 100 + i, "cached_input_tokens": 50}
    if window is not None:
        info["model_context_window"] = window
    return {"type": "event_msg", "payload": {"type": "token_count", "info": info}}


def _random_rollout(rnd, path):
    lines = []
    for i in range(rnd.randint(0, 40)):
        kind = rnd.random()
        if kind < 0.35:
            lines.append(json.dumps({"type": "response_item", "payload": {
                "type": "function_call_output", "output": "ж" * rnd.randint(0, 3000)}},
                ensure_ascii=rnd.random() < 0.5))
        elif kind < 0.75:
            lines.append(json.dumps(_token_count(
                i, window=rnd.choice([258400, None, 0]),
                last=rnd.random() < 0.8, total=rnd.random() < 0.8)))
        elif kind < 0.85:
            lines.append('{"type": "event_msg", "payload": {"type": "token_co')  # torn write
        else:
            lines.append("")
    text = "\n".join(lines)
    if rnd.random() < 0.5:
        text += "\n"
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("chunk", [7, 64, 4096, 64 * 1024])
def test_tail_reader_matches_forward_scan(tmp_path, monkeypatch, chunk):
    # Small chunks force lines (including multibyte UTF-8) across read boundaries.
    monkeypatch.setattr(backend_codex, "_ROLLOUT_TAIL_CHUNK", chunk)
    rnd = random.Random(1179 + chunk)
    path = tmp_path / "rollout.jsonl"
    for _ in range(60):
        _random_rollout(rnd, path)
        assert _read_rollout_context(path) == _forward_latest(
            path, backend_codex._rollout_context_from)
        assert _read_rollout_totals(path) == _forward_latest(
            path, backend_codex._rollout_totals_from)


def test_tail_reader_parses_only_rows_after_latest_match(tmp_path, monkeypatch):
    path = tmp_path / "rollout.jsonl"
    rows = []
    for i in range(1, 500):
        rows.append({"type": "response_item", "payload": {"output": "x" * 2000}})
        rows.append(_token_count(i))
    rows.append({"type": "response_item", "payload": {"output": "tail"}})
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    parsed = []
    real_row = backend_codex._rollout_row
    monkeypatch.setattr(
        backend_codex, "_rollout_row", lambda line: parsed.append(line) or real_row(line))

    assert _read_rollout_totals(path)["input_tokens"] == 499_000
    assert _read_rollout_context(path)["input_tokens"] == 599
    # Trailing newline piece, the non-matching tail row, then the match — per read.
    assert len(parsed) == 6


def test_tail_reader_skips_non_object_rows_and_bad_totals(tmp_path):
    path = tmp_path / "rollout.jsonl"
    bad_totals = _token_count(9)
    bad_totals["payload"]["info"]["total_token_usage"]["output_tokens"] = "many"
    path.write_text("\n".join([
        json.dumps(_token_count(3)),
        json.dumps(bad_totals),
        '["token_count", {"type": "event_msg"}]',
        '"token_count"',
        json.dumps({"type": "event_msg", "payload": "token_count"}),
        json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": []}}),
        '{"type": "event_msg", "payload": {"type": "tok',
    ]))

    assert _read_rollout_context(path)["input_tokens"] == 109
    # One malformed row is skipped instead of discarding the whole rollout's totals.
    assert _read_rollout_totals(path)["input_tokens"] == 3000


def test_tail_reader_fails_soft_on_empty_and_missing_files(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert _read_rollout_context(empty) is None
    assert _read_rollout_totals(empty) is None
    assert _read_rollout_totals(tmp_path / "missing.jsonl") is None
    assert _read_rollout_context(tmp_path) is None  # a directory is an OSError, not a crash


def test_runtime_totals_does_not_parse_rollout_for_context(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-5.6-sol", cwd=str(tmp_path))
    backend._thread_id = "thread-1179"
    backend._codex_home = str(tmp_path / "home")
    rollout = tmp_path / "home" / "sessions" / "2026" / "11" / "01" / "rollout-thread-1179.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(json.dumps(_token_count(4)) + "\n")
    calls = []
    monkeypatch.setattr(
        backend_codex, "_read_rollout_context",
        lambda path: calls.append(path) or None)

    assert backend._runtime_totals()["input_tokens"] == 4000
    assert backend._rollout_path == rollout
    assert calls == []


def test_rows_without_token_count_are_not_json_parsed(tmp_path, monkeypatch):
    # Worst case: no usable token_count at all, so the scan reaches the file start.
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(
        json.dumps({"type": "response_item", "payload": {"output": "x" * 100}})
        for _ in range(200)) + "\n" + json.dumps(_token_count(1, window=None, total=False)))
    real_loads = json.loads
    parsed = []
    monkeypatch.setattr(
        backend_codex.json, "loads", lambda text: parsed.append(text) or real_loads(text))

    assert _read_rollout_context(path) is None
    assert len(parsed) == 1
