# V-1205 model picker

Changed: app.js (picker, `_isModelChoiceHidden`, orchestrator selector), style.css (`.model-picker*`), i18n.js, CHANGELOG, tests/test_model_picker_v1205.py, selector in tests/test_frontend.py.
Checks: new guards 9 passed (headless Chromium, synthetic catalog, desktop 1280x720 and narrow 360x640, bottom-anchored flip, Escape/outside-click/keyboard, GigaChat current still shown). Related model-catalog/reason tests: 14 passed.
Unrun: 5 existing browser tests errored because the pinned Playwright Chromium build is missing here (environment, not this change); test_frontend.py picker test (needs server + git) was updated by selector only and not run.
Raw screenshots: private-raw/shots (ignored).
