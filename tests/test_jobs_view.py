"""Расчёт «когда сработает» и «забытое» в панели JOBS: ошибка здесь показывает владельцу чужое время."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent.parent / "app/static/js/jobs-timeline.js"


def _run(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    code = f"global.window = {{}}; require({json.dumps(str(JS))}); const V = window.JobsView; {script}"
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_cron_next_is_utc_and_strictly_after():
    r = _run("""console.log(JSON.stringify([
        V.cronNext('*/3 * * * *', new Date('2026-10-02T07:03:00Z')).toISOString(),
        V.cronNext('0 4 24 10 *', new Date('2026-10-02T00:00:00Z')).toISOString(),
        V.cronNext('30 9 * * 1', new Date('2026-10-02T00:00:00Z')).toISOString(),
        V.cronNext('bad', new Date())]))""")
    assert r == ["2026-10-02T07:06:00.000Z", "2026-10-24T04:00:00.000Z", "2026-10-05T09:30:00.000Z", None]


def test_forgotten_flag_only_for_long_lived_not_for_pending_timers():
    r = _run("""const now = new Date('2026-10-20T00:00:00Z');
        const mk = (type, days, extra) => V.describe(Object.assign({type, status:'active', config:'{}',
            created_at: new Date(now - days*864e5).toISOString(), target_name:'a', created_by_name:'a'}, extra), now).stale;
        console.log(JSON.stringify([
            mk('idle', 1), mk('idle', 3), mk('idle', 17),
            mk('timer', 20, {trigger_at: '2026-10-25T00:00:00Z'}),
            mk('timer', 1, {trigger_at: '2026-10-19T00:00:00Z'})]))""")
    assert r == [0, 1, 2, 0, 2]
