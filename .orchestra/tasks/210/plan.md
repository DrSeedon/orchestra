# #210 Фаза 2 — план: фаза плана заканчивается красным тестом

Одно изменение, два файла ролей, один файл тестов. Ничего сверх.

## Зачем (основание, честное)

**Первый довод — не экономия.** В ретроспективном реплее (`research.md`, раздел 3) оба
Luna-воркера отчитались `DONE` с ЗЕЛЁНОЙ командой тестов, которую написали сами. У одного из двух
за этим стояли **шесть невыполненных пунктов AC**, включая ложную тревогу на спокойной неделе
(дефицит 21.57 при пороге 14.0) — то есть ровно тот дефект, ради предотвращения которого метрика и
писалась. Действующее правило маршрутизации ловит провал по признаку «названная команда тестов
остаётся красной → эскалация»; **оно не может сработать никогда, пока команду пишет исполнитель.**
Этот довод стоит сам по себе: он остаётся верным, даже если экономия окажется нулевой, и относится
к любому исполнителю, не только к дешёвому.

**Второй довод — экономия, и она скромнее, чем показывает наивная перецена.** Перенос фазы
реализации «как есть» снял бы 16–28 % расхода `full-cycle`. Но если оракул остаётся на дорогой
стороне (а он обязан), переносится примерно треть работы: тест — **65 % строк** ушедшего в `main`
диффа (402 из 615 у T1, 447 из 654 у T3). Реалистичная оценка — **≈6–10 % расхода `full-cycle`,
то есть ≈2–3 п.п. недельного пула в неделю**. Оценка сделана по строкам диффа, а строки — плохая
мера токенов, поэтому читать как порядок величины.

**Третий довод — побочный и бесплатный.** Красный тест на фазе плана ловит расхождение плана с
реализацией у СВОЕГО же воркера. В #186 `main` уехал от собственного тикета по сигнатурам
(`alert_state_advance(window_id)` в тикете против `(window_id, now)` в коде) и по формуле
(единственный числовой пример вырожден), и `plan.md` при этом не правился ни разу.

## Что меняется

### Дословный текст — шаг 3 фазы 2 в `roles/full-cycle.md`

Вставляется между нынешним шагом 2 (нарезка на тикеты) и нынешним шагом 3 (Codex-ревью плана);
последующие шаги перенумеровываются. Codex обязан ревьюить план ВМЕСТЕ с тестом, поэтому шаг
стоит до ревью, а не после.

```
3. **The plan ends with a red test, not with AC prose.** For every ticket whose outcome is
   behaviour, write the check NOW and commit it FAILING, before any implementation exists.
   - The check lives in the test file the ticket names and is named after the ticket
     (`test_t1_*`), so criterion → assertion is a lookup, not a reconstruction.
   - **"Red" means:** the ticket's command exits non-zero AND the failure is the missing
     behaviour — an ImportError or a collection error is NOT red, it is broken. Paste the
     failing assertion line into the ticket.
   - Anything the test cannot express — a constant, a formula, a signature — goes into the
     ticket VERBATIM. A named-but-unvalued symbol in a ticket means the implementer invents
     the value.
   - The ticket's AC then reads `AC: <command> is green`, and it can be handed to any
     executor, including a cheap one: the escalation rule ("the named test command stays red
     → escalate, never retry") finally has something to observe.

   **When the ticket's outcome is TEXT, not behaviour** — prompt/rule/doc edits, research
   write-ups, anything whose result a human reads — do NOT invent a test for prose. Write a
   one-line DELIVERY check instead: a command proving the text reaches its consumer (for a
   role prompt: `build_system_prompt` for that role contains the anchors AND a role without
   the step does not). If not even a delivery check exists, mark the ticket
   `oracle: none — <why neither a behavioural nor a delivery check is possible>`. The reason is
   part of the mark: a bare `oracle: none` is not a valid ticket.
   **A ticket marked `oracle: none` stays on the expensive side and is never handed to a
   cheap executor** — that mark is the whole point, not an escape hatch.
```

### Дословный текст — расширение шага Codex-ревью плана (шаг 4 после перенумерации)

К нынешнему «Codex review the plan + tickets» дописывается второе предложение:

```
   Codex reviews the plan, the tickets AND the committed test. A test that is
   already green at review time is a blocking finding, and so is an `oracle: none`
   whose stated reason Codex can refute by naming a viable check.
```

Перенос строк здесь — часть контракта, а не оформление: ассерт ищет непрерывную подстроку
`already green at review time is a blocking finding`, и первая редакция рвала её между `green` и
`at`. Тест это поймал на реализации.

### Дословный текст — зубы в фазе 3 (шаг 2 фазы 3)

Нынешнее «After each ticket: check it against its AC (self-verify)» заменяется на:

```
2. Before touching code, run the ticket's named test and **see it red before you change
   anything**. Already green, or missing → the test is not about this ticket: STOP and say so,
   do not implement around it. After the ticket: the same command must be green, and no other
   test may have gone red. **The only exception:** a ticket whose Test field is a reviewed
   `oracle: none — <reason>` has no such command — verify it against its AC by hand and name
   in the report the check you could not run.
```

### Дословный текст — шаблон тикета в том же файле (шаг 2)

```
   ### T1 — <short title>
   - Files: <files touched>
   - Test: <path>::<test name> — committed RED in <commit>
           | oracle: none — <why neither a behavioural nor a delivery check is possible>
   - AC: <command> is green + <anything the test cannot express, verbatim>
   - blocked-by: none
```

Форма без причины в шаблоне не встречается вовсе: голая метка `oracle: none` — невалидный тикет,
и шаблон не должен её показывать, иначе агент скопирует именно её (blocking раунда 2).

### Дословный текст — строка отчёта `PLAN READY` (шаг 5 после перенумерации)

```
5. Report: `PLAN READY #<id>: <approach>, N tickets, M with a red test (K `oracle: none`).
   <command> → exit 1: <first failing line>. Plan + Codex in docs/tasks/<id>/. Awaiting approval.`
```

### Дословный текст — контрправило в `roles/worker.md`

```
- **Never author the acceptance test for a ticket someone else wrote.** If the ticket names a
  command, run it FIRST and confirm it is red; if it is green or missing, say so and stop —
  do not write the check yourself. A green run of a test you wrote is not evidence: measured
  in #210, two workers did exactly that, one of them with six unmet AC.
```

## Как это не станет ритуалом — у шага есть потребители

Премортем в #198 держится не на дисциплине, а на том, что его результат КУДА-ТО идёт
(`report.md` + Codex). Здесь потребителей три, и все механические:

1. **Codex-ревью плана (следующий шаг) ревьюит тест вместе с планом.** Тест, зелёный на момент
   ревью, — это blocking finding: он ничего не проверяет.
2. **Отчёт `PLAN READY` обязан процитировать падающую строку и ненулевой exit.** Подделать это,
   не произведя артефакт, нельзя, а оркестратор проверяет артефакты, а не пересказ.
3. **Фаза 3 читает его как вход.** Шаг 2 фазы 3 заменяется целиком (дословный текст выше): тест
   обязан пройти путь красный → зелёный, **и красным его надо УВИДЕТЬ до правки**; уже зелёный
   или отсутствующий = STOP. Это та самая мутационная проверка, которую мы пишем в отчётах
   постфактум, только встроенная в маршрут. Единственное исключение — отревьюенная метка
   `oracle: none — <reason>`, у неё команды нет по определению.

Все три потребителя живут в ДОСЛОВНОМ тексте роли, а не в прозе этого плана. Различие не
косметическое: в первой редакции два из трёх были только здесь и до промпта не доехали бы вовсе
— это и был blocking раунда 1.

Отдельно про счёт: **`oracle: none` не наказывается и не считается провалом.** Он меняет
маршрутизацию (тикет остаётся на дорогой стороне) и попадает в отчёт `PLAN READY` числом. Если
метка окажется массовой — это данные о том, что схема неприменима, а не повод её прятать.

## Tickets

### T1 — шаг «план заканчивается красным тестом» в роли full-cycle
- **Files:** `pipelines/default/prompts/roles/full-cycle.md`, `tests/test_default_pipeline.py`
- **Test:** `tests/test_default_pipeline.py::TestOracleGate` — коммитится КРАСНЫМ вместе с этим
  планом (см. раздел «Красный тест» ниже)
- **AC:**
  - `uv run python -m pytest tests/test_default_pipeline.py -k OracleGate -q` — зелёный;
  - **составная мутация красная:** шаг удалён из `roles/full-cycle.md` И маркер
    `commit it FAILING` вставлен в `prompts/base.md` → тот же прогон обязан упасть. Одиночной
    мутации недостаточно — на ней ассерт «строка есть в собранном промпте» остаётся зелёным
    (#198);
  - **потребители шага стоят в тексте роли, а не в прозе плана** (правка раунда 1): шаг
    Codex-ревью говорит «already green at review time is a blocking finding», шаг 2 фазы 3 —
    «see it red before you change anything»; оба закрыты
    `test_the_step_has_teeth_in_phase_3_and_in_the_codex_gate`;
  - **метка без причины невалидна**: в промпте присутствует форма `oracle: none — <why`;
  - шаги фазы 2 перенумерованы сквозно, ссылок на «шаг 3» в старом смысле в файле не осталось;
  - `docs/tasks/<id>/` в секции `<artifacts>` не менялся — новых файлов схема не вводит.
- **blocked-by:** none

### T2 — контрправило исполнителю в роли worker
- **Files:** `pipelines/default/prompts/roles/worker.md`, `tests/test_default_pipeline.py`
- **Test:** `tests/test_default_pipeline.py::TestOracleGate::test_executor_rule_reaches_worker_and_full_cycle`
  — коммитится КРАСНЫМ вместе с планом
- **Почему без T2 правило не доезжает** (оркестратор просил доказать, а не заявить): дешёвый
  исполнитель — это агент роли `worker`. Текст T1 живёт в промпте `full-cycle` и до него не
  доходит вовсе. Замер: **2 прогона из 2** (`replay-a`, `replay-b`) сами написали себе файл
  тестов и отчитались `DONE` с зелёным прогоном — `replay-a` при шести невыполненных AC. Ни один
  не был проинструктирован писать тест: оба сделали это по умолчанию. Без строки в `worker.md`
  T1 меняет то, как тикет ПИШЕТСЯ, и не меняет того, как он ЧИТАЕТСЯ.
- **AC:**
  - маркер `Never author the acceptance test` присутствует в собранных промптах ролей `worker`
    и `full-cycle` и отсутствует у `orchestrator` и `sub-orchestrator`;
  - составная мутация (строка удалена из `worker.md` + вставлена в `base.md`) — красная.
- **blocked-by:** T1 (общий тест-класс)

## Красный тест — как он устроен и почему не тавтология

Ассерт «фраза из файла роли есть в собранном промпте» проверяет только склейку. Поэтому класс
состоит из двух половин, и вторая ловит именно составную мутацию:

1. **Доставка.** Якоря извлекаются ИЗ ФАЙЛА роли (все строки блока, не 2–3 выписанных руками —
   ручные якоря остаются зелёными на копии соседнего пункта, #203) и проверяются в выводе
   `P.build_system_prompt(PIPELINE, "full-cycle")`. Пустое извлечение = падение, а не зелёный
   прогон: гард на непустоту списка обязателен.
2. **Не-фоновость.** Отличительный маркер обязан ОТСУТСТВОВАТЬ в собранных промптах
   `orchestrator` и `sub-orchestrator`. Вот это и есть проверка против составной мутации: если
   шаг удалили из роли, а слова посадили в `base.md`, маркер появится у ВСЕХ ролей, и половина 2
   покраснеет, хотя половина 1 останется зелёной.

Команда мутационной проверки — одной строкой, с обязательным откатом и сверкой после него:

```bash
cd <worktree> && cp pipelines/default/prompts/base.md /tmp/base.bak \
 && cp pipelines/default/prompts/roles/full-cycle.md /tmp/fc.bak \
 && python3 - <<'PY'
import re, pathlib
fc = pathlib.Path("pipelines/default/prompts/roles/full-cycle.md")
b  = pathlib.Path("pipelines/default/prompts/base.md")
t  = fc.read_text()
i, j = t.index("3. **The plan ends with a red test"), t.index("\n4. Codex review the plan")
fc.write_text(t[:i] + t[j+1:])
b.write_text(b.read_text() + "\nwrite the check NOW and commit it FAILING\n")
PY
 uv run python -m pytest tests/test_default_pipeline.py -k OracleGate -q; echo "exit=$?" \
 ; cp /tmp/base.bak pipelines/default/prompts/base.md \
 ; cp /tmp/fc.bak pipelines/default/prompts/roles/full-cycle.md \
 ; grep -c "commit it FAILING" pipelines/default/prompts/roles/full-cycle.md
```

Ожидание: `exit` ненулевой, после отката `grep -c` снова печатает 1. Бэкап одноразовый — каждая
следующая мутация начинается со своего `cp`.

### Красный прогон, снятый на этом плане (собственный оракул схемы)

`tests/test_default_pipeline.py::TestOracleGate` закоммичен вместе с планом и КРАСЕН:

```
uv run python -m pytest tests/test_default_pipeline.py -k OracleGate -q  → exit 1
8 failed, 1 passed, 49 deselected
E  AssertionError: roles/full-cycle.md: шаг «план заканчивается красным тестом» должен жить
   в файле САМОЙ роли, иначе он потеряется при перекомпоновке слоёв
```

Красное — по отсутствию поведения, не по ImportError и не по ошибке сборки: 49 тестов файла
собрались и отобрались нормально, из девяти новых упали восемь. Девятый
(`test_orchestrator_roles_receive_neither`) зелёный законно — маркеров ещё нет нигде, и он
обязан покраснеть только при составной мутации.

Форма класса скопирована с `TestPremortemReachesWorkingRolesOnly` (#198) намеренно: тройка
«источник / доставка / не-утечка» — это тот же инвариант, и второй способ делать то же самое в
проекте заводить незачем.

## Чего этот план НЕ делает

- Не трогает `pipelines/default/pipeline.yaml`, модели, эффорт и маршрутизацию.
- Не вводит новых файлов в `docs/tasks/<id>/` и не меняет секцию `<artifacts>`.
- Не правит `pipelines/default/prompts/modules/model-routing.md`: определение закрытой задачи там
  уже верное, ему не хватало ровно того, что даёт T1, — существующего красного теста. Если после
  внедрения окажется, что маршрутизацию всё же надо трогать, это отдельная задача с отдельным
  замером.
- Не правит `docs/tasks/186/plan.md` — заведено оркестратором отдельно.
- Не строит второй замер экономии: 6–10 % проверяются не спором, а первым же тикетом, уехавшим
  к дешёвому исполнителю с красным тестом.

## Codex-ревью плана, раунд 1 — обе находки приняты

Артефакт: `docs/tasks/210/codex-review-plan.md`. Вердикт «changes required», два blocking.

**1. Ритуальная дыра — принято, исправлено.** «An executor can run only the final green command
and comply». Codex прав, и дыра была моя: два из трёх заявленных потребителей жили в ПРОЗЕ этого
плана, а в дословный текст для роли не попали вовсе — то есть до промпта они бы не доехали.
Добавлены два дословных блока: расширение шага Codex-ревью («тест, зелёный на момент ревью, —
blocking») и замена шага 2 фазы 3 («увидеть красным ДО правки; уже зелёный или отсутствует →
STOP»). Закрыто тестом
`TestOracleGate::test_the_step_has_teeth_in_phase_3_and_in_the_codex_gate`.

**2. `oracle: none` — самое дешёвое поведение агента. Принято, исправлено.** «The agent may mark
every ticket `oracle: none` without explaining why». Метка теперь обязана нести причину
(`oracle: none — <why…>`), а Codex-ревью плана обязано считать blocking такую метку, чью причину
оно может опровергнуть, назвав рабочую проверку. Отсутствие штрафа сохранено намеренно — наказание
за метку вернуло бы выдумывание тестов на прозу, ради чего метка и вводилась. Закрыто ассертом в
`test_ticket_template_carries_the_test_field_and_a_REASONED_none_marker`.

**Что Codex подтвердил, а не оспорил.** Составная мутация: падают
`test_plan_step_is_owned_by_the_full_cycle_file`,
`test_every_clause_of_the_plan_step_survives_assembly`,
`test_orchestrator_roles_receive_neither`; остальные четыре остаются зелёными, и «нет
правдоподобного варианта этой мутации, где зелёными остаются все семь». Владелец теста и
копирование формы `TestPremortemReachesWorkingRolesOnly` — без замечаний, классы не конфликтуют
(разные якоря, пересечение только структурное).

**Несогласий, которые надо было бы отстаивать, нет** — обе находки указывали на настоящие дыры, и
обе закрыты текстом, а не спором. Первоначальное несогласие для протокола (правило
«research/architecture exception»): я считал, что счёта меток `oracle: none` в отчёте
`PLAN READY` достаточно, потому что он делает злоупотребление видимым. Codex возразил, что
видимость ПОСЛЕ передачи не мешает самому дешёвому поведению ДО неё, и это сильнее моего довода.

После правок красный прогон: **7 failed, 1 passed, 49 deselected → exit 1** (было 6 failed).

## Codex-ревью плана, раунд 2 (последний) — обе находки приняты

Потолок для прозы — 2 раунда, и он безусловный: третьего не будет независимо от того, появятся ли
новые замечания. Обе находки раунда 2 — настоящие дефекты, внесённые МОИМИ ЖЕ правками раунда 1.

**1. `oracle: none` стал невыполнимым — принято, исправлено.** Мой новый шаг фазы 3 требует
безусловно: «команда отсутствует → STOP». У тикета с `oracle: none` команды нет по определению,
то есть я собственной правкой сделал такие тикеты нереализуемыми даже на дорогой стороне.
Добавлено единственное исключение: у тикета с отревьюенной меткой команды нет, он проверяется
против AC руками, и в отчёте называется проверка, которую запустить не удалось. Закрыто тестом
`test_phase_3_names_the_only_exception_for_oracle_none`.

**2. Ассерт про причину не привязан к шаблону — принято, исправлено.** Codex прав, и это тот же
класс дефекта, что составная мутация #198: ассерт `"oracle: none — <why" in out` был зелёным,
пока причина упомянута ГДЕ-УГОДНО в промпте, а шаблон тикета продолжал показывать безпричинную
форму — именно её агент и копирует. Шаблон переписан так, что форма без причины в нём не
встречается вовсе, а ассерт теперь пиннит полную строку поля
(`- Test: <path>::<test name> — committed RED in <commit>` и `| oracle: none — <why`).

Про содержательность причины Codex сказал прямо: пустая причина вроде «no test possible»
допустима, потому что бэкстопом стоит ревью, обязанное её опровергнуть, назвав рабочую проверку.
Согласен и лишнего предложения в промпт не добавляю.

**Подтверждено без замечаний:** нумерация фаз 2 и 3 когерентна, границы извлечения блока
(`"\n3. "` … `"\n4. "`) по-прежнему выделяют ровно новый шаг, новые якоря не сталкиваются с
существующим текстом роли.

Красный прогон после правок раунда 2: **8 failed, 1 passed, 49 deselected → exit 1**
(6 → 7 → 8 по мере того, как ревью находило дыры — рост числа красных здесь и есть след работы
ревью).

## Риски

1. **Шаг подорожает фазу плана.** Тест — 65 % строк, и теперь его пишет дорогая сторона на фазе
   плана вместо фазы реализации. Чистая экономия от этого и падает до 6–10 %; работа не исчезает,
   а переезжает. Наблюдаемо: доля фазы плана в расходе `full-cycle` (сейчас 8.8 %) обязана
   вырасти, доля реализации — упасть. Если план вырастет, а реализация не упадёт — правка не
   работает, и это видно тем же скриптом `docs/tasks/194/phases.py`.
2. **`oracle: none` станет отпиской.** Смягчено тем, что метка не наказывается, но считается в
   отчёте: массовая метка = данные о неприменимости.
3. **Тест, написанный до реализации, зафиксирует неверный контракт.** Это уже случалось в
   обратную сторону (#186: код уехал от тикета молча). Красный тест делает расхождение видимым
   на фазе плана, где оно стоит одного Codex-раунда, а не переделки.
