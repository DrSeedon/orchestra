"""V-1135: the JOBS card shows only observed progress, honestly and escaped (node, synthetic data)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent.parent / "app/static/js/jobs-timeline.js"
NOW = "2026-10-29T12:00:00Z"


def _run(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    code = (
        "global.window = {}; global.orchLocale = () => 'ru-RU'; global.document = {};"
        "global.escHtml = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');"
        f"require({json.dumps(str(JS))}); const V = window.JobsView; const now = new Date('{NOW}');"
        "const iso = sec => new Date(now - sec*1000).toISOString();"
        "const job = (rec, extra) => Object.assign({id:'bg-1', type:'run', status:'active', target_name:'a', created_by_name:'a',"
        " message:'m', created_at: iso(600), config: JSON.stringify({command:'x', progress:{mode:'command'}, _progress: rec})}, extra||{});"
        "const info = (rec, extra) => V.describe(job(rec, extra), now).progress;"
        + script
    )
    out = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_running_job_shows_percent_rate_and_approximate_eta():
    r = _run("""const p = info({interval:5, updated_at: iso(2), moved_at: iso(2),
        sample:{status:'running', completed:30, total:120, unit:'MB', percent:25, rate:2.5, eta_seconds:36, eta_source:'estimated', label:'Загрузка'}});
        console.log(JSON.stringify([p.percent, p.rateText, p.etaText, p.stale, p.stalled, p.countText]))""")
    assert r[0] == 25 and r[1].startswith("2,5") and r[1].endswith("MB/с") and r[2] == "меньше минуты"
    assert r[3] is False and r[4] is False and "30 из 120" in r[5]


def test_stale_sampler_hides_rate_and_eta_and_says_so():
    r = _run("""const p = info({interval:5, updated_at: iso(300), moved_at: iso(300),
        sample:{status:'running', completed:1, total:2, unit:'GB', percent:50, rate:1, eta_seconds:60}});
        console.log(JSON.stringify([p.stale, p.etaText, p.rateText, p.staleText]))""")
    assert r[0] is True and r[1] == "" and r[2] == "" and "устарели" in r[3]


def test_no_movement_reset_pause_and_error_are_reported_not_hidden():
    r = _run("""const base = {interval:5, updated_at: iso(1)};
        const stalled = info(Object.assign({moved_at: iso(400), sample:{status:'running', completed:5, total:10, unit:'GB', eta_seconds:99}}, base));
        const reset = info(Object.assign({moved_at: iso(1), sample:{status:'running', completed:1, total:10, reset:true, eta_seconds:99}}, base));
        const paused = info(Object.assign({moved_at: iso(1), sample:{status:'paused', completed:5, total:10, eta_seconds:99}}, base));
        const err = info(Object.assign({moved_at: iso(1), error:'sampler timed out', sample:{status:'running', completed:5, total:10}}, base));
        console.log(JSON.stringify([stalled.stalledText, stalled.etaText, reset.resetText, reset.etaText,
          paused.statusText, paused.etaText, err.errorText]))""")
    assert "без движения" in r[0] and r[1] == ""
    assert "сброшен" in r[2] and r[3] == ""
    assert r[4] == "на паузе" and r[5] == ""
    assert "timed out" in r[6]


def test_unknown_total_gives_no_percent_and_bad_numbers_never_leak():
    r = _run("""const p = info({interval:5, updated_at: iso(1), moved_at: iso(1),
        sample:{status:'running', completed:7, unit:'files', percent:null, rate:-5, eta_seconds:'soon'}});
        const q = info({interval:5, updated_at: iso(1), moved_at: iso(1),
        sample:{status:'running', completed:1, total:2, percent:250, rate:null, eta_seconds:null}});
        const n = info({interval:5, updated_at: iso(1), sample:{status:'wat', completed:NaN, percent:null}});
        console.log(JSON.stringify([p.percent, p.rateText, p.etaText, p.countText, q.percent, n.statusText]))""")
    assert r[0] is None and r[1] == "" and r[2] == "" and r[3] == "7 files"
    assert r[4] == 100 and r[5] == "статус неизвестен"


def test_jobs_without_progress_are_unchanged_and_first_sample_is_pending():
    r = _run("""const plain = V.describe({type:'run', status:'active', config:'{"command":"x"}', created_at: iso(5)}, now).progress;
        const timer = V.describe({type:'timer', status:'active', config:'{}', created_at: iso(5)}, now).progress;
        const waiting = V.describe({type:'run', status:'active', config:'{"command":"x","progress":{"mode":"output"}}', created_at: iso(5)}, now).progress;
        console.log(JSON.stringify([plain, timer, waiting.waiting]))""")
    assert r == [None, None, True]


def test_card_html_escapes_everything_from_the_source():
    r = _run("""const rec = {interval:5, updated_at: iso(1), moved_at: iso(1), raw:'<img src=x onerror=alert(1)>',
        error:'<b>boom</b>', sample:{status:'running', completed:1, total:4, percent:25, unit:'<u>', label:'<script>alert(1)</script>'}};
        const panel = {innerHTML:'', scrollTop:0, addEventListener(){}};
        window.renderJobsPanel(panel, [job(rec)]);
        console.log(JSON.stringify(panel.innerHTML))""")
    assert "<script>" not in r and "<img" not in r and "<b>boom" not in r and "<u>" not in r
    assert "&lt;script&gt;" in r and 'role="progressbar"' in r and 'aria-valuenow="25"' in r


def test_finished_job_keeps_last_observation_without_live_claims():
    r = _run("""const p = info({interval:5, updated_at: iso(900), moved_at: iso(900),
        sample:{status:'running', completed:9, total:10, percent:90, rate:1, eta_seconds:10}}, {status:'triggered'});
        console.log(JSON.stringify([p.live, p.stale, p.etaText, p.rateText, p.percent]))""")
    assert r == [False, False, "", "", 90]


def test_sampler_errors_do_not_refresh_the_last_good_observation_or_show_eta():
    r = _run("""const p = info({interval:5, updated_at:iso(1), last_ok_at:iso(300),
        moved_at:iso(300), error:'sampler failed',
        sample:{observed_at:iso(300), status:'running', completed:5, total:10, percent:50,
          rate:1, eta_seconds:60}});
        const q = info({interval:5, updated_at:iso(1), last_ok_at:iso(2), moved_at:iso(2),
        error:'sampler failed', sample:{observed_at:iso(2), status:'running', completed:5,
          total:10, rate:1, eta_seconds:60}});
        console.log(JSON.stringify([p.stale, p.ageText, p.etaText, p.rateText, q.etaText, q.rateText]))""")
    assert r[0] is True and '5 мин назад' in r[1]
    assert r[2:] == ['', '', '', '']


def test_sampler_error_before_first_measurement_is_visible():
    r = _run("""const panel = {innerHTML:'', scrollTop:0, addEventListener(){}};
        window.renderJobsPanel(panel, [job({interval:5, updated_at:iso(1), error:'sampler timed out'})]);
        console.log(JSON.stringify(panel.innerHTML))""")
    assert 'sampler timed out' in r and 'не удалось прочитать прогресс' in r
