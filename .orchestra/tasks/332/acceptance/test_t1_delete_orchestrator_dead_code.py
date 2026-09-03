"""#332 T1: freeze the dead JS helper's absence and the surviving delete UX."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
APP_JS = ROOT / "app/static/js/app.js"
TEMPLATE = ROOT / "app/templates/dashboard.html"
JS_ROOT = ROOT / "app/static/js"
STATIC_ROOT = ROOT / "app/static"

LEGACY_NAME = "deleteOrchestrator"
LEGACY_DISPATCH_PATTERNS = (
    re.compile(r"(?:window|globalThis|self)\s*\[\s*['\"]delete['\"]\s*\+\s*['\"]Orchestrator['\"]"),
    re.compile(r"(?:window|globalThis|self)\s*\[\s*['\"]deleteOrchestrator['\"]\s*\]"),
    re.compile(r"['\"]deleteOrchestrator['\"]\s*:\s*"),
    re.compile(r"['\"]delete['\"]\s*\+\s*['\"]Orchestrator['\"]"),
    re.compile(r"(?:['\"]delete['\"]|\bdelete\b).{0,120}(?:['\"]Orchestrator['\"]|\bOrchestrator\b)"),
    re.compile(r"(?:['\"]Orchestrator['\"]|\bOrchestrator\b).{0,120}(?:['\"]delete['\"]|\bdelete\b)"),
)


def _production_js() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(JS_ROOT.glob("*.js")))


def _assert_legacy_name_absent_without_computed_dispatch(source: str) -> None:
    assert LEGACY_NAME not in source, (
        "legacy deleteOrchestrator must have no production declaration/caller/string"
    )
    for pattern in LEGACY_DISPATCH_PATTERNS:
        assert not pattern.search(source), (
            f"legacy helper must not be hidden behind computed/string dispatch: {pattern.pattern}"
        )


def test_t1_no_production_delete_orchestrator_reference_or_dispatch():
    """The frozen absence oracle catches direct and compound computed-name mutants."""
    _assert_legacy_name_absent_without_computed_dispatch(_production_js() + "\n" + TEMPLATE.read_text())


def test_t1_surviving_orchestrator_delete_path_is_wired():
    """Deleting the dead helper must leave the current context-menu UX intact."""
    source = APP_JS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "function openDeleteOrchModal(name, scope)" in source
    assert "openDeleteOrchModal(name, scope)" in source
    assert "method: 'DELETE'" in source
    assert "/api/orchestrators/${name}" in source
    assert 'id="delete-orch-modal"' in template
    assert 'id="delete-orch-confirm"' in template


def test_t1_dashboard_js_parse_and_render_smoke():
    """The normal five-file dashboard load remains parseable and render-complete."""
    script_paths = re.findall(r"g\.asset\(['\"](js/[^'\"]+\.js)['\"]\)", TEMPLATE.read_text())
    assert script_paths == [
        "js/utils.js",
        "js/tool-renderers.js",
        "js/usage.js",
        "js/analytics.js",
        "js/app.js",
    ]
    for rel in script_paths:
        path = STATIC_ROOT / rel
        assert path.is_file(), rel
        subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)

    source = _production_js()
    for handler in re.findall(r'onclick="[^\"]*?\b([A-Za-z_$][\w$]*)\s*\(', TEMPLATE.read_text()):
        if handler in {"fetch", "if"}:
            continue
        assert re.search(rf"\bfunction\s+{re.escape(handler)}\s*\(", source), handler
