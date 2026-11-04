# V-1270 — terminal-mac: применимость к Orchestra

**RESEARCH DONE, 04.11.2026 UTC. Реально добавить отдельное управляемое GUI-окружение; запуск самого terminal-mac на нашем Linux x86 VPS/ноутбуке не поддерживается. Для него нужен Apple silicon Mac с macOS.** На Linux полезнее сначала проверить браузерный observe → act → verify через существующий MCP/CLI-контур. Это варианты для решения владельца, не принятое архитектурное решение и не разрешение внедрять.

Основание: публичные исходники и официальные документы, текущий выданный safe source bundle Orchestra, один локальный offline probe. **Mac runtime sample — UNTESTED.** Пересланные видео не предоставлены и не просматривались. Ничего не устанавливал, VM/браузер/модели не запускал, продукт и конфиги не менял; SSH, живые сервисы/БД/секреты и чужие проекты не использовал.

## Зафиксированная версия и доказательства

- terminal-mac: commit [`7009117f9e910c3dd4b4bd863e8bc331bd3c9d96`](https://github.com/govijr/terminal-mac/commit/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96), committer date `2026-11-03T11:52:08Z`, получен GitHub API, не выдуманный локальный HEAD.
- На момент чтения latest release — [`v0.2.0-6`](https://github.com/govijr/terminal-mac/releases/tag/v0.2.0-6), `2026-11-03T12:34:42Z`; API `prerelease=false`. Это флаг GitHub; [README][readme] всё ещё называет продукт early release candidate. Бинарный ZIP не скачивал и соответствие бинарника исходникам не проверял.
- [source_inventory.json](source_inventory.json): URL/SHA-256 24 публичных файлов terminal-mac и SHA-256 22 файлов Orchestra. Копия Orchestra **без `.git`**, её commit неизвестен. Выводы о текущем коде относятся к этому bundle, не к Python в работающем сервисе.
- [checks.log](checks.log), [offline probe](check_bundle_contracts.py), [source extraction](public-source-checks.log), [команды и ошибки чтения](commands.md), [заметки](notes.md). Стороннего clone нет: вне workspace worker писать запрещено; исходники читались HTTPS в память, инструкции/skills стороннего проекта не исполнялись.

## Что это и где работает

Это Swift-приложение из трёх частей: **контроллер macOS VM** на Apple Virtualization; **guest helper**, который снимает экран и отправляет ввод внутри гостя; **терминальный viewer**. Гостевая ОС — настоящая macOS из Apple IPSW. Терминал отображает её и передаёт команды. См. [VirtualMachines.configuration/create][vm], [GuestRuntime.handle][guest], [TerminalViewer][viewer].

| Условие | Проверенное по источникам ограничение |
|---|---|
| Host | Apple silicon Mac; заявлен macOS 14+. `scripts/build.sh:4` отвергает не-arm64, код использует AppKit/Virtualization/Darwin, `VZVirtualMachine.isSupported`, проверку совместимого hardware model и `config.validate()`. Intel Mac также вне поддержки этой реализации. [Build][build], [Package][package], [VM][vm] |
| Сборка/дистрибутив | README: готовой сборке не нужны dev tools; для сборки Xcode 16+/Swift 6. Package имеет tools-version 6.0, deployment macOS 14, language mode v5. Это заявленный минимум, не наша матрица совместимости. Host bundle требует `com.apple.security.virtualization`; helper его не получает. [Package][package], [entitlements][ent], [build][build] |
| Зависимости | В Package.swift нет внешних Swift package dependencies: локальные TerminalMacCore/TerminalUI/CPhoneShim; Apple frameworks Virtualization, AppKit, ScreenCaptureKit, ApplicationServices, ServiceManagement, CoreMedia. LZ4 используется через системный Foundation API. Не нужны QEMU, Docker, отдельный MCP SDK или LLM API для самого контроллера. [Package][package], [renderer][renderer], [MCP][mcp] |
| Linux x86 VPS или Linux/Windows x86 laptop | Сам terminal-mac не запустить и не перенести переключателем MCP: отсутствуют Apple frameworks и нужная платформа. KVM/nested virtualization на VPS этого не исправляет. Linux может быть клиентом **будущего** моста к Mac либо хостом другого browser/desktop backend. Это вывод из зависимостей, не проведённый эксперимент. |
| Apple laptop / отдельный Mac | Возможен native сценарий при Apple silicon/macOS, поддержанном IPSW, entitlement и интерактивной настройке. Apple silicon под Linux недостаточен: нужен macOS host. VPS может оставаться оркестратором, но VM должна жить на Mac; готового сетевого сервера у terminal-mac нет. |
| Viewer | Ghostty/Kitty/iTerm2, иначе native VM window и CLI. tmux passthrough и автосплиты не реализованы. Shared memory требует общей машины с терминалом; для удалённого терминала рассчитывать только на проверенный PNG transport, не на локальную скорость. [Viewer][viewer], [renderer][renderer], [Kitty protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/), [iTerm protocol](https://iterm2.com/documentation-images.html) |

Apple [installation documentation](https://developer.apple.com/documentation/virtualization/installing-macos-on-a-virtual-machine) подтверждает привязку restore image к поддерживаемой конфигурации, hardware identity и auxiliary storage. Их [текущий sample](https://developer.apple.com/documentation/virtualization/running-macos-in-a-virtual-machine-on-apple-silicon) уже обновлён под macOS/Xcode 27; его deployment target нельзя выдавать за минимум terminal-mac. Автонастройка guest account есть в [новом API macOS 27](https://developer.apple.com/documentation/virtualization/vzmacguestprovisioningoptions), но исследуемый проект её не реализует.

## Ресурсы, права и эксплуатация

- `VirtualMachines.create:64–80`: CPU default `max(IPSW_min, min(4, host_logical_CPU/2))`; RAM default `max(4 GiB, IPSW_min)`, диапазон ограничен restore image и Virtualization. Диск default **64 GiB logical**, sparse; CLI принимает 32–2048 GiB, но это не доказательство, что выбранная macOS установится на нижнюю границу. Отдельно нужны cached IPSW (несколько GB), auxiliary storage и запас под приложения/обновления; фактическую RAM/RSS, занятое место и время установки не измерял. [VM][vm]
- По умолчанию экран 1280×800 points с масштабом 2: 2560×1600 display pixels. MCP/CLI screenshot возвращает points-sized image для согласованных координат; viewer имеет свой resize/downscale. [VM][vm], [GuestRuntime.handle:115][guest]
- Данные: `~/Library/Application Support/terminal-mac/machines/NAME`, override `TERMINAL_MAC_HOME`; VM работает отдельным процессом. Hide/закрытие окна/выход viewer не выключают VM. Есть status/start/pause/resume/show/hide/stop, force-stop теряет несохранённое. [Store][models], [CLI][cli]
- Первый запуск требует Setup Assistant, аккаунта, запуска bundled helper и **Screen Recording + Accessibility внутри гостя**. Helper регистрирует guest login item; разрешения нельзя обойти CLI. Host не должен давать эти privacy grants для guest actions. Заблокированный/разлогиненный guest или отсутствующий helper препятствуют работе. [CLI.up][first], [GuestGuard/GuestRuntime][guest], [bootstrap][bootstrap]
- VM runtime/setup locks защищают экземпляр/установку, а не владение GUI-задачей одним агентом на весь observe→act→verify. При нескольких клиентах одной VM действия могут перемешаться: это вывод о недостающем task lease, не найденный live race. Для пилота — один управляющий агент. [CLI.up][first], [CLI.isRunning][cli], [Mailbox][mailbox]
- `up` умеет повторить записанную незавершённую установку с совместимым hardware; установленную VM автоматически не переустанавливает. **Нет clone/reset/rollback/delete/file-import API**, нет AX-tree snapshot; `snapshot` — alias screenshot. Нельзя обещать быстрые одноразовые VM с восстановлением. [FirstRun][first], [CLI.action][cli], [agent guide][guide]
- Host shares только `control` RW и `tools` RO; host home, desktop/clipboard/camera/microphone не подключаются. Guest helper проверяет `hw.model` с префиксом `VirtualMac`; это защита от случайного запуска на host, не attestation. Default NAT допускает доступ к сети/потенциально host/LAN; `--offline` убирает NIC, а mailbox продолжает работать. Поэтому это не hardened sandbox для враждебного кода. [VM.configuration][vm], [GuestGuard][guest]
- **Код MIT**: перенос/модификация возможны с сохранением copyright/license notice, гарантий нет. **macOS под отдельной Apple SLA**, MIT её не разрешает. Для Tahoe 26 §2B(iii) в соответствующей ветке лицензии — до двух дополнительных виртуальных экземпляров на Apple-branded host под macOS для разработки/тестирования, macOS Server или личного некоммерческого использования. Это не общее разрешение коммерческой фермы/terminal-sharing: §2I/3 отдельно ограничивают удалённые сессии и аренду. Для выбранного guest/способа приобретения/договора применимую SLA надо проверить, а не переносить правило «2 VM» без условий. [MIT][license], [Apple SLA Tahoe](https://www.apple.com/legal/sla/docs/macOSTahoe.pdf), [Apple SLA index](https://www.apple.com/legal/sla/).
- Поддержка — ранний RC: README сообщает self-signed/no notarization. Старый validation описывает Developer ID для другого build `0.2.0-2`; это не проверка подписи release 6. [docs/VALIDATION.md][validation] содержит vendor build/package checks, но **live guest acceptance всё ещё not completed**. Реальную надёжность input, Retina, обновлений и долгой работы пока нельзя принять на веру.

## Реальные интерфейсы и live computer-use

`terminal-mac mcp [NAME]` — **JSON-RPC 2.0, строки stdin/stdout**, без HTTP/SSE/WebSocket listener. Initialize возвращает tools capability, server name/version и instructions; tools/list доступен ещё до создания VM; вызов требует работающего guest. Ошибка tool — `content:[text]` + `isError:true`. [AgentServer.run/call][mcp]

| MCP tool | Обязательные аргументы и важные опции |
|---|---|
| `screenshot`, `status` | `{}`; status требует работающий guest helper, не управляет lifecycle |
| `click` | `x,y`; `button:left/right`, `clicks:1..3` |
| `move` | `x,y` — присутствует в коде, хотя короткий перечень README его пропускает |
| `drag` | `x,y,toX,toY` |
| `scroll` | `x,y,dy`; optional `dx`, guest ограничивает компоненты ±1000; negative dy — вниз |
| `type` | `text` |
| `key` | `key`, например `cmd+space`, `return` |

Итого **8 инструментов**. Все action tools принимают `screenshot:true`: после ввода ждут фиксированные 400 ms и возвращают дополнительный screenshot, не проверяют успешность намерения. MCP screenshot — `{type:"image",data:"<base64>",mimeType:"image/jpeg"}` плюс text с размерами (JPEG quality 0.85); это не локальная PNG-ссылка. Schemas: object, `additionalProperties:false`; x/y — integer ≥0, top-left в последнем screenshot. [AgentServer.tools/screenshot][mcp]

`mcp --config` печатает оболочку `{"mcpServers":{"terminal-mac":{"command":"<absolute launcher>","args":["mcp"]}}}`; для другой VM args `["mcp","NAME"]`. Это клиентский конфиг запуска **на Mac**, не URL удалённого сервиса. В `spawn_worker.mcp_servers` Orchestra нужна внутренняя карта серверов, без внешнего `mcpServers`. [CLI.run:116][cli], `app/mcp_stdio.py:spawn_worker:1122`.

CLI: `up [NAME] --plan/--no-view/--detach/--ipsw`, create/start/view/status/stop; `action [NAME] screenshot --output PATH`, click/move/drag/scroll/type/key/status. **Успех action** — JSON map, screenshot сохраняет PNG и возвращает host path; failure в `Entry.main` — сообщение stderr + exit 1, а не гарантированный JSON error. Help/version/skill text тоже не JSON. Shell-execution action отсутствует. [CLI.action][cli], [Entry.main][entry]

Skill — обычный bundled `SKILL.md` с YAML name/description и текстовым observe→act→verify. `skills get/path/install --dir PATH` читает/копирует файл; default destination `~/.claude/skills/terminal-mac/SKILL.md`. Plugin JSON связывает skill и `{command:"terminal-mac",args:["mcp"]}` и требует CLI на PATH; это не установщик ОС и не новый runtime Orchestra. [Skill][skill], [plugin][plugin], [CLI.run:126][cli]. Здесь прочитан как недоверенный источник, не применён как инструкция.

Механизм: CLI/MCP → JSON `Request{id,action,arguments,deadline}` в **virtio-fs mailbox** → helper в guest → ScreenCaptureKit/CGEvent → `Reply{id,ok,values,error}` и image file. Unicode typing использует события клавиатуры, без clipboard. Mailbox закрепляет directory FD, использует openat/O_NOFOLLOW, regular-file/nlink/size checks, request ID/deadline и cleanup; это полезные меры, не наш security audit. [Models][models], [Mailbox][mailbox], [GuestRuntime.handle/postMouse/press][guest]

Live viewer отличается от MCP: долгоживущий `SCStream`, interval до 30 fps, sequence/unchanged и long-poll, кадры BGRA-LZ4 размером под viewport через share. Renderer держит последний pending frame; Kitty/Ghostty после probe используют POSIX shared memory, иначе PNG через pty, iTerm2 — inline PNG. Stream останавливается после >15 s без viewer. Старый helper — fallback snapshots. **30 fps — настройка, не замер; «нулевая стоимость idle» не доказана:** mailbox/viewer продолжают ждать/проверять состояние. Это не видеострим MCP и не SSE dashboard. [DesktopStream][capture], [TerminalViewer.streamFrames][viewer], [DesktopRenderer][renderer]

## Что уже есть в текущем Orchestra

Проверка по исходникам bundle; runtime-настройки, включение и установленные внешние серверы не проверялись.

| Механизм | Точные refs и фактическая граница |
|---|---|
| Сторонний MCP | `app/mcp_stdio.py:spawn_worker:1122` принимает JSON `mcp_servers`; `app/manager.py:_parse_custom_mcp:355`, `_make_mcp_config:373` убирают override orchestra и добавляют extra. `Session.mcp_servers_custom` (`app/session.py:466`, `_to_db_dict:5185, поле на 5222`) сохраняется; manager reload читает его на `2292`. **Транспорт подключения уже есть**, terminal-mac integration нет. |
| По backend | `app/runtime_registry.py:_load_scope_mcp_servers:131` читает project MCP; `_claude_factory:173`, `_codex_factory:215`, `_grok_factory:278` передают его; `ClaudeBackend._write_mcp_config:1040`, `CodexBackend._mcp_servers_toml:2790`, `GrokBackend._mcp_server_configs:1376` формируют provider config. **Hub исключение:** `_hub_factory:333` MCP не передаёт; `app/backend_hub.py:HubBackend.build_handoff_manifest:1197` указывает `mcp_servers={}`. Возможность T3 MCP сама по себе не доказывает путь Orchestra→Hub. |
| Harness MCP/картинки | `app/harness/mcp.py:_Server.start/_handshake:53/71`, `MCPClient.call:244`, `_extract_text:323`: stdio есть, image становится строкой `[image]`. **Это подтверждено offline probe.** `app/harness/llm.py:OpenRouterClient._prepare_messages:396` умеет отдельный workspace `read_image` для vision route; произвольные MCP image blocks этим путём не восстанавливаются. `MCPClient._register` хранит bare tool names и отвергает дубликаты: generic `status/click/type` разных MCP могут конфликтовать; реальный roster не проверен. |
| CLI | `app/harness/tools.py:bash:131`, `dispatch`, `BUILTIN_NAMES` — shell и файловые tools; `app/agent_cli_exec.py:main:14` запускает provider CLI в cgroup. Возможность вызвать установленную внешнюю CLI уже есть; это не VM manager и не установка macOS API. |
| Скриншоты/browser | `app/harness/images.py:read_image:32`, `app/harness/tools.py:read_image` — проверенное чтение файла в workspace, не съёмка desktop. `app/limits_card.py:render_limits_card:552` использует Playwright `page.goto`/`page.screenshot` для карточки квот; это renderer, **не агентный browser controller**. В builtin tools и реестре Orchestra MCP нет browser navigation/click/desktop input. Такой сервер можно подключать отдельно на поддерживающем backend, но текущее живое подключение не установлено. |
| Stream events | `app/events.py:AgentEvent:111`, `app/live_broker.py:LiveBroker.publish:105`, `coalesce:42`, `app/routes/sessions.py:stream_session_logs:846`: tool/text partials, ограниченная очередь/replay и SSE уже есть. Захвата desktop, кадрирования/координат/30-fps video endpoint и interactive viewer в исследованных путях нет. Текстовые events не заменяют картинку для модели. |
| Artifacts/delivery | `app/mcp_stdio.py:send_file:2208` — durable доставка существующего файла; `publish_artifact:2347`, `app/artifacts.py:publish_snapshot:238`, `app/routes/artifacts.py:publish_artifact:122` — immutable HTML snapshot с TTL/revoke, при включённой конфигурации. Можно переиспользовать для итогового отчёта/скриншота через файл или HTML; это не live desktop transport. Ничего не публиковалось/не отправлялось. |
| Skills | `app/prompting.py:inject_skills_to_worktree_report:338`, `build_skills_index:627`, `app/runtime_registry.py:_codex_factory:215` — существующая доставка pipeline skills в runtime. Новый отдельный skill engine не нужен; контент computer-use нужно будет согласовать и проверить, не копировать автоматически сторонние глобальные настройки. |

Итак, **нет оснований говорить «computer-use уже есть»**: есть часть plumbing, чтение изображений и событийная лента; недостаёт конкретного browser/desktop provider, гарантированного пути картинки к выбранной модели, владения окружением и live-наблюдения за GUI.

## Что брать и как доказать пользу

Оценки ниже — исследовательская прикидка в инженерных днях, не план/обязательство; установка окружения и ожидание IPSW отдельно. **Benefit % для каждой строки: не измерено без comparable measurement.** Важность качественная и зависит от наличия GUI-задач; цифры чужих демо не переносятся.

| Полезный механизм | Вывод и место применения | Польза / усилия и ресурсы | Проверка, доказывающая пользу |
|---|---|---|---|
| Регистрация внешнего MCP/CLI | **Уже есть**, переиспользовать manager/runtime_registry/provider config, без нового runtime ради инструмента | Высокая повторная применимость; 0.5–1 д на пилот одного поддерживаемого backend, сам сервер отдельно | Mock stdio tools/list/call, error/restart; реально выбранный backend видит tools после reload и получает image |
| Observe→act→verify, координаты + after-shot | **Брать как контракт**, будущий scoped skill и выбранный browser/desktop tool; не все viewer frames слать модели | Высокая для воспроизводимости GUI; 1–2 д вместе с проверками screenshot→модель, без новой VM | Одни и те же 10 GUI-сценариев до/после: успешность, неверные клики, число повторов, tokens и время; screenshot после действия показывает ожидаемый результат |
| Изолированное GUI-окружение и один владелец | **Брать принцип**: отдельный browser context на Linux или VM на Mac; task lease в выбранном integration layer ещё отсутствует | Высокая против вмешательства в рабочий desktop; browser 1–3 д, desktop/lease/recovery 3–7+ д; один browser/VM за раз | Host focus/clipboard не меняются, два агента не смешивают действия; lock/logout/helper crash дают понятный отказ и восстановление |
| Native terminal-mac через MCP | **Брать условно для macOS QA**, отдельный Apple host и image-capable client; VPS нужен явный transport bridge | Высокая только при Mac-only задачах; 1–3 д локальный PoC после setup, ещё 3–7+ д на проверяемый удалённый мост/ownership; RAM/диск как выше | Чистый Mac: установка, permissions, status→screenshot→input→verify, повторный boot; Retina resize, denied permissions, pause/helper restart, два клиента |
| Latest-frame/idle stop/downscale | **Брать при доказанной нужде в live GUI**, отдельный observer layer, не копировать кадры в log DB | Средняя для наблюдения и ограничения трафика; browser view 2–5 д, desktop stream 5–10+ д; CPU/RAM/bandwidth только измерять | Одинаковый сценарий/viewport/качество, CPU процесса, RSS, bytes/s, latency, читаемость; idle/slow viewer/disconnect не наращивают очередь |
| Защищённый local mailbox | **Брать при Mac bridge/локальном helper**, не переписывать существующий MCP на файлы | Средняя, когда нужен guest/host IPC без listener; 1–3 д на контракты/проверку платформенных различий, кроме транспорта | Symlink/hardlink/FIFO/oversize/stale ID/timeout отрицательные проверки, успешный normal path и cleanup после crash |
| Events/artifacts/skill delivery | **Уже есть**, использовать указанные owners, добавить только нужные контракты/metadata при отдельной реализации | Высокая экономия дублирования; 0.5–2 д wiring, storage растёт с количеством сохраняемых screenshots | Открытие результата/TTL/reconnect, правильная привязка к task/session, отсутствие кадров другой VM и утечек в опубликованном |
| Kitty/Ghostty/iTerm renderer | **Не брать в Orchestra dashboard сейчас**; может остаться штатным viewer на Mac оператора | Низкая для web/телефона; перенос Swift/CoreGraphics на Linux и browser — другая реализация, недели, без подтверждённой нужды | Только если нужен terminal UX: отдельное сравнение с browser view на тех же задачах, включая remote link/tmux |
| Перенос Apple VM/controller на Linux, unattended macOS farm | **Не брать как «быструю интеграцию»**; нет нужной платформы, lifecycle/reset/lease и проверенной эксплуатации | Сейчас низкая применимость, высокая цена/неопределённость; выход за PoC, отдельное решение и SLA/hardware | Сначала реальный запрос на Mac-only QA и native acceptance; без них польза не доказана |

## Два минимальных варианта для обсуждения

**Для имеющейся Linux-инфраструктуры:** один headless Chromium в отдельном контексте и browser MCP на backend, который действительно получает custom MCP; semantic `browser_snapshot`/refs для действий, screenshots для проверки, сохранённые результаты через существующую доставку. Первичный кандидат — официальный [Microsoft Playwright MCP, commit `176c8ea1832d5d0b36963af38191ac0088abdac6`](https://github.com/microsoft/playwright-mcp/blob/176c8ea1832d5d0b36963af38191ac0088abdac6/README.md): Node 18+, headless/isolated, screenshot/snapshot/click, image-response и output-dir options. Он **не установлен и не прогнан**. Browser profile isolation не является OS/security boundary, desktop apps/macOS он не даёт. На harness прямой image response пока теряется; для пилота выбрать проверенный image-capable путь либо отдельно изменить image plumbing. Hub path также требует отдельной проверки/работы. Нельзя считать renderer карточки готовым агентным браузером.

Оценка Linux PoC 1–3 инженерных дня при доступном браузере/runner; для бронирования ресурсов ориентир 2–4 GiB на один browser, затем заменить ориентир фактическим RSS/CPU. Это не замер и не обещание уложиться в лимит ноутбука 2 GiB: при превышении такой пилот там не запускать. Прямое управление Linux desktop, если оно реально нужно, потребует другого provider; terminal-mac этого не поставляет. Ничего из варианта сейчас не реализовано.

**При настоящем Apple hardware:** выделить одну VM для Mac GUI QA, выполнить ручной setup/permissions, на том же Mac проверить CLI/MCP с одним управляющим и viewer для человека. Практический бюджет — default guest ≥4 GiB + host/client overhead и свободное место сверх sparse disk/IPSW; машину 16 GiB можно рассматривать как стартовый ориентир, не официальный минимум. Основной VPS остаётся Linux; соединение с Mac и доставка скриншотов обратно — отдельный проверяемый мост, а не «вставить локальный command на VPS». Существующие provider launch/cgroup пути Orchestra Linux-специфичны, поэтому переносить всю Orchestra на Mac ради пилота не предлагается. Не давать проекту обещаний CI-ready/безоператорной фермы до native acceptance и проверки лицензии.

## Фактические проверки и оставшиеся ограничения

| Проверка | Результат |
|---|---|
| Публичный source read + версии | GitHub API commit/tree (`truncated:false`)/latest release и pinned raw HTTPS; inventory 24 файлов terminal-mac, 22 локальных source hashes. Без clone/установки/исполнения upstream scripts |
| Offline deterministic probe | **6/6 PASS**, exit 0, `python3 -I .orchestra/tasks/V-1270/check_bundle_contracts.py`; AST извлекает только чистую `_extract_text` и проверяет text/image/mixed/error/empty, отдельно AST формы `_hub_factory`. Подтверждает потерю image payload, не работоспособность MCP/VM |
| Python runner | Probe — стандартная библиотека `/usr/bin/python3`, **не required uv/pytest check**. Provisioned uv `0.11.28` присутствует, `.venv` отсутствует; зависимости/окружение не создавались из-за запрета установки. Импортированный `app`: **NONE**. checks.log — **sanitizedpublicationcopy**: только source path заменён на относительный `app/harness/mcp.py`; остальные строки исходного probe сохранены. По сообщению root точный оригинал и его SHA сохранены у root приватно в `.orchestra/private/tasks/V-1270/checks-original.log`; этот файл/receipt здесь не читались, hash не заявляется. Product pytest/full suite не запускались; их зелёного статуса нет |
| Ошибки чтения | Web parser дважды `400 Unsupported content-type: text/markdown` на Apple `.md`; прямой HTTPS read успешен. Login profile один раз сообщил `fork: retry: Resource temporarily unavailable` при чтении лога, команда exit 0; далее login=false. Это не красный VM test |
| Native/GUI acceptance | **SKIPPED / UNTESTED:** Mac отсутствует; Swift build/XCTest, подпись/notarization release binary, IPSW install/boot, permissions, guest screenshots/input, host focus/clipboard isolation, Retina/resize, live FPS/CPU/RSS/disk/bandwidth, mailbox adversarial tests, updates/recovery и remote-terminal behavior |
| Orchestra/browser integration | **SKIPPED:** реальные external MCP connect, browser launch, provider/model calls, image rendering до модели, SSE UI/artifact delivery, restart/reload. Живые конфиги/БД не читались. Замера до/после нет |
| Product changes/commit | Только task artifacts. Коррекции найденных ограничений не делались. `.git` отсутствует; git commit/push не выполнялись и HEAD не заявляется. Импорт/коммит ветки `task-V-1270/research-terminal-mac`, доставка владельцу и приёмка — у broker/root |
| Artifact integrity | [validation.log](validation.log): ссылки/локальные файлы разрешаются, 22 source hashes неизменны, синтаксис probe корректен, credential-shape findings = 0. Проверены только формы из `publication_secrets.HUB_SECRET_SHAPES`; literal credentials inventory/живые секреты не читались |

Выводы о механизмах — source-based; один offline probe узкий. Будущая проверка должна покрыть старые helper (fallback snapshots), существующие MCP-конфиги и восстановление после остановки/разлогина; обещать совместимость всем backend нельзя. **RESEARCH DONE не разрешает реализацию.**

[vm]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/VirtualMachine.swift
[guest]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/Guest.swift
[viewer]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/Viewer.swift
[renderer]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/DesktopRenderer.swift
[capture]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/GuestCapture.swift
[build]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/scripts/build.sh
[package]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Package.swift
[ent]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/resources/terminal-mac.entitlements
[mcp]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/AgentServer.swift
[cli]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/CLI.swift
[models]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMacCore/Models.swift
[mailbox]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMacCore/Mailbox.swift
[first]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/FirstRun.swift
[bootstrap]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/GuestBootstrap.swift
[entry]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/Sources/TerminalMac/Entry.swift
[skill]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/skills/terminal-mac/SKILL.md
[plugin]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/.claude-plugin/plugin.json
[guide]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/docs/AGENT.md
[validation]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/docs/VALIDATION.md
[license]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/LICENSE
[readme]: https://github.com/govijr/terminal-mac/blob/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96/README.md
