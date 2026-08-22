"""#369 verification: harness tool bubbles render like Claude worker bubbles.

Runs against the LIVE :8888 dashboard (static there comes from the main checkout),
substituting app.js / tool-renderers.js / style.css from THIS worktree via page.route.
First gate: wait for a symbol that does NOT exist in main (HARNESS_TOOL_ALIASES) —
otherwise we would be verifying old code.

Usage: uv run python docs/tasks/369/verify_bubbles.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")
BASE = "http://127.0.0.1:8888"


def source(rel: str) -> str:
    return (ROOT / rel).read_text()


def main() -> int:
    failures = []
    checks = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for rel, ctype in [
            ("app/static/js/tool-renderers.js", "application/javascript"),
            ("app/static/js/app.js", "application/javascript"),
            ("app/static/css/style.css", "text/css"),
        ]:
            pattern = f"**/static/{rel.split('app/static/')[1]}*"
            body, ct = source(rel), ctype

            def serve(route, _request, b=body, c=ct):
                route.fulfill(status=200, content_type=c, body=b)

            page.route(pattern, serve)
        page.goto(BASE, wait_until="domcontentloaded")
        if page.locator('input[name="password"]').count():
            page.fill('input[name="username"]', os.environ["DASHBOARD_USER"])
            page.fill('input[name="password"]', os.environ["DASHBOARD_PASSWORD"])
            page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        # Gate: substituted tool-renderers must be live (symbol absent in main).
        page.wait_for_function("() => typeof HARNESS_TOOL_ALIASES !== 'undefined'",
                               timeout=10000)
        check("new code served (HARNESS_TOOL_ALIASES present)", True)
        page.evaluate("""() => {
            selectedAgent = null;
            if (eventSource) { eventSource.close(); eventSource = null; }
            window.compactMode = false;
            document.querySelector('#chat').innerHTML = '';
        }""")

        # ── full bubbles: inject + assert in ONE evaluate (live SSE writes into #chat
        # between Python round-trips would otherwise race the assertions) ──
        results = page.evaluate("""(calls) => {
            const chat = document.querySelector('#chat');
            selectedAgent = null;
            if (eventSource) { eventSource.close(); eventSource = null; }
            window.compactMode = false;
            chat.innerHTML = '';
            for (const [type, content] of calls) {
                addChatEntry(type, content, null, null, {});
            }
            const t = chat.innerText;
            const q = (sel) => chat.querySelectorAll(sel).length;
            return {
                text: t,
                diffViews: q('.diff-view'),
                bashStatus: [...chat.querySelectorAll('[data-is-bash] .flex.items-center span')]
                    .map(s => s.textContent).join('|'),
                readAttached: !!chat.querySelector('[data-read-path]'),
                diffLines: q('.diff-line-del,.diff-line-add'),
                grepRows: q('.grep-result-row'),
                headers: [...chat.children].map(d => d.innerText.split('\\n')[0]),
            };
        }""", [
            ["tool", 'bash: {"command":"echo hi\\nls -la\\npwd"}'],
            ["tool_result", "exit_code=0\\nhi\\nfile1.py\\nfile2.py\\n/home/x"],
            ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/ui.py","offset":3,"limit":10}'],
            ["tool", 'edit: {"path":"app/ui.py","old":"const a = 1;","new":"const a = 2;"}'],
            ["tool", 'write: {"path":"app/new.py","content":"line1"}'],
            ["tool", 'grep: {"pattern":"foo_bar"}'],
            ["tool_result", "app/ui.py:10:def foo_bar():\\napp/ui.py:44:    foo_bar()"],
            ["tool", 'glob: {"pattern":"**/*.py"}'],
            ["tool", 'todo_write: {"todos":[{"content":"one","status":"completed"},{"content":"two","status":"in_progress"},{"content":"three","status":"pending"}]}'],
            ["tool", 'review: {"focus":"check the diff for regressions"}'],
        ])

        t = results["text"]
        check("bash header shows Bash (not raw name)", "Bash" in t)
        check("bash icon not default 🔧", "🔧 bash" not in t and "🖥" in t)
        check("diff-views rendered (bash cmd + read + edit + write)",
              results["diffViews"] >= 4, f"got {results['diffViews']}")
        check("exit_code line stripped from output", "exit_code=0" not in t)
        check("bash result status ✓ 0 in header", "✓ 0" in results["bashStatus"],
              results["bashStatus"])
        check("read view attached", results["readAttached"])
        check("edit diff has del/add lines", results["diffLines"] >= 2,
              f"got {results['diffLines']}")
        check("grep results rendered as rows", results["grepRows"] >= 2,
              f"got {results['grepRows']}")
        check("glob header", "🔎 Glob:" in t and "**/*.py" in t)
        check("todo header count", "📝 Todos 1/3" in t)
        check("todo rows rendered", "three" in t)
        check("review header", "🧠 Review" in t and "check the diff" in t)
        check("no raw JSON arg dump leaked into headers",
              all('"command"' not in h and '"todos"' not in h
                  for h in results["headers"]), str(results["headers"]))

        # ── compact mode ──
        page.evaluate("""() => {
            document.querySelector('#chat').innerHTML = '';
            window.compactMode = true;
            addChatEntry('tool', 'bash: {"command":"echo hi"}', null, null, {});
            addChatEntry('tool', 'todo_write: {"todos":[{"content":"a","status":"completed"}]}', null, null, {});
            addChatEntry('tool', 'review: {"focus":"regressions"}', null, null, {});
            addChatEntry('tool', 'read: {"path":"/w/x/app/main.py","offset":1,"limit":5}', null, null, {});
        }""")
        ct = page.evaluate("document.querySelector('#chat').innerText")
        check("compact bash preview = command", "echo hi" in ct)
        check("compact todo preview", "📝 1/1 todos" in ct)
        check("compact review preview", "🧠 regressions" in ct)
        check("compact read preview = path", "main.py" in ct)

        browser.close()

    print(f"\n{checks - len(failures)}/{checks} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
