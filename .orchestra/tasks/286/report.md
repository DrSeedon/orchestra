# #286 — Luna vs Spark: свежая очная ставка на закрытых задачах

## Вердикт

**На полностью закрытом one-file leaf Spark реально быстрее, но не доказан дешевле.** В двух
предрегистрированных реальных задачах Luna и Spark дали 2/2 PASS, сохранили frozen tests и в
каждой паре произвели побайтно одинаковый production diff. Spark закончил обе задачи быстрее:
суммарно 80.304 s против 112.138 s у Luna, то есть на 28.4% меньше wall.

Это не расширяет допуск Spark. Главный результат #222 остаётся несущим: при недостающем решении
Spark молча выдумал его 2/2 и оба раза провалил будущий oracle, тогда как Luna 2/2 остановилась и
спросила. Поэтому **Luna — максимальный/default исполнитель закрытых задач**, а Spark — только
latency/overflow lane, когда задача уже сжата до независимого механического oracle и в ней нечего
додумывать.

**Долларовый ответ односторонний:** Luna стоит $0.20 fresh-input / $0.02 cached-input / $1.20
output за MTok и две новые задачи дали $0.017845 API-equivalent. Официальная ставка Spark всё ещё
`research preview`, локально `price=None`; следовательно, «Spark дешевле в долларах» —
**UNKNOWN**, не `true` и не `$0`.[O2][O4][C1]

## Что переиспользовано, а не повторено

`data.json.reused_222` содержит все 20 confirmatory rows и SHA-256 исходного
`docs/tasks/222/blind-grades.json`. Ячейки #222 не запускались снова:

| Уже доказанная ячейка #222, N=2 на модель | Spark | Luna | Граница |
|---|---|---|---|
| Закрытый code fix | 2 PASS, median 38.98 s | 2 PASS, median 49.55 s | Spark на 21% быстрее |
| Точная semantic text edit | 1 PASS + 1 тихий PARTIAL | 2 PASS | внешний test не гарантирует полноту текста |
| Недостающая константа | 2 SILENT, future oracle 19/42 и 18/42 | 2 SAFE_LOUD question | любой missing decision запрещает Spark |
| Extraction ~102K | 2 PASS | 2 PASS | практическая ничья |
| Extraction ~164K | 2 LOUD_FAIL до ответа | 2 PASS | Spark держать с запасом ниже 128K |

Из #222 также переиспользованы totals: Spark 7,619,975 input / 135,699 output / 268 tools;
Luna 2,490,870 input / 21,312 output / 112 tools. Эти числа не смешиваются с новым N: корпуса и
даты разные.[M1]

## Новый протокол

Предрегистрация — commit `89d00a00d3b9b09731e0eb1910ebbba9e3ca6145`, до первого model
turn. Основа worktree — свежий `main` `43eb156a`. Две задачи появились после #222 и не участвовали
в старом стенде:

1. #272 `silence_mark_announced`: атомарно восстановить отсутствующую singleton-row; writable
   file `app/db.py`.
2. #277 `turn ended`: убрать quota/reset suffix, сохранив reason/turns/cost/context; writable file
   `app/session_turns.py`.

На каждую задачу создан отдельный seed из исторического base snapshot. В него наложен только уже
закоммиченный acceptance test. Из seed сделаны два `git clone --no-local`; обеим моделям переданы
одинаковые prompt, repo tree и effort `high`. Пара стартовала одновременно, каждый ход — fresh
`codex exec --ephemeral`, CLI `0.146.0`; retries не было.[M2]

До model turns exact commands были честно RED:

- #272: `1 failed, 1 passed`, `assert row is not None`;
- #277: `1 failed`, `assert "5h:" not in ended` при старом `Claude 5h:67% ...` suffix.

В seed и всех четырёх clones: `.git/objects/info/alternates` отсутствовал, future implementation
commit был недостижим через `git cat-file -e`, frozen test hash совпал с prereg. Harness запускал
model process с `InaccessiblePaths=/home/kesha/orchestra` и
`InaccessiblePaths=/home/kesha/orchestra-archive`; отдельного enforcement probe изнутри процесса
не было. В recorded commands нет leakage markers.[M2]

## Новые результаты side by side

Cold start — предрегистрированное время от запуска fresh процесса до первого model-generated
JSONL item. Client start — до первого JSONL event. `Tool fail` считает completed command с
non-zero exit/failed status либо MCP error.

| Задача | Модель | Frozen oracle | Wall | Cold start | Tools / fail | Input / cached / output | Virtual API-equivalent |
|---|---|---:|---:|---:|---:|---:|---:|
| silence-upsert | Luna | PASS | 52.593 s | 7.428 s | 7 / 0 | 170,474 / 149,504 / 1,522 | $0.00901048 |
| silence-upsert | Spark | PASS | **30.046 s** | 10.135 s | 4 / 0 | 93,202 / 80,384 / 1,615 | **UNKNOWN** |
| no-quota-suffix | Luna | PASS | 59.545 s | 6.792 s | 6 / 0 | 160,875 / 142,336 / 1,900 | $0.00883452 |
| no-quota-suffix | Spark | PASS | **50.258 s** | 6.586 s | 7 / 0 | 175,052 / 156,032 / 3,522 | **UNKNOWN** |

Обе внешние проверки после model turn зелёные (`2 passed` и `1 passed`), frozen hashes неизменны,
changed paths равны одному разрешённому production file. Cross-model diff SHA-256:

- silence-upsert: `64d6e1e9…` у обеих моделей;
- no-quota-suffix: `96179e9e…` у обеих моделей.

### Агрегат новых двух задач

| Метрика | Luna | Spark | Spark относительно Luna |
|---|---:|---:|---:|
| PASS | 2/2 | 2/2 | ничья |
| Wall total | 112.138 s | 80.304 s | **−28.4%** |
| Client first event, mean | 2.646 s | 2.627 s | практически ничья |
| Cold start, mean | **7.110 s** | 8.360 s | Spark +17.6% |
| Tool calls / failures | 13 / 0 | 11 / 0 | −15.4%; failures не случились |
| Input | 331,349 | 268,254 | −19.0% |
| Cached input | 291,840 | 236,416 | −19.0% |
| Fresh input | 39,509 | 31,838 | −19.4% |
| Output | **3,422** | 5,137 | Spark +50.1% |
| Virtual API-equivalent | $0.017845 | **UNKNOWN** | сравнение невозможно |

Spark выиграл wall в обеих парах: −42.9% на upsert и −15.6% на suffix deletion. Но выигрыш не
про cold start: в первой паре Spark начал первое model item на 36.4% позже, во второй — на 3.0%
раньше. Ускорение возникло в полном agent loop после начала работы. OpenAI отдельно предупреждает,
что duration складывается из inference, prefill, tools и network overhead; один TPS не предсказывает
end-to-end wall.[O1][O3]

Tool-call failures получены 0 против 0. Это честный результат измерения, но **не доказательство
равной обработки tool failure**: ни один из четырёх ходов не встретил отказавший tool.

## Цена

Официальная публичная страница Luna существует; Luna не является непубличным внутренним именем.
Она описана как модель для cost-sensitive high-volume workloads и сейчас публикует цены
$0.20 / $0.02 / $1.20 за MTok fresh/cached/output. Эти же ставки стоят в
`app/backend_codex.py::CODEX_TOKEN_PRICES`.[O2][C1]

Если **только для sensitivity** оценить Spark-трейсы ставками Luna, получится:

- silence-upsert: $0.00610928 против Luna $0.00901048 (−32.2%);
- no-quota-suffix: $0.01115104 против Luna $0.00883452 (+26.2%);
- сумма: $0.01726032 против $0.017845 (−3.3%).

Разнонаправленные задачи и −3.3% на N=2 не дают даже устойчивого token-cost преимущества. Главное:
это **не цена Spark**. Codex rate card всё ещё помечает все Spark token rates как research preview /
not final, а локальный runtime хранит `None`.[O4][C1]

Отдельный Spark wallet тоже не бесплатен: официальный анонс называет его отдельным preview rate
limit, который может меняться с demand. Его ёмкость этот минимальный replay не калибровал.
Поэтому правильное утверждение — «Spark переносит узкий latency-sensitive leaf в отдельный
конечный wallet», а не «Spark дешевле» или «Spark удваивает ёмкость».[O1]

## Публичное предназначение моделей

| Модель | Первичный публичный owner claim | Что подтверждает наш стенд | Что стенд не подтверждает |
|---|---|---|---|
| Spark | Research preview для real-time coding: targeted edits, reshaping logic, refining interfaces; text-only 128K, lightweight style, tests не запускает автоматически без просьбы; отдельный rate limit | три закрытые code-задачи (#222 + две новые) прошли, и Spark был быстрее во всех трёх | универсальную замену Luna, semantic completeness, безопасное поведение при missing data, долларовую экономию |
| Luna | Публичная GPT-5.6 для cost-sensitive high-volume workloads; public API 1.05M context и цены $0.20/$0.02/$1.20 | известная низкая цена; безопасная остановка 2/2 на missing decision; все новые closed tasks PASS | перенос public API 1.05M на ChatGPT-auth CLI: локальный effective limit остаётся 258.4K |

Product claims принадлежат разным surfaces: Spark описан прежде всего внутри Codex preview, Luna —
на API model page. Routing опирается на наши CLI measurements, а не переносит API context limit.

## Конкретная таблица маршрутизации

| Признак ДО спавна | Маршрут | Почему |
|---|---|---|
| Один writable Python file; все решения и значения заданы; frozen independent test механически покрывает каждый critical criterion; короткий task prompt; существующий ≤100K gate проверен отдельно до спавна; важен wall либо основной Codex wallet binding | **Spark допустим** | 2/2 новых fixtures PASS и на 15.6–42.9% быстрее; старый #222 code cell согласуется |
| Та же закрытая задача, но цель — доказанная долларовая экономия или большой устойчивый throughput | **Luna default** | Luna имеет опубликованную низкую цену; Spark dollar rate UNKNOWN, preview wallet отдельный и конечный |
| Два writable files или initial context приближается к 100K | **Luna default; Spark только как lower-confidence overflow по существующему gate** | #222 дал лишь один успешный two-file code cell и отдельную 102K extraction cell; новый replay эту границу не подтвердил |
| Не задана хотя бы одна correctness-critical константа/формула/политика | **Luna**, с инструкцией спросить | #222: Luna спросила 2/2, Spark молча выдумал 2/2 |
| Semantic prose/prompt edit без literal/per-criterion oracle | **не Spark; Luna только если задача всё же закрыта**, иначе Sol/Opus | #222: Spark тихо потерял обязательный факт при зелёном targeted suite |
| Initial context около 100K только для extraction | **Luna default; Spark лишь при latency/overflow** | 102K: 2/2 обе, wall практически равен; преимущества Spark не было |
| Initial context >100K или задача tool-heavy и может дорасти до 128K | **Luna** | 164K: Spark громко отказал 2/2; запас нужен до старта |
| Research, review, architecture, security, vision, открытая постановка | **ни Luna, ни Spark: Sol/Opus по routing** | вне измеренного closed-leaf класса и вне заявленного предназначения Spark |
| Spark-run не завершён или oracle красный | **не retry Spark; Luna/Sol** | повтор Spark после раскрытого failure не добавляет информации и тратит маленький wallet |

Итого: **Luna использовать максимально как дешёвый и безопасный default закрытой работы. Spark
реально лучше только по end-to-end wall на предельно закрытых leaf; реальной долларовой дешевизны
не установлено.**

## Режимы ошибок

Все четыре новых хода прошли frozen oracle и scope checks: 4/4 PASS, false-success 0,
tool failure 0. Узкие tests не исключают unrelated semantic errors. Новый стенд не меняет
failure-mode boundary, а только подтверждает, что внутри измеренного one-file класса корректная
работа существует и Spark там действительно быстрее.

Нагрузочный риск остаётся асимметричным:

- Spark при missing decision может завершиться **тихо неправильно**;
- Luna в измеренной ячейке завершилась **громким вопросом**;
- Spark у context ceiling завершился **громким pre-output failure**, а не тихой порчей.

## Ограничения и counter-evidence

1. Новый N=2 задач. Это routing probe, не оценка population accuracy или p-value.
2. Обе задачи — one-file Python изменения с сильными tests. Multi-file, frontend, migrations,
   review и prose не обобщаются.
3. Cold start измеряется до первого completed model-generated JSONL item, не до первого
   streaming token; Codex JSONL не выдаёт token timestamps.
4. 0 tool failures означает отсутствие события, а не доказанную устойчивость к нему.
5. Две Spark-задачи дали противоположный Luna-priced token sensitivity (−32.2% и +26.2%).
6. Strict physical answer-unreachability опять не доказана глобально. Доказаны standalone Git
   store и отсутствие future object; harness настроил parent roots как inaccessible, а recorded
   commands не показывают fetch/leakage, но исполнение запрета изнутри процесса не проверялось.
   Сеть нужна Codex API, остальной HOME доступен. Это та же граница, что честно записана в #222.
7. Публичный API context Luna 1.05M не является контекстом этого CLI surface; локальный owner
   фиксирует 258,400.[O2][C1]

## Confidence

- **CONFIRMED на новых двух fixtures:** обе модели 2/2 PASS, exact diff pairs identical, Spark wall
  ниже в обеих парах — tier 1 direct measurement.[M2]
- **CONFIRMED:** Spark dollar price неизвестна, Luna public price известна — две primary public
  pages плюс текущий source.[O2][O4][C1]
- **CONFIRMED на #222 ambiguous cell:** Spark silent 2/2, Luna asked 2/2 — reused preregistered
  measurement.[M1]
- **LIKELY, не confirmed globally:** Spark быстрее на полностью closed leaf — три measured code
  tasks согласуются, но корпус мал и однороден.[M1][M2]
- **UNKNOWN:** кто лучше восстанавливается после реального tool-call failure — событий 0/0.

## Артефакты и источники

- **[M1], tier 1:** `docs/tasks/222/blind-grades.json`, SHA-256
  `27745fe6bffbde79c6c771893525b6b9216245b050bb64c11ce134e5f683f477`; полный старый корпус
  также вложен в `data.json.reused_222`.
- **[M2], tier 1:** `docs/tasks/286/data.json`, SHA-256
  `9d9e212a924dd91aec5247c66d4301f0ac4641ca274f9bde3b154763f8d2c11a`; четыре новые runs,
  fixtures, RED tails, full production patches + SHA-256, finals и token/tool/wall/cold-start
  metrics.
- **[C1], tier 2:** `app/backend_codex.py`: Spark context 128,000 / price `None`; Luna effective
  context 258,400 / price `0.2, 0.02, 1.2`.
- **[O1], tier 2:** https://openai.com/index/introducing-gpt-5-3-codex-spark/
- **[O2], tier 2:** https://developers.openai.com/api/docs/models/gpt-5.6-luna
- **[O3], tier 2:** https://openai.com/index/speeding-up-agentic-workflows-with-websockets/
- **[O4], tier 2:** https://help.openai.com/en/articles/20001106

`research-limit-truth` для #285 отправлен напрямую после проверки data JSON и до написания этого
синтеза. Runtime, config, service и live DB не менялись.
