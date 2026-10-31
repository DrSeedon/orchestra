# V-1150 — воспроизведение

Все команды — из корня копии. Никаких credentials/live provider calls.

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
mkdir -p .orchestra/tasks/V-1150/tmp .orchestra/tasks/V-1150/private
export TMPDIR="$PWD/.orchestra/tasks/V-1150/tmp"
uv --version
uv run --frozen python -m pytest \
  tests/test_codex_compact_delivery_1150.py \
  tests/test_codex_compact_ui_1150.py \
  tests/test_codex_compact_state.py tests/test_backend_codex.py \
  tests/test_codex_usage.py tests/test_compact_receipt_and_tail.py \
  tests/test_compact_pending_ack_467.py tests/test_compact_pending_rollback_467.py \
  tests/test_compact_gate_438.py tests/test_double_compaction_v1026.py \
  tests/test_session.py tests/test_mcp_codex_review.py \
  -k 'codex or compact or hibernate or interrupt' -q \
  --basetemp=.orchestra/tasks/V-1150/pytest-tmp-final2 \
  > .orchestra/tasks/V-1150/private/final-tests-2.txt 2>&1
node --check app/static/js/app.js
node tests/test_codex_compact_ui_1150.cjs
uv run --frozen python scripts/check_instruction_contract.py \
  > .orchestra/tasks/V-1150/private/instruction-contract.txt 2>&1
uv run --frozen python -c "import runpy; runpy.run_path('.orchestra/tasks/V-1150/verify.py', run_name='__main__')" \
  > .orchestra/tasks/V-1150/validation.txt 2>&1
uv run --frozen python -c "import runpy; runpy.run_path('.orchestra/tasks/V-1150/mutation_probe.py', run_name='__main__')" \
  > .orchestra/tasks/V-1150/private/mutation-summary.txt 2>&1
uv run --frozen python -m pytest tests/test_codex_compact_delivery_1150.py \
  tests/test_codex_compact_ui_1150.py -q \
  --basetemp=.orchestra/tasks/V-1150/pytest-tmp-restored \
  > .orchestra/tasks/V-1150/private/restored-tests.txt 2>&1
uv run --frozen python -c "import runpy; runpy.run_path('.orchestra/tasks/V-1150/verify.py', run_name='__main__')" \
  > .orchestra/tasks/V-1150/validation.txt 2>&1
```

Текущий probe по умолчанию последовательно возвращает шесть дефектов, запускает новые
behavioral tests штатным frozen uv/conftest и в `finally` восстанавливает исходные
байты каждого source. Его собственный успех означает ожидаемые красные tests
на мутациях; не означает зелёный pytest мутированной программы. После probe
надо снова сверить final source hashes и выполнить чистые новые regression tests.

Первые baseline tests запускались той же provisioned uv командой на
`tests/test_codex_compact_state.py tests/test_backend_codex.py -q`, с task-local
`--basetemp`, до изменения production. Для последующих запусков TMPDIR также
направлен внутрь task directory: actual conftest создаёт catalog уже при импорте.
Промежуточные выводы сохранены без редакции в `private/`.

Первый baseline ещё не задавал TMPDIR: import-time conftest создал пустой catalog
в системном temp. Этот каталог не публиковался и не удалялся за границей проекта;
последующие прогоны используют только task-local TMPDIR/basetemp.

## Приёмочная доработка

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1150/tmp"
# Red до исправления supported immediate overlap:
uv run --frozen python -m pytest tests/test_codex_compact_immediate_1150.py \
  -k 'result or supported_model_change' -q \
  --basetemp=.orchestra/tasks/V-1150/pytest-tmp-immediate-before \
  > .orchestra/tasks/V-1150/private/immediate-before.txt 2>&1
# Green: новые regressions + релевантный session subset:
uv run --frozen python -m pytest tests/test_codex_compact_delivery_1150.py \
  tests/test_codex_compact_immediate_1150.py tests/test_codex_compact_ui_1150.py \
  tests/test_session.py \
  -k 'codex_compact or codex_manual_compact or codex_native_compact or precompact_timer or codex_post_turn_compacts' \
  -q --basetemp=.orchestra/tasks/V-1150/pytest-tmp-review-revision \
  > .orchestra/tasks/V-1150/private/review-revision-tests.txt 2>&1
uv run --frozen python .orchestra/tasks/V-1150/mutation_probe.py \
  --only immediate_freshness \
  > .orchestra/tasks/V-1150/private/review-mutation-summary.txt 2>&1
uv run --frozen python -m pytest tests/test_codex_compact_delivery_1150.py \
  tests/test_codex_compact_immediate_1150.py tests/test_codex_compact_ui_1150.py -q \
  --basetemp=.orchestra/tasks/V-1150/pytest-tmp-review-restored \
  > .orchestra/tasks/V-1150/private/review-restored-tests.txt 2>&1
uv run --frozen python -c "import runpy, sys; sys.argv=['verify', '--record-current']; runpy.run_path('.orchestra/tasks/V-1150/verify.py', run_name='__main__')" \
  > .orchestra/tasks/V-1150/validation.txt 2>&1
```

`--record-current` явно регистрирует identity новой намеренной ревизии после её
тестов. Без него verifier запрещает расхождение production/test bytes с ранее
зарегистрированной ревизией. Manifest первой зелёной версии сохранён отдельно в
`private/initial-green-source-sha256.txt`; он не подменяется новым результатом.
