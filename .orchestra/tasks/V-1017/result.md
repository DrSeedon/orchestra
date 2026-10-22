# Dashboard UI locale formatting

Added `orchLocale()` in utils.js, reading the existing `orchLang()` API on each call. Routed dashboard locale formatters through it, including analytics, usage, quota/job timelines, activity, chat and money displays. Kept configured currencies, time zones and decimal precision. Updated the Fixed changelog entry.

Regression coverage: tests/test_i18n_formatters.py checks every dashboard locale call and executes actual i18n/formatter code in Node for RU and EN, independent of browser language. Updated the standalone jobs harness and the English task-money assertion.

Verification: node --check passed for all eight changed JS files. The Node regression payload passed for both languages, monetary precision, time zones and invalid inputs. A complete scan of dashboard locale formatter calls passed.

Attempted related pytest files with uv run --offline --frozen python -m pytest. Blocked because uv is unavailable in this environment (the installed forwarding shim cannot run here). No Python app module was imported; its imported path therefore could not be reported. Browser and pytest verification remain pending in an environment with the project dependencies.
