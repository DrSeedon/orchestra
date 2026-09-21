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
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import ast
from contextlib import contextmanager
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
# The rollback probe is deliberately bounded independently of the existing mapped-test
# budget: it is evidence for the changed tests, not a second full merge suite.  Production
# measurements on V-606/V-602/V-603 took 16.89/14.03/16.60 s of pytest time, so 25 s leaves
# headroom for startup and load; an unfinished probe is reported as INCONCLUSIVE and does not
# masquerade as proof.
MUTATION_MAX_TIMEOUT_SECONDS = 25.0


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
            timeout=60,
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
    # `--no-renames` здесь и быстрее, и ТОЧНЕЕ. Точнее — потому что нам нужен список
    # затронутых путей: при переименовании тесты и бюджет должны видеть обе стороны,
    # старый путь и новый, а не одну строку R100. Быстрее — потому что детектор
    # переименований на бинарных ассетах стоит секунды: замер 11.09.2026 на ветке
    # task-56/voice-astra (2402 файла, ~1900 изображений, 60 переименований) дал
    # 37.0 с против 0.026 с — в 1400 раз. Прежние 37 с не укладывались в таймаут
    # `_git`, тот отдавал None, и merge_worker падал с «cannot derive target-relative
    # merge paths», отправляя чинить несуществующую поломку оракула.
    named = _git(wt, "diff", "--no-renames", "--name-only", f"{base}...HEAD")
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
# Браузерные тесты сняты с БЛОКИРУЮЩЕГО набора, но не удалены и не выключены: они гоняются
# в CI отдельной джобой и вручную (`uv run pytest -m browser tests/`). Решение владельца
# 07.09 «выносим их из гейта, не убиваем» на числах: 169 браузерных узлов из 4091, а два
# мержа подряд встали с `TEST_GATE_INCONCLUSIVE` — бюджет кончался внутри `test_frontend.py`
# при НУЛЕ красных тестов, то есть гейт блокировал чужую работу зависанием, а не находкой.
BROWSER_MARKER = "browser"
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
        "-m", f"not {LIVE_PROBE_MARKER} and not {BROWSER_MARKER}",
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


def run_pytest(
    worktree: str,
    tests: list[str],
    *,
    timeout: float | None = None,
    interpreter: str | None = None,
) -> dict:
    budget = budget_for(len(tests)) if timeout is None else timeout
    interpreter = interpreter or _pytest_interpreter(worktree)
    argv = pytest_argv(tests, interpreter=interpreter)
    env = os.environ.copy()
    # Merge-gate runs beside the live Orchestra process.  Its state selectors must never
    # point pytest at the service database/task repository (the latter once consumed a
    # real task from a test fixture).  Remove them before pytest imports ``app`` and give
    # every invocation disposable state of its own.  Quota and systemd variables are also
    # live-process inputs; ordinary tests have their own deterministic fixtures.
    for name in (
        "ORCHESTRA_DB_PATH", "ORCHESTRA_TASK_REPOSITORY", "ORCHESTRA_TASK_PREFIX",
        "NOTIFY_SOCKET", "SYSTEMD_EXEC_PID", "LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES",
        "QUOTA_GATED_LANES", "QUOTA_CURVED_LANES", "QUOTA_HARD_STOP_PCT",
        "QUOTA_LANE_HARD_STOP_PCT", "QUOTA_TOLERANCE_START_PP",
        "QUOTA_TOLERANCE_END_PP", "QUOTA_CURVE_EXPONENT",
    ):
        env.pop(name, None)
    root = str(Path(worktree).resolve())
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not prior else f"{root}{os.pathsep}{prior}"
    try:
        with tempfile.TemporaryDirectory(prefix="orchestra-merge-gate-") as isolated:
            env["ORCHESTRA_DB_PATH"] = str(Path(isolated) / "orchestra.db")
            env["ORCHESTRA_TASK_REPOSITORY"] = str(Path(isolated) / "tasks")
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


_TEST_PATH_PREFIX = "tests/"
_SOURCE_PREFIXES = ("app/", "scripts/")
_NON_SOURCE_PREFIXES = (
    ".orchestra/", ".github/", "docs/", "prompts/", "prompt/",
)
_NON_SOURCE_SUFFIXES = {
    ".md", ".rst", ".txt", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json",
}


def changed_test_paths(changed: list[str]) -> list[str]:
    """Return test modules supplied by the worker, not merely source-mapped tests."""
    return sorted({
        path.replace("\\", "/").lstrip("./")
        for path in changed
        if path.replace("\\", "/").lstrip("./").startswith(_TEST_PATH_PREFIX)
        and path.replace("\\", "/").lstrip("./").endswith(".py")
    })


def changed_source_paths(changed: list[str]) -> list[str]:
    """Classify executable changes while leaving docs, config and prompts out."""
    sources: set[str] = set()
    for raw in changed:
        path = raw.replace("\\", "/").lstrip("./")
        if not path or path.startswith(_TEST_PATH_PREFIX) or path.startswith(_NON_SOURCE_PREFIXES):
            continue
        suffix = Path(path).suffix.lower()
        if suffix in _NON_SOURCE_SUFFIXES:
            continue
        if path.startswith(_SOURCE_PREFIXES) or suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html"}:
            sources.add(path)
    return sorted(sources)


def _changed_added_lines(worktree: str, target_commit: str, path: str) -> set[int] | None:
    """Return worker-side lines touched by a committed diff, or None for untracked files."""
    diff = _git(
        Path(worktree), "diff", "--no-renames", "--unified=0",
        f"{target_commit}...HEAD", "--", path,
    )
    if diff is None:
        return None
    lines: set[int] = set()
    current = 0
    for raw in diff.splitlines():
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if not match:
                continue
            current = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            lines.update(range(current, current + count))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            current += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        elif current:
            current += 1
    return lines


def _test_nodes_for_file(path: str, source: str, changed_lines: set[int]) -> list[str] | None:
    """Map changed lines to pytest node IDs; None requests a safe file fallback."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return None
    nodes: list[tuple[str, int, int]] = []

    def visit(body: list[ast.stmt], parents: tuple[str, ...] = ()) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, parents + (node.name,))
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                visit(getattr(node, "body", []), parents)
                continue
            end = getattr(node, "end_lineno", node.lineno)
            starts = [node.lineno]
            starts.extend(dec.lineno for dec in node.decorator_list)
            start = min(starts)
            identity = "::".join((path, *parents, node.name))
            nodes.append((identity, start, end))

    visit(tree.body)
    if not nodes:
        return None
    selected = [identity for identity, start, end in nodes
                if any(start <= line <= end for line in changed_lines)]
    covered = {
        line for _identity, start, end in nodes
        for line in changed_lines if start <= line <= end
    }
    # A changed import/helper/fixture/class setup is semantically shared by tests. Running
    # one guessed node would claim proof for siblings, so keep the whole file in that case.
    if covered != changed_lines:
        return None
    return sorted(set(selected)) or None


def changed_test_nodes(
    worktree: str, target_commit: str, tests: list[str],
) -> tuple[list[str], list[str]]:
    """Select changed test functions, with file fallback for ambiguous Python diffs."""
    selected: list[str] = []
    fallback: list[str] = []
    for path in tests:
        lines = _changed_added_lines(worktree, target_commit, path)
        source_path = Path(worktree) / path
        if lines is None or not source_path.is_file():
            fallback.append(path)
            continue
        nodes = _test_nodes_for_file(path, source_path.read_text(encoding="utf-8"), lines)
        if nodes is None:
            fallback.append(path)
        else:
            selected.extend(nodes)
    return sorted(set(selected)), sorted(set(fallback))


def _target_commit(worktree: str, target_ref: str, target_sha: str) -> str | None:
    ref = target_sha.strip() or target_ref.strip() or "main"
    resolved = _git(Path(worktree), "rev-parse", "--verify", f"{ref}^{{commit}}")
    return resolved.strip() if resolved else None


def _copy_test_into_tree(worker: Path, target: Path, relative: str) -> None:
    source = worker / relative
    destination = target / relative
    if not source.exists() and not source.is_symlink():
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


@contextmanager
def _mutation_tree(worker: str, target_commit: str, tests: list[str]):
    """Yield a disposable target checkout overlaid with the worker's changed tests."""
    temporary = tempfile.TemporaryDirectory(prefix="orchestra-merge-mutation-")
    root = Path(temporary.name)
    try:
        archive = root / "target.tar"
        with archive.open("wb") as stream:
            proc = subprocess.run(
                ["git", "archive", "--format=tar", target_commit],
                cwd=worker, stdout=stream, stderr=subprocess.PIPE,
                text=False, timeout=30, check=False,
            )
        if proc.returncode != 0:
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            raise RuntimeError(f"git archive target failed: {detail}")
        tree = root / "tree"
        tree.mkdir()
        with tarfile.open(archive, "r:") as tar:
            tar.extractall(tree, filter="data")
        for path in tests:
            _copy_test_into_tree(Path(worker), tree, path)
        yield tree
    finally:
        temporary.cleanup()


def evaluate_mutation_gate(
    worktree: str,
    changed: list[str],
    *,
    target_ref: str = "",
    target_sha: str = "",
    interpreter: str | None = None,
) -> dict:
    """Run worker tests against target sources in an isolated disposable tree."""
    tests = changed_test_paths(changed)
    sources = changed_source_paths(changed)
    result = {
        "status": SKIPPED,
        "reason": "no_changed_tests" if not tests else "no_changed_sources",
        "exit_code": None,
        "output": "",
        "tests": tests,
        "changed_tests": tests,
        "changed_sources": sources,
        "interpreter": interpreter or _pytest_interpreter(worktree),
        "selected_nodes": [],
        "fallback_files": [],
    }
    if not tests or not sources:
        return result
    commit = _target_commit(worktree, target_ref, target_sha)
    if not commit:
        return {
            **result,
            "status": INCONCLUSIVE,
            "reason": "target_unavailable",
            "output": "cannot resolve target commit for mutation tree",
        }
    selected_nodes, fallback_files = changed_test_nodes(worktree, commit, tests)
    selected_tests = selected_nodes + fallback_files
    if not selected_tests:
        return {
            **result,
            "status": INCONCLUSIVE,
            "reason": "changed_test_nodes_unavailable",
            "output": "changed test files contain no selectable test nodes",
            "selected_nodes": [],
            "fallback_files": [],
        }
    try:
        with _mutation_tree(worktree, commit, tests) as tree:
            second = run_pytest(
                str(tree), selected_tests,
                timeout=MUTATION_MAX_TIMEOUT_SECONDS,
                interpreter=result["interpreter"],
            )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {
            **result,
            "status": INCONCLUSIVE,
            "reason": "tree_failed",
            "output": str(exc),
        }
    mutation = {
        **second,
        "changed_tests": tests,
        "changed_sources": sources,
        "target_sha": commit,
        "interpreter": result["interpreter"],
        "selected_nodes": selected_nodes,
        "fallback_files": fallback_files,
    }
    if second["status"] == FAILED:
        # The rollback is expected to break a regression test: that is the proof that
        # the worker test actually watches the source change.
        return {**mutation, "status": PASSED, "reason": "guarded_source_change"}
    if second["status"] in {INCONCLUSIVE, SKIPPED}:
        return mutation
    # A passing target-source run means the changed tests did not observe the source delta.
    return {
        **mutation,
        "status": FAILED,
        "reason": "tests_not_guarding_source",
        "output": (
            (second.get("output") or "")
            + "\nworker tests also pass with target sources; no regression is guarded"
        ),
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
            "changed_tests": [], "changed_sources": [],
            "interpreter": _pytest_interpreter(worktree),
            "mutation_gate": {
                "status": SKIPPED, "reason": "no_diff", "tests": [],
                "changed_tests": [], "changed_sources": [],
                "interpreter": _pytest_interpreter(worktree),
            },
            **evidence,
        }
    tests = select_tests(changed, worktree=worktree)
    if not tests:
        changed_tests = changed_test_paths(changed)
        changed_sources = changed_source_paths(changed)
        interpreter = _pytest_interpreter(worktree)
        return {
            "status": SKIPPED, "reason": "no_mapped_tests",
            "exit_code": None, "output": "", "tests": [], "mapped_files": [],
            "changed_tests": changed_tests, "changed_sources": changed_sources,
            "interpreter": interpreter,
            "mutation_gate": {
                "status": SKIPPED,
                "reason": "no_mapped_tests",
                "exit_code": None,
                "output": "",
                "tests": changed_tests,
                "changed_tests": changed_tests,
                "changed_sources": changed_sources,
                "interpreter": interpreter,
            },
            **evidence,
        }
    if len(tests) > MAX_TEST_FILES:
        batches = _ordered_batches(tests)
        result = _batch_result(worktree, batches)
    else:
        result = run_pytest(worktree, tests)
    result = {
        **result,
        "mapped_files": tests,
        "changed_tests": changed_test_paths(changed),
        "changed_sources": changed_source_paths(changed),
        "interpreter": _pytest_interpreter(worktree),
        **evidence,
    }
    if result["status"] == PASSED:
        mutation = evaluate_mutation_gate(
            worktree,
            changed,
            target_ref=target_ref,
            target_sha=target_sha,
            interpreter=result["interpreter"],
        )
    else:
        mutation = {
            "status": SKIPPED,
            "reason": "first_gate_not_passed",
            "exit_code": None,
            "output": "",
            "tests": result["changed_tests"],
            "changed_tests": result["changed_tests"],
            "changed_sources": result["changed_sources"],
            "interpreter": result["interpreter"],
        }
    result["mutation_gate"] = mutation
    if mutation["status"] == FAILED:
        result["status"] = FAILED
        result["reason"] = mutation.get("reason") or "mutation_failed"
    return result
