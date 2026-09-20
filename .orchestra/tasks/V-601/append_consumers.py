import json
from pathlib import Path
p=Path(__file__).parent
refs=json.loads((p/'references.json').read_text()); c=json.loads((p/'consumers.json').read_text())
groups={}
for n,row in c['tools'].items():
    names=tuple(sorted(set(row['live_prompt_agents'])))
    if names and names not in groups: groups[names]=f"G{len(groups)+1}"
text='\n### Группы живых ссылок в system_prompt\n\n'
for names,g in groups.items(): text+=f"**{g}**: "+', '.join(f'`{n}`' for n in names)+'.\n\n'
text+='### Поимённая карта для всех 45 инструментов\n\n'
for n,r in refs.items():
    text+=f'#### {n}\n\n'
    for key,label in [('prompts','Промпты'),('code','Код'),('tests','Тестовые файлы')]:
        text+=f'**{label}**: '+('; '.join('`'+a['path']+':'+str(a['lines'][0])+'`' for a in r[key]) or 'прямых ссылок нет')+'.\n\n'
    names=c['tools'][n]['live_historical_agents']; group=groups.get(tuple(sorted(set(c['tools'][n]['live_prompt_agents']))),'нет')
    text+='**Живые исторические пользователи**: '+(', '.join(f'`{x}`' for x in names) or 'в сохранённом TSV не установлены')+f'. **Ссылки в живом system_prompt**: {group}.\n\n'
text+='''## Воспроизводимость и фактическая проверка исследования

Артефакты: `schemas.json` — реальный registry snapshot; `tokens.json`/`modes.json` — измерения; `proposed-descriptions.json` — точно тот макет, для которого вычислена разница; `references.json` — строки исходников и имена тестов; `consumers.json` — снимок незавершённых сессий и привязка к V-600; `decisions.json` — причины 45 решений. Сборка документа: `build_report.py`, затем `sections.md` и `append_consumers.py`.

Команды измерения: `uv run --no-project --with 'tiktoken==0.13.0' python .orchestra/tasks/V-601/count_tokens.py`, аналогично `count_modes.py`. Первая установка измерителя выполнялась server-side background job `bg-9a9944e11c`, RC=0; повторные offline прогоны завершились менее секунды. Это не добавляет зависимости в `pyproject.toml` или `uv.lock`.

Схема снята из `/home/kesha/orchestra/worktrees/home-kesha-orchestra/tools-redesign/app/mcp_stdio.py` и повторно побайтно сопоставлена с этим реестром; вызовов backend из registry inspection нет. Итоговая проверка явно закрепляет импорт за worktree (обычный запуск скрипта через общую venv первоначально разрешал `app` из основного checkout). Владелец файлов и configured service user — `kesha`; Git выполнялся тем же пользователем. Прочитана только живая БД `/home/kesha/orchestra/data/orchestra.db` через read-only connection. Экспортированное содержимое прошло `app.secret_mask.mask_secrets` перед коммитом; исходные журналы в новый артефакт не копировались.

Проверка целостности: ровно 45 уникальных решений совпадают с именами FastMCP и V-600; суммы 34+11=45; суммы token deltas и mode totals пересчитаны; все названные локальные файлы проверены на существование; git diff ограничен `.orchestra/tasks/V-601/`. Код, промпты, тесты, CHANGELOG и политика заморозки не изменены. Тесты продукта не запускались, поскольку исследование не меняет исполняемый продукт. Секретов, публикации, merge и рестарта нет.
'''
with (p/'tools-redesign.md').open('a') as f:f.write(text)
print('prompt groups',len(groups),'append chars',len(text))
