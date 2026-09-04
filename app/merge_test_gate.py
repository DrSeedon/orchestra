"""Merge-time test subset. Not the full suite.

Full pytest is ~728s (grok-51, 2026-08-14) and takes the one-per-project
test_lock — four workers would queue. This gate never launches the full suite
and never passes pytest -x (CI with -x hid a red main for a week).

Subset: tests/test_<stem>.py for each changed app/*.py, plus
tests/test_routes_surface.py when app/routes/**, app/main.py or the snapshot
change. Docs-only / no git diff → skipped (fixtures without git stay skipped
so #240 oracles keep working). Unmapped app modules are a hole we accept —
missing tests ≠ landing a red test that already exists.

Tests marked `live_probe` are deselected: they spend a real provider turn, so they go red
on quota and provider outages instead of on the diff. They stay runnable by hand
(`pytest -m live_probe tests/`) and their inventory is pinned by a test.

Mapped files are run in sequential batches of MAX_TEST_FILES. The batches share one
wall-clock budget and never turn into a full-suite invocation.

Every node also carries its own PER_TEST_TIMEOUT_SECONDS ceiling, so one hung test turns into a
named red instead of eating the whole batch budget and answering `inconclusive`.

Killed by the budget → the partial pytest output decides, because "the tests are red" and
"we did not finish" arrive as the same TimeoutExpired and must not be answered the same way:
a verdict pytest already printed (`FAILED`/`ERROR`) makes it FAILED — a red test is red whether
or not the rest ran — and only a kill with no verdict at all is INCONCLUSIVE, reported with what
was verified and what was never reached. Does not close bash: the worker can rewrite this file.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED

MAX_TEST_FILES = 12
MAX_BATCH_TESTS = 6

# Бюджет ВЫВЕДЕН ИЗ ЗАМЕРА (#336), а не назначен. Прежние фиксированные 180 с числом про
# pytest никогда не были: `git log -S` показывает, что это дефолт операторской команды
# приёмки (#240), скопированный в гейт вместе с ним (#255). Каждое число ниже — с источником,
# иначе через месяц оно станет вторым таким же 180.
#
# ПОЛ = BASE + PER_FILE = 330 с. Самый дорогой одиночный тест-файл замерен в 219.5 с
#   (`tests/test_manager.py`; под нагрузкой 15+ тот же файл дал 283 с) — взят полуторный
#   запас. Батч не может быть меньше одного файла, поэтому при бюджете ниже этого числа
#   дифф, задевающий `app/manager.py`, не получает вердикта ни при какой раскладке батчей.
# ШАГ = 150 с на файл. Медиана тест-файла ≈33 с, среднее ≈68 с, хвост тяжёлый
#   (`tests/test_frontend.py` — 71–148 с по пяти прод-замерам). Шаг взят от среднего с
#   двойным запасом, чтобы набор средних файлов укладывался, а не впритык.
# ПОТОЛОК = 1200 с. Худший правдоподобный набор из замеренных (manager+frontend+db+session+
#   mcp_stdio+tg_bridge) = 682 с суммой одиночных прогонов, полуторный запас. Потолок нужен,
#   потому что число файлов со стоимостью коррелирует слабо: один и тот же файл замерен
#   14.3 и 149.5 с (10.5×) — разброс задаёт конкурентная загрузка машины, и подобрать
#   «точный» бюджет нельзя в принципе. Отсюда же второй контур защиты: отказ по времени
#   обязан оставаться информативным (см. `_partial_progress`), а не только редким.
BASE_TIMEOUT_SECONDS = 180.0
PER_FILE_TIMEOUT_SECONDS = 150.0
MAX_TIMEOUT_SECONDS = 1200.0
_BATCH_DIAGNOSTIC_LIMIT = 4000

# ПОТОЛОК НА ОДИН УЗЕЛ = 120 с, тоже из замера (#474), а не с потолка. Общий бюджет выше не
# ограничивает ОДИН тест: 04.09 мерж #466 простоял 9+ минут в
# `test_concurrent_keys_start_exactly_one_executor_and_survive_request_return` (процесс жив,
# CPU 1%, состояние `S` — ждал события, переставшего наступать), съел бюджет всей партии и
# вернул `inconclusive` без имени, а мержи ВСЕГО проекта стояли всё это время.
# ЧИСЛО: `--durations=0` по восьми самым тяжёлым файлам (1118 тестов из 3214, 3353 фазы)
#   даёт самый долгий одиночный узел 14.90 с (`test_frontend.py::
#   test_dashboard_polling_equivalent_twelve_minutes_before_after`), дольше 5 с всего три
#   узла, дольше 10 с — один. 120 с это восьмикратный запас к измеренному максимуму, то есть
#   ложная краснота под нагрузкой требует восьмикратного замедления ОДНОГО теста; ошибаться
#   безопаснее в эту сторону, потому что ложный красный блокирует мержи всех проектов, а
#   проспавший потолок стоит одной партии.
# ПОЛЕЗНОСТЬ: пол бюджета партии = BASE + PER_FILE = 330 с, то есть потолок втрое меньше
#   самого маленького бюджета — один висяк физически не может выесть партию, а второй и
#   третий уже приносят FAILED С ИМЕНАМИ раньше, чем истечёт общий бюджет.
# МЕТОД = signal (SIGALRM), а не thread, и это не умолчание ради умолчания: `thread` печатает
#   стеки и убивает ВЕСЬ процесс через `os._exit`, то есть уносит ровно те построчные вердикты
#   `-vv`, по которым `_partial_progress` отличает «набор красный» от «мы не успели». `signal`
#   поднимает исключение в главном потоке: висящий узел получает свой `FAILED` с именем, а
#   остаток партии продолжает считаться. Главный поток здесь и нужный: `pytest-asyncio` крутит
#   корутину через `run_until_complete` на нём же, а синхронный Playwright ждёт драйвер на
#   прерываемом чтении. Узел, которому законно нужно больше, ставит свой
#   `@pytest.mark.timeout(N)` — маркер сильнее флага (`tests/test_native_history_import.py:199`).
PER_TEST_TIMEOUT_SECONDS = 120.0
PER_TEST_TIMEOUT_METHOD = "signal"


def budget_for(file_count: int) -> float:
    """Бюджет всего гейта под набор из `file_count` файлов."""
    return min(
        MAX_TIMEOUT_SECONDS,
        BASE_TIMEOUT_SECONDS + PER_FILE_TIMEOUT_SECONDS * max(0, file_count),
    )


ROUTE_TEST = "tests/test_routes_surface.py"
_ROUTE_EXACT = frozenset({
    "app/main.py",
    "tests/route_surface_snapshot.json",
    "tests/test_routes_surface.py",
})


def _normalize_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", "replace")
    return output


def _pytest_interpreter(worktree: str) -> str:
    """Select the project's interpreter before falling back to this process."""
    wt = Path(worktree).resolve()
    candidates = [wt / ".venv" / "bin" / "python"]
    common_dir = (
        _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if (wt / ".git").exists()
        else None
    )
    root = Path(common_dir.strip()).parent if common_dir else None
    if root:
        candidates.append(root / ".venv" / "bin" / "python")
    candidates.append(Path(sys.executable))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def _diagnostic_output(interpreter: str, output: str | bytes | None) -> str:
    marker = f"interpreter={interpreter}\n"
    trailer = marker.rstrip("\n")
    body = _normalize_output(output)
    body_limit = max(0, 4000 - len(marker) - len(trailer) - 1)
    return marker + body[-body_limit:] + "\n" + trailer


def _git(cwd: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def changed_paths(
    worktree: str,
    *,
    target_ref: str = "",
    target_sha: str = "",
) -> list[str] | None:
    wt = Path(worktree)
    if not wt.is_dir():
        return None
    inside = _git(wt, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.strip() != "true":
        return None
    base = target_sha.strip()
    if base and _git(wt, "rev-parse", "--verify", f"{base}^{{commit}}") is None:
        return None
    if not base:
        for ref in (target_ref, "main", "master"):
            if ref and _git(wt, "rev-parse", "--verify", ref) is not None:
                base = ref
                break
    if not base:
        return None
    named = _git(wt, "diff", "--name-only", f"{base}...HEAD")
    if named is None:
        return None
    paths = [line.strip().replace("\\", "/") for line in named.splitlines() if line.strip()]
    extra = _git(wt, "ls-files", "--others", "--exclude-standard")
    if extra:
        paths.extend(
            line.strip().replace("\\", "/")
            for line in extra.splitlines() if line.strip()
        )
    return sorted(set(paths))


def select_tests(changed: list[str], *, worktree: str) -> list[str]:
    wt = Path(worktree)
    selected: set[str] = set()
    for raw in changed:
        path = raw.replace("\\", "/").lstrip("./")
        if path.startswith("app/routes/") or path in _ROUTE_EXACT:
            if (wt / ROUTE_TEST).is_file():
                selected.add(ROUTE_TEST)
        if path.startswith("app/") and path.endswith(".py"):
            cand = f"tests/test_{Path(path).stem}.py"
            if (wt / cand).is_file():
                selected.add(cand)
        if path.startswith("tests/test_") and path.endswith(".py") and (wt / path).is_file():
            selected.add(path)
    return sorted(selected)


LIVE_PROBE_MARKER = "live_probe"
NO_TESTS_EXIT_CODE = 5  # pytest EXIT_NOTESTSCOLLECTED
USAGE_ERROR_EXIT_CODE = 4  # pytest EXIT_USAGEERROR


def pytest_argv(
    tests: list[str],
    *,
    interpreter: str | None = None,
    per_test_timeout: float | None = None,
) -> list[str]:
    # No -x / --exitfirst / --maxfail=1: one red must not hide the rest.
    # `-m "not live_probe"` снимает с гейта пробы, тратящие настоящий ход провайдера: они
    # краснеют от квоты и недоступности, а не от диффа, и блокируют чужие мержи (18.08:
    # codex-проба стояла красной по rate_limit в самом main). Умолчание безопасное — новая
    # проба БЕЗ маркера гоняется гейтом и падает громко; исчезнуть незаметно она не может.
    #
    # `-vv` рядом с `-q` — не косметика, а единственный источник, по которому «набор
    # красный» отличимо от «мы не успели»: pytest печатает вердикт КАЖДОГО теста отдельной
    # строкой сразу по его окончании и успевает это сделать до убийства по таймауту, тогда
    # как `-q` даёт безымянные точки (а при убийстве в фазе сбора — пустой выход вовсе).
    # Замер #336: убитый прогон отдал `test_b_red FAILED` и имя висящего теста, тогда как
    # `-q` на том же прогоне — 0 символов.
    # Арифметика флагов проверена прогоном и неочевидна: `-q` это −1, `-vv` это +2, сумма
    # +1 — тот же режим, что голый `-v`. Писать `-q -v` НЕЛЬЗЯ: сумма 0, снова точки.
    #
    # `--timeout` / `--timeout-method` — потолок на ОДИН узел (см. PER_TEST_TIMEOUT_SECONDS).
    # Флаг стоит только здесь, а не в `[tool.pytest.ini_options]`: ручной прогон и живые пробы
    # ограничивать нечем и незачем, потолок нужен ровно гейту, который держит чужие мержи.
    python = interpreter or sys.executable
    ceiling = PER_TEST_TIMEOUT_SECONDS if per_test_timeout is None else per_test_timeout
    return [
        python, "-m", "pytest", "-q", "-vv",
        f"--timeout={ceiling:g}",
        f"--timeout-method={PER_TEST_TIMEOUT_METHOD}",
        "-m", f"not {LIVE_PROBE_MARKER}",
        *tests,
    ]


# `tests/test_x.py::test_name[param] PASSED [ 12%]`.
# Строка обязана НАЧИНАТЬСЯ с nodeid: тогда строки итоговой сводки (`FAILED tests/x.py::y - ...`)
# сюда не попадают и провал не считается дважды.
# Вердикт берётся ПОСЛЕДНИЙ на строке, а не первый: nodeid параметризованного теста содержит
# произвольный текст, в том числе пробелы и сами эти слова. Замер #336 — на строке
# `tests/test_a.py::t2[a b PASSED c] FAILED [2%]` нежадный разбор возвращал PASSED, то есть
# КРАСНЫЙ тест читался как зелёный; это ровно то направление ошибки, которого быть не должно.
# Требование пробела перед вердиктом отсекает `nodeid[FAILED]` у теста, который ещё идёт.
_NODEID_RE = re.compile(r"^\S+\.py::\S")
_VERDICT_RE = re.compile(r"\s(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)(?=\s|$)")


def _partial_progress(output: str, tests: list[str]) -> dict:
    """Что pytest успел сообщить до убийства по таймауту.

    Обе неудачи приходят одним и тем же `TimeoutExpired`, и без разбора этого выхода они
    неразличимы. Замер #336 на живых операциях: у #248 в убитом выходе стояли девять `F`
    (настоящая краснота), у #329 — сплошные точки (набор зелёный, просто не доехал); гейт
    доложил обоим одно и то же «inconclusive».
    """
    failed: list[str] = []
    passed = 0
    seen_files: set[str] = set()
    stopped_in = ""
    for raw in output.splitlines():
        line = raw.rstrip()
        if not _NODEID_RE.match(line):
            continue
        verdicts = list(_VERDICT_RE.finditer(line))
        if not verdicts:
            # Имя напечатано, вердикта ещё нет — на этом тесте нас и прервали.
            stopped_in = line.strip()
            seen_files.add(stopped_in.split("::", 1)[0])
            continue
        last = verdicts[-1]
        nodeid = line[:last.start()].strip()
        seen_files.add(nodeid.split("::", 1)[0])
        if last.group("verdict") in {"FAILED", "ERROR"}:
            failed.append(nodeid)
        elif last.group("verdict") == "PASSED":
            passed += 1
        stopped_in = ""
    return {
        "failed_tests": failed,
        "passed_count": passed,
        "stopped_in": stopped_in,
        "unreached": [test for test in tests if test not in seen_files],
    }


def describe_progress(result: dict) -> str:
    """Одна строка для человека: что проверено, что нет. Пусто — сказать нечего."""
    if "passed_count" not in result:
        return ""
    parts = [f"verified green: {result['passed_count']}"]
    if result.get("failed_tests"):
        shown = ", ".join(result["failed_tests"][:5])
        extra = len(result["failed_tests"]) - 5
        parts.append(f"RED: {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
    if result.get("stopped_in"):
        parts.append(f"ran out of budget inside {result['stopped_in']}")
    if result.get("unreached"):
        parts.append(f"never reached: {', '.join(result['unreached'])}")
    return "; ".join(parts)


def run_pytest(worktree: str, tests: list[str], *, timeout: float | None = None) -> dict:
    budget = budget_for(len(tests)) if timeout is None else timeout
    interpreter = _pytest_interpreter(worktree)
    argv = pytest_argv(tests, interpreter=interpreter)
    env = os.environ.copy()
    root = str(Path(worktree).resolve())
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not prior else f"{root}{os.pathsep}{prior}"
    try:
        proc = subprocess.run(
            argv,
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": INCONCLUSIVE, "reason": "not_found",
            "exit_code": None, "output": _diagnostic_output(interpreter, argv[0]),
            "tests": tests,
        }
    except subprocess.TimeoutExpired as exc:
        out = _normalize_output(exc.stdout) + _normalize_output(exc.stderr)
        progress = _partial_progress(out, tests)
        # Красный тест красен независимо от того, доехал ли остаток набора: мерж такого
        # состояния посадил бы красноту в main. Поэтому увиденный провал — это FAILED
        # (окончательно, повтор не поможет), и только отсутствие провалов — INCONCLUSIVE.
        if progress["failed_tests"]:
            return {
                "status": FAILED, "reason": "timeout_with_failures",
                "exit_code": None, "output": _diagnostic_output(interpreter, out),
                "tests": tests,
                **progress,
            }
        return {
            "status": INCONCLUSIVE, "reason": "timeout",
            "exit_code": None, "output": _diagnostic_output(interpreter, out),
            "tests": tests,
            **progress,
        }
    except OSError as exc:
        return {
            "status": INCONCLUSIVE, "reason": "os_error",
            "exit_code": None, "output": _diagnostic_output(interpreter, str(exc)),
            "tests": tests,
        }
    output = _normalize_output(proc.stdout) + _normalize_output(proc.stderr)
    diagnostic = _diagnostic_output(interpreter, output)
    if proc.returncode == 0:
        return {
            "status": PASSED, "reason": "", "exit_code": 0,
            "output": diagnostic, "tests": tests,
        }
    if proc.returncode == NO_TESTS_EXIT_CODE:
        # Файл выбран, но после `-m "not live_probe"` в нём не осталось ни одного теста —
        # то есть весь файл состоит из живых проб. Это не провал, но и не «проверено»:
        # FAILED врал бы про красноту, PASSED — про пустой прогон.
        return {
            "status": SKIPPED, "reason": "no_tests_after_deselect",
            "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
        }
    if re.search(r"No module named ['\"]?pytest['\"]?", output):
        return {
            "status": INCONCLUSIVE, "reason": "pytest_unavailable",
            "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
        }
    if (
        proc.returncode == USAGE_ERROR_EXIT_CODE
        and "unrecognized arguments" in output
        and "--timeout" in output
    ):
        # Интерпретатор без `pytest-timeout` отвергает НАШ флаг ещё до сбора: pytest выходит
        # с usage error, тесты не запускались вовсе. Общая ветка ниже объявила бы это
        # `exit_nonzero`, то есть «набор красный», и заблокировала мержи всех проектов на
        # отсутствующем плагине.
        return {
            "status": INCONCLUSIVE, "reason": "pytest_timeout_unavailable",
            "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
        }
    return {
        "status": FAILED, "reason": "exit_nonzero",
        "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
    }


def _compact_output(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    marker = "\n…\n"
    if limit <= len(marker):
        return text[:limit]
    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def _ordered_batches(tests: list[str]) -> list[list[str]]:
    if len(tests) <= MAX_TEST_FILES:
        return [tests]
    batch_count = (len(tests) + MAX_BATCH_TESTS - 1) // MAX_BATCH_TESTS
    base_size, remainder = divmod(len(tests), batch_count)
    batches = []
    cursor = 0
    for index in range(batch_count):
        size = base_size + (index < remainder)
        batches.append(tests[cursor:cursor + size])
        cursor += size
    return batches


def _batch_result(worktree: str, batches: list[list[str]]) -> dict:
    """Run every mapped batch under one deadline and combine its evidence."""
    deadline = time.monotonic() + budget_for(sum(len(batch) for batch in batches))
    batches_left = len(batches)
    results: list[dict] = []
    for batch in batches:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = {
                "status": INCONCLUSIVE,
                "reason": "timeout",
                "exit_code": None,
                "output": "total timeout budget exhausted before this batch",
                "tests": batch,
            }
        else:
            result = run_pytest(worktree, batch, timeout=remaining / batches_left)
        batches_left -= 1
        results.append(result)

    failed = [result for result in results if result["status"] == FAILED]
    inconclusive = [
        result for result in results if result["status"] == INCONCLUSIVE
    ]
    if failed:
        status = FAILED
        reason = "batch_failed"
        exit_code = failed[0].get("exit_code")
    elif inconclusive:
        status = INCONCLUSIVE
        reason = "batch_inconclusive"
        exit_code = None
    else:
        status = PASSED
        reason = ""
        exit_code = 0

    sections = []
    for index, result in enumerate(results, start=1):
        lines = [
            f"batch {index}/{len(results)} "
            f"status={result['status']} tests={','.join(result['tests'])}"
        ]
        if result.get("reason"):
            lines.append(f"reason={result['reason']}")
        section_limit = max(
            1,
            (_BATCH_DIAGNOSTIC_LIMIT - max(0, len(results) - 1)) // len(results),
        )
        section = "\n".join(lines)
        output = result.get("output") or ""
        budget = section_limit - len(section) - 1
        if output and budget > 0:
            section = f"{section}\n{_compact_output(output, budget)}"
        sections.append(section[:section_limit])
    return {
        "status": status,
        "reason": reason,
        "exit_code": exit_code,
        "output": "\n".join(sections),
        "tests": list(sum(batches, [])),
        "failed_tests": [
            node for result in results for node in result.get("failed_tests", [])
        ],
        "passed_count": sum(result.get("passed_count", 0) for result in results),
        "stopped_in": next(
            (result["stopped_in"] for result in results if result.get("stopped_in")), ""
        ),
        "unreached": [
            test for result in results for test in result.get("unreached", [])
        ],
    }


def evaluate_test_gate(
    worktree: str,
    *,
    target_ref: str = "",
    target_sha: str = "",
) -> dict:
    if target_ref or target_sha:
        changed = changed_paths(
            worktree, target_ref=target_ref, target_sha=target_sha,
        )
    else:
        changed = changed_paths(worktree)
    evidence = {
        "target_ref": target_ref,
        "target_sha": target_sha,
    }
    if changed is None:
        return {
            "status": SKIPPED, "reason": "no_diff",
            "exit_code": None, "output": "", "tests": [], "mapped_files": [],
            **evidence,
        }
    tests = select_tests(changed, worktree=worktree)
    if not tests:
        return {
            "status": SKIPPED, "reason": "no_mapped_tests",
            "exit_code": None, "output": "", "tests": [], "mapped_files": [],
            **evidence,
        }
    if len(tests) > MAX_TEST_FILES:
        batches = _ordered_batches(tests)
        result = _batch_result(worktree, batches)
    else:
        result = run_pytest(worktree, tests)
    return {**result, "mapped_files": tests, **evidence}
