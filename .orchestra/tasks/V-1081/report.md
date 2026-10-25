# V-1081 — native Codex limit continuation

Реализовано в выданной Gitless-копии. Изменены только `app/backend_codex.py`,
`app/session.py`, `app/limit_wake.py`, `app/quota_queue.py`, `app/manager.py`,
`tests/test_codex_limit_resume_v1081.py`, `tests/test_codex_quota_103.py`,
`CHANGELOG.md` и материалы этой задачи. Compact-методы и `session_hibernate.py`
V-1079, `db.py`/routes V-1078 и limits-card/TG V-1082 не изменялись.

## Проверенный разрыв и изменение

1. Backend передавал `codex_quota_exhausted` в отдельном error-событии, но терял его
   при ошибке только в `turn/completed`. Session выставляла `_session_limit_hit`,
   однако сохраняла лишь текст ошибки; поиск limit-wake требовал `provider_limit`.
   Теперь сохраняется структурированный отказ с native turn ID и привязкой
   модели, native session, задания и ветки. Слова ассистента не считаются отказом.
2. Поиск последних ходов у сессии с единственным terminal-record начинал чтение
   с этого record и терял сам отказ. Исправлена граница индексной выборки.
3. UUID продолжения определяется Orchestra session + native session + native turn,
   поэтому повтор terminal-события не создаёт вторую доставку. Используется
   существующая `message_deliveries` с первоначальным `WAITING_QUOTA`. Принятие
   переживает debounce; уже работающий quota-sweep восстанавливает пропущенное
   принятие после падения. Дополнительных таблиц, сервисов и poll-таймеров нет.
4. Перед release и повторно перед send проверяются fresh provider capacity и
   обычный weekly admission, включая оркестраторов/system provenance. Прошедшее
   время reset при оставшихся 100%, неизвестное окно, неуспешный refresh или
   отсутствие запрошенного provider не разрешают продолжение. Свежая реальная
   ёмкость допускает ранний reset. Неизвестный reset не теряет очередь. Исходные
   provider windows тоже проверяются: display-проекция могла отбросить malformed
   второе окно. Spark использует свой существующий bucket, не ёмкость Codex.
5. Проверки до автосмены задания и под lifecycle lock после await отсекают Stop,
   новое принятое пользовательское/агентское сообщение, archive, закрытое задание,
   смену модели/native session/ветки/task/turn generation. Stop до terminal-record
   тоже сохраняет силу после рестарта. Incidental platform notices не создают
   работу. Неоднозначная отправка остаётся за существующим delivery owner и не
   повторяется. Метка ожидания читает очередь, не обещает несуществующий таймер.

Claude timer/retry-путь и честный текст V-1035 сохранены. Изменение существующего
test_codex_quota_103 усиливает проверку новой структурированной записи; старый
текст reset/no-retry по-прежнему проверяется. Frozen receipt-тесты не изменялись.
Все доказательства синтетические; выводов о причине конкретного исторического
производственного сбоя здесь нет.

## Проверки и stdout

Раннер: provisioned **uv 0.11.28**, default `.venv`, `--frozen`, `nice -n 15`.
В каждом shell установлен PATH из задания и TMPDIR внутри этой задачи.
Импортированное приложение:
`/home/<publication-runtime-redacted>/orchestra-ws/vmi3407579/hub-77dea0e3499944e1/app/__init__.py`.
Точный interpreter и версия — [runner.stdout](runner.stdout).

Команда окончательного прогона (exit **0**, **721 passed, 21 subtests passed**):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1081/tmp"
nice -n 15 uv run --frozen python -m pytest tests/test_codex_limit_resume_v1081.py tests/test_limit_wake.py tests/test_interruption_honest_v1035.py tests/test_codex_quota_103.py tests/test_quota_wait_queue.py tests/test_message_delivery_receipts_380.py tests/test_backend_codex.py tests/test_session.py tests/test_usage_readiness.py tests/test_quota_map_api.py tests/test_cron_drain_delivery_v1074.py tests/test_delivery_head_of_line_block.py tests/test_delivery_queue_block_connection.py tests/test_instruction_contract.py tests/test_quota_gate.py tests/test_durable_steering_562.py -q
```

Дословный вывод — [required.stdout](required.stdout). В новых тестах проходит
реальная цепочка backend notification → AgentSession event/terminal handling →
индексный поиск → auto scheduler → durable acceptance → quota release →
SessionManager → AgentSession.send → синтетический backend. Проверены Sol/Luna/
Spark, worker/orchestrator, terminal-only error, повтор события/планировщика,
повторный настоящий limit, crash до acceptance, recovery очереди, uncertain
submission, failure-before-submit, Stop во время awaited admission, completed/
cancelled task, новое уже принятое сообщение, неизвестные/несколько окон,
старая метадата, ранний reset и обычный разрешённый пользовательский ход.

## Отказы проверок

- `uv run --frozen python .orchestra/tasks/V-1081/reproduce_old_gap.py`:
  ожидаемый exit **1**, **16 failed, 1 passed**. Скрипт возвращает исходные два
  разрыва только в памяти процесса (нет `provider_limit` и старое generic-решение
  readiness для Codex); новый suite действительно краснеет, обычный user-send
  остаётся зелёным. Это surgical defect restoration, а не полный исторический
  checkout: `.git` в копии нет. Дословно: [old-gap.stdout](old-gap.stdout).
- `uv run --frozen python scripts/check_instruction_contract.py`: exit **1**,
  `CLAUDE.md must be a symlink to AGENTS.md`. В выданной копии `CLAUDE.md`
  отсутствует; файл не удалялся и корневые инструкции не правились. Fixture-тесты
  самого checker прошли в общем прогоне. Полную проверку канонического checkout
  должен повторить root: [contract.stdout](contract.stdout).

## Ограничения и передача root

- Legacy text-only Codex refusal либо запись без native turn ID/task binding не
  разрешает безопасно установить владельца прерванного хода. Такие записи не
  воспроизводятся автоматически. Для старого уже оборванного хода без этих
  доказательств требуется явное продолжение владельцем/root.
- `FAILED_BEFORE_SUBMIT` сохраняет существующую терминальную семантику receipt;
  он не объявляется доставленным. `DELIVERY_UNKNOWN`/orphaned и cancelled receipts
  не получают нового ID и не переигрываются. Автоповторов provider work нет.
- Гарантия fresh опирается на существующий `current_provider_usage(force_refresh=True)`:
  его реальные transport/CLI не запускались. Offline-тесты подменяют только внешнюю
  границу и фоновые уведомления; полная production-система не тестировалась.
- Полный `scripts/run_tests.py` не запускался; выполнены перечисленные необходимые
  и смежные suites. Gitless-копия не позволяет проверить diff к точному main.
  Root принимает diff, совмещает V-1079 и повторяет canonical instruction contract,
  затем владеет merge/push/CI/idle-watcher activation. Коммитов, push, deployment,
  SSH, live providers, боевой БД, `.env`, NOTIFY_SOCKET и рестартов здесь не было.

Артефакты содержат только синтетические stdout/код и этот отчёт. Временные БД и
pytest-каталоги удалены из результата; проверка формы секретов записана отдельно
в `artifact-scan.stdout`.

## Правка по приёмке: дискриминант limit_wake (root review)

Дефект: `manager.send_message_delivery`, `session.send` и `quota_queue.release_waiting` применяли Codex-валидатор/допуск ко всякому `subtype=limit_wake`, включая Claude-таймер (`uuid4`-ref). Теперь владелец определяется долговечной записью: `limit_wake.is_codex_wake_ref(ref)` — есть `message_deliveries` с `delivery_id=ref` и `source_principal='limit_wake'` (создаёт только `queue_codex_limit_wakes`). Не по текущему backend: старая Codex-квитанция после смены на Claude остаётся Codex-владения и отклоняется (CANCELLED). Добавлены 3 теста (реальные SessionManager/AgentSession): Claude прямой таймер, Claude WAITING_QUOTA e2e, старая Codex-квитанция после смены модели. Без правки первые два краснеют (`red-claude-regression.stdout`); после — `required.stdout`: 715 passed, 21 subtests (без test_instruction_contract: нет CLAUDE.md в копии). Старые простые платформенные ошибки «квота Codex исчерпана…» без native turn ID автоматически НЕ возобновляются. Не запускались: контракт инструкций (корень).

## Root integration acceptance

Actual three-way integrated tree includes merged V-1079 compact fix, V-1080 and V-1078. Frozen uv host selection plus compact oracles: 819 passed, 21 subtests. Canonical instruction contract passes. Imported app is /tmp/orc-v1081-integration-20261025/app/__init__.py (private detached acceptance tree, not a publishable merge commit). Root in-memory old-gap restoration fails 16 committed cases; forcing every limit_wake through Codex fails both real Claude positive paths; removing durable binding validation fails the changed-model cancellation oracle. No real providers, restart or historical text-only wake replay was run. Public raw stdout paths are labelled derivatives with hashes; exact originals retained privately.
