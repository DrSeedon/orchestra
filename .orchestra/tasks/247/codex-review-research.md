## Summary

Основные выводы подтверждены: 12-строчный каталог строится из `MODELS`, usage/counts и размеры воспроизводятся, Grok действительно создал session/worktree до credential failure, а матрица reinjection/restart корректно описывает `prompt_overlay=NULL`.

Точный фрагмент из отчёта: “Один ноль без экспозиции не приговор.”

Блокирующих дефектов нет. Найдены три существенных методологических/фактических замечания.

## Findings

### suggestion — Таблица ошибочно утверждает, что staged gate сейчас запрещает Fable и Terra

В строках 75 и 81 указано `staged gate deny`. Но `worker_model_policy` в текущем `pipeline.yaml` полностью закомментирован. Значит текущий server-side gate эти модели не запрещает; действует только prompt policy `do not use`.

Сам отчёт позднее правильно признаёт это в строках 316–317: “сейчас `worker_model_policy` закомментирован, поэтому Fable/Terra держатся только на послушании prompt.”

Это внутреннее противоречие в нагрузочной таблице. Следует заменить `staged gate deny` на что-то вроде `staged but inactive deny; prompt-only prohibition`. Иначе таблица завышает Orchestra spawn readiness/policy enforcement.

### suggestion — Payment prose объявлен “LIKELY dead” без измеренной экспозиции финансовых задач

Ноль вызовов `payment_receive/payment_status` и пустые payment tables подтверждаются. Но частое использование task tools не доказывает, что агенты получали задачи, где платежные инструменты были уместны.

Пустые domain tables скорее подтверждают отсутствие финансовых событий, чем достаточную экспозицию правила. Поэтому строки 196–197 не удовлетворяют собственному критерию отчёта о “нуле при достаточной экспозиции”.

Допустим вывод “кандидат на удаление из always-on prompt, поскольку schema сохраняет discoverability”, но confidence должен быть `UNCERTAIN` либо требовать выборку релевантных задач.

### suggestion — Grok spawn failure доказан, но corrected `remote_fetch` chronology не воспроизводима из перечисленных артефактов

SQLite backup подтверждает:

- session `audit247-grok-probe`;
- `grok-4.5`;
- 0 turns;
- создание в 08:37 CEST;
- точную credential error;
- последующую архивацию.

Код также подтверждает порядок: quota admission → подготовка worktree/backend → публикация → первая доставка.

Но утверждения строк 107–111 о появлении auth-файла в 08:53, смене вывода `grok models` и устранении конфаунда удалением `remote_fetch=false` представлены только повествовательно. Отчёт не сохраняет timestamped command output или другой неизменяемый артефакт, а текущий auth/config читать запрещено. Поэтому `CONFIRMED` в строке 122 слишком сильный для всей хронологии.

Следует разделить confidence:

- credential failure и late-failure path — `CONFIRMED`;
- `remote_fetch=false` как причина наблюдения 4.5-only — подтверждено внешним исследованием #251, но не воспроизводимо из доказательств этого отчёта.

### question — “CONFIRMED duplicate/stale” захватывает examples, которые schema не дублирует

`bg_create` schema действительно перечисляет типы и параметры, а prompt enum протух, поскольку пропускает `cron_command`. Но строки 210–212 рекомендуют убрать также examples как подтверждённый duplicate.

Examples в `background-jobs.md` содержат конкретные сценарии и значения, которых tool description не содержит. Данные о 111 worker/full-cycle calls показывают, что affordance доступна без manager module, но не доказывают ненужность examples именно для manager behavior.

Устаревший enum-каталог подтверждён; удаление examples требует более низкой confidence или behavioral evidence.

## Verdict

**REQUEST CHANGES — non-blocking research corrections required.**

Главные архитектурные выводы проходят adversarial review:

- каталог действительно hardcoded и не является availability;
- usage arithmetic и 10/14-day limitation корректны;
- Grok late credential failure подтверждён;
- zero-use в остальных разделах в основном трактуется осторожно;
- hot-apply/restart matrix, включая `prompt_overlay=NULL`, соответствует коду и DB.

Перед использованием отчёта как основания для implementation нужно исправить активность staged gate и снизить confidence для payment prose, background examples и невоспроизводимой части Grok chronology.

## Round (2026-08-13T07:23:52Z)

## Summary

Все четыре замечания прошлого раунда исправлены. Новых P1/P2-дефектов не найдено.

Точная цитата из обновлённого файла: “Не основание удалять код или объявлять текст доказанно мёртвым.”

## Findings

- **FIXED — Fable/Terra enforcement.** Таблица теперь явно различает активный prompt-запрет и staged, но неактивный server deny. Итоговый P0 согласован с этим.
- **FIXED — payment exposure.** Вывод снижен до `UNCERTAIN`; отсутствие платежных событий больше не выдано за достаточную экспозицию. P1 допускает только проверку экспозиции или обратимый pilot.
- **FIXED — Grok chronology.** Credential failure и late path отделены как `CONFIRMED`; объяснение `remote_fetch=false` маркировано `LIKELY`, tier 4 и локально невоспроизводимое. Ограничение повторено в источниках и контрдоказательствах.
- **FIXED — background-job catalog.** Подтверждён только stale enum. Examples и manager behavior оставлены до A/B; P1 сохраняет эту границу.
- **New findings:** нет.

## Verdict

**APPROVED.** Исследование теперь держит confidence и приоритеты в пределах представленных доказательств.
