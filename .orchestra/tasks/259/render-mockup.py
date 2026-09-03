"""Render and sanity-check the self-contained #259 dashboard mockup."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUT = Path(__file__).parent.resolve()


def main() -> None:
    errors: list[str] = []
    measurements: dict[str, dict[str, int | bool | str]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        for width in (1280, 1440, 1680, 1920):
            page = browser.new_page(viewport={"width": width, "height": 1080})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((OUT / "mockup.html").as_uri(), wait_until="load")
            page.wait_for_function("() => typeof setDashboardMockupMode === 'function'")
            measurements[str(width)] = page.evaluate(
                """() => ({
                    title: document.title,
                    dashboardWidth: Math.round(document.querySelector('.dashboard').getBoundingClientRect().width),
                    viewportWidth: innerWidth,
                    documentOverflows: document.documentElement.scrollWidth > innerWidth,
                    proposalVisible: document.querySelector('.after-only').offsetParent !== null,
                })"""
            )
            if width == 1920:
                page.screenshot(path=OUT / "mockup-proposed-1920.png")
                page.evaluate("setDashboardMockupMode('before')")
                measurements[str(width)]["beforeVisible"] = page.locator(
                    ".before-only"
                ).first.is_visible()
                measurements[str(width)]["afterHidden"] = not page.locator(
                    ".after-only"
                ).first.is_visible()
                page.screenshot(path=OUT / "mockup-before-1920.png")
            page.close()
        browser.close()
    print(json.dumps({"errors": errors, "measurements": measurements}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
