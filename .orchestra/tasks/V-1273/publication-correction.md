# sanitized-publication-copy
# Private originals: private/tasks/V-1273/originals/ (root-held SHA-256/bytes manifest; not accessed here).

# V-1273 — исправление публикационных артефактов

Изменены только 18 существующих task artifacts и добавлен этот manifest. Product source, committed tests и CHANGELOG не менялись. Тесты/модели/живая инфраструктура повторно не запускались. Root-private не читался. Новый HEAD создаст broker после окончания worker.

Все артефакты помечены `sanitized-publication-copy`; точные исходные файлы и их SHA-256/bytes manifest сохранены root: `private/tasks/V-1273/originals/`. Это указатель на root-held originals, а не прочитанная/скопированная worker папка.

Замены: абсолютный workspace root → `<workspace>`; pytest temporary root → `<task-tmp>`; account в pytest paths → `pytest-of-<account>`; системные пути интерпретатора/stdlib → `<python-bin>`/`<python-stdlib>`. Команды с `$HOME`/`$PWD` остаются шаблонами. Два URL в collected.txt — публичные Telegram API fixture-шаблоны с `{t}`/`<id>:<token>`, не идентификаторы сессий/хостов и не секреты; сохранены ради точности test IDs.

Сохранность: для каждого не-Markdown artifact проверено точное сохранение output кроме указанных замен и добавления маркера. В report.md дополнительно уточнено, что исходный import-path был абсолютным. Все RED/failed/143/skips/числа/выводы сохранены; новых результатов тестов не добавлено. Исторические compile/scan строки прежних логов относятся к исходному прогону. Конкретных code defects при коррекции не обнаружено; продукт не анализировался заново.

Проверка публикации: 18 исправленных артефактов и этот manifest; 0 оставшихся account/workspace/system-path identifiers, 0 secret-shape findings. Syntax-only compile двух executable artifacts успешен. Защищённые source hashes до/после совпали. Первый audit дополнительно обнаружил вложенный относительный task tmp suffix; он также заменён плейсхолдером.

## Защищённые source hashes (SHA-256, до = после)

| Файл | SHA-256 |
|---|---|
| `app/hub_workspace.py` | `ad2ad846751a0e5d774366f5ce924d0251d7b5844a67b19d03ce1cb226d2481f` |
| `tests/test_hub_untracked_delete_v1273.py` | `06836f885a06eca42e6edc19f1d803a603af403763452e5d533d52736dbe13e4` |
| `CHANGELOG.md` | `de4d08897c5597d4c843b3b99dec54377c7b64f45952f057fa5ff6b59404632e` |

## Changed artifacts (пути относительно `.orchestra/tasks/V-1273/`)

| Файл | Publication SHA-256 | Publication bytes |
|---|---|---:|
| `collected.txt` | `0030d0dda56bf7338f15937e4712c061d2daab3dda9386c8e145eb845a25b825` | 40004 |
| `commit_sync_before.txt` | `1bb7cf87731cd7ba1d3a08e13abf83f90dc0dbe7a157e58aff70c7105484e636` | 2731 |
| `core-command.txt` | `160cde8e69e389b3335b029141aaeb72515803745aa81a990a23c21d1744e451` | 945 |
| `final-review.txt` | `9b9a25235fbad991ccf5df6bd9d32c92f582a197f4efd5ffc35ed1f7dc829dbd` | 526 |
| `green-core.txt` | `8fb952f4f13d33db041c9dd4ba15bfb65be26c925c7ceaf0991892376e4630ed` | 373 |
| `green-focused.txt` | `8d8fa8a41548bcc6d80713e7d2b1e62302b1b42e24c970552ebb38d588deb353` | 237 |
| `green-suite.txt` | `1755bd8112fa3a6fd3eefc11e9da7c5abab8c0614cacd8d3b0e414594abb2a4b` | 432 |
| `guards.txt` | `5f86bb6d3cc70ac305f97b932c14b2c12944464a2b4a40d3673747c8cbc4d16e` | 7603 |
| `import-path.txt` | `fcba7597a63016c322ee547bd5dc805df5099b57c3d745ef6b6db1d3ab10b430` | 219 |
| `mutate.py` | `5c5e4db6de59652756e47e1cd1772a9ae79c406a220e456f221774289b407139` | 664 |
| `mutation.txt` | `ec798b61312e73e692aee883e624dc1a19d6bc0536ec3a3d4bab56023f8f5f3b` | 4219 |
| `notes.md` | `72b620f1bc58bb61e53ec6f2aff3cb89f67aba858c51443d209ecfce9d092660` | 5317 |
| `prompt-baseline.txt` | `ae40c1fc59a6d60235ff798099498353e6ce43da2f7e4734b9ea37680aea3412` | 1813 |
| `prompt-control.txt` | `fea1d97682097205f47aa44025b27ccc81a34938ab24069e15484ff6831b4316` | 1813 |
| `red-initial-test-typo.txt` | `617b223367c39654b71e036c05a19fe2dfc374480ee3da8784cf3178cf59a87c` | 24504 |
| `red.txt` | `09684ae81509dac5cab68974cc46e37c9b2fa20bc6b475dd46717cedb6ccaa12` | 25000 |
| `report.md` | `d9f78ed9cec5a6e5d90509554de94dfb167e283fadd6c93ed39f30bd7fdf82df` | 10243 |
| `source-review.txt` | `45be1ee2f033e2cd0d8a986c11a86d18e594586cb8aacbd14f867d245136a5d1` | 1921 |

Дополнительно добавлен `publication-correction.md` (этот manifest; его собственный hash в таблицу не включён).
