# V-1071 — RESEARCH DONE

Исследование от 24.10.2026. Архитектурное решение остаётся у root/владельца.

- [Полный отчёт: доказательства и три требуемые схемы](report.md).
- [Контракт будущего controlled E2E измерения](measurement-contract.md) — спецификация, запуск не разрешён и не выполнялся.
- [Воспроизведение и фактические проверки](reproduce.md).
- `exemplar/manual_sample.py` — ручной sample реальных tools из kit на его публичной вымышленной support-desk fixture.
- `exemplar/edge_cases.py` — воспроизводимые границы интерпретации coupling/coverage/compare.
- `evidence/*.stdout`, `evidence/commands.json`, `evidence/recorded-statistics.json` — собственные результаты без модели.
- `upstream/manifest.json` — commit и SHA-256 всех 215 файлов kit; `upstream/kit/` — неизменённый Apache-2.0 snapshot.
- `upstream/external-manifest.json` — закреплённые внешние skills и plugin; `evidence/source-catalog.json` — охват поиска, включая ненайденный открытый source `/skill-doctor`.

Изменения ограничены этой task-директорией. Kit не установлен в каталог активных skills. App, тесты Orchestra, pipeline, prompts, политики и пользовательская документация не менялись. Модельный review заморожен; его, заменяющих оценщиков и дополнительных воркеров не запускали. Внешние обращения были только чтением публичных источников.
