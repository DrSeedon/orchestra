# T1 — фиксация формулировок и адресность правки

Записано ДО любого прогона. Тексты ниже уходят в плечи A и B побайтово в этом виде.

## Плечо A — baseline (действующий `CLAUDE.md:164`, дословно, 360 B)

```
- Мутационная проверка на УЖЕ ЗАКОММИЧЕННОМ фиксе → откатывай файл через `git show <commit>^:<file>` и подтверждай откат маркером (`grep -c`). `git stash push` стэшит пустоту, даёт ложное «7/7 passed» и целится `pop` в чужой стэш
```

## Плечо B — кандидат (500 B)

```
- Мутационная проверка — три клаузы в ОДНОЙ команде: `cp F F.bak` → мутация → `mv F.bak F`, и `grep -c` маркера после отката. Любой git-откат (`checkout`, `show <ref>:F >`, `stash`) уничтожает НЕЗАКОММИЧЕННУЮ правку в F ровно так же, как мутацию: замер — три воркера за двое суток, один потерял работу за задачу
```

Исходники для прогона: `/tmp/rule_base.txt`, `/tmp/rule_cand.txt` (копии — `arm-a.txt`,
`arm-b.txt` в этом каталоге). Плечи не отличаются больше ничем.

## Бюджет байт

| Величина | Значение |
|---|---|
| `CLAUDE.md` сейчас | 42 372 B |
| дельта строки (500 − 360) | +140 B |
| `CLAUDE.md` после правки | 42 512 B |
| `project_doc_max_bytes` на этом хосте (`~/.codex/config.toml`) | 65 536 B |
| запас | 23 024 B |

Обрезки у Codex-воркеров не будет. Кириллица считалась `wc -c`, не символами.

## Адресность: до кого правка доедет

**Механизм — первичный источник, не рассуждение.** `app/backend_claude.py:180-182`:

```python
options.setting_sources = (
    ["user", "project", "local"] if self._inherit_claude_md else ["local"]
)
```

То есть SDK сам подкладывает и пользовательский `~/.claude/CLAUDE.md`, и проектный
`CLAUDE.md` — каждому Claude-воркеру, у которого `inherit_claude_md` истинно.
В `pipelines/default/pipeline.yaml` он истинен по умолчанию (`defaults.inherit_claude_md: true`)
и ни одна роль его не переопределяет. Плюс `app/workspace.py:29` кладёт `CLAUDE.md` в каждый
новый worktree (`PROJECT_FILES`), а `workspace.sync_agents_md` зеркалит его в `AGENTS.md`
для Codex-воркеров.

Косвенное подтверждение из фазы 1: правило «лесенка перед тем как писать код» существует
только в пользовательском `~/.claude/CLAUDE.md` и цитируется четырьмя воркерами
(`perf`, `frontend`, `feat-charts`, `back`) — пользовательский слой доезжает фактически,
а не только по коду.

**Кому это нужно — замер фазы 1, мутационные прогоны по ролям:**

| Роль | Агенты | Эпизодов мутации |
|---|---|---|
| `full-cycle` | perf, feat-charts, feat-instant, audit-front | 34 |
| `worker` | back, frontend, fix-ws-auth-tests | 16 |
| `orchestrator` | Orchestra-orchestrator | 1 |

Роль `worker` — половина случаев и три отката через `git checkout`. Правка, положенная в
`pipelines/default/prompts/modules/research-method.md`, до неё **не дошла бы**: этот модуль
грузит только `full-cycle` (`pipeline.yaml`, `roles.full-cycle.modules`).

## Почему в `pipelines/` менять нечего

```
$ grep -rn "мутац\|Мутац\|mutation\|MUTANT" pipelines/
pipelines/default/prompts/skills/vps-deploy.md:11:This skill provides a procedure, never permission. Before any SSH or external mutation, verify
```

Единственное совпадение — про «external mutation» при деплое, к мутационному тестированию
отношения не имеет. Рецепт мутационной проверки живёт ТОЛЬКО в `CLAUDE.md`, дублировать
его в промпты незачем: файл и так читают все роли (см. выше), а копия разошлась бы с
оригиналом — ровно тот дефект, который зафиксирован в `CLAUDE.md` как «одна мысль = один owner».

Конфликта с порядком фаз новый текст не создаёт: он не требует коммита до мутации, поэтому
`full-cycle.md` Phase 3 (`commit` пятым шагом) править не нужно.
