# V-830 — fast mode: этап 1 (находки), этап 2 НЕ делался

**Вывод: fast mode не входит в подписку Max, это платный режим (usage credits / extra usage), и на нашем аккаунте он сейчас вообще недоступен. Только Opus, Sonnet не поддерживается. Остановился по правилу «платное — только по слову владельца».**

## Что это
Тот же Opus с другой конфигурацией API: до 2.5× быстрее, дороже за токен. Research preview.
Источник: https://code.claude.com/docs/en/fast-mode (открыт, WebFetch 13.10.2026).

- Настройка: `"fastMode": true` в settings (user settings, либо `--settings '{"fastMode":true}'`). В SDK-пути единственный рабочий вариант — `ClaudeAgentOptions(settings=json.dumps({"fastMode": True}))` (= flagSettings). Без него SDK-сессия отвечает `fast_mode_disabled_reason: sdk_opt_in_required` (замер ниже; в бинарнике 2.1.293 `FU()` требует `flagSettings.fastMode===true` для SDK). Отдельного поля запроса/CLI-флага нет; в `ClaudeAgentOptions` специального параметра нет, только `settings`.
- Применяется со следующего хода; тоглится `/fast` внутри сессии.
- Наш путь запуска (`app/backend_claude.py:1086`, `ClaudeAgentOptions(...)`) `settings` не передаёт, упоминаний fast нет — то есть сейчас не включается.

## Модели
Доки: «supported on Opus 5.5, Opus 5, Opus 4.8. It is not available on Sonnet, Haiku, or other models.» Opus 4.7 убран. В бинарнике `FU()`/`model_not_allowed` и «Switching to other models turns off fast mode»: при включении на неподдерживаемой модели CLI молча переключает на Opus. Для Sonnet 5.5 ответ: НЕТ (в проверке `s2()` сам бинарь Sonnet не отсекает — но доки однозначны; на нашем аккаунте проверить нельзя, см. ниже).

## Цена и учёт на Max 20x
Доки: «On subscription plans fast mode is available via usage credits only and not included in the subscription rate limits»; «draws directly from usage credits, even if you have remaining usage on your plan». Цены за MTok (in/out) по докам: Opus 5.5 — $8/$40 (Opus 5 и 4.8 — $10/$50). Сравнение со стандартной ценой Opus 5.5 не проверял. Первое включение в разговоре платится как полный несрезанный (uncached) input всего контекста — поэтому включать в начале сессии.
Следствие для нас: каждый токен fast — реальные деньги сверх подписки; чтение кэша в подписке почти бесплатно, а здесь нет.

## Реальные вызовы (probe.py, probe.log, probe2.log; claude 2.1.293, SDK 0.2.164, подписка, `ANTHROPIC_API_KEY=""`)
| модель | settings.fastMode | init.fast_mode_state | причина | usage.speed |
|---|---|---|---|---|
| opus-5-5 | нет | — | — | standard |
| opus-5-5 | true | off | `extra_usage_disabled` | standard |
| sonnet-5-5 | true | off | `extra_usage_disabled` | standard |
| sonnet-5-5 | нет | off | `sdk_opt_in_required` | standard |
RateLimitEvent: `overage_status='rejected'`, `overage_disabled_reason='org_level_disabled'` — extra usage на аккаунте выключен организацией. Т.е. fast ни разу не применился (`speed: standard`), денег не потрачено сверх обычной подписки (два вызова по ~$0.07 list-стоимости кэш-записи и $0.002 — подписочные).

## Что нужно, чтобы вообще заработало (решения владельца)
1. Включить usage credits/extra usage на аккаунте (сейчас org_level_disabled) и задать лимит расхода;
2. принять, что fast — только Opus 5.5 (Sonnet недоступен — запрос «fast для Sonnet 5.5» невыполним);
3. включать осознанно: в SDK это `settings={"fastMode": True}` в `_make_client`.

Этап 2 не начат: платное, нужно слово владельца. Если решит — план: поле `fast_mode` у сессии (БД, переживает рестарт), `settings` в ClaudeAgentOptions при `claude-opus-5-5`, отказ для остальных моделей, параметр в `change_worker_model`-подобном инструменте + дашборд, тесты, CHANGELOG; Python-правки → нужен рестарт.
