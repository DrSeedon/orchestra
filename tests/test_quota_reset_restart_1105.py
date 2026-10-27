"""Порог квоты на графике должен начинаться заново после любого сброса окна, в том числе
досрочного, когда сетка истории (30 мин) пропускает снимок с 0%."""
from pathlib import Path
import json
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "app/static/js/quota-lines.js").read_text(encoding="utf-8")

NODE = r"""
const src = process.argv[1];
const grab = re => new RegExp(re).exec(src)[0];
eval(grab(String.raw`const _QL_RESET_HISTORY_HOURS[^\n]*`).replace('const ', 'var ')
  + ';' + grab(String.raw`const _QL_RESET_JUMP_MS[^\n]*`).replace('const ', 'var ')
  + ';' + grab(String.raw`function _qlObservedWindowResets[\s\S]*?\n}\n`));
const win = (u, r) => ({id: 'w', window_minutes: 10080, utilization: u, resets_at: r});
const row = (ts, u, r) => ({ts, providers: {codex: {windows: [win(u, r)]}}});
const rows = JSON.parse(process.argv[2]).map(([ts, u, r]) => row(ts, u, r));
const out = _qlObservedWindowResets({rows, step_minutes: 30}, 'codex', win(0, ''));
console.log(JSON.stringify(out.map(e => e.at)));
"""


def run(rows):
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    res = subprocess.run([node, "-e", NODE, SRC, json.dumps(rows)], capture_output=True,
                         text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def ms(ts):
    from datetime import datetime
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def test_early_reset_without_zero_sample_starts_new_cycle():
    # Real 2026-10-26 sequence: 30-min grid sees 58% then 4%, never 0%.
    rows = [
        ["2026-10-26T05:30:00Z", 57, "2026-11-01T06:26:27Z"],
        ["2026-10-26T06:00:00Z", 58, "2026-11-01T06:26:27Z"],
        ["2026-10-26T06:30:00Z", 4, "2026-11-02T06:10:32Z"],
        ["2026-10-26T07:00:00Z", 11, "2026-11-02T06:10:33Z"],
    ]
    assert run(rows) == [ms("2026-10-26T06:30:00Z")]


def test_zero_sample_reset_and_resets_at_jitter():
    rows = [
        ["2026-10-25T06:00:00Z", 93, "2026-10-30T17:42:59Z"],
        ["2026-10-25T06:30:00Z", 0, "2026-11-01T06:26:27Z"],
        ["2026-10-25T07:00:00Z", 2, "2026-11-01T06:26:28Z"],
        ["2026-10-25T07:30:00Z", 3, "2026-11-01T06:26:27Z"],
    ]
    assert run(rows) == [ms("2026-10-25T06:30:00Z")]


def test_scheduled_rollover_still_detected_and_steady_state_is_not():
    rows = [
        ["2026-10-30T17:00:00Z", 80, "2026-10-30T17:43:00Z"],
        ["2026-10-30T17:30:00Z", 80, "2026-10-30T17:42:59Z"],
        ["2026-10-30T18:00:00Z", 0, "2026-11-06T17:43:00Z"],
        ["2026-10-30T18:30:00Z", 1, "2026-11-06T17:43:01Z"],
    ]
    assert run(rows) == [ms("2026-10-30T18:00:00Z")]
