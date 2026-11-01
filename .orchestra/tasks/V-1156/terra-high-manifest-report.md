# V-1156 — Terra High manifest READY

Обе роли `orchestrator` / `sub-orchestrator` теперь выбирают native `gpt-6.1-terra` и **явный `high`** из карты effort. English `model-routing` отражает выбор владельца и сохраняет запреты native workers. Ручной explicit model имеет приоритет; общий `defaults.model`, worker/full-cycle/reducer models, hub routing, manual-only, защищённая Luna, quota и billing не изменены. У reducer уже была общая карта effort: новый exact Terra High равен прежнему fallback High, admission не расширяется.

Reading order: diff `pipeline.yaml` → `model-routing.md` → новый `tests/test_orchestrator_terra_manifest_v1156.py`; затем неизменённые callers `CreateSessionRequest.validate_worktree`, `list_models`, `pipeline.resolve_effort`, runtime factory. Изменения: YAML +4/-3, routing +14/-5, новый behavioral test +100, CHANGELOG +2. Старый `report.md` не редактировался; V-1166 не импортировалась. Ни один product Python/frontend/catalog/backend файл не менялся.

## Фактические проверки

Provisioned **uv 0.11.28**, `uv run --frozen python -m pytest`, locked default `.venv`, `UV_OFFLINE=1`; TMPDIR/basetemp и пустой synthetic CODEX_HOME — вне checkout. NOTIFY_SOCKET снят; для lifespan-тестов использована shell-local synthetic Git identity, без изменения Git config. Imported app:

`worker-copy/app/__init__.py`

- **До правки:** новый файл — **3 failed / 8 passed**, 10.34 s: обе роли и API всё ещё выбирали Opus. Это ожидаемый red, не скрыт.
- **После правки:** `tests/test_orchestrator_terra_manifest_v1156.py tests/test_orchestrator_defaults_v1156.py tests/test_default_pipeline.py tests/test_local_luna_route.py tests/test_model_gates.py tests/test_instruction_contract.py` — **113 passed / 0 failed / 0 skipped**, 25.82 s; `-q --tb=short --timeout=20`. Покрыты реальные manifest → request → native Codex backend/High без inference, API default и visibility, explicit Sol/Sonnet/Luna, worker defaults/admission, защищённая Luna, billing refusal, prompt assembly и instruction-contract mechanics.
- **4/4 мутации пойманы** тестами, включёнными в source result: Terra→Sol; High→Low; удаление exact Terra key при сохранённом fallback High; Terra в worker/full-cycle default. Каждая дала ожидаемый behavioral FAILED/RC1, YAML восстановлен byte-for-byte в finally. После восстановления новый файл: **11 passed**, 9.04 s, без skipped/failed.
- `uv run --frozen python scripts/check_instruction_contract.py` — **RC1**: `CLAUDE.md must be a symlink to AGENTS.md, not a copy`. По отдельной проверке формы пути в этой broker-копии `CLAUDE.md` отсутствует (`exists=false`, `is_symlink=false`); формулировка checker не доказывает существование обычной копии. Файл правил не менялся. Контракт остановился на этом первом нарушении, downstream проверки полного root не подтверждены. Отдельно прочитанная ссылка AGENTS на `.orchestra/rules-model-defaults.md` отсутствует в предоставленной копии; новую политику взамен не создавал.
- Просмотрен scoped diff из сохранённых исходных байтов; Python AST и `git apply --numstat` успешны. YAML semantic check: изменены только модели двух orchestrator roles и exact Terra High key; global defaults и worker/full-cycle declarations идентичны. SHA-256 неизменённых product Python/JS/catalog/backend/quota/session и прежнего `report.md` совпали. Проверены все 4 изменённых source/test файла по формам ключей/токенов: совпадений и ошибок чтения нет.

Полный 7k suite, browser, модельное ревью и реальные model calls не выполнялись; новый CI ещё не проверен. Model review frozen. Raw outputs маленькие, только task-local ignored `private/terra-high-manifest/`: `before.log`, `targeted.log`, `mutation-*.log`, `mutations.json`, `restored.log`, `instruction-contract.log`, `source.diff`, `source-hashes.json`, `scope-check.log`, `secret-form-check.json`, `import-path.log`. DB/tar/credentials в артефакты не копировались; synthetic test basetemp остаётся вне checkout и не входит в результат.

## Границы активации и выводы

Родитель сообщил о завершённом единственном VPS restart на принятом main `a215` и независимо подтверждённом live API Terra/OpenAI Codex. Это основание разрешённого source-этапа, **не повторно проверенный здесь host receipt**. Одновременная готовность offline laptop для VPS default больше не требуется. Offline host должен сначала активировать Python registry на safe bootstrap с OLD YAML, подтвердить live Terra, затем получить новый manifest. Никакого deploy/pull/restart, orchestrator API или миграции живых сессий этот worker не выполнял.

**Open question для приёмки:** проверить настоящий root instruction contract в canonical checkout; локальный RC1 broker shape и отсутствие переданного rules-файла не выдаются за поломку canonical main. Других must-fix findings в выполненных source checks нет. Runtime rollout существующих оркестраторов остаётся у родителя/local executor.

Source-only copy без `.git`: commit, clean WIP и настоящий branch diff здесь подтвердить невозможно; платформа коммитит source result, parent принимает/мержит/push. Замена default в исходниках не доказывает изменение работающих сессий.

SHA-256:

| Файл | После |
|---|---|
| `.orchestra/pipelines/default/pipeline.yaml` | `4ba444771a5fa8decc59d3b138d9bb2e7d57dec60b877848360a3a5ce709f223` |
| `.orchestra/pipelines/default/prompts/modules/model-routing.md` | `e8f713e6d8ee236eb64559c7fe7a272778cd546c522b09350f647c69c053dda4` |
| `tests/test_orchestrator_terra_manifest_v1156.py` | `e96b0d54180c0fe88b47dc24e24cde7c76c16fc7c90934b1ab39b6a35c45d77e` |
| `CHANGELOG.md` | `d7be916e1f1237a9192684961804a0439b1d8a8a802cf65e427ff59e147afddd` |
