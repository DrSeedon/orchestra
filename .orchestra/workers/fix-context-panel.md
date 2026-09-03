# fix-context-panel

- Frontend regression tests can stay isolated in `tests/test_frontend_<id>.py`; reuse the dashboard fixture with `test_frontend.dashboard_browser.__wrapped__` and route the branch `app.js` via `_route_frontend_sources`. Shared tests may be read and run, but not edited.
