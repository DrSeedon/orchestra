# V-967 — Orchestra tool cards

Compact chat now renders Orchestra tools with a humanized action and a short argument preview. Expanded cards keep the existing custom renderers, format generic fields and text blocks, and expose complete arguments and structured results under disclosures. Tools without a custom renderer use the same generic view; operation states such as `FAILED` and `UNKNOWN` show as failures.

Playwright screenshots from the isolated dashboard test fixture:

- [Compact rows](tool-cards-compact.png)
- [Expanded future-tool fallback](tool-cards-expanded.png)
- [Expanded checklist](tool-cards-expanded-checklist.png)
- [Expanded artifact publication](tool-cards-expanded-artifact.png)

The fixture uses actual Orchestra tool names and argument shapes, includes the no-argument `list_agents` tool, and adds an unknown future tool to exercise fallback rendering. It uses an isolated test database; the production database was not changed.

Checks: the V-967 Playwright case plus adjacent tool-result correlation and task-result cases — 6 passed; `node --check app/static/js/chat.js` and `git diff --check` passed.
