"""Measure the usage/header controls across desktop widths with optional branch static files."""

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8888"
WIDTHS = (390, 1280, 1440, 1680, 1920)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "after"))
    args = parser.parse_args()
    env = dotenv_values("/home/kesha/orchestra/.env")
    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
    measurements = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        for width in WIDTHS:
            context = browser.new_context(
                extra_http_headers=headers,
                viewport={"width": width, "height": 800},
                device_scale_factor=1,
            )
            page = context.new_page()
            hits = {"usage.js": 0, "style.css": 0}
            if args.mode == "after":
                def branch_usage(route):
                    hits["usage.js"] += 1
                    route.fulfill(
                        status=200,
                        content_type="text/javascript",
                        body=(ROOT / "app/static/js/usage.js").read_text(),
                    )

                def branch_css(route):
                    hits["style.css"] += 1
                    route.fulfill(
                        status=200,
                        content_type="text/css",
                        body=(ROOT / "app/static/css/style.css").read_text(),
                    )

                page.route("**/static/js/usage.js*", branch_usage)
                page.route("**/static/css/style.css*", branch_css)
            page.goto(BASE, wait_until="load")
            page.wait_for_selector("#usage-info-btn", state="attached")
            if args.mode == "after":
                page.wait_for_function("() => typeof _renderUsageBarShell === 'function'")
                if hits != {"usage.js": 1, "style.css": 1}:
                    raise RuntimeError(f"branch static was not applied at {width}: {hits}")
            measured = page.evaluate(
                """() => {
                    const box = node => {
                        const r = node.getBoundingClientRect();
                        return {left:r.left, right:r.right, width:r.width, top:r.top, bottom:r.bottom};
                    };
                    const bar = document.querySelector('#usage-bar');
                    const info = document.querySelector('#usage-info-btn');
                    const analytics = document.querySelector('#analytics-btn');
                    const limits = document.querySelector('.usage-limits');
                    const barBox = box(bar);
                    const infoBox = box(info);
                    const visible = r => r.width > 0 && r.left >= 0 && r.right <= innerWidth
                        && r.left >= barBox.left && r.right <= barBox.right;
                    return {
                        viewport: innerWidth,
                        bar: {...barBox, clientWidth:bar.clientWidth, scrollWidth:bar.scrollWidth},
                        info: {...infoBox, visible:visible(infoBox)},
                        analytics: {...box(analytics), visible:box(analytics).right <= innerWidth},
                        limits: limits ? {...box(limits), scrollWidth:limits.scrollWidth, clientWidth:limits.clientWidth} : null,
                        text: bar.innerText,
                    };
                }"""
            )
            measurements[str(width)] = measured
            if width == 1280:
                page.screenshot(
                    path=Path(__file__).with_name(f"topbar-{args.mode}-1280.png"),
                    clip={"x": 0, "y": 0, "width": width, "height": 105},
                )
            context.close()
        browser.close()

    print(json.dumps(measurements, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
