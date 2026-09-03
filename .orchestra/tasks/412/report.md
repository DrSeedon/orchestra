# #412 — Phase 3 report

## Статус

T1 и T2 завершены. T3 реализован и persisted owner активирован на 18 проектах; merge/restart и
живой HTTP/MCP query выполняет оркестратор как отдельный gate. Центральное хранилище не очищалось.

Live T2 выполнен 2026-08-28 в выбранном пользователем режиме: файлы положены в
`<project>/docs/kb/` **без `git add`, без commit и без push**. Backup перед раздачей не делался
по явному решению пользователя; это принятый риск.

## Итог раздачи

| Проект | Записей | Путь назначения | Контрольный count/SHA |
|---|---:|---|---|
| `orchestra` | 12,759 | `/mnt/data/Projects/Python/orchestra/docs/kb/records/evidence/` | ДА |
| `cog-second-brain-77dd306ac2a0` | 5,106 | `/mnt/data/Рабочий стол/Cursor/COG-second-brain/docs/kb/records/evidence/` | ДА |
| `scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9` | 1,728 | `/mnt/data/Projects/comfy-image-pipeline/docs/kb/records/evidence/` | ДА |
| `seedon` | 321 | `/mnt/data/Projects/Python/seedon/docs/kb/records/evidence/` | ДА |
| `sensar-5e197e867bb2` | 180 | `/mnt/data/Рабочий стол/Cursor/Sensar/docs/kb/records/evidence/` | ДА |
| `tradingcryptobot` | 177 | `/mnt/data/Projects/Python/TradingCryptoBot/docs/kb/records/evidence/` | ДА |
| `mnt-data-projects-python-claude-code-game-master-ccdad4e9b586` | 152 | `/mnt/data/Projects/Python/Claude-Code-Game-Master/docs/kb/records/evidence/` | ДА |
| `mnt-data-projects-python-aperant-0972b1340a75` | 112 | `/mnt/data/Projects/Python/Aperant/docs/kb/records/evidence/` | ДА |
| `kesha-tg-bot` | 96 | `/mnt/data/Projects/Python/kesha-tg-bot/docs/kb/records/evidence/` | ДА |
| `polus` | 86 | `/home/maxim/polus/docs/kb/records/evidence/` | ДА |
| `university` | 77 | `/mnt/data/Projects/University/docs/kb/records/evidence/` | ДА |
| `vpn-service-7c16d6f598b1` | 75 | `/mnt/data/Projects/Python/VPN-Service/docs/kb/records/evidence/` | ДА |
| `parsing-hub` | 43 | `/mnt/data/Projects/Python/Parsing/docs/kb/records/evidence/` | ДА |
| `stargate-tactics` | 12 | `/mnt/data/Projects/Python/stargate-tactics/docs/kb/records/evidence/` | ДА |
| `mnt-data-projects-unity-defaultprojectunity-317002a674e4` | 10 | `/mnt/data/Projects/Unity/DefaultProjectUnity/docs/kb/records/evidence/` | ДА |
| `mnt-data-projects-python-games-b14eae05bed5` | 9 | `/mnt/data/Projects/Python/games/docs/kb/records/evidence/` | ДА |
| `webview-c212de852078` | 5 | `/mnt/data/Projects/Python/WebView/docs/kb/records/evidence/` | ДА |
| `mnt-data-media-30494f74a194` | 0 | `/mnt/data/media/docs/kb/records/evidence/` | ДА; manifest + `.gitattributes` |
| **Итого** | **20,948** | **18 project directories** | **20,948/20,948; quarantine 0** |

В каждом проекте также лежат `docs/kb/manifest.json` и `docs/kb/.gitattributes`.

## Git и чужое рабочее состояние

- Внешний allowlist gate пропустил только read-only Git-команды. Журнал apply+verify:
  `show=41,896`, `status=255`, `rev-parse=241`, `config=144`, `ls-files=126`,
  `ls-remote=76`, `show-ref=72`, `symbolic-ref=54`, `check-ignore=36`, `ls-tree=2`.
- `add/commit/update-index/stash/clean/reset/checkout/push/fetch/pull`: **0** вызовов с нашей стороны.
- Verify-window: 18/18 `HEAD`, raw index, local refs/config и foreign worktree snapshots
  совпали before/after. Direct content parity: 20,948/20,948.
- `Aperant`: существующий ignore скрывает `docs/kb/`; `git add -f` не выполнялся. Файлы лежат
  на диске, но Git их не показывает, пока владелец сам не изменит ignore/индекс.
- `COG-second-brain`: project-owned cron каждые пять минут выполняет `git add -A`, commit и push.
  После landing он внешним commit `20707ebb0172ea323805f7131e8098dfb1362bd2`
  (`auto-sync 2026-08-28 12:25`) забрал только `docs/kb/**` и отправил их в remote.
  Это действие владельца, не migration engine; content parity после commit подтверждён.
- Остальные 17 проектов не получили commit от migration. Пока владелец сам не закоммитит
  `docs/kb/`, знания не бэкапятся Git-репозиторием и не приезжают в свежем clone. Это принятое
  пользователем следствие режима «просто положить».

## Central и evidence

- Source: `/home/maxim/.local/state/orchestra/knowledge-v1/canonical`.
- Frozen/current HEAD: `4acb0cea5edbfceddaf1839bca609392333db2eb`.
- Central status после T2: clean; source records не удалялись и не менялись.
- Scope registry SHA-256:
  `0978fd91fa2556c6eec35422f5dd59da555f0f2fdad13b6a608ce0f4ad129b2e`.
- Global verified receipt: `docs/tasks/412/distribution-manifest.json`.
- Independent Git gate log: `docs/tasks/412/git-command-log.jsonl`.

## T3 — project-local owner

- Engine state: `/home/maxim/.local/state/orchestra/knowledge-v1/project-knowledge-owner.json`;
  `active_owner=project-local`, 18 project heads, SHA-256
  `5d18f8578296776da1781ee593d1416d24425f97bd97806170d54477832ad7d1`.
- Activation receipt: `docs/tasks/412/project-owner-activation.json`; 18 projects,
  20,948 records, SHA-256
  `3084fb93326ab0cba851f38432f6437639b4cbf28bdf6d585337234cecc40707`.
- Activation дважды перечитала каждый manifest/record и сравнила полный project/root map с
  engine `scope-registry.json` до persistence.
- Branch-process probe: Orchestra и ignored/untracked Aperant читаются и ищутся напрямую с
  filesystem; cross-project read отказан; process-global router доступен; central Git остался
  clean на `4acb0cea5edbfceddaf1839bca609392333db2eb`.
- Runtime routing подключён к `query_for_scope`, `/api/knowledge` и `/api/memory/search` через
  существующий `KnowledgeRuntime`. Запущенный production process ещё держит старый Python-код;
  положительный HTTP/MCP query возможен только после merge/restart и является следующим gate.

## Проверки

| Проверка | Результат |
|---|---|
| `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t1_byte_preserving_distribution_is_scoped_and_manifested tests/test_project_distribution_review_412.py tests/test_project_distribution_dirty_412.py` | `21 passed in 9.24s` |
| `uv run pytest -q tests/test_project_knowledge_distribution_412.py` | T1/T3 green; T4–T6 remain `xfail(strict=True)` |
| T3 named + Luna regression suite | `9 passed in 3.09s` |
| knowledge-focused regression set including T3 | `34 passed, 3 xfailed in 9.29s` |
| scratch authoritative activation | `18/18 projects`, `20,948/20,948`, receipt/state activation IDs equal |
| live CLI `--dry-run --probe-remotes` | planned, `20,948`, 18 projects, quarantine 0 |
| live CLI `--apply --probe-remotes` без `--commit` | prepared, `20,948`, 18 projects, quarantine 0 |
| live CLI `--verify --probe-remotes` | verified, `20,948`, 18 projects, quarantine 0 |
| `uv run pytest -q docs/tasks/412/acceptance/test_t2_live_distribution.py::test_t2_live_distribution_matches_frozen_manifest` | `1 passed in 113.27s` |

## Review

Чистый reviewer verdict по T1/плану не заявляется: Luna исчерпала разрешённый потолок раундов,
а последний артефакт остался `Incorrect/BLOCKED` до механических закрытий. Phase-3 gate и решение
продолжить после внешнего COG auto-sync принял оркестратор; это не переименовано в reviewer approval.

### T3 review inputs

- Changed: `app/ia/project_knowledge.py`, `app/ia/runtime.py`,
  `scripts/activate_project_knowledge.py`, T3 oracle. Consumers: `/api/knowledge`,
  `/api/memory/search`, process-global `knowledge_runtime_mode`, all 18 project folders and
  persisted `project-knowledge-owner.json`.
- Author metadata: `gpt-5.6-sol`, Codex runtime, `full-cycle`.
- AC: exact 18-project activation; failure leaves central state byte-identical; persisted global
  owner; cross-project read/write refusal; central fallback until T5; direct filesystem read of
  ignored/untracked Aperant; no foreign Git mutation.
- Oracle: T3 named test `1 passed in 2.25s`; knowledge-focused regression set
  `26 passed, 3 xfailed in 8.56s`; scratch live-ledger activation `18/18`, `20,948/20,948`;
  Aperant probe `ignored=True`, `tracked=False`, read/query stable ID identical.
- Route: shared process + persistent activation is high-risk. Sol review is technically preferred
  but no auxiliary Sol run was authorized; one Luna session used 3 evidence-backed rounds.
- Outcome: Luna ran 3 rounds (executable ceiling). Round 3 retained one new blocking receipt-conflict
  deletion bug; it was reproduced, covered by a RED regression and fixed mechanically after the
  ceiling. No clean reviewer verdict is claimed. Final T3/review command is green (`9 passed`).

## Следующий gate

T4 не начат. T5 central cleanup запрещён до positive live HTTP/MCP query from the merged/restarted
project-local runtime and subsequent T4 parity.
