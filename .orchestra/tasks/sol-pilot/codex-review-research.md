## Summary

Главный вывод опровергнуть не удалось. Официальная API-карточка GPT-5.6 Sol подтверждает окно `1,050,000`, а локальные данные Codex CLI 0.144.3 согласованно показывают `context_window = 272000`, `effective_context_window_percent = 95` и `model_context_window = 258400`. Арифметика верна: обе пары отличаются в `3.860294…×`, поэтому hardcode `997500` действительно занижает отображаемое заполнение примерно до `25.9%` от корректного значения для этого runtime.

Блокирующих ошибок нет. Evidence достаточно для вывода о клиентском accounting/compaction budget текущего ChatGPT-auth runtime, но не для утверждения о физическом серверном лимите модели; документ в основном признаёт это ограничение, однако несколько формулировок всё ещё сильнее доказательств.

## Findings (Conventional Comments)

- **suggestion:** [`docs/tasks/sol-pilot/research.md:92`] Формулировки «реальный usable-контекст» и `CONFIRMED` звучат как доказанный транспортный предел. Измерены server-fed metadata и клиентское поле `model_context_window`, но запрос свыше 258,4K и серверный отказ не проверялись. Точнее утверждать, что Codex CLI 0.144.3 этого аккаунта **advertises и использует для accounting/compaction** effective budget `258400`; физический предел ChatGPT backend остаётся непроверенным. Это не меняет вывод о неверном Orchestra denominator.

- **suggestion:** [`docs/tasks/sol-pilot/research.md:98`] Разделить измеренный факт и прогноз последствий. Неверный denominator `997500` в `CodexBackend` доказан, как и примерно четырёхкратное занижение `context_pct`; утверждение о точном порядке «Codex уже упрётся в окно или выполнит компактацию раньше Orchestra» выводится из контрактов и порогов, но E2E до границы не выполнялся. Для него уместнее `EXPECTED`, а не общая уверенность `CONFIRMED` всего finding.

- **suggestion:** [`docs/tasks/sol-pilot/research.md:126`] `app/models.py:CONTEXT_LIMITS` нельзя без оговорки называть raw-контекстом и предписывать ему `272000`: словарь уже содержит `258400` для GPT-5.5, используется в `available_models_block()` и при восстановлении `_last_context`, а live Codex percentage считает отдельный `app/backend_codex.py:CODEX_CONTEXT_LIMITS`. Поэтому локальные refs верны по строкам, но контракты и последствия двух hardcode следует описать отдельно; непосредственно четырёхкратное занижение live `context_pct` создаёт `CODEX_CONTEXT_LIMITS = 997500` в `CodexBackend`.

- **suggestion:** [`docs/tasks/sol-pilot/research.md:86`] Источник [4] относится к ChatGPT Business, тогда как проверенные rollout metadata текущего аккаунта сообщают `plan_type = plus`; источник [5] подтверждает минимальную версию CLI, но не публикует CLI context window. Эти страницы подтверждают лишь возможность различия API и подписочного продукта, а точное число для данного CLI доказывают локальные cache/session events. Стоит явно назвать это inference и добавить в audit trail план аккаунта, точные rollout-файлы и команды извлечения: сейчас ключевые evidence находятся в изменяемом `~/.codex` и из одного `research.md` позднее невоспроизводимы.

## Verdict

**PASS with suggestions.** Вывод «`1050000/997500` неверны для проверенного ChatGPT-auth Codex CLI 0.144.3 runtime» поддержан сильными и согласованными данными; blocking findings нет. Область доказательства нужно удержать на уровне текущего аккаунта, версии и клиентского effective budget, не превращая её в универсальный серверный лимит GPT-5.6 Sol.

> Восстановлено дословно из `custom_tool_call_output` Codex-сессии `019f6986-afb4-7191-8ce8-5420a076d58e`: после успешного job `bg-f6772e9682` MCP-обёртка перезаписала этот файл коротким финальным `agent_message`. Инфраструктурный баг зарегистрирован через `report_bug`.

## Round 2

### Re-review status

- **Round 1 #1 — STILL BROKEN (suggestion):** итоговые findings и ограничения теперь корректно говорят о client accounting/compaction budget, но H2 в `research.md:20-32` всё ещё сформулирована как «Sol ограничен» 258,4K и считается прошедшей только по cache/session metadata. Эти данные не доказывают транспортный предел; формулировку самой H2 также нужно сузить до advertised/effective client budget.
- **Round 1 #2 — FIXED:** `research.md:108-116` отделяет измеренное занижение denominator (`CONFIRMED`) от ожидаемого поведения auto-compact (`EXPECTED`) и явно отмечает отсутствие E2E у границы.
- **Round 1 #3 — FIXED:** `research.md:139-146` различает контракты `app.models.CONTEXT_LIMITS` и `backend_codex.CODEX_CONTEXT_LIMITS`, правильно связывает live `context_pct` со вторым и больше не требует механически записывать raw `272000` в общий словарь.
- **Round 1 #4 — STILL BROKEN (suggestion):** `plan_type = plus`, границы применимости Business docs и точные rollout-файлы добавлены, но обещанная воспроизводимость неполна: `research.md:86` перечисляет поля, не приводя точную `jq`-команду извлечения. Внешние mutable-файлы теперь локализованы, однако результат всё ещё нельзя повторить копированием одной команды из документа.

### New findings

Новых blocking/suggestion findings нет.

### Verdict

**APPROVED.** Главный вывод корректен для проверенного Codex CLI 0.144.3 runtime, blocking findings нет. Два оставшихся замечания ограничены точностью гипотезы и воспроизводимостью audit trail и не меняют Phase 1 decision.


## Round (2026-07-16T06:15:47Z)

Даже исправления умудрились оставить два аккуратных хвоста. 🧐

`## Round 2` добавлен в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/sol-pilot/docs/tasks/sol-pilot/codex-review-research.md).

- #1 — STILL BROKEN: H2 всё ещё подразумевает транспортный предел.
- #2 — FIXED.
- #3 — FIXED.
- #4 — STILL BROKEN: нет точной воспроизводимой `jq`-команды.
- Новых findings нет.
- Вердикт: **APPROVED**, блокеров нет.

Обычный `git diff` пуст, поскольку каталог пока untracked; содержимое проверено через `git diff --no-index`. То есть документ одобрен, просто два винтика ещё лежат рядом с корпусом. 🔩

## Round 3

### Re-review status

- **Round 2 #1 — FIXED:** H1/H2, критерии опровержения и pass/fail в `research.md:14-34` теперь явно проверяют client-advertised effective accounting/compaction budget; физический транспортный предел отдельно исключён из области эксперимента.
- **Round 2 #4 — FIXED:** `research.md:78-100` содержит точные команды для model cache и всех трёх rollout-файлов. Команды выполнены повторно: они возвращают только `slug`, context-поля, `model`, `model_context_window`, `plan_type` и ожидаемые значения `272000 / 95% / 258400 / plus`.

### New findings

Новых blocking findings нет.

### Verdict

**APPROVED.** Оба оставшихся suggestion закрыты; главный вывод корректен в заявленной области текущего Codex CLI 0.144.3 runtime.


## Round (2026-07-16T06:18:54Z)

Третий раунд наконец-то без торчащих хвостов. ✅

`## Round 3` добавлен в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/sol-pilot/docs/tasks/sol-pilot/codex-review-research.md).

- Round 2 #1 — **FIXED**
- Round 2 #4 — **FIXED**
- Новых blocking findings нет
- Вердикт — **APPROVED**

Обе `jq`-команды выполнены и вернули ожидаемые безопасные поля. Обычный `git diff` пуст из-за untracked-каталога, поэтому содержимое проверено через `git diff --no-index`.

Теперь 272K хотя бы не пытаются притворяться миллионом. 🎭