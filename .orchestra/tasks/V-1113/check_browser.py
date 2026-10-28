"""Offline browser fallback for this partial hub copy; not the required suite."""

from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from playwright.sync_api import BrowserType, Page


def main():
    mutate = "--mutate-hour" in sys.argv[1:]
    launch = BrowserType.launch
    add_script = Page.add_script_tag
    quota_js = Path("app/static/js/quota-lines.js").resolve()

    def launch_chrome(self, **kwargs):
        return launch(self, **{**kwargs, "channel": "chrome"})

    def add_script_tag(self, **kwargs):
        if mutate and kwargs.get("path") and Path(kwargs["path"]).resolve() == quota_js:
            content = quota_js.read_text(encoding="utf-8")
            original = "submitOverride(hourButton, {minutes: 60})"
            assert content.count(original) == 1
            kwargs = {"content": content.replace(original, "submitOverride(hourButton, {minutes: 61})")}
        return add_script(self, **kwargs)

    args = ["--noconftest", "tests/test_t344_quota_lines_browser.py", "-q"]
    if mutate:
        args += ["-k", "gate_hour_sends_exact_minutes"]
    with patch.object(BrowserType, "launch", launch_chrome), patch.object(Page, "add_script_tag", add_script_tag):
        return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
