"""Optional test-only executable override; no downloads or dependency changes.

Use with pytest -p browser_override --jobs-browser-executable /path/to/chromium.
"""

def pytest_addoption(parser):
    parser.addoption("--jobs-browser-executable", action="store", default=None)
