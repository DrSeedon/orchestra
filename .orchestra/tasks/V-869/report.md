# V-869: generated Tailwind CSS

`bash scripts/build-tailwind.sh` regenerated `app/static/css/vendor/tailwind.css` for Tailwind utilities introduced by V-858. The mismatch was detected by `tests/test_tailwind_css.py::test_committed_css_matches_current_sources`.

## Verification

- `uv run --frozen python -m pytest tests/test_tailwind_css.py -q` — 3 passed.
- `uv run --frozen python -m pytest -m browser tests/ -q` — 193 passed, 7 skipped, 4435 deselected.
- Rendered the actual dashboard template and assets with fixture data in Chromium. The INFO panel matched the committed V-858 screenshots on desktop and mobile: panel width was 410 px at 1440 px viewport width and 351 px at 390 px; mobile document width remained 390 px with no horizontal overflow. Screenshots: [desktop.png](desktop.png), [mobile.png](mobile.png).

The generated CSS is the only application asset changed. No Python code or service lifecycle changed.
