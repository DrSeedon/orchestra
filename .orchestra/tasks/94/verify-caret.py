#!/usr/bin/env python3
"""#94 — путь картинки встаёт в позицию каретки, а не в конец поля.

Живой :8888 отдаёт статику из ОСНОВНОГО чекаута, поэтому `app.js` подменяем на файл
из worktree через `page.route` и печатаем СЧЁТЧИК срабатываний: без него неработающий
перехват дал бы зелёную проверку прода вместо моей правки. Факт применения — `typeof
_insertPathAtCaret` в рантайме.

`/api/upload` тоже перехвачен: путь возвращаем сами, чтобы не писать мусор в
`data/uploads/` живого сервера. После вставки допечатываем «ещё» — так видно, что
юзер продолжает писать ПОСЛЕ пути, а не перед ним (в этом и была жалоба).

Запуск:  python3 docs/tasks/94/verify-caret.py
"""
import json

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
BASE = "http://127.0.0.1:8888"
APP_JS = open(f"{WT}/app/static/js/app.js", encoding="utf-8").read()

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

hits = {"app_js": 0, "upload": 0}
READ_INPUT = """() => {
    const i = document.querySelector('#chat-input');
    return {value: i.value, start: i.selectionStart, end: i.selectionEnd,
            focused: document.activeElement === i};
}"""
UPLOADED = "/home/kesha/orchestra/data/uploads/pic.png"


def run_case(page, title, before_text, caret, select_to=None, type_after=True):
    """Ставит текст и каретку/выделение, дропает файл, возвращает состояние поля."""
    page.evaluate(
        """([text, start, end]) => {
            const i = document.querySelector('#chat-input');
            i.value = text; i.focus(); i.setSelectionRange(start, end);
        }""",
        [before_text, caret, select_to if select_to is not None else caret],
    )
    # настоящий drop с файлом — тот же путь, что у вставки из буфера (_uploadToChat)
    page.evaluate("""() => {
        const i = document.querySelector('#chat-input');
        const dt = new DataTransfer();
        dt.items.add(new File([new Uint8Array([137,80,78,71])], 'pic.png', {type: 'image/png'}));
        i.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
    }""")
    page.wait_for_function(
        "() => document.querySelector('#chat-input').value.includes('pic.png')", timeout=15000)
    state = page.evaluate(READ_INPUT)
    print(f"\n--- {title}")
    print(f"  было:  {before_text!r}  каретка {caret}"
          + (f"..{select_to}" if select_to is not None else ""))
    print(f"  стало: {state['value']!r}")
    print(f"  selectionStart={state['start']} end={state['end']} focused={state['focused']}")
    if type_after:
        page.keyboard.type("ещё")
        state["typed"] = page.evaluate(READ_INPUT)["value"]
        print(f"  дописал 'ещё': {state['typed']!r}")
    return state


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))

        def sub_js(route):
            hits["app_js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8",
                          body=APP_JS)

        def sub_upload(route):
            hits["upload"] += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"path": UPLOADED, "url": "/static/favicon.ico"}))

        page.route("**/static/js/app.js*", sub_js)
        page.route("**/api/upload", sub_upload)

        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#chat-input", timeout=20000)

        applied = page.evaluate("() => typeof _insertPathAtCaret")
        print(f"перехват app.js сработал раз: {hits['app_js']}; "
              f"typeof _insertPathAtCaret = {applied}")
        assert applied == "function", "подмена не применилась — дальше мерили бы прод"

        results = {}
        results["середина"] = run_case(page, "каретка в СЕРЕДИНЕ", "посмотри сюда", 9)
        results["пусто"] = run_case(page, "поле ПУСТОЕ", "", 0, type_after=False)
        results["конец"] = run_case(page, "каретка в КОНЦЕ", "хвост", 5)
        results["выделение"] = run_case(page, "ВЫДЕЛЕНИЕ заменяется", "убери это слово",
                                        6, 9, type_after=False)

        # второй путь вставки — кнопка ➜ в файловом дереве (было продублировано, теперь общее)
        page.wait_for_selector("#file-tree span[title='Send path to chat']", timeout=20000)
        page.evaluate("""() => {
            const i = document.querySelector('#chat-input');
            i.value = 'файл тут'; i.focus(); i.setSelectionRange(5, 5);
        }""")
        btn = page.locator("#file-tree span[title='Send path to chat']").first
        btn.hover()
        btn.click()
        tree_state = page.evaluate(READ_INPUT)
        print(f"\n--- кнопка ➜ в дереве; было 'файл тут' каретка 5")
        print(f"  стало: {tree_state['value']!r}  selectionStart={tree_state['start']}")

        page.screenshot(path=f"{WT}/docs/tasks/94/caret-insert.png")

        print(f"\nперехватов: app.js={hits['app_js']}, /api/upload={hits['upload']}")
        print(f"ошибок в консоли: {errors or 'нет'}")

        # --- приёмка ---
        checks = []
        for name, r in results.items():
            pos = r["value"].find(UPLOADED)
            checks.append((f"[{name}] каретка сразу после пути",
                           pos >= 0 and r["start"] == pos + len(UPLOADED)
                           and r["end"] == r["start"]))
        mid = results["середина"]
        checks.append(("путь ПЕРЕД хвостом, не в конце", mid["value"].startswith("посмотри")
                       and mid["value"].rstrip().endswith("сюда")))
        checks.append(("путь не слипся с соседями",
                       f"\n{UPLOADED}\n" in mid["value"]))
        checks.append(("продолжение печатается ПОСЛЕ пути, не перед",
                       mid["typed"] == f"посмотри \n{UPLOADED}ещё\nсюда"))
        checks.append(("пустое поле — только путь", results["пусто"]["value"] == UPLOADED))
        checks.append(("каретка в конце — как раньше (регресса нет)",
                       results["конец"]["value"] == f"хвост\n{UPLOADED}"))
        sel = results["выделение"]
        checks.append(("выделение заменено", sel["value"] == f"убери \n{UPLOADED}\n слово"))
        checks.append(("фокус в поле", all(r["focused"] for r in results.values())))
        tpath = tree_state["value"][5:].split("\n")[1]
        checks.append(("кнопка ➜ вставила в каретку",
                       tree_state["value"] == f"файл \n{tpath}\nтут"
                       and tree_state["start"] == 5 + 1 + len(tpath)))
        checks.append(("нет ошибок в консоли", not errors))

        print()
        for name, ok in checks:
            print(f"  {'OK  ' if ok else 'FAIL'} {name}")
        print("\nИТОГ:", "всё зелёное" if all(ok for _, ok in checks) else "ЕСТЬ ПАДЕНИЯ")
        browser.close()


if __name__ == "__main__":
    main()
