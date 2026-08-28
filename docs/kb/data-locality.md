# Локальность данных проектов

## Установлено

- Project knowledge owner зафиксирован пользователем как `<project>/docs/kb/`; central `~/.local/state/orchestra/knowledge-v1/` раздаётся по project repo и не остаётся shared cache · прямое решение пользователя 2026-08-27; `docs/tasks/412/research.md` §§Зафиксированное решение,4 · 2026-08-27, #412
- Central evidence на HEAD `309f4b058a57576065b15f421679de670ab248f8` содержит 20 948 JSON records / 13 103 260 apparent Б по 17 project ids; все 17 repo доступны, но Comfy/stargate/games/WebView имеют 0 remotes и держат 1 754 records · read-only JSON inventory + `git remote` per destination; `docs/tasks/412/research.md` §1.2 · 2026-08-27, #412
- `/mnt/data/media` зарегистрирован как `evidence_mode=none`, не является Git repo, имеет 0 evidence и 1 debt record; future knowledge нельзя молча класть в Orchestra, нужен Git owner либо explicit quarantine · scope registry + debt inventory; `docs/tasks/412/research.md` §1.3 · 2026-08-27, #412
- Формат target folder: human Markdown остаётся в `docs/kb/*.md`, machine state хранится one-record-per-file JSON в `docs/kb/records/`; current baseline — 21 Markdown file / 276 065 apparent Б (328 KiB allocated), готовая extraction — 764 facts / 588 931 Б · `git ls-tree`, `du -s -B1`, parse `main:docs/tasks/kb-extract/part-1..5.json`; `docs/tasks/412/research.md` §2 · 2026-08-27, #412
- Location меняется раньше format: сначала byte-identical landing + per-project count/SHA parity, затем отдельный 764-fact JSON commit; это оставляет по одной причине mismatch на каждом gate · `docs/tasks/412/research.md` §§4–5 · 2026-08-27, #412
- Current consumers не готовы к local owner: runtime/knowledge/projection держат один central root/head, а `app/ia/cutover.py:31-38` запрещает правильные `docs/kb` prompt directives; все code/prompt/script owners перечислены в `docs/tasks/412/research.md` §3 · primary source trace · 2026-08-27, #412

## Отвергнуто

- «Оставить central knowledge как общий rebuildable cache» · пользователь прямо выбрал полную раздачу; current projection содержит 8 255 foreign records / 85 080 576 chars, поэтому cache оставит вторую копию project knowledge · read-only `current.db`; `docs/tasks/412/research.md` §1.1 · 2026-08-27, #412
- «Сначала преобразовать формат central records, потом раздать» · одновременно меняются bytes и owner, byte-parity перестаёт локализовать потерю; fixed order — byte-identical distribution, parity, затем format commit · `docs/tasks/412/research.md` §4 · 2026-08-27, #412
- «Локальный Git commit уже решает clone/backup» · четыре destination repo имеют remote count 0; fresh clone невозможен, а central canonical сам имеет remote count 0 · live `git remote` inventory · 2026-08-27, #412

## Пробелы

- Назначить private remotes для Comfy/stargate/games/WebView и private off-host owner для pre-cutover bundle · current config destination не содержит · 2026-08-27, гейт после #412
- Решить Git ownership `/mnt/data/media` до появления первого evidence record · сейчас evidence=0 позволяет сделать это без data migration · 2026-08-27, гейт после #412
- Восстановить отсутствующие `decided_at` у 275 и `reason` у 397 extracted facts можно только отдельным research; migration обязана сохранить null и не выдумывать значения · extraction measurement · 2026-08-27, гейт после #412

## Источники

- `docs/tasks/412/research.md` — distribution ledger, format recommendation, owners, reversible order and backup gate.
