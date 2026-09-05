# #515 — почему CI красный и что именно в нём падает

## Вопрос (Step 0)

- **Контекст:** `.github/workflows/ci.yml`, последний шаг `uv run pytest -q --timeout=30`; за всю
  историю workflow успешен 1 прогон из 258.
- **Проверяемое изменение:** разбиение прогона на несколько процессов вместо одного.
- **База сравнения:** прогон `33893200040` — `##[error]Process completed with exit code 137` на 81%,
  60 `F` напечатано до обрыва, итоговой сводки нет вовсе.
- **Измеримый исход:** (1) доходит ли прогон до терминальной сводки; (2) пиковая память группы
  против лимита раннера; (3) полный состав падений по node id; (4) совпадает ли состав собранных
  тестов до и после разбиения.

## Гипотезы и их фальсификаторы (Step 1)

| # | Гипотеза | Что её опровергает | Итог |
|---|---|---|---|
| H1 | `RC=137` — накопление памяти за прогон, а не один тяжёлый тест → лечится делением на процессы, без правки тестов | шард всё равно упирается в память, или суммарный пик шардов ≈ пику одиночного прогона | **ПОДТВЕРЖДЕНА** — пик шарда 233–291 МБ при лимите 16 ГБ |
| H2 | Один конкретный тест жрёт память, и после его починки одиночный прогон пройдёт | пик распределён ровно по шардам, ни один шард не выделяется | **ОТВЕРГНУТА** — разброс пиков 233–291 МБ, то есть 1.25×, выброса нет |
| H3 | Состав падений на CI и на VPS одинаков, окружение ни при чём | множества падений расходятся | **ОТВЕРГНУТА** — 27 падений из 57 существуют только на раннере |
| H4 | Разбиение по файлам теряет тесты (часть перестаёт собираться) | множества node id до и после совпадают | **ОТВЕРГНУТА** — 3949 против 3949 |

## Findings

### F1. `RC=137` — накопление за прогон; разбиение на 6 процессов снимает его с запасом 55–68× · CONFIRMED (прямое измерение, тир 1)

Живой прогон на ветке: <https://github.com/DrSeedon/orchestra/actions/runs/33956684131>.
Все 6 шардов дошли до терминальной сводки, `RC=137` нет ни в одном.

| шард | CI: пик RSS, КБ | CI: время | локально: пик RSS, КБ | локально: время |
|---|---|---|---|---|
| 0 | 243 008 | 65.0 с | 234 848 | 359.1 с |
| 1 | 250 820 | 53.3 с | 240 972 | 184.7 с |
| 2 | 244 480 | 52.6 с | 233 352 | 158.9 с |
| 3 | 233 800 | 45.2 с | 220 560 | 162.4 с |
| 4 | 291 484 | 105.6 с | 291 440 | 313.7 с |
| 5 | 261 088 | 117.0 с | 242 160 | 283.7 с |

Числа сняты `/usr/bin/time -v` внутри самого шага (`Maximum resident set size (kbytes)`), а не
оценкой. Лимит `ubuntu-latest` для публичного репозитория — **4 CPU / 16 ГБ**
(`.orchestra/tasks/515/raw/github-hosted-runners.html`, таблица «Virtual machine / container»;
для приватных — 2 CPU / 8 ГБ, наш репозиторий `PUBLIC` по `gh repo view --json visibility`).
Запас худшего шарда: 16 ГБ / 291 484 КБ = **57×**; по всему диапазону 55–68×.

H2 отвергнута прямо этой таблицей: если бы память жрал один тест, его шард выделялся бы на порядок.
Пики совпадают между CI и VPS с точностью до 5% при полностью разном железе — значит потолок
задаёт не машина, а объём накопленного за прогон состояния.

### F2. Разбиение не теряет тестов; ровно 2 node id несравнимы по построению · CONFIRMED (прямое измерение)

Базовый `--collect-only` до правки — 3949 node id
(`raw/nodeids-before.txt`, `manifest.json: selected_nodes 3949`).
Объединение `--collect-only` по шести шардам новой раскладки — 3949
(`raw/nodeids-after-shards.txt`). Симметрическая разность — **2 node id**:

```
tests/test_turn_usage.py::test_cached_quota_state_returns_null_without_fresh_data[None-1788589361.5905912]
tests/test_turn_usage.py::test_cached_quota_state_returns_null_without_fresh_data[None-1788598982.427632]
```

Причина — `tests/test_turn_usage.py:104-106`: `time.time()` вычисляется прямо в
`@pytest.mark.parametrize`, поэтому node id содержит момент СБОРА и меняется при каждом запуске.
То есть по этому тесту точное сравнение множеств невозможно в принципе, а не из-за шардирования.
Раскладка проверена отдельно: 42/41/41/41/41/41 файлов, объединение равно всем 247 файлам
`git ls-files 'tests/test_*.py'`, дублей 0.

Второй, независимый признак сохранности состава — арифметика сводок. CI:
`57 failed + 3807 passed + 82 skipped + 3 xfailed = 3949`. Локально:
`33 + 3829 + 84 + 3 = 3949`. Оба равны baseline; `deselected 4` — это `live_probe`,
снятые `addopts = ["-m", "not live_probe"]` (`pyproject.toml:68`).

### F3. Полный состав падений: 57 на CI, 33 локально, 30 общих · CONFIRMED (прямое измерение)

Сырьё: `raw/ci-33956684131/` (6 логов джобов целиком, `failed-ci.txt`,
`failed-ci-with-reason.txt`) и `raw/local-shards/` (та же раскладка на VPS,
`.orchestra/tasks/515/run_local_shards.sh`). Сводная таблица с дословными причинами —
`.orchestra/tasks/515/failures.md`, машинная разметка — `raw/classification.json`.

- **30** падают И на CI, И на VPS → настоящие.
- **27** только на CI → дыра окружения раннера.
- **3** только на VPS → `test_compact_gate_438.py` ×2 и
  `test_usage_readiness.py::test_anthropic_refresh_is_target_isolated_and_singleflight`.
  На приёмку CI не влияют, но это тот же класс «тест читает живое состояние».

Отдельно: `tests/test_harness_tools.py::test_t1_grep_perf_repo_tree` падал в прогоне прошлой сессии
(`grep over repo took 26.4s (>20s)`) и прошёл в этом — перф-ассерт по загрузке машины, флак.

### F4. Классификация 57 падений по причине · CONFIRMED для A1–A4, B1–B2; UNCERTAIN для D

| группа | шт | падают везде | причина | где чинится |
|---|---|---|---|---|
| A1 | 8 | 8 | `codex_review` с #488 требует git-репозиторий и файл project-context | `tests/` |
| A2 | 9 | 9 | порог считается по параболе с `b757e834`, тест считает по диагонали | `tests/` |
| A3 | 1 | 1 | сигнатура `_shutdown_runtime` сменилась в `748e81e3` (#395) | `tests/` |
| A4 | 1 | 0 | тест прибит к пути `/home/kesha/orchestra` | `tests/` |
| B1 | 4 | 3 | нет `main` и родительских коммитов: `actions/checkout@v4` берёт один коммит | `.github/workflows/` + один случай глубже, см. F5 |
| B2 | 1 | 0 | на раннере нет `ffprobe` | `.github/workflows/` |
| C | 14 | 0 | нужен проприетарный Codex CLI и живой `auth.json` | **развилка, см. F6** |
| D | 19 | 9 | диагноз в `app/` не поставлен | к оркестратору |

**A1 (8) — доказательство.** `70547310` (#488) ввёл `_load_review_project_context`
(`app/mcp_stdio.py:3717`), который через `_review_repository_root` (`:3617`) зовёт
`git rev-parse --git-common-dir` в переданном `cwd` и падает `ValueError`, если это не репозиторий.
Единственный файл, где заглушка появилась, — `tests/test_mcp_codex_review.py:27-38`
(autouse-фикстура `valid_project_context_owner`). `tests/test_mcp_quota_gate.py` (7 падений) и
`tests/test_codex_bin_resolution.py::test_resolved_binary_reaches_the_shell_command` подают
`tmp_path`, то есть каталог вне git, и получают
`ValueError: fatal: not a git repository (or any of the parent directories): .git`
(`cwd = '/tmp/pytest-of-runner/pytest-0/test_resolved_binary_reaches_t0'` — дословно из лога).
Это ровно правило `CLAUDE.md` «тест утверждает свойство окружения, которого сам не создал».

**A2 (9) — доказательство.** `tests/test_quota_map_api.py:167-171` требует, чтобы `payload["rule"]`
равнялся словарю ровно из трёх ключей; `app/routes/system.py:1822-1828` с коммита `b757e834`
(«порог Sol по параболе») отдаёт ещё `curve_exponent` и `curved_lanes`. Отсюда же
`assert 7.5 == 5.5 ± 5.5e-06` и `assert 'open' == 'opens_in'`: вспомогательный `_line_at`
(`tests/test_quota_map_api.py:151-157`) считает норму линейно, а `line_limit`
(`app/quota_gate.py:118-124`) для полос из `CURVED_LANES` — как `progress ** (1/CURVE_EXPONENT)`.
Замысел теста («панель не хардкодит числа правила — иначе она разойдётся с гейтом молча»)
при починке сохраняется: в ожидание добавляются те же константы из `app/quota_gate.py`,
а не подгоняется число.

**A4 (1) — доказательство.** `tests/test_codex_bin_resolution.py:71,76` монкипатчит
`SCOPE = "/home/kesha/orchestra"` и возвращает `worktree_path` с тем же путём. На раннере
такого каталога нет → `ValueError: fatal: cannot change to '/home/kesha/orchestra'`. Тест
проверяет текст ошибки про `CODEX_BIN`, а не конкретную машину, — путь должен быть `tmp_path`.

**B2 (1) — доказательство.** `tests/test_voice_input.py::test_ffprobe_reads_actual_audio_duration`
→ `FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe'`. На `ubuntu-latest` ffmpeg
не предустановлен; тест по названию обязан звать НАСТОЯЩИЙ `ffprobe`, поэтому честная починка —
поставить пакет в workflow, а не подменять бинарь.

### F5. Три теста #430 заморожены на коммитах, которых в этом репозитории НЕТ · CONFIRMED

`tests/test_orchestra_layout_430.py:374` сверяет
`git rev-parse <location_runtime_commit>^` с `before_ref` из `.orchestra/tasks/430/move-receipt.json`.
Оба SHA не существуют: `git cat-file -t 1f80bb50b81db380fb5f51a0894209538553087f` и
`git cat-file -t 848c8d5146909bd7d70aca9271effad5cc3a3a37` отвечают `ABSENT` при 5792 коммитах в
`--all`. Квитанция заморозила SHA ВЕТКИ воркера, а `merge_worker` мержит squash — эти коммиты в
`main` не попадали никогда. Отсюда `assert 128 == 0` и `fatal: not a tree object`.
Тест такого вида не может позеленеть ни на одной машине, и на CI это не «shallow checkout»
(`fetch-depth` его не воскресит). Починка меняет предмет проверки — решение не моё.

### F6. Развилка: 14 тестов требуют проприетарного Codex CLI, которого на раннере быть не может · CONFIRMED по факту, решение за владельцем

`tests/test_mcp_codex_review.py` (7), `tests/test_codex_review_sandbox.py` (4),
`tests/test_fd_adopt.py` (2), `tests/test_mcp_config_isolation.py::test_t4_...` (1).
Дословные причины с раннера: `codex не найден: ни CODEX_BIN в окружении, ни codex в PATH`,
`FileNotFoundError: configured executable was not found`,
`AssertionError: в изолированном CODEX_HOME нет auth.json — Codex не авторизуется`,
и как следствие `KeyError: 'config'` (тест читает `captured["config"]`, а до записи дело не дошло).
Локально все 14 зелёные — на VPS Codex установлен и авторизован.

Три ветки, и они не равноценны:

1. **Сделать тесты герметичными** — стаб-исполняемый файл в `tmp_path` + `CODEX_BIN` на него.
   Замысел 13 из 14 тестов — проверить, КАК мы собираем команду, а не что Codex установлен;
   для них стаб усиливает проверку (сегодня они молча зависят от машины). Цена: правка в `tests/`.
2. **Пометить `live_probe`** — механизм в проекте уже есть и уже исключает 3 пробы
   (`pyproject.toml:68,74`), новая проба обязана попасть в `test_live_probe_inventory_is_explicit`.
   Честно ровно для одного теста — `test_t4_subscription_auth_is_reachable_from_isolated_home`:
   он по смыслу утверждает, что живая подписка достижима, и герметичным не бывает.
   Для остальных 13 это было бы вычёркиванием из прогона.
3. **Ставить Codex CLI на раннер** — отклонено: бинарь проприетарный, а `auth.json` — живые креды
   владельца, которым в публичном CI не место.

Рекомендация: 13 → ветка 1, `test_t4_...` → ветка 2. Это архитектурное решение, выношу его,
а не исполняю.

### F7. `tests/test_grok_usage_frontend.py` пишет скриншоты в трекнутый каталог · CONFIRMED

После любого прогона `git status` показывает
`M .orchestra/tasks/356/usage-bar-provider-grid-1280.png` и `-1920.png`
(`git diff --stat`: `Bin 20443 -> 19077`, `Bin 22738 -> 19896`). Тест сам делает дерево грязным,
а грязное дерево блокирует `merge_worker` и `codex_review(mode="implementation")`.
Тот же класс, что #114 (`report_bug` писал в `BUGS.md` рабочего чекаута).

## Counter-evidence

- **Против «шардирование и есть решение»:** оно не чинит ни одного падения — до правки состав
  падений вообще не был известен, теперь их 57. Утверждение F1 узкое: прогон стал ДОХОДИТЬ до
  конца. Зелёным CI делает работа по F4, а не F1.
- **Против «локальный прогон = CI»:** 27 из 57 падений на VPS не воспроизводятся, и 3 падения
  VPS не воспроизводятся на CI. Любой вывод «починил, локально зелено» про CI ничего не значит;
  приёмка — только живой прогон.
- **Против моей же группы D:** 19 падений я НЕ диагностировал, а лишь отделил. Называть их
  «код неверен» сейчас нельзя — из них 10 существуют только на раннере, и такой перекос обычно
  означает окружение, а не дефект. Это гипотеза, а не находка.
- **Против выбора «6 шардов»:** число взято от прошлого протокола (#430), а не измерено.
  При 4 CPU у раннера 6 параллельных джобов всё равно исполняются на 6 РАЗНЫХ машинах, поэтому
  CPU не ограничение; но если шардов станет мало, самый длинный шард (117 с) вырастет линейно.
  Оптимум не измерялся — см. Пробелы.

## Затронутые файлы и риски

- `.github/workflows/ci.yml` — уже переписан (коммит `3b7eb105`), матрица 6×.
  Ожидают решения: `fetch-depth: 0` (B1) и установка ffmpeg (B2).
- `tests/test_quota_map_api.py`, `tests/test_usage_readiness.py`,
  `tests/test_t344_quota_lines_browser.py` (A2, 9 шт) — правка ожиданий под параболу.
- `tests/test_mcp_quota_gate.py`, `tests/test_codex_bin_resolution.py` (A1+A4, 9 шт) — фикстура
  project-context и снятие прибитого пути.
- `tests/test_restart_generation_liveness.py` (A3) — сигнатура `_shutdown_runtime`.
- `tests/test_orchestra_layout_430.py` (F5) — предмет проверки меняется, решение владельца.
- `app/static/css/*` (`test_tailwind_css`) — вне моего владения, чинится
  `bash scripts/build-tailwind.sh`.
- **Риск разъезда:** каждая правка теста обязана сохранять его замысел. Правило проекта —
  «изменилось ПОВЕДЕНИЕ или только ФОРМА?»: A2/A3 — форма и константы, A1/A4 — окружение,
  поэтому правка теста здесь законна. Ни один случай не закрывается `skip`.

## Источники

1. Живой прогон CI `33956684131`, 6 логов джобов целиком — `raw/ci-33956684131/shard-*.log` (тир 1).
2. Прогон `33893200040` (база) — `raw/ci-run-33893200040.log` (тир 1).
3. Локальный прогон той же раскладки — `raw/local-shards/` (тир 1).
4. GitHub, «Using GitHub-hosted runners», сохранённая страница — `raw/github-hosted-runners.html`;
   `ubuntu-latest` = 4 CPU / 16 ГБ для публичных репозиториев (тир 2, первоисточник).
5. `gh repo view DrSeedon/orchestra --json visibility` → `PUBLIC` (тир 1).
6. Код: `app/mcp_stdio.py:3613-3719`, `app/routes/system.py:1822-1828`, `app/quota_gate.py:79-124`,
   `pyproject.toml:60-75`, `tests/test_turn_usage.py:104-106`,
   `tests/test_quota_map_api.py:151-171`, `tests/test_codex_bin_resolution.py:71-76`,
   `tests/test_mcp_codex_review.py:27-38`, `tests/test_orchestra_layout_430.py:374` (тир 2).
7. История: `git log -S` по `_load_review_project_context` → `70547310`; по `curve_exponent` →
   `b757e834`; по `projection_repair_task` → `748e81e3` (тир 1).
