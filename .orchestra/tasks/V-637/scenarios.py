"""V-637: 8 agent tasks for the registry-review stand and their machine checks.

Each scenario = a user message + check(env) -> (ok, detail). `env` gives sh(), read(path) and
sql(query) against wherever the stand lives (local copy or the real stand over ssh).
The tasks are themed for a registry-of-Russian-software expert (ПП РФ № 1236) and are built on
the demo workspace files: требования.md, компоненты.csv, проверка_лицензий.py, сводка.md.
"""
import json
import re

WS = "/workspace/project"
NAMES = ["FastAPI", "SQLite", "Uvicorn", "Pydantic", "Модуль оркестрации"]
LICENSES = ["MIT", "Public Domain", "BSD-3-Clause", "Проприетарная"]


def _new_py(env):
    out = env.sh(f"cd {WS} && ls *.py 2>/dev/null")
    return [f for f in out.split() if f not in env.py_before]


def c_bubble(env):
    files = _new_py(env)
    for f in files:
        r = env.run(f"cd {WS} && timeout 20 python3 {f}")
        if r.code == 0 and all(n in r.out for n in NAMES):
            if sorted(NAMES, key=lambda n: r.out.find(n)) == sorted(NAMES):
                return True, f"{f} prints the components sorted"
    return False, f"no new script prints the sorted names (new .py: {files})"


def c_countries(env):
    for f in _new_py(env):
        r = env.run(f"cd {WS} && timeout 20 python3 {f}")
        if r.code == 0 and re.search(r"Россия\D{0,12}1\b", r.out) and re.search(
                r"Иностранн\w*\D{0,12}4\b", r.out) and "80" in r.out:
            return True, f"{f}: {r.out.strip()[:120]!r}"
    return False, f"no script printed Россия 1 / Иностранные 4 / 80 (new .py: {_new_py(env)})"


def c_summary(env):
    if not env.exists(f"{WS}/справка_эксперту.md"):
        return False, "справка_эксперту.md is missing"
    t = env.read(f"{WS}/справка_эксперту.md")
    miss = [l for l in LICENSES if l not in t]
    if miss:
        return False, f"licenses missing: {miss}"
    # 5 requirements, 5 components, 4 foreign: each number must appear next to its noun
    if not re.search(r"5\D{0,40}требован|требован[^\n]*\b5\b", t, re.I):
        return False, "requirement count 5 not stated"
    if not re.search(r"4\D{0,60}иностран|иностран[^\n]*\b4\b", t, re.I):
        return False, "foreign count 4 not stated"
    return True, "справка_эксперту.md has licenses and correct counts"


def _workers(env, n=1):
    rows = env.sql("select name,status from sessions where is_orchestrator=0 and status!='archived'")
    return [r for r in rows if r["name"] not in getattr(env, "workers_before", ())]


def c_inventory(env):
    workers = _workers(env)
    if not workers:
        return False, "no worker was spawned"
    if not env.exists(f"{WS}/инвентаризация.md"):
        return False, "инвентаризация.md was not delivered into the project folder"
    t = env.read(f"{WS}/инвентаризация.md")
    for junk in ("$(", "Собирается", "TODO", "заглушк"):
        if junk in t:
            return False, f"placeholder left in the file: {junk!r}"
    pyv = env.sh("python3 --version").strip().split()[-1]
    osn = env.sh("grep ^NAME= /etc/os-release | cut -d= -f2 | tr -d '\"'").strip()
    if pyv not in t and pyv.rsplit(".", 1)[0] not in t:
        return False, f"python version {pyv} not in file"
    if osn.split()[0].lower() not in t.lower() and "linux" not in t.lower():
        return False, f"OS name {osn} not in file"
    return True, f"worker {workers[0]['name']}, file has python {pyv} and OS {osn}"


NEW_TASKS = ["происхождения", "иностранных выплат", "заявление"]


def c_tasks(env):
    rows = env.sql(f"select id,title from tm_tasks where id>{env.task_base} order by id")
    hit = {k: [r["id"] for r in rows if k.lower() in r["title"].lower()] for k in NEW_TASKS}
    bad = {k: v for k, v in hit.items() if len(v) != 1}
    if bad or len(rows) != 3:
        return False, f"tasks id>4: {[(r['id'], r['title'][:40]) for r in rows]}; matches {hit}"
    final = env.final_text
    total = env.sql("select count(*) n from tm_tasks")[0]["n"]
    if str(total) not in final:
        return False, f"final answer does not give the total {total}"
    return True, f"3 new tasks {[r['id'] for r in rows]}, answer states total"


def c_json(env):
    r0 = env.run(f"cd {WS} && python3 проверка_лицензий.py")
    if "Итого: допустимо — 5, требует проверки — 0" not in r0.out or "FastAPI — MIT — допустима" not in r0.out:
        return False, f"plain output changed: {r0.out[:200]!r}"
    r1 = env.run(f"cd {WS} && python3 проверка_лицензий.py --json")
    try:
        d = json.loads(r1.out)
    except Exception as e:
        return False, f"--json output is not JSON: {r1.out[:200]!r}"
    if d != {"допустимо": 5, "требует_проверки": 0}:
        return False, f"--json content {d}"
    return True, "both modes correct"


def c_tests(env):
    if not _workers(env):
        return False, "no worker was spawned"
    f = f"{WS}/test_проверка_лицензий.py"
    if not env.exists(f):
        return False, "test_проверка_лицензий.py was not delivered"
    r = env.run(f"cd {WS} && python3 -m unittest -v test_проверка_лицензий 2>&1")
    kept = env.run(f"cd {WS} && test -f компоненты.csv && git diff --quiet -- компоненты.csv")
    if kept.code != 0:
        return False, "the tests destroyed or changed the project's компоненты.csv"
    n = len(re.findall(r"\.\.\. ok", r.out))
    if r.code != 0 or n < 3:
        return False, f"unittest exit {r.code}, {n} passed: {r.out[-200:]!r}"
    # the tests must exercise the real script: break it and they have to go red
    m = env.run(f"T=$(mktemp -d) && cp -r {WS}/. $T/ && cd $T && sed -i \"s/'MIT'/'MIT-broken'/\" проверка_лицензий.py && python3 -m unittest test_проверка_лицензий 2>&1; echo rc=$?")
    if m.out.rstrip().endswith("rc=0"):
        return False, f"{n} tests pass, but they still pass when MIT is removed from the allowed list: they do not test the real script"
    return True, f"{n} tests pass and catch a broken allowed list"


def c_checklist(env):
    rows = env.sql(f"select id,title from tm_tasks where id>{env.task_base}")
    if len([r for r in rows if "пакет документов" in r["title"].lower()]) != 1 or len(rows) != 1:
        return False, f"tasks id>4: {[r['title'][:40] for r in rows]}"
    if not env.exists(f"{WS}/чеклист_реестра.md"):
        return False, "чеклист_реестра.md is missing"
    t = env.read(f"{WS}/чеклист_реестра.md")
    n = len(re.findall(r"^\s*- \[ \]", t, re.M))
    if n < 6:
        return False, f"only {n} checkbox lines"
    return True, f"{n} checkbox lines, 1 task"


def c_audit(env):
    if not _workers(env):
        return False, "no worker was spawned"
    files = env.sh(f"cd {WS} && ls | grep -i -E 'audit|аудит'").split()
    if not files:
        return False, "no audit report file in the project folder"
    kern = env.sh("uname -r").strip()
    problems = []
    for f in files:
        t = env.read(f"{WS}/{f}")
        if len(re.findall(r":\s*\$\([a-z]", t)) >= 3:
            problems.append(f"{f}: unexpanded $(...) template values")
        elif kern not in t:
            problems.append(f"{f}: kernel {kern} missing")
        elif len(t) < 800:
            problems.append(f"{f}: only {len(t)} chars")
        elif re.search(r"(?i)(token|secret|password)\s*[=:]\s*\S{12,}", t):
            problems.append(f"{f}: secret-looking value in the report")
        else:
            return True, f"{f}: real kernel {kern}, {len(t)} chars"
    return False, "; ".join(problems)


def c_commit(env):
    log = env.sh(f"cd {WS} && git log -1 --format=%s").strip()
    dirty = env.sh(f"cd {WS} && git status --porcelain --untracked-files=no").strip()
    if "json" not in log.lower():
        return False, f"last commit message {log!r}"
    if dirty:
        return False, f"tracked files still dirty: {dirty[:100]}"
    return True, f"committed: {log}"


SCENARIOS = [
    dict(id="S1", cls="free, code+run",
         msg="Напиши на питоне сортировку пузырьком для списка компонентов из файла компоненты.csv (по названию) и покажи, что получилось.",
         check=c_bubble),
    dict(id="S2", cls="code, run, fix",
         msg="Напиши скрипт страны.py: он читает компоненты.csv и считает, сколько компонентов у правообладателей из России и сколько из других стран (третья колонка). Скрипт печатает «Россия — N», «Иностранные — M» и долю иностранных в процентах, округлённую до целого. Запусти его и скажи результат.",
         check=c_countries),
    dict(id="S3", cls="read several files, summarize",
         msg="Прочитай требования.md, компоненты.csv и сводка.md и составь файл справка_эксперту.md: сколько требований в ПП РФ № 1236, сколько компонентов в перечне, сколько из них у иностранных правообладателей и какие лицензии встречаются.",
         check=c_summary),
    dict(id="S4", cls="worker, wait, use result",
         msg="Создай воркера, который сделает инвентаризацию окружения, где запускается программа: версия ОС, версия Python и первые десять установленных Python-пакетов, результат в файл инвентаризация.md. Когда он отчитается, перенеси файл в проект и назови мне три главных факта.",
         check=c_inventory),
    dict(id="S5", cls="tracker",
         msg="Заведи в трекере три задачи: «Собрать подтверждение российского происхождения ПО», «Подготовить расчёт доли иностранных выплат» и «Оформить заявление в реестр». Потом скажи, сколько всего задач сейчас в трекере, и назови номера новых.",
         check=c_tasks),
    dict(id="S6", cls="edit existing code, test",
         msg="Доработай проверка_лицензий.py: добавь ключ --json — с ним скрипт печатает только один JSON-объект {\"допустимо\": число, \"требует_проверки\": число}, без ключа вывод остаётся прежним. Проверь оба режима.",
         check=c_json),
    dict(id="S6x", cls="edit existing code (explicit wording)",
         msg="Доработай проверка_лицензий.py: добавь ключ --json. Без ключа скрипт печатает всё как раньше. С ключом --json он не печатает построчный вывод и итоговую строку, а печатает единственную строку — JSON-объект {\"допустимо\": число, \"требует_проверки\": число}. Запусти оба режима и покажи вывод.",
         check=c_json),
    dict(id="C1", cls="git commit on request",
         msg="Закоммить в git одним коммитом изменения в проверка_лицензий.py и новые файлы страны.py, справка_эксперту.md и чеклист_реестра.md (остальное не трогай), сообщение коммита «Проверка лицензий: ключ --json, справка, чеклист».",
         check=c_commit),
    dict(id="S7", cls="worker writes tests",
         msg="Создай воркера, пусть он напишет unittest для проверка_лицензий.py в файле test_проверка_лицензий.py, не меньше трёх тестов. Когда он отчитается, перенеси файл в проект, запусти python3 -m unittest и скажи результат.",
         check=c_tests),
    dict(id="S8", cls="tracker + file + report",
         msg="Заведи задачу «Подготовить пакет документов для реестра», затем создай чеклист_реестра.md: по одному пункту вида «- [ ] …» на каждое из пяти требований из требования.md и шестой пункт про подачу заявления. В конце покажи список задач.",
         check=c_checklist),
    dict(id="S9", cls="owner phrasing: worker audit",
         msg="сделай воркера чтобы он изучил текущее кружение впс и аудит сделал системы",
         followups=["да давай"], check=c_audit),
]
