# #113 — отчёт реализации

Дата: 2026-08-01.

## Итог

Задача предложила три оптимизации и сняла все три после измерений:

| Тикет | Решение | Почему |
|---|---|---|
| T1, batch 64→16 | снят, default остался 64 | batch size детерминированно меняет embeddings и реальную hybrid-выдачу |
| T2, embedder child + idle exit | снят | 0 GiB active gain, ≤0.21 GiB time-weighted gain в busy trace не окупают отдельный процесс/IPC |
| T3, automatic orphan reaper | снят | stale numeric PGID может принадлежать чужой новой group; race-free supervisor равен по сложности отклонённому T2 |

Отрицательный результат тикетов не является отрицательным результатом задачи:

1. Владелец памяти доказан: текущий bge-m3 ONNX embedder добавил в среднем
   **0.8900 GiB `PSS+SwapPss`** в четырёх изолированных прогонах; unload+trim
   возвращал **0.8179 GiB / 91.90%**. Подробные raw numbers — в `plan.md`.
2. Версия «main PID держит гигабайты в историях 100 сессий» опровергнута:
   persisted prompts+summaries+history занимали **1.86 MiB**, а не GiB (`research.md`).
3. Из production удалён уже существовавший опасный post-exit `killpg` по stale
   числовому PGID; вместо автоматики добавлен warning-only детектор сирот.
4. Составлена карта остальных мест отправки сигналов для отдельных задач.

## Реализовано

- `app/bg_jobs.py`: после завершения leader сканируется его Linux process session.
  Если остались процессы, пишется структурированный warning:
  `orphan_tree=1 session=<sid> processes=<N> oldest_process_age_seconds=<age> observation_only=true`.
- Путь с inherited-open stdout больше не посылает TERM/KILL: reader отсоединяется,
  transport закрывается, job продолжает обычную validation/notification семантику.
- `tests/test_bg_jobs.py`: integration test воспроизводит leader exit + sleeping child
  с открытым stdout. `os.killpg` заменён на hard-fail mock, поэтому тест одновременно
  доказывает наличие warning и отсутствие сигнала.

Ограничение observability: `oldest_process_age_seconds` — полный возраст старейшего
процесса, не время с момента orphaning. Warning снимает snapshot сразу после завершения
job; он не является периодическим reaper/monitor и намеренно ничего не убивает.

## T1: A/B качества batch 64 против 16

Критерии были записаны до запуска: 33 реальных чанка, 20 последних уникальных реальных
запросов `search_memory`, одинаковая модель и размерность; pass требовал max component
delta ≤`1e-5`, min cosine ≥`0.999999` и 20/20 одинаковых ordered top-5.

Первый probe провалил numerical gate: max `|Δ|=0.0296734`, minimum cosine `0.9718105`,
mean cosine `0.9798435`. Текущий production index дал 20/20 одинаковых top-5, но это
не доказательство: он уже построен batch64, а query embedding всегда имеет batch size 1.

Falsifier отделил batch effect от недетерминизма:

| Сравнение, 17 реальных chunks | max `|Δ|` | min cosine | mean cosine |
|---|---:|---:|---:|
| batch64 против повторного batch64 | 0 | ≈1.0 | 1.0 |
| batch16 против повторного batch16 | 0 | ≈1.0 | 1.0 |
| batch64 против batch16, run 1 | 0.0281301 | 0.9719969 | 0.9798335 |
| batch64 против batch16, run 2 | 0.0281301 | 0.9719969 | 0.9798335 |

Практический falsifier построил baseline и пять 50/50 mixed old64/new16 индексов на
128 реальных baseline hits. На тех же 20 запросах mixed hybrid RRF сохранил exact
ordered top-5 только для **3–7/20**, top-1 для **17–19/20**, mean overlap@5 —
**0.91–0.94**. Полный batch16 дал exact top-5 **3/20**, top-1 **17/20**,
overlap@5 **0.88**. Семантика не исчезла: baseline top-1 оставался в candidate top-20
для 20/20 запросов во всех splits, но ранжирование сдвинулось измеримо.

Вывод: за transient ceiling около 0.8 GiB нельзя покупать mixed-index drift или полный
backfill 441-MiB базы. `app/rag.py` не изменён, default остаётся 64. Raw результаты и
точный query set сохранены в `quality-ab.json`.

## Почему T3 снят

Первый implementation review нашёл две гонки:

1. после reap leader сохранённый numeric PGID может быть переиспользован чужой новой
   process group до `killpg`;
2. outer timeout/cancellation может оборвать TERM→KILL escalation и оставить descendants.

Race-free вариант требовал supervisor-wrapper на каждый run: отдельный процесс, новый
режим запуска и новый класс отказов. Это сложность уровня уже отклонённого T2 при
**0 GiB active gain**, поэтому automatic reaper снят. Принят warning-only detection.

## Опасные сигналы: найдено, исправлено, оставлено

### Исправлено в #113

- Старый terminal path `app/bg_jobs.py` после leader exit ждал stdout 2 секунды, затем
  делал `killpg(proc.pid, SIGTERM)` и позже SIGKILL. `proc.pid` к этому моменту был stale
  integer: при исчезновении исходной group тот же PGID мог получить чужой новый процесс,
  поэтому Orchestra могла убить не своё ревью. Этот kill удалён; текущий observation-only
  путь находится в `app/bg_jobs.py:715-733` до финальной нумерации коммита.

### Найдено, не изменено

- `app/bg_jobs.py:118-127`, `_kill_proc()`: пока `returncode is None`, получает
  `os.getpgid(proc.pid)` и отдельно вызывает `killpg` TERM/KILL. Окно TOCTOU существенно
  уже удалённого post-exit пути, но требует отдельного lifecycle-плана.
- `app/ssh_tunnel.py:72-84`, `_kill_stale()`: `pkill -f` по собранному шаблону полной
  командной строки SSH. Это не stale numeric PID, но broad full-command matching может
  задеть чужой процесс пользователя; выделено как более приоритетный отдельный аудит.

### Проверено, другой класс

- `terminate()/kill()` по живым process handles: `app/ssh_tunnel.py:168,172,226,232`,
  `app/backend_codex.py:462,466`, `app/backend_grok.py:511,515`,
  `app/backend_opencode.py:632,636`, `app/routes/sessions.py:620`,
  `app/routes/system.py:660,666`.
- `app/routes/system.py:1067`: `os.kill(os.getpid(), SIGINT)` адресован текущему service PID.

Эти места перечислены для карты, но не относятся к доказанному stale-PGID post-exit багу
и в #113 не менялись.

## Проверка

- Focused: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_bg_jobs.py`
  → **27 passed in 3.86s** под `nice -n 15`.
- Cancellation + off-loop scan focused rerun: **2 passed in 2.59s**.
- Full suite под глобальным test lock и `nice -n 15`:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`
  → **1323 passed, 7 skipped in 115.81s** (`/tmp/pytest-113.log`, exit 0).
- Глобальный test lock освобождён сразу после чтения результата.
- Codex review: Round 1 нашёл stale-PGID/cancellation races; Round 2 подтвердил P1
  fixed и нашёл cancellation transport leak + event-loop scan. Оба P2 и non-ASCII P3
  исправлены и покрыты тестами. Round 3 истёк по инфраструктурному timeout без review
  message и **не считается APPROVED**; partial sandbox hang `asyncio.to_thread` локально
  не воспроизвёлся (1.1 ms до clean close). Полная история — `codex-review-impl.md`.

## Совместимость и эксплуатация

- Restart/reboot не выполнялись.
- RAG model/schema/index/default не изменены; reindex не нужен.
- Breaking API/DB changes: нет.
- Поведение изменилось только для completed bg run с оставшимися descendants: Orchestra
  теперь логирует их и не пытается автоматически убить по недостоверной числовой identity.
