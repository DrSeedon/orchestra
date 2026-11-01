"""V-1135: real DOM progress transitions with synthetic local observations only."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app import bg_progress as bp

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser_type_launch_args(browser_type_launch_args, pytestconfig):
    executable = pytestconfig.getoption("--jobs-browser-executable", default=None)
    return {**browser_type_launch_args, **({"executable_path": executable} if executable else {})}


@pytest.mark.parametrize("width", [390, 1280])
def test_jobs_progress_card_transitions_in_browser(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.route("**/*", lambda route: route.abort())
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    now = datetime.now(timezone.utc).timestamp()
    iso = lambda stamp: datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    job = {
        "id": "bg-browser", "type": "run", "status": "active", "target_name": "worker",
        "created_by_name": "worker", "message": "Обработка файлов", "created_at": iso(now - 100),
    }

    def render(record=None, status="active"):
        payload = {**job, "status": status, "config": {
            "command": "synthetic-command", "progress": {"mode": "output"},
            **({"_progress": record} if record is not None else {}),
        }}
        payload['config'] = json.dumps(payload['config'])
        page.evaluate("job => window.renderJobsPanel(document.querySelector('#jobs'), [job])", payload)

    try:
        # A routed, offline origin gives the real view switch its localStorage.
        page.route('http://jobs.test/', lambda route: route.fulfill(
            content_type='text/html', body='<main id="jobs"></main>',
        ))
        page.goto('http://jobs.test/')
        page.add_style_tag(path=str(ROOT / "app/static/css/style.css"))
        page.add_script_tag(content="""
            window.orchLocale = () => 'ru-RU';
            window.escHtml = value => {
                const element = document.createElement('span');
                element.textContent = String(value);
                return element.innerHTML.replace(/"/g, '&quot;');
            };
        """)
        page.add_script_tag(path=str(ROOT / "app/static/js/jobs-timeline.js"))
        render()
        assert "ждём первое измерение" in page.locator('.job-prog').inner_text()
        assert page.get_by_role('progressbar').count() == 0

        render(bp.mark_error(None, 'sampler timed out', 'output', 5, now=now))
        assert 'не удалось прочитать прогресс' in page.locator('.job-prog').inner_text()
        assert 'sampler timed out' in page.locator('.job-prog').inner_text()

        record = None
        for index in range(3):
            record = bp.ingest(record, {"completed": index * 10, "total": 100, "unit": "MB"},
                               'synthetic', 'output', 5, now=now - 10 + index * 5)
        render(record)
        assert page.get_by_role('progressbar').get_attribute('aria-valuenow') == '20'
        assert 'MB/с' in page.locator('.job-prog').inner_text()
        assert 'осталось' in page.locator('.job-prog').inner_text()

        # Re-rendering a persisted old observation after a recent error must show
        # its true age, and no current speed/ETA.
        old = deepcopy(record)
        old['sample']['observed_at'] = old['last_ok_at'] = iso(now - 300)
        render(bp.mark_error(old, 'sampler failed', 'output', 5, now=now))
        text = page.locator('.job-prog').inner_text()
        assert 'данные устарели' in text and '5 мин назад' in text
        assert 'осталось' not in text and 'MB/с' not in text
        assert page.get_by_role('progressbar').get_attribute('aria-valuenow') == '20'

        paused = bp.ingest(record, {"status": "paused", "completed": 20, "total": 100,
                                   "unit": "MB", "eta_seconds": 10}, '', 'output', 5, now=now + 1)
        render(paused)
        assert 'на паузе' in page.locator('.job-prog').inner_text()
        assert 'осталось' not in page.locator('.job-prog').inner_text()

        reset = bp.ingest(paused, {"completed": 1, "total": 100, "unit": "MB"}, '', 'output', 5, now=now + 2)
        render(reset)
        assert 'счётчик сброшен' in page.locator('.job-prog').inner_text()
        assert 'осталось' not in page.locator('.job-prog').inner_text()

        unknown = bp.ingest(None, {"completed": 7, "unit": "files"}, '', 'output', 5, now=now)
        render(unknown)
        assert page.get_by_role('progressbar').count() == 0
        assert '7 files' in page.locator('.job-prog').inner_text()

        injected = bp.ingest(None, {"completed": 1, "total": 4,
                                   "label": '<img src=x onerror="window.injected=1">'},
                             '<script>window.injected=1</script>', 'output', 5, now=now)
        render(injected)
        assert '<img' in page.locator('.job-prog-head').inner_text()
        assert page.locator('.job-prog img').count() == 0
        page.locator('[data-job-toggle]').first.click()
        assert '<script>' in page.locator('.job-detail').inner_text()
        assert page.evaluate('window.injected') is None
        # The existing timeline contains dated events; a completed run has one.
        render(injected, status='triggered')
        page.get_by_role('button', name='Лента', exact=True).click()
        assert page.locator('.job-ev .job-card').count() == 1
        assert page.get_by_role('progressbar').get_attribute('aria-valuenow') == '25'

        render(record, status='triggered')
        assert page.locator('[data-job-cancel]').count() == 0
        assert 'осталось' not in page.locator('.job-prog').inner_text()
        assert 'MB/с' not in page.locator('.job-prog').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert errors == []
    finally:
        page.close()
