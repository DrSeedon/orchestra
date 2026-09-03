#!/usr/bin/env python3
"""Browser smoke test for analysis.html."""

import os
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


HTML = Path(__file__).with_name("analysis.html").resolve()
CHART_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7"
CHART_ROUTE = "**/chart.js@4.4.7*"


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    request_errors: list[str] = []
    chart_js = urlopen(CHART_URL, timeout=20).read()
    with sync_playwright() as playwright:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        launch_options = {"headless": True}
        if proxy:
            launch_options["proxy"] = {"server": proxy}
        browser = playwright.chromium.launch(**launch_options)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=1,
            ignore_https_errors=True,
        )
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: request_errors.append(f"{request.url}: {request.failure}"))
        page.route(
            CHART_ROUTE,
            lambda route: route.fulfill(status=200, body=chart_js, content_type="application/javascript"),
        )
        page.goto(HTML.as_uri(), wait_until="networkidle")
        try:
            page.wait_for_function(
                "window.Chart && Object.keys(Chart.instances).length === 7", timeout=5_000
            )
        except PlaywrightTimeoutError as error:
            raise AssertionError(
                {
                    "chart_type": page.evaluate("typeof window.Chart"),
                    "chart_instances": page.evaluate(
                        "window.Chart ? Object.keys(Chart.instances).length : null"
                    ),
                    "console_errors": console_errors,
                    "page_errors": page_errors,
                    "request_errors": request_errors,
                }
            ) from error

        assert page.locator("canvas").count() == 7
        assert page.locator("#oProb").inner_text() == "99.22%"
        assert page.locator("#wProb").inner_text() == "99.28%"

        page.locator("#timer").evaluate("el => { el.value = 50; el.dispatchEvent(new Event('input')) }")
        assert page.locator("#oProb").inner_text() == "94.78%"
        assert page.locator("#wProb").inner_text() == "97.87%"
        page.locator("#ctx").evaluate("el => { el.value = 80; el.dispatchEvent(new Event('input')) }")
        assert page.locator("#evTitle").inner_text() == "EV per trigger at 80% ctx"
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.screenshot(path="/tmp/precompact-analysis-desktop.png", full_page=True)

        mobile = browser.new_page(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            ignore_https_errors=True,
        )
        mobile.route(
            CHART_ROUTE,
            lambda route: route.fulfill(status=200, body=chart_js, content_type="application/javascript"),
        )
        mobile.goto(HTML.as_uri(), wait_until="networkidle")
        mobile.wait_for_function("window.Chart && Object.keys(Chart.instances).length === 7")
        assert mobile.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        mobile.screenshot(path="/tmp/precompact-analysis-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if console_errors or page_errors:
        raise AssertionError({"console_errors": console_errors, "page_errors": page_errors})
    print("PASS: 7 charts; timer/context controls; desktop/mobile overflow; zero JS errors")


if __name__ == "__main__":
    main()
