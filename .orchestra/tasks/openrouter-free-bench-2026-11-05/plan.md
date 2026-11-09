# Пять бесплатных моделей через Harness — 2026-11-05

Источник: прямая вторая задача Максима в треде Orchestra. Только Flint,
Dots3-Note, Nemotron 3 Ultra, North Mini Code и Nemotron 3.5 Super VL,
только их точные маршруты `:free`. Платные подмены и пополнение не разрешены.

Предыдущие находки сохраняются: ветка V-1283 на VPS,
`task-V-1283/bench-free-models-v1283`, commit
`12a3daa8b62c5b335734ef21625876c23e8cc5b0`. Отчёт прочитан через SSH;
его попытки завершились до моделей из-за userns и worker dispatch.

## Разрешённый способ оценки

Текущий checkout на хабе: `/mnt/claude-data/astrahancev-maxim-911aird/orchestra`,
HEAD `b57f36199`, импортируемый app будет из этого абсолютного пути.
На хабе `.venv/bin/python -m scripts.local_bench doctor` успешно подтвердил
bwrap, Landlock ABI 4, приватные tmp/proc и сетевой фильтр. Настройки ОС не меняются.

Существующий `app.harness.oneshot` — отдельный ручной вход Harness без
создания платформенного worker. Для оценки используется тот же AgentLoop,
OpenRouterClient, canonical model validation и quota admission. Политика
`ensure_spawn_allowed` обычных воркеров не меняется: worker spawn не вызывается.

Отдельный адаптер оценки хранится только в этой папке задачи. Он использует
существующие snapshot/oracle/изоляцию `scripts.local_bench`, не маскирует
провайдеров под offline fixtures и не ослабляет frozen oracle. Новый runtime
в production Orchestra и основные модули бенчмарка не добавляются.

## Границы

- Свежий каталог OpenRouter, пять точных IDs, tools и нулевые публичные цены.
- Только синтетические задания и публичный пример calc.total.
- 3 задания × 5 моделей × максимум 3 model POST = 45 запросов максимум.
- Один запуск на вопрос/модель, timeout, без HTTP retries и без подмены модели.
- API key берётся существующий на собственном VPS в RAM и передаётся
  sandbox-процессу только через stdin. В файлы/argv/вывод не попадает.
- Изолированные SQLite, HOME и процессы. Production DB/catalog/flags не меняются.
- Неприменимость subscription quota к Harness фиксируется явно;
  дополнительно проверяются статус ключа и ограничения бесплатного API.
- Объём проверки — небольшой текстовый benchmark N=1 на каждую задачу.
  Vision и общий интеллект из него не выводятся.

## Доступность

Свежий публичный каталог вернул все пять разрешённых exact free routes с tools.
На VPS провайдеры Harness/OpenRouter не отключены; отключены только Claude/Grok.
Локальный production-счётчик OpenRouter за текущий UTC-день показывал 0 попыток.

## Подготовительные проверки

Первый offline-запуск адаптера остановился до моделей: snapshot.overlay
ожидает frozen oracle как путь к файлу, а адаптер передал bytes (TypeError).
Исправлена форма передачи: отдельный замороженный файл вне workspace,
с прежним содержимым и фиксируемым SHA-256. Приёмочные проверки не менялись.
Model requests на этой ошибке: 0.

## Обнаруженный дефект приватности стенда

В завершённом прогоне два результата `bash ls` (Flint/repair и North/repair)
содержали реальное имя владельца файлов хаба. Последующие model requests
включили эти tool results. Причина: унаследованный из local_bench bind
настоящих /etc/passwd и /etc/group, из которых ls разрешает UID/GID в имя.
Это непредусмотренное раскрытие идентификатора пользователя провайдерам
Recursive/Cohere через OpenRouter. На NVIDIA такой tool output не обнаружен.
API-ключевых шаблонов в артефактах нет; код не передавал ключ модели.

Сами задания синтетические, но утверждать, что весь переданный контекст
исходного прогона был только синтетическим, нельзя. Результаты и raw сохранены
без подмены. Оригинальная версия адаптера архивирована в runtime-src прогона.
В адаптер добавляется synthetic passwd/group и hostname внутри namespace;
это проверяется локально без новых model calls. Полный benchmark не перезапускается.

Исправленный identity-check прошёл: `bench / bench / benchmark`. Все три
negative/positive oracle controls повторно прошли без model calls.
Негативные route checks отклонили платную и постороннюю free-модель до API.
Исходные runtime sources архивированы отдельно от исправленного адаптера.
При генерации итогового Markdown была ошибка quoting в JS-обёртке до
исполнения Python; файлы/запросы ею не изменялись, генератор исправлен.
