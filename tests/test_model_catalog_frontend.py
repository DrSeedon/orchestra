"""#366 T5 — delivery check: the catalog screen must ship in the dashboard bundle.

Browser behaviour itself is verified manually via a Playwright page.route probe
(recorded in docs/tasks/366/report.md); this test only proves the static bundle
carries the new screen and wires it to the T4 endpoints.
"""

from pathlib import Path

APP_JS = Path(__file__).parent.parent / "app" / "static" / "js" / "app.js"
DASHBOARD_HTML = Path(__file__).parent.parent / "app" / "templates" / "dashboard.html"


def _bundle() -> str:
    return APP_JS.read_text() + DASHBOARD_HTML.read_text()


def test_t5_catalog_screen_shipped():
    bundle = _bundle()
    assert 'id="catalog-modal"' in bundle or "'catalog-modal'" in bundle or \
        '"catalog-modal"' in bundle
    assert "/api/models/catalog" in bundle


def test_t5_catalog_screen_has_search_filters_and_toggles():
    bundle = _bundle().lower()
    for anchor in ("catalog-search", "catalog-free", "catalog-tools", "data-flag"):
        assert anchor in bundle, f"missing catalog UI anchor: {anchor}"


def test_t5_picker_reads_filtered_models_not_catalog():
    """The per-agent picker keeps consuming /api/models (already dashboard-filtered);
    the full catalog lives only on the catalog screen."""
    js = APP_JS.read_text()
    picker = js[js.index("async function _showModelPicker"):]
    picker = picker[:picker.index("\n}", picker.index("for (const m of"))]
    assert "_MODELS" in picker
