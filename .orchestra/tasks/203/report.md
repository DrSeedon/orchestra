# #203 — маршрутизация после замера #199: Luna на закрытые, Sol на открытые, Terra убрана

Правка одна: `pipelines/default/prompts/base.md`, блок `<model-routing>` (+877 Б, 1249 → 2126).
Основание — `docs/tasks/199/research.md`. Кода не касался.

## Что стало

| было | стало |
|---|---|
| `Terra / Luna — NOT a default. Luna only on the orchestrator's explicit pilot instruction` | строки нет; Terra убрана целиком, Luna — отдельный пункт |
| Opus — `DEFAULT worker` на всё | `DEFAULT for OPEN work`, явно: `A closed task goes to Luna instead` |
| Sol — `override` для замеров и механических протоколов | `OPEN task on the Codex pool` + эти два override'а забирают Sol **даже если задача закрытая** |
| Spark — просто «быстрый leaf-worker» | закрытая задача **на своём пуле**: брать вместо Luna, когда узкое место — пул Codex |

Признак закрытой задачи сформулирован как проверяемый ДО спавна: «можешь назвать файл и строку,
критерий приёмки и команду тестов». Не назвал все три → задача открытая. Это единственная
формулировка, которую агент может исполнить, не имея ничего кроме текста задания.

## Пункт 4 (эффорт) исполним только как выбор РОЛИ

`spawn_worker` не имеет параметра эффорта (`app/mcp_stdio.py:711-720`), и тула смены эффорта нет.
Эффорт приходит из манифеста роли: `pipeline.yaml` — orchestrator/sub-orchestrator `medium`,
`worker` `high`, `full-cycle` `xhigh` (строки 23, 39, 55, 71). Поэтому «не ставить xhigh на
закрытые задания» записано в единственной исполнимой форме: закрытая работа идёт в роль `worker`
(`high`), а не в `full-cycle` (`xhigh`). Правило «не ставь xhigh» без этого было бы инструкцией,
которую некому выполнить.

## Границы данных в тексте
- «Measured on 3 closed single-turn tasks (N=1 per cell)» — прямо в промпте, чтобы никто не читал
  это как «Luna = Sol».
- Про эффорт названы ОБЕ измеренные точки: `×2.04 and ×1.13` (первая редакция цитировала только
  ×2.04 — это переобобщение поймал Codex, см. ниже).
- Длинный контекст у Luna — только извлечение (`9/9 at 164K`), разрешение ссылок между похожими
  фрагментами запрещено с чужой цифрой (`MRCR: Luna 41.3% vs Sol 91.5%, untested here`).
- Про открытые задачи Luna текст не утверждает ничего.

**Осознанное решение, которое стоит знать оркестратору:** приоритет «закрытая задача → Luna, а не
Opus» — это политика по цене и пулу, а НЕ вывод замера. Opus в #199 не участвовал, сравнения
Luna↔Opus по качеству нет ни в одну сторону. Оставить развилку было нельзя (агент законно выбирал
бы любой из двух), поэтому приоритет назначен явно; разворачивается одной строкой.

## Codex-ревью — 2 раунда, потолок прозы исчерпан
`docs/tasks/203/codex-review-impl.md`, сессия `019ff3f2`.

Раунд 1 — три находки, все по делу:
1. **P2, развилка Opus/Luna.** «Opus — DEFAULT worker: implementation, fixes» и новый пункт Luna
   покрывали одну и ту же закрытую правку → принято, приоритет прописан в обе стороны.
2. **P2, переобобщение эффорта.** «xhigh cost ×2.04» выведено из одного прогона Sol T1, а второе
   измерение дало ×1.13 → принято, названы обе точки.
3. **P3, вырезать числа.** Принято частично: убрал «all passed a hidden grader» (на выбор модели
   не влияет). Оставил `20.5×` (это и есть основание правки), `9/9 at 164K` (единственное, что
   вообще разрешает длинный контекст) и пару MRCR (без неё «Luna потянула 164К» читается как
   разрешение на разрешение ссылок). Возражение записано в файл ревью.

Раунд 2 — все три помечены FIXED, дословная цитата текущего файла в ответе есть. Одна новая
находка уровня suggestion, и верная: закрытый эмпирический замер и закрытая механическая
bulk-правка подходили и под Luna, и под Sol («also …» не было ограничено открытыми задачами).
Исправлено: `these two take Sol even when the task is closed`.

Третьего раунда нет — потолок для прозы 2 раунда, безусловный.

## Приёмка — сборкой промпта, не чтением
```
build_system_prompt(DEFAULT_PIPELINE, role), прогон из своей воркти:
role              luna_id terra old_pilot closed_ahead effort_both sol_closed_exc spark_pool  bytes
orchestrator      True    False False     True         True        True           True        42481
sub-orchestrator  True    False False     True         True        True           True        42832
worker            True    False False     True         True        True           True        25211
full-cycle        True    False False     True         True        True           True        41493
```
`terra=False` по всем ролям — старая строка не осталась нигде; `old_pilot=False` — формулировка
«только по пилотной команде» исчезла. Тесты не запускал: правка текстовая, кода не касается.

## Найденное попутно (не чинил — не мой мандат)
`<model-routing>` лежит в `base.md`, то есть в промпте ВСЕХ ролей, но действовать по нему может
только тот, кто умеет спавнить. У роли `worker` `can_spawn: []` (`pipeline.yaml:58`), а сессий с
этой ролью 75 из 121 (62%, свежий счёт по `sessions`, read-only). Эти 75 платят +877 Б за блок,
которым не могут воспользоваться, и платили за него и раньше — 2126 Б. Кандидат на переезд блока
из `base.md` в модуль `orchestration` + роль `full-cycle`; это решение оркестратора, не моё.

---

# Продолжение #203: эскалация Luna + переезд блока к исполнителям

Коммит второй. Файлы: `pipelines/default/prompts/modules/model-routing.md` (новый),
`pipelines/default/prompts/base.md` (−12 строк), `pipelines/default/pipeline.yaml` (3 роли),
`tests/test_default_pipeline.py` (+1 тест, обновлены списки модулей).

## Правка A — путь эскалации у Luna

Было: у Spark путь провала прописан, у Luna нет — агент мог законно переспросить Luna на той же
задаче и потратить экономию 20× на круги. Стало (в пункте Luna):

> **On failure escalate, never retry: the named test command stays red, or an acceptance criterion
> is not shown met by the output of a command → hand that ticket to Sol, do not send it back to
> Luna.** A criterion nobody can check by running something is not an AC, and its task was never
> closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at
> Sol's price.

Вторая фраза появилась после ревью: Codex показал дыру — «критерий приёмки не выполнен» решается
на глаз, если сам критерий вида «формулировка ясная». Теперь такой критерий выводит задачу из
класса закрытых, то есть до Luna не доходит вовсе.

**Сверх мандата, называю явно:** у Spark триггер `scope grows` страдал тем же — заменён на
`the ticket needs a file outside the ones you named → Sol`. Одна фраза, тот же дефект, тот же
блок; если считаешь это лишним — откатывается одной строкой.

## Правка B — блок переехал к тем, кто может его исполнить

Новый модуль `modules/model-routing.md`, подключён в `pipeline.yaml` первым в списке `modules`
у `orchestrator`, `sub-orchestrator`, `full-cycle` (все `can_spawn: ["*"]`), из `base.md` удалён.

**Отступление от буквы поручения, обоснование.** Было сказано «`orchestration` + роль
`full-cycle`». Это две копии одного правила: `orchestration` не грузится ролью `full-cycle`
(`pipeline.yaml:73`), поэтому пришлось бы дублировать текст в `roles/full-cycle.md` — ровно тот
дрейф, который мы вычищаем. Отдельный модуль отдаёт блок тем же трём ролям одной копией.
Первым в списке — потому что `modules/orchestration.md:175` говорит «Use the single
`<model-routing>` block above»; порядок проверен на собранном промпте.

`pipeline.yaml` правится руками: генератор `scripts/extract-manifest.py` мёртв — его источник
`app/prompts/` удалён, `--check` не гоняет ни один тест и ни один workflow.

## Приёмка

```
role              routing escalate above_ok bytes
orchestrator      yes     True     True     42739 → +258 к #203
sub-orchestrator  yes     True     True     43090
full-cycle        yes     True     True     41751
worker            NO      False    True     23083  (−2128 Б, блок ушёл)
```

Тесты: `tests/test_default_pipeline.py tests/test_pipeline.py tests/test_manager.py` — **288
passed** (`/tmp/pytest-203c.log`).

Новый тест `test_model_routing_reaches_only_spawn_capable_roles` держит обе стороны: блок ровно
один раз у каждой спавн-способной роли (`out.count(module) == 1`) и ни одного дословного пункта
у `worker`. Якоря берутся ИЗ модуля (`ln.startswith("- **")`), а не выписаны руками.

Мутации — 6, все красные:
1. `model-routing` добавлен воркеру;
2. убран у `full-cycle`;
3. **составная**: убран у `full-cycle` И блок возвращён в `base.md`;
4. модуль указан дважды у оркестратора (проверяет `count == 1`);
5. пункт **Luna** скопирован в `base.md` без тегов;
6. пункт **Opus** скопирован в `base.md` без тегов (это контрпример Codex к первой версии теста —
   она была на нём зелёной).

Предел теста записан в докстринге честно: дословную копию пункта он ловит, переписанную своими
словами — нет.

## Codex — 3 раунда (исполняемый артефакт), `docs/tasks/203/codex-review-move.md`

- Р1: два P2 — (а) ветка «AC не выполнен» не машинная; (б) тест зелен на копии без тегов. Приняты.
- Р2: обе исправленными не признаны до конца — нашёл, что немашинный триггер остался у Spark, и
  привёл рабочий контрпример к тесту (копия пункта Opus). Обе приняты и закрыты.
- Р3: **APPROVED**, дословные цитаты текущего файла в вердикте, новых находок нет.

## Что ещё в `base.md` воркер исполнить не может (перечислил, не трогал)

- `:10` `**Auto-report.**` — половина абзаца про то, что у оркестраторов авто-репорта нет.
- `:16` `**Cross-project.**` — «если ты оркестратор, можешь писать чужим оркестраторам».
- `:23` `list_orchestrators()` в списке тулов — с оговоркой «workers should NOT use this».
- `:39` критическое правило про `Agent tool` — ветка «Spawn-capable roles use `spawn_worker`».
- `:53` context economy — ветка «spawn-capable roles may delegate a bounded slice».

Общая форма у всех одна: правило с развилкой «ты оркестратор → …; ты воркер → …». В отличие от
`<model-routing>`, у каждого есть и вторая половина, адресованная воркеру, поэтому механический
перенос их сломает — нужно резать надвое. Не трогаю без твоего слова.
