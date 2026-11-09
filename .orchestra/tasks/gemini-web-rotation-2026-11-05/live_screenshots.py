"""Screenshots of actual authenticated Orchestra, using repository's Playwright stack."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, '/home/kesha/orchestra')
from dotenv import load_dotenv
from app.auth import create_session
from playwright.sync_api import sync_playwright
ROOT=Path('/home/kesha/orchestra')
TASK=ROOT/'.orchestra/tasks/gemini-web-rotation-2026-11-05'
load_dotenv(ROOT/'.env')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    try:
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'session','value':create_session(os.environ.get('DASHBOARD_USER','')),'url':'http://127.0.0.1:8888'}])
        page=context.new_page()
        page.goto('http://127.0.0.1:8888/',wait_until='domcontentloaded')
        page.wait_for_selector('[data-usage-compact-provider="gemini-web"]',timeout=45000)
        page.evaluate("async () => {currentScope='/home/kesha/orchestra'; await refreshSessions();}")
        page.locator('.gemini-web-account-pill').first.wait_for(timeout=15000)
        page.screenshot(path=str(TASK/'live-desktop.png'))
        page.locator('#usage-info-btn').click()
        page.locator('[data-usage-provider="gemini-web"]').wait_for(timeout=5000)
        page.screenshot(path=str(TASK/'live-desktop-details.png'))
        details=page.locator('[data-usage-provider="gemini-web"]').inner_text()
        # Close the tooltip, resize, let the existing responsive layout settle.
        page.locator('#usage-info-btn').click()
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(TASK/'live-mobile.png'))
        result={'compact_accounts':page.locator('.usage-gemini-account').count(),
                'session_pills':page.locator('.gemini-web-account-pill').count(),
                'details_contain_all_accounts':all(x in details for x in ('the…ool','max…0as','kat….ks')),
                'mobile_overflow':page.evaluate('document.documentElement.scrollWidth > innerWidth')}
        (TASK/'live-visual.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally: browser.close()
