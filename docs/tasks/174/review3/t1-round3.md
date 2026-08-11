# #174 T1 — третий и последний круг зрячего ревью

## Вердикт

**МЕРЖИТЬ.** В immutable commit `4d145e9ce2849f4f49d49414df561e2531c7ad22`
три блокера второго круга закрыты по существу. Новых блокеров и остатка, который нужно
выносить в отдельную задачу, не найдено. Четвёртый круг не нужен и по установленному
потолку не допускается.

## Проверка исправлений второго круга

### 1. Общий потолок tool history — закрыто

`_cap_claude_tool_entries()` считает размер сериализованного `entry["message"]` для
каждой группы с одним native tool ID. Группы перебираются от новых к старым, а при
нехватке остатка целиком не включаются. Поэтому в лимит входят payload, tool metadata,
truncation/omission markers и synthetic completion; половина call/result-пары не
остаётся. После фильтрации `parentUuid` пересобирается по фактически оставшимся entries.

Независимый стресс-прогон на точном blob `4d145e9` использовал 1 200 call/result-пар с
экранирование-ёмкими payload, которых нет в тесте автора:

```text
serialized_tool_chars=255910
cap=256000
whole_tool_entries=54
identity count for every retained native tool ID=2
```

Потолок выдержан с учётом JSON escaping. Все сохранённые записи остались полными
call/result-парами; часть старых пар была отброшена целиком.

### 2. Wrapped, whitespace и URL-safe base64 — закрыто

`_BASE64_CANDIDATE` принимает оба алфавита и пробелы, tab, CR/LF между символами.
`_sanitize(binary=True)` удаляет whitespace перед строгим decode с `altchars=b"-_"`.

Независимый пример отличался от авторского: 1 680 символов URL-safe base64 с реально
присутствующими `-` и `_`, разбивка по 61 символу, разделитель `CRLF + tab + два
пробела`. Нормализованная строка строго декодировалась в исходные байты; sanitizer
вернул один `[binary/base64 omitted]`, исходный wrapped payload в результате отсутствует.

### 3. Version-preflight cleanup — закрыто

В `ClaudeBackend.reconnect()` version preflight находится внутри `try`, а
`await self.disconnect()` — в `finally`. Независимый прогон подставил новый
`RuntimeError` из `_verify_history_versions()` при уже owned mock client:

```text
old client disconnect awaits=1
backend._client=None
preflight exception propagated unchanged
```

Старый Claude client отключается и ownership освобождается до выхода failure наружу.

## Разделение T1 и T2

Проверка выполнена по immutable commits, поскольку `HEAD` reviewer-worktree не является
проверяемой поставкой:

```text
$ git merge-base --is-ancestor 41f2ca4 4d145e9; echo $?
1
$ git merge-base --is-ancestor 41f2ca4 44fcda3c60c58aaed85d719077874fdc7000d2be; echo $?
0
$ git rev-parse task-174/t2-history-wip
44fcda3c60c58aaed85d719077874fdc7000d2be
```

T1 не содержит WIP-коммит `41f2ca4`, а сохранённый T2 ref содержит. В списке файлов
T1 diff нет `app/backend_codex.py` или `tests/test_backend_codex.py`. Имена
`CodexHistoryImport`, `render_codex_history`, `experimentalApi` и
`_change_to_codex_with_history_locked` встречаются только в добавленном тексте
`t1-report.md`, где их отсутствие заявлено; исполняемого T2-кода в поставке нет.

## Внешний Codex review

Единственный запуск третьего круга состоялся и дал `MERGE`: пять независимых проверок,
включая собственные sanitizer/reconnect примеры и стресс общего cap. Он получил
`252574 / 256000` сериализованных символов и 56 целых tool records.

Доказательство чтения артефакта — отсутствовавшая в запросе дословная строка:

```text
$ grep -F '+TOOL_VISIBLE_BUDGET = 256_000' /tmp/t1-r3.diff
+TOOL_VISIBLE_BUDGET = 256_000
```

Полный артефакт: [`codex-t1-round3.md`](codex-t1-round3.md).

## Объём проверки

Полный suite по прямому условию не запускался. Самостоятельно исполнены три узких
проверки на точном commit blob: общий cap/целостность пар, независимый URL-safe wrapped
base64 и cleanup version-preflight. Дополнительно проверены ancestry T1/T2,
список/символы diff и `git diff --check`. Blocking findings: **0**; неблокирующие
находки для отдельной задачи: **0**.
