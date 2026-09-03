"""Browser acceptance for #245 with branch static files and a mobile layout viewport."""

from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
APP_JS = ROOT / "app/static/js/app.js"
STYLE = ROOT / "app/static/css/style.css"
OUT = Path(__file__).with_name("voice-recording-mobile.png")
BASE = "http://127.0.0.1:8888"


def main() -> None:
    env = dotenv_values("/home/kesha/orchestra/.env")
    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
    hits = {"app.js": 0, "style.css": 0, "transcribe": 0}
    upload = {"bytes": 0, "content_type": ""}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[
            "--no-sandbox",
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
        ])
        context = browser.new_context(
            extra_http_headers=headers,
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=3,
        )
        context.grant_permissions(["microphone"], origin=BASE)
        page = context.new_page()

        def branch_js(route):
            hits["app.js"] += 1
            route.fulfill(status=200, content_type="text/javascript", body=APP_JS.read_text())

        def branch_css(route):
            hits["style.css"] += 1
            route.fulfill(status=200, content_type="text/css", body=STYLE.read_text())

        def transcribe(route):
            hits["transcribe"] += 1
            upload["bytes"] = len(route.request.post_data_buffer or b"")
            upload["content_type"] = route.request.headers.get("content-type", "")
            route.fulfill(
                status=200,
                content_type="application/json",
                json={"text": "Текст из голосовой записи"},
            )

        page.route("**/static/js/app.js*", branch_js)
        page.route("**/static/css/style.css*", branch_css)
        page.route("**/api/transcribe", transcribe)
        page.goto(BASE, wait_until="load")
        page.wait_for_function("() => typeof initVoiceInput === 'function'")
        page.locator("#voice-btn").click()
        page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'recording'")
        page.wait_for_timeout(1100)
        observed = page.evaluate(
            """() => ({
                state: $('#voice-controls').dataset.state,
                timer: $('#voice-timer').textContent,
                level: Number($('#voice-level').style.getPropertyValue('--voice-level')),
                mime: _voiceRecorder?.mimeType,
                visible: Boolean($('#voice-btn').offsetWidth && $('#voice-btn').offsetHeight),
            })"""
        )
        minutes, seconds = map(int, observed["timer"].split(":"))
        if observed["state"] != "recording" or not 1 <= minutes * 60 + seconds < 10:
            raise RuntimeError(f"recording UI is not live: {observed}")
        if observed["level"] <= 1 or not observed["visible"]:
            raise RuntimeError(f"volume meter is not visible: {observed}")
        page.locator("#chat-input").locator("xpath=..").screenshot(path=OUT)
        page.locator("#voice-btn").click()
        page.wait_for_function("() => $('#chat-input').value === 'Текст из голосовой записи'")
        if hits != {"app.js": 1, "style.css": 1, "transcribe": 1}:
            raise RuntimeError(f"unexpected request path: {hits}")
        if upload["bytes"] < 1000 or "multipart/form-data" not in upload["content_type"]:
            raise RuntimeError(f"recorded audio was not uploaded: {upload}")
        print(f"hits={hits}")
        print(f"voice={observed}")
        print(f"upload={upload}")
        print(f"screenshot={OUT}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
