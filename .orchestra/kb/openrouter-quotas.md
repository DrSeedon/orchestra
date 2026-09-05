# openrouter-quotas

## Established
- **Нулевая цена prompt/completion НЕ доказывает бесплатность маршрута:** Lyria вернула
  оба нуля в Models API, но тарифицируется отдельно за песню. Production Harness допускает
  только exact `:free`, text output и tools; на 24.08 это 14 прямых маршрутов. Unsuffixed
  Ox, обе Lyria, content-safety и случайный `openrouter/free` исключены · live Models API
  + страницы Lyria + production guard `app/model_catalog.py`/`app/harness/llm.py` · 24.08.2026
- На 23.08 аккаунт точно в тире 1000/сутки: `/credits` вернул `total_credits=97` при пороге 10; текущий source docs задаёт 20/мин и 1000/сутки · `.orchestra/tasks/236/evidence/matrix/account-sanitized.json` + `openrouter-limits-source-2026-08-23.txt` · 23.08.2026, #236
- Бесплатная платформенная квота глобальна для ключей аккаунта, а помодельная/provider capacity действует ДОПОЛНИТЕЛЬНО: GLM дал 22 upstream-429 из 24 попыток, Ultra 0/21, Super 0/37 · OpenRouter limits source lines 224–226 + `.orchestra/tasks/236/evidence/matrix/summary.json` · 23.08.2026, #236
- Живой text-каталог содержал 422 модели, 20 точных бесплатных маршрутов и 19 из них с `tools`; `inclusionai/ling-3.0-flash:free` в каталоге отсутствовал и exact lookup дал 404 · `.orchestra/tasks/236/evidence/free-model-metadata-2026-08-23.json` + 6 guard failures · 23.08.2026, #236
- `1000-local_count` — только ВЕРХНЯЯ граница остатка, не безопасное точное число: frozen-стенд #236 потратил 88 запросов через изолированную БД, которых production local counter не видел; сегодняшний provider request count API не отдаёт · `guard.json` 88 rows vs isolated counter + #368 F9 · 23.08.2026, #236
- Frozen-сравнение на двух повторах: Ultra закрыл 3/6 полезных задач при 7.0 запроса/закрытие и 0/21 429; Super 3/6 при 12.333 и 0/37; GLM 0/6 при 22/24 upstream-429; Ox 0/6 с шестью пустыми ответами · `.orchestra/tasks/236/evidence/matrix/*.json` · 23.08.2026, #236
- Бесплатные модели `:free`: 20 зап/мин всегда; в сутки 50 (<$10 lifetime) или 1000 (≥$10). Наш аккаунт в тире 1000 ($77 куплено, `is_free_tier:false`) · https://openrouter.ai/docs/api_reference/limits.md + GET /api/v1/key 22.08 #368
- Успешные ответы OpenRouter НЕ содержат X-RateLimit-* · доки дословно + пробы 200-ответов 22.08 #368
- GET /api/v1/key не даёт числа запросов: только деньги (usage_daily=0 у бесплатных), `rate_limit` в ответе deprecated («safe to ignore») · живой вызов 22.08 #368
- Management key открывает GET /api/v1/activity: построчно (дата, модель, провайдер) с полем `requests` по ВСЕМУ аккаунту; окно 30 дней · живой вызов 06:55 UTC 22.08 #368
- /activity отдаёт только ЗАВЕРШЁННЫЕ сутки: сегодняшней даты нет, `?date=<сегодня>` → 400 «Date must be within the last 30 (completed) UTC days» — в одиночку задачу «не упереться внезапно» не решает · живой вызов 22.08 #368
- Запасной агрегатный путь: POST /api/v1/analytics/query, метрика `request_count`, размерность `date__day`, тоже management key · openapi-спека 22.08 #368
- На ПЛАТФОРМЕННОМ 429 ответ несёт X-RateLimit-Limit/-Remaining/-Reset (+Retry-After) · доки; живьём не воспроизведён — LIKELY #368
- Бесплатные модели часто отвечают UPSTREAM-429 («temporarily rate-limited upstream», только Retry-After:5) — это не исчерпание нашей квоты; llm.py уже ретраит · burst-замер 26 запросов 22.08 #368
- Единица расхода квоты — HTTP-вызов, не ход агента: harness делает вызов на каждый tool-раунд, потолок 50 раундов/ход (+15 у ревьюер-сублупа), app/harness/loop.py:35 · код #368
- `app/harness/llm.py:stream()` — единственный владелец POST к OpenRouter в `app/`; проверено ревьюером и grep 22.08 #368, повторно после удаления OpenCode 24.08
- Масштаб реального расхода аккаунта: пик 662 зап/сутки (08.08), 92 (21.08, из них 7 stealth/ox-alpha) — юзер уже подходил к 2/3 лимита · GET /activity 22.08 #368

## Rejected
- «Три захардкоженные модели всё ещё можно считать лучшими по имени» — текущая полезность разошлась: Ultra годен узко для public read-only audit, Ox дал пустые ответы, GLM упёрся в upstream, Super отсутствует в manifest, но закрыл 3/6 · frozen commit `9e814761`, matrix #236 · 23.08.2026, #236
- «Локальный SQLite сам даёт безопасный remaining всего аккаунта» — 88 внешних к production-счётчику попыток расходуют ту же глобальную квоту; `/activity` сегодня не показывает · matrix #236 + limits source · 23.08.2026, #236
- «Число запросов можно взять с текущим inference-ключом» — /api/v1/key отдаёт только деньги, /activity без management → 403, заголовков на успехах нет · 22.08 #368
- «Каждый 429 = исчерпание суточной квоты» — upstream-429 перегруза провайдера выглядит иначе (без X-RateLimit-*) · burst-замер #368
- «Management key решает задачу сам» — /activity показывает только завершённые сутки; для «сегодня» нужен локальный счёт · F9, 22.08 #368

## Gaps
- Первый completed-day `/activity` после frozen-88 нужен, чтобы измерить, какие отклонённые upstream-429 вошли в provider request count · сегодня provider endpoint дня не отдаёт · 23.08.2026, #236
- Точное связывание провайдером намеренно отдельных user accounts документ не раскрывает; доказана глобальность ключей/нашей account capacity, не anti-abuse identity graph · primary docs говорят `globally`, без формальной сущности · 23.08.2026, #236
- Окно X-RateLimit-* на платформенном 429 (минута/сутки?) — не воспроизведён; ловить opportunistically логированием заголовков 429 · #368
- Scope лимитов 20/мин и 1000/сутки (аккаунт/модель?) — доки молчат; burst >30 зап/мин без платформенного 429 · #368
- Считает ли провайдер отклонённые 429/5xx в суточный лимит — неизвестно; первая сверка локального счёта с /activity за 22.08 даст эмпирическую границу · #368

## Источники
- .orchestra/tasks/368/research.md — полный разбор обоих путей (локальный счёт vs management key) с живыми пробами
- .orchestra/tasks/236/research.md — текущий каталог, account-tier, frozen free-only matrix и границы безопасного routing/remaining
