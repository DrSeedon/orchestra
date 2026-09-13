# Проверки 13.09.2026, текущий VPS

Все проверки read-only; root-команда — только `sudo -n true`. Ничего не перезапускалось.

| Проверка | Наблюдение | Что из этого следует |
|---|---|---|
| `systemctl show ai-proxy-manager.service -p LoadState -p ActiveState -p MainPID` | not-found / inactive / 0 | Именованный системный сервис на этом VPS отсутствует |
| `ss -ltnH`, фильтр портов 12300–12399 и 18109 | Ни одной строки, команда ss успешна | Названные локальные слушатели отсутствуют |
| stat ~/.claude/docs/ai-proxy-manager.md и vps-registry.md | ENOENT для обоих | Автоматически отправлять агента читать эти пути здесь нельзя |
| stat ~/.claude/docs/{mcp-websearch-models,vpn-ezhik-setup,agent-teams-playbook}.md | Все три существуют | Личный список документов сохранён |
| stat /opt/cog-second-brain/CLAUDE.md | Существует, 97 090 байт | Указатель личности сохранён; содержимое не читалось и не менялось |
| `/usr/bin/trash --version` | 0.23.11.10, exit 0 | Команда доступна; настоящих удалений ради проверки не было |
| `/proc/self/status` + `sudo -n true` | NoNewPrivs=1; sudo отказал именно из-за no-new-privileges | Прямой sudo внутри текущего процесса не работает |
| `ssh -o BatchMode=yes -o ConnectTimeout=5 kesha@localhost 'grep "^NoNewPrivs:" /proc/self/status; sudo -n true'` | NoNewPrivs=0, exit 0 | Разрешённый владельцем локальный SSH-маршрут работает |
| Каталог /home/kesha/orchestra-archive | 315 файлов | Исторические 314 сессий + README согласуются с наличием архива; число логов и размер снимка повторно не подсчитаны |
| systemctl show orchestra/tinyproxy + `/proc/<MainPID>/oom_score_adj` | Оба active; фактические 800 / −900 | Личная настройка жива, не удалена как устаревшая |
| Прямой curl с `--noproxy '*'` к api.anthropic.com/api.openai.com | HTTP 404 / 421, exit 0 | Прямой HTTPS достигает ответа; это НЕ успешный модельный запрос и НЕ доказательство доступности любой API-функции |
| ~/.claude/mcp-servers/websearch/generated и ~/.claude/mcp-configs | Оба каталога существуют | Путь локального восстановления картинки сохранён |
| /home/maxim/.claude/mcp-servers/pandoc-reference.docx | Не существует | Предписание из личного справочника невыполнимо на данном VPS; актуальный путь не угадан |
| ~/.orchestra/codex-home/*/AGENTS.md | 53 home-каталога, 0 файлов AGENTS.md | Текущие managed homes не получают глобальный AGENTS.md |

Код `_prepare_codex_home` в app/backend_codex.py переносит auth/config, не глобальные
инструкции. У текущего процесса CODEX_HOME указывает на такой managed каталог.
В Claude `_inherit_claude_md=True` включает user/project/local источники; default
pipeline включает это наследование. Это проверка текущей конфигурации доставки,
не утверждение «ни одна сессия никогда не получала текст» по всей истории.

Отсутствие proxy-manager на VPS не доказывает его отсутствие на ноутбуке: ноутбук
не обследовался. Именованные VPS-ссылки удаляются как неверные для этого контура,
личные ограничения ручного управления прокси сохраняются отдельно. Восстанавливать
старый сервис/ранбуки или угадывать замену задача не разрешает.
