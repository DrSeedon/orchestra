from pathlib import Path
import difflib
import json

ROOT = Path(__file__).resolve().parent
rows = [
(1,5,'Личное','proposed/global-claude.md','Область уточнена; исходный заголовок и указатель личности сохранены.'),
(6,6,'Перенос','modules/safety.md','rm-r/rf, trash/rm-i, не обходить недоступный инструмент. Исторические 45/9/2 сохранены в original, не вклеиваются каждый ход.'),
(7,7,'Перенос','modules/safety.md','Вне проекта, конфигурации и dotfiles: отдельное явное разрешение владельца; задача на иной объект его не даёт.'),
(8,8,'Перенос','modules/safety.md','Запрет chmod777 и скачанный код в shell.'),
(9,9,'Перенос','modules/safety.md','Показ и разрешение деструктивного. Разрешение на ту же операцию не спрашивается снова.'),
(10,10,'Личное + перенос','proposed/global-claude.md; modules/safety.md; modules/user-values.md','SSH/sudo личное, проверено NNP1/SSH0. Читаемость/stderr в safety. Деструктивное/прод/restart ограничены gates. Whitelist ноутбука сохранён с вопросом.'),
(12,14,'Личное','proposed/global-claude.md','Весь Git-блок ДОСЛОВНО, автор, Co-Authored-By, watermark.'),
(16,17,'Уже общий','modules/code-quality.md: Simplicity first','Минимальность, без спекулятивного и одноразовых абстракций.'),
(19,23,'Перенос','modules/code-quality.md: Simplicity first','Четыре ступени в исходном порядке одним пунктом.'),
(25,25,'Перенос','modules/safety.md','Защита trust boundaries, потери данных, безопасности, доступности.'),
(27,27,'Перенос','modules/code-quality.md: comments','Плотность добавлена к существующему правилу.'),
(29,29,'Уже общий','modules/code-quality.md: Surgical changes','Соседний/чужой мёртвый и осиротевший код, запрет постороннего refactor.'),
(31,31,'Уже общий','modules/user-values.md: proven new path','Callers без shim; действующее решение владельца защищает внешние контракты отдельно.'),
(33,33,'Уже общий','modules/code-quality.md: Pit of success','Flat/explicit/один способ/без side effects/три строки. Fail loud с действующей оговоркой про optional metadata.'),
(35,35,'Конфликт старого с действующим','modules/code-quality.md: Think before coding; modules/user-values.md','Простой вариант назвать. Любая неоднозначность→стоп уступает уже принятому gate существенных scope/authority/cost/contract; это явное разрешение конфликта, не дословный дубль.'),
(37,38,'Перенос','modules/project-maintenance.md: Issues','TODO неустранённой проблемы и сообщение; буквальный русский заголовок секции не навязан всем языкам.'),
(40,46,'Личное, один справочник','proposed/mcp-websearch-models.md: Web Search','Все шесть пунктов: WebSearch-first, sonar, pro-search, два запрета, язык, проверка Perplexity. Цены исторические.'),
(48,50,'Личное, один справочник','proposed/mcp-websearch-models.md: Image Generation','Тул, английский, nano-banana, lite/riverflow/seedream; недостающее добавлено из глобала. Цены не объявлены проверенными.'),
(51,51,'Личное','proposed/mcp-websearch-models.md','Запрет gpt-5-image-mini сохранён.'),
(52,53,'Личное','proposed/mcp-websearch-models.md','Одна картинка, показать сразу, не пересоздавать, восстановить из cache без повторного вопроса.'),
(55,56,'Личное','proposed/mcp-websearch-models.md','Serena: символы vs литералы/форматы, оба названных метода.'),
(57,59,'Личное','proposed/mcp-websearch-models.md','Pandoc рядом с источником, GitHub/CI, .mcp.json. Шаблон из справочника сохранён как ноутбучный, неприменимый на VPS.'),
(61,62,'Перенос','modules/project-maintenance.md: CHANGELOG','Вести существующий, создавать для крупного. Commit/публикация не дают отдельного разрешения push.'),
(64,64,'Перенос','modules/project-maintenance.md: CHANGELOG','Ручное ведение, запрет автосборки из внутренних отчётов. Инцидент04.08 остаётся в original.'),
(66,66,'Перенос','modules/project-maintenance.md: CHANGELOG','Что, symbols/files, triggering case для будущего читателя.'),
(68,70,'Перенос','modules/project-maintenance.md: CHANGELOG','Версии, шесть секций, честность недофиксов, исключение linter/dev/style.'),
(72,73,'Перенос','modules/project-maintenance.md: architecture','Обновлять существующий при значимых изменениях, не создавать самому.'),
(75,81,'Личное','proposed/global-claude.md: Docs','Три указателя и действие по сохранению в глобал дословно.'),
(83,84,'Личное, уточнение','proposed/global-claude.md: VPS','Не поднимать Hiddify/1234x. HTTPS достигает ответа, не доказан успех API-модели. География не используется как разрешение.'),
(86,87,'Личное','proposed/global-claude.md: Orchestra','Код, юнит, User, URL сохранены; дата начала не рабочее правило, остаётся в original.'),
(88,89,'Уже общий','modules/user-values.md; repo AGENTS.md','Owner-only restart и не втягивать чужие проекты; оставлен указатель. История отмены не повторяется в личном промпте.'),
(90,90,'Личное, вопрос','proposed/global-claude.md; questions.md','main/ноутбук сохранено как неподтверждённое. Git не различает машины при едином авторе.'),
(91,91,'Личное','proposed/global-claude.md','Указатель на канонический AGENTS; CLAUDE остаётся синхронизированным зеркалом.'),
(92,92,'Личное','proposed/global-claude.md','OOM800/−900 и запрет выравнивать сохранены; проверены на PID.'),
(93,93,'Перенос','modules/safety.md','Реальное состояние процесса, не только конфиг systemd.'),
(95,102,'Личное','proposed/global-claude.md: Cold archive','Раздел дословно: исторический снимок/исследования/не импортировать/не выводить живое состояние.'),
(104,108,'Перенос','modules/safety.md: service ownership','До работы проверить ownership; service user; root для пакетов; снимок владельцев, сохранить modes. find/chown не единственный маршрут. 3021 и дата сохранены в original.'),
(110,111,'Удалено по прямому решению','task V-570 owner quote','Запрет правки md/meta отменён владельцем, а не объявлен технически мёртвым.'),
]
source=(ROOT/'originals/global-claude.md').read_text().splitlines()
covered={i for a,b,*_ in rows for i in range(a,b+1)}
assert not [i for i,line in enumerate(source,1) if line.strip() and i not in covered]
(ROOT/'ledger.json').write_text(json.dumps([dict(start=a,end=b,status=c,destination=d,reason=e) for a,b,c,d,e in rows],ensure_ascii=False,indent=2)+'\n')
lines=['# Карта фрагментов исходного глобального CLAUDE.md','','Номера из originals/global-claude.md. Все непустые строки покрыты. Это проверка полноты карты, не автоматическое доказательство смысловой эквивалентности.','','| Строки | Решение | Рабочее место | Причина/детали |','|---|---|---|---|']
lines += [f'| {a}–{b} | {c} | {d} | {e} |' for a,b,c,d,e in rows]
lines += ['','## Отличия исходного Codex','','Остальные строки совпадают с Claude (сдвиг после88). Старая строка10 Codex заменена проверенным режимом привилегий. Строка88 несла прежнее owner-only условие рестарта, теперь владелец user-values. Отсутствовавший у Codex запрет инфраструктурной координации покрыт там же. Оригиналы и diffs сохранены; других уникальных фрагментов Codex нет.','','## Удалённые фрагменты корня Orchestra','','| Строки originals/repo-agents.md | Решение |','|---|---|','| 42–44 | safety: точная область, свежая проверка/разрешение, незаменимые данные/cache |','| 56–60 | Сервис, порты, ранбук отсутствуют на VPS: live-checks. Ручной режим и запрет авто-failover/IP-балансировки сохранены личными. HTTP_PROXY/HTTPS_PROXY сохранены личными; старый Default Contabo сохранён неподтверждённым для ноутбука и не назначает маршрут VPS |','| 61–62 | Отсутствующий registry удалён как обязательный VPS-путь; не угадывать host/user/port — safety |','| 63 | Запрет трогать архивного клиента перенесён в личный proposed/global-claude.md |','| 101 | TODO уже принадлежит knowledge; из владельца не удалён |','','Корневой CLAUDE.md синхронизирован штатным --sync: зеркало тех же изменений.']
lines += ['', '## Изменённые фрагменты личного MCP-справочника', '\n\n- Вступление: обязанность обновлять при смене моделей/цен сохранена; добавлена оговорка\n  об исторических ценах, не новая проверка прайса.\n- Первые три уровня поиска: разрешённый конфликт решён в пользу WebSearch-first.\n  Короткий sonar/глубокий pro-search, исторические цены и месячная оценка сохранены.\n  Старые оценки «не выдумывает»/#1 Search Arena явно помечены историческими,\n  не превращены в гарантию. Остальные запреты/язык запросов не удалялись.\n- Картинки: существующая таблица и правила сохранены; добавлены отсутствовавшие\n  в справочнике nano-banana-lite, старые поштучные цены и запрет пересоздания готового.\n- Pandoc reference_doc: исходный путь сохранён как ноутбучный/неприменимый на VPS,\n  вопрос владельцу; не подменён новым путём.\n- Serena: добавлена из удаляемого глобального раздела, со всеми границами применения.\n']
(ROOT/'ledger.md').write_text('\n'.join(lines).rstrip()+'\n')
for name in ['global-claude','global-codex','mcp-websearch-models']:
 before='originals/'+name+'.md';after='proposed/'+name+'.md'
 diff=''.join(difflib.unified_diff((ROOT/before).read_text().splitlines(True),(ROOT/after).read_text().splitlines(True),fromfile=before,tofile=after))
 (ROOT/(name+'.diff')).write_text(''.join('\n' if line==' \n' else line for line in diff.splitlines(True)))
print(len(rows),'rows; all nonempty global source lines covered; 3 diffs written')
