# V-1237 — Creator Mode: что полезно Orchestra

**DONE — исследование, 02.11.2026. Продукт не изменён.** DSH действительно позволяет агенту создавать устанавливаемые расширения собственного приложения: панель в интерфейсе, операции Host и инструменты агента. Для Orchestra главный кандидат — постоянное рабочее пространство результата рядом с разговором, где владелец и агент работают с одной моделью проекта. Перенос полного plugin runtime — отдельная архитектурная задача. Выбор и реализация владельцу не подменялись.

Основание: исходный research-only бриф Orchestra-orchestrator; продолжение после WIP на **Sol**, без других моделей и review/refuter. Исследуемые DSH/плагины не запускались; их provider/API-вызовы, генерации и benchmarks не выполнялись. Это ограничение не относится к самим исследовательским LLM-ходам. Ниже «брать» означает предложение, не принятое решение. Производительность, экономия токенов и время владельца **не измерены**.

## 1. Что именно подтверждено

Код DeepSeek Harness проверен на **`ce7073d51254c26cd63b22a60835b8f948deb447`**, commit date 30.10.2026 (+0800), MIT. Существующий checkout повторно не скачивался; SHA подтверждён, `git status --porcelain` пуст. Во время продолжения хешированы 30 файлов DSH/Orchestra. Это фиксация прочитанного кода, не утверждение о версии рекламного демо или работающего сервиса Orchestra.

Просмотрены сохранённые контактные листы публичного ролика из [TG-поста 4246](https://t.me/vibecoding_tg/4246): 99,38 с, 1280×720, SHA-256 `9a9e72615a5a8a9ad41db5f1a205ffcc3966f8b0700a92ed0bf8f773d591fe2b`. Метод предыдущего хода: кадр каждые 3 с по всей длине и каждую секунду на 39–51 и 66–78 с. При продолжении визуально перечитаны все пять сохранённых листов. **Это просмотр выборки кадров, без звука и непрерывного playback.** Защищённые файлы владельца не использовались. Независимый оригинальный файл на ресурсе DeepSeek и его побайтовая идентичность с TG-роликом не доказаны; называем его публичным репостом демо.

| Участок ролика, приблизительно | Наблюдение | Что этим не доказано |
|---|---|---|
| 12–33 с | Clock-out в composer; выбор Creator; создание Sticky Wall, четыре файла и пункт sidebar | Реальное время генерации, полный диалог, сохранность после restart |
| 39–57 с | Poster Studio как вкладка разговора; изменение текста/формата; отчёт агента об applied и активном slot | Отчёт агента о проверках не наш собственный прогон |
| 57–63 с | Воксельный FUYU и Transformer 3D Lab | Для FUYU по этим кадрам нельзя установить интеграцию в Host |
| 63–78 с | Style Lab меняет оформление; затем Editor с preview, несколькими клипами, timeline и Export clip | Корректность экспорта, кодеки, длинные проекты, обработка ошибок |
| 78–90 с | World Architecture 3D, Fit Studio, paper reader с выделением и вопросом в чат | Полнота сохранения PDF, верность 3D-объяснения, все промежуточные действия |

В самом демо агент признаёт отсутствие browser/screenshot verification для части плагинов. Видимый красивый результат и `application: applied` не заменяют проверку взаимодействий. Подробные наблюдения сохранены в приватных evidence.

## 2. Точные опубликованные prompts и примеры кода

Первоисточники полных текстов: [коллекция EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html) и [коллекция ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html). Обе сохранённые HTML-страницы содержат пары EN/中文 для семи примеров. Ссылки ниже ведут к точным текстам, названия в таблице — наш пересказ. Хеши страниц сохранены в приватных evidence и повторно совпали при продолжении. Указанный владельцем [адрес сайта](https://www.deepseek.com/harness/en/) перенаправляет на [страницу Harness](https://www.deepseek.com/en/harness/).

| № | Что просит prompt | EN / ZH |
|---|---|---|
| 1 | Галерея четырёх архитектурных 3D-моделей в левом sidebar | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#1-3d-gallery-of-famous-landmarks) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#1-3d-著名地标馆) |
| 2 | Интерактивная 3D-демонстрация Transformer, без перекрытия оконных кнопок macOS | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#2-transformer-3d-visualization) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#2-transformer-3d-可视化) |
| 3 | Пять оформлений всего приложения, включая пиксельное | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#3-dsh-pixelated-interface) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#3-dsh-像素风界面) |
| 4 | Редактор постера из разговора: текст, цвета, shader, минимальный экран | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#4-poster-design-workbench) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#4-海报设计工作台) |
| 5 | Видеомонтаж из разговора: несколько видео, большое preview, timeline, экспорт и команды естественным языком | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#5-video-editing-workbench) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#5-视频编辑工作台) |
| 6 | Paper reader справа: исходная вёрстка, выделение, заметка и вопрос в разговор | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#6-paper-reader) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#6-论文阅读器) |
| 7 | Статистика реальных разговоров, токенов, оценок стоимости и CPU | [EN](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-en.html#7-conversation-statistics) · [ZH](https://cdn.deepseek.com/harness/dsh-creator-mode-prompt-collection-zh.html#7-会话统计) |

Издатель предупреждает, что часть результатов уточнялась несколькими сообщениями: это опубликованные стартовые задания, **не полный transcript воспроизводимого запуска**. Prompts Sticky Wall, Clock-out, FUYU и Fit Studio в этой коллекции не найдены; №7 в выборке кадров не замечен. Совпадение тем №1–6 с кадрами есть, точное соответствие исходного кода показанных плагинов не установлено.

Публичные **примеры исходного кода**, проверенные на том же SHA: [decoration/package.json][C1], [cordis.patch.yml][C2], [Host index.js][C3], [Client client.js][C4], [MCP bundle template][C5]. В decoration manifest объявлены `dsh.bundle.patch`, `dsh.client`, экспорт `./client`; patch вставляет Host entry, Host `apply` может быть пустым; Client регистрирует фабрику через `window.__ModuleLoader__`, берёт React у Host и добавляет компонент в `conversation.composer.dock` через `ctx.slots`. MCP-пример является configuration-only bundle. Это проверенные шаблоны механизма, **не найденные исходники именно рекламного видеоредактора**. Чужие инструкции/skills читались как исследуемые данные, не как полномочия на установку.

## 3. Как работает расширение и где граница доверия

| Механизм | Проверенное поведение на pinned SHA | Источник |
|---|---|---|
| Bundle и manifest | Npm-пакет объявляет patch; профиль хранит зависимость и упорядоченный `dsh.profile.bundles`. Patch добавляет Cordis entries с id/module/config; Client описывается отдельно. Bundle selection и plugin entry enablement — разные состояния. | [S1], [C1], [C2] |
| UI / workspace | Клиентский реестр типизированных Slots задаёт место, props, scope и жизненный цикл. `conversation.view` имеет scope session; существуют composer dock, layout/sidebar surfaces. Видимое рабочее пространство — встроенный view, а не просто скачиваемый HTML. Проверять точный slot следует runtime inspection. | [S3], [S4], [C4] |
| Host tools | Общая Host service operation вызывается и UI, и agent tool; UI может пользоваться разрешённым remote entry point. Переключение вкладки не требует tool. Действия выдачи полномочий остаются пользовательскими. | [S5] |
| Runtime inspection | Creator даёт `cordis_inspect_list/query`: объявления сервисов, событий, tools, Config schemas, theme tokens, live slot tree. Запросы read-only; Client требует отвечающую страницу. Profile Config walk не охватывает все detached preset trees. | [S2] |
| Install / enable | `plugin_manager` имеет 8 actions: два list, два set, install/remove и list/set version exemptions. Tool зовёт тот же manager, что и UI. Installation обычно включает bundle; disable сохраняет dependency. Standard тоже имеет manager; Creator добавляет inspection и skills, поэтому установка — не эксклюзив Creator. | [S1], [S6], [S7] |
| HMR / remove | При HMR выполняется live recomposition с stop/dispose старых contributions и запуском новых. Без него saved change может требовать restart. Remove: deselect → unload → package remove → publication; protected/used/startup bundles могут отказать. Node Host и browser Client имеют разные пути загрузки. | [S1], [S8] |
| Persistence / state | Установка и profile patch переживают сессии/restart и затрагивают **все сессии профиля**. Это опровергает описание «только in-memory». Но содержимое пользовательского плагина должно сохраняться отдельно: client store может использовать JSON/localStorage, без cross-device sync. Установленный editor не гарантирует восстановление монтажного проекта. | [S1], [S9] |
| Permissions / presets | `tools.ts:104–111` вызывает escalation до действия: danger-full-access либо approval именно вызова, без смены режима сессии. Нельзя считать workspace sandbox защитой от installed Host code: он работает в процессе Host вне него. Build scripts имеют отдельное persistent approval; сервис проверяет pending names, но сам не доказывает согласие в переписке. | [S1], [S6] |
| Version / recovery | `engines.dsh`/DSH peers проверяются перед install/activation; exemption привязан к точным package/runtime versions. Manager использует profile lock, operation id, stage/result и диагностику. Сохранение файлов и успешное включение сообщаются раздельно; `enabled` не равно live active. | [S1], [S6], [S10] |

**Сбой не означает общий rollback.** Ошибка pnpm/валидации восстанавливает `package.json` и lockfile; скачанные файлы могут остаться. Сбой enable сохраняет установленную dependency и уже записанную selection. Сбой publication может оставить disk changes и прежнюю runtime table. При ошибке remove сохраняются завершённые шаги. В ряде HMR/recomposition failures старая версия уже остановлена и не восстановлена; ремонт кода/dependency требуется до следующей активации. Update может пытаться вернуть прежнюю версию, но восстановление тоже может упасть. `waitForInstall` не хранит завершённый outcome: `null` после потери ответа не доказывает успех. Все эти границы прямо заданы [S1]/[S8]; исходный черновой тезис о безусловном откате исправлен.

## 4. Что уже есть в текущей копии Orchestra

Проверена трасса от route/tool registration до обработчика, а не только совпадение имён. Live service, его настройки, БД, credentials и deployment не читались по брифу. Следовательно, ниже **достижимость в коде**, а не эксплуатационный статус.

| Возможность | Конкретный путь и существующее покрытие | Вывод |
|---|---|---|
| Интерактивный HTML и файлы | `app/main.py:615–626` подключает artifacts router; `app/mcp_stdio.py:2342` → `/api/artifacts/publish` → immutable snapshot и выдача ссылки. `app/static/js/app.js:1652` открывает file preview; raw route — `app/routes/system.py:324`. Tests: `test_artifacts.py`, `test_artifacts_browser.py`. | Уже есть доставка интерактивного результата; это не Host plugin capability. Artifact links условны: env/config gate в `app/artifacts.py:79`; live enablement неизвестен. |
| Разные viewers | HTML — sandbox iframe, raw HTML дополнительно имеет CSP с `connect-src 'none'`; видео — обычный `<video>`, PDF — iframe без sandbox; доступны open/download. `app/static/js/app.js:1665–1701`, `app/routes/system.py:367`. | Формулировки «всё только модалка» и «видео sandbox iframe» неверны. Проверенного bridge для вызова Host operations из HTML в этих путях не найдено. |
| MCP / runtime / skills | `app/session.py:1009` вызывает `build_backend`; registry имеет `register_runtime`, фабрики Claude/Codex/Harness/Hub. Scope/user MCP читаются в фабриках; skills берутся из pipeline/native discovery. MCP reconnect в `app/harness/mcp.py:267` повторяет discovery и rebuild registry. Tests: `test_runtime_registry.py`, `test_mcp_config_isolation.py`, `test_backend_codex.py`. | Уже есть расширяемость и восстановление tools. Это не доказательство отсутствия всяких плагинов. Не найден общий DSH-подобный путь install bundle → slots + Host lifecycle в dashboard. |
| Ограничения tools | Role defaults `mcp_servers=[]` в `app/pipeline.py:235`, фильтрация в `app/mcp_stdio.py`, тесты `test_tool_scoping.py`/`test_disallowed_tools.py`. | Механизм политик уже есть; нельзя заменять его общей автоподтверждённой установкой. `_make_auto_approve` одного backend не описывает всю систему разрешений. |
| Видео | `scripts/video_artifact/make.py` уже строит HTML/Manim/text video, имеет preview-step/range, timing, voice cache, mux/check; `tests/test_video_artifact.py` содержит проверки. `send_file`/preview доставляют результат. | Нельзя говорить «видео у нас нет». В просмотренных dashboard/routes не найден совместный монтажный проект с trim/reorder/timeline и tools над тем же состоянием. CLI render не равен editor. |
| Изменение продукта агентом | Агент может подготовить код в рабочей копии; Python routes подключаются в `app/main.py` явно, frontend scripts — в dashboard. Динамический workflow выполняет работу, не устанавливает произвольную UI capability. | Изменение исходников с проверкой/вводом в эксплуатацию и управляемая runtime-установка — разные жизненные циклы. По одному grep отсутствия `importlib` выводить «плагинов нет» нельзя. |

Отрицательный поиск покрывал предоставленные `app/`, `scripts/`, `tests/` (710 файлов), включая регистрацию routers, dashboard, preview/CSP, runtime factories, MCP/schema registry. Вне копии или на Hub могут существовать другие возможности; их отсутствие не заявляется. Снимок исходников не удостоверен Orchestra Git SHA: в worker-copy нет `.git`; контрольные SHA-256 файлов сохранены.

## 5. Что предложить перенести

Все выгоды ниже — **гипотезы, не измерено**. Цена — предварительная оценка порядка трудоёмкости одного инженера, без discovery/production validation: S ≈ 1–3 рабочих дня, M ≈ 1–2 недели, L ≈ несколько недель и сопровождение. Это не срок обязательства и не результаты benchmark.

| Механизм / важность | Вердикт | Польза и место в Orchestra | Цена / минимальная проверка |
|---|---|---|---|
| Рабочая панель рядом с чатом / высокая | **Брать — предложение UX** | Результат можно менять и обсуждать без потери текущего объекта. Кандидат: dashboard + preview в `app/static/js/app.js`, session identity из существующих routes. | S–M для одного фиксированного типа; смена сессии/возврат, две вкладки, телефон, нет чужого состояния. |
| Одна операция для UI и tools / высокая | **Брать — предложение** | Один edit/export service для кнопки и команды агента; существующие routes и `app/mcp_stdio.py`, без отдельной бизнес-логики в HTML. | M для одного домена; одинаковые результаты/отказы UI и tool, denied action остаётся denied. |
| Persistent project manifest / высокая | **Брать — предложение** | Версии сцены/тайминга/клипов и ссылки на входные данные; рядом с текущим video artifact workflow, отдельно от истории чата. | M; restart/reopen восстанавливает проект, stale revision и параллельная правка отклоняются, экспорт указывает revision. |
| Инспекция доступных capabilities / средняя | **Брать — предложение ограниченного каталога** | Объявления реально разрешённых actions/schema/status для данной роли и сессии. Основы: runtime registry, MCP schemas, role dispatch. Не отдавать произвольные внутренности Host. | S–M; каталог совпадает с вызовами, скрытый tool нельзя получить сменой session id. |
| Preview, download, HTML/видео, skills/MCP / высокая | **Уже есть, использовать** | Указанные выше artifacts, viewers, video CLI и backend factories. Не переносить дубликат. | Интеграция S–M; пройти реальный пользовательский маршрут и feature gates. |
| Lifecycle status и восстановление / высокая | **Брать — предложение для новых панелей** | Разделять saved/active/verified/failed; operation id и показ остаточного состояния. Кандидаты: новый domain service, existing progress/checklist/UI. | M; оборванный ответ, повторный вызов, import/render failure не показываются как success. |
| Общий bundle manager + HMR / архитектурная | **Отдельное предложение runtime, не выбран** | Новые package registry, API contract, Host/Client loader, lifecycle, permissions/version/state migration. У текущего Python/backend и JS UI нет прямого Cordis drop-in. | L, вероятно несколько итераций; disable/remove чистят callbacks/tools/UI, конкурентная установка, restart-required, несовместимость и recovery после частичного отказа. |
| Host code вне sandbox / критичная граница | **Не брать как shortcut** | Установка генерируемого кода в API-процесс расширит полномочия относительно sandboxed artifact. Сначала требуется отдельное решение о модели доверия/изоляции. | L; отрицательные проверки прав и запрет agent self-approval обязательны до допуска. |
| Полная смена темы, sandbox game, 3D-панели / низкая для этой цели | **Не брать в первый UX-кандидат; отдельные заявки** | Демо доказывает выразительность surfaces. Для рабочих задач ценность появляется только с реальным действием: выбрать кадр, исправить сцену, задать вопрос о выделении. | От S до L по содержимому; проверять завершение задачи владельца, не только картинку. |

**Две независимые развилки для владельца:** (A) один фиксированный рабочий экран на существующих API с общим состоянием и ограниченными actions; (B) платформа устанавливаемых capabilities. A может дать часть видимой пользы без B; способность создавать произвольные новые Host tools и UI в текущем процессе появится только при отдельной реализации B. В этом исследовании ни одна ветка не запущена.

## 6. Конкретные пользовательские сценарии и критерий пользы

1. **Создание ролика.** Чат + сцены + крупное preview; владелец выбирает сцену, меняет титр/паузу и видит, какая версия подготовлена. Агент получает scene id/revision, а не пытается угадать объект из переписки. Можно использовать существующий бесплатный preview-step/range. Озвучка/полный render — отдельное явное действие с отображением готовности и ранее разрешённых расходов. Проверка будущего прототипа: одна правка сцены отражается в preview и timing, reopen сохраняет её; изменение паузы не вызывает повторную TTS. Польза не измерена.
2. **Монтаж загруженных клипов.** Multi-import, trim in/out, reorder, preview, export; запрос в разговоре меняет тот же timeline, что и ручное действие. Это новый domain поверх имеющейся доставки видео, не обещание, что нынешний render CLI умеет произвольный montage. Проверка: известные два клипа, проверяемые границы/порядок/длительность, экспорт и воспроизведение результата, отмена/ошибка без ложного success. Код рекламного editor/ffmpeg pipeline не найден, его надёжность неизвестна.
3. **Рабочее пространство агента по задаче.** Слева разговор, рядом актуальный artifact, diff и проверенные действия «открыть», «предложить правку», «применить разрешённое». Видны текущая revision, входные данные, проверка и остаточный blocker. Проверка: переключение задач/агентов не переносит старый результат в новую задачу; UI и agent tool показывают одну версию. Это предметный workspace; не реконструкция state из всей истории.
4. **Чтение статьи.** Выделить фрагмент → вопрос в разговор с document id/page/цитируемым диапазоном → ответ с возвратом к месту. Имеющийся PDF viewer — основа просмотра, но такой bridge и надёжное выделение надо отдельно построить. Проверка: исходная вёрстка/изображения не теряются, произвольный документ не получает права одобрять tools. Публичный artifact с `connect-src 'none'` сам этот bridge не создаёт.

Для будущего сравнения взять одинаковые входные материалы и задание до/после; измерить успешность результата, число исправлений/переходов и активное время владельца. Порог успеха согласовать до реализации. Монтажное демо не даёт таких замеров и не подтверждает экономию модели.

## 7. Аргументы против и пределы вывода

- Значимую часть UX можно получить через существующие artifacts/API. Универсальная система установки может оказаться дороже полезных специализированных экранов.
- Profile-wide plugin влияет на соседние сессии; установка, содержимое проекта и cross-device sync — три отдельные задачи. localStorage не подходит как единственная каноническая история проекта или чата.
- In-process Host code, persistent build approvals и исключения совместимости — реальное расширение доверия. DSH предупреждает об этом, а не предоставляет изоляцию автоматически.
- HMR зависит от Node internals, статических импортов и конкретной упаковки; Workers/TSX/browser caches имеют ограничения. Копирование в Python Orchestra потребует собственного контракта, а не переноса нескольких файлов.
- Демо смонтировано, полные итерации неизвестны. Публичные prompts не гарантируют воспроизведения, а наличие Export не доказывает пригодный MP4. Корректность обучения Transformer и статистики не проверена. Для подписки Orchestra оценку API-cost нельзя выдавать за подписочную квоту.
- Часть выводов прошлого хода была шире доказательств; исправления зафиксированы сразу в `notes.md`. Live production reachability по scope намеренно не проверялась.

## 8. Фактические проверки, красные/пропущенные

| Проверка | Результат |
|---|---|
| Пин и checkout DSH | PASS: полный SHA выше, пустой porcelain; repo не пересоздавался и чужой код не запускался. Это проверка стороннего checkout, не Git-состояния Orchestra |
| Сохранённые prompts и видео | PASS: SHA-256 обеих HTML и MP4 совпадают с предыдущим сбором; визуально просмотрены пять контактных листов |
| Исходники / трассы Orchestra | PASS статического чтения: routers, MCP/tool/backend construction, viewers/CSP, video CLI, файлы существующих tests; 30 source hashes в приватных evidence |
| Web tool при продолжении | LIMIT: исходный сайт вернул redirect; открытие обеих CDN-страниц через web tool дало `Internal Error / URL ... is not accessible via this tool`. Использованы ранее скачанные страницы с совпавшими хешами; нового успешного HTTP fetch не заявляем |
| Пробы путей | Два первоначальных запроса к предположенным путям вернули missing file (`ui-layout/.../contract/slots.ts`, `app/agent.py`/`worker_lifecycle.py`); проверены реальные conversation slot declarations, layout tree и `app/session.py`. Это не падение продукта |
| Автоматические проверки отчёта | Предыдущий прогон: **47/47 PASS**; лог и скрипт сохранены как приватные verification evidence. Проверены source paths, anchors, SHA/hashes, reference labels и формы секретов. Семь ошибочных ZH anchors первой версии исправлены. Этот прогон предшествует редактуре публичной метадаты; повторно не запускался и не доказывает product tests или Git diff |
| Pytest / builds / browser e2e / запуск DSH | **Не запускались**: продукт не менялся, воспроизведение runtime не входит в исследование. Ни один плагин не прогнан; прочитанные tests не объявляются зелёными. Исследован source package `app/`; `app` не импортировался |
| Provider/API/generation/benchmark исследуемых DSH/плагинов / review | Не выполнялись. Исследовательские LLM-ходы выполнялись; continuation только Sol, без делегирования и модельного ревью |
| Live config/БД/credentials/инфраструктура | Не читались; живой сервис не перезапускался и плагины не устанавливались |
| Git diff/commit/clean index Orchestra | **Не проверены:** worker-copy без `.git`; результат брокерного коммита из этой копии не подтверждён. Продукт не менялся |

Публичный состав результата ограничен `report.md`, `notes.md`, `.gitignore`. Raw, скрипт и лог проверки относятся к приватным evidence; их перенос в ignoredprivate и состояние родительского индекса проверяет принимающий оркестратор, из worker-copy это не подтверждено. Clone/video/cache и сырой текст не публикуются; public site для отчёта не создавался.

## Индекс первоисточников и артефактов

Все ссылки S/C ниже закреплены на одном SHA. EN/ZH prompts — изменяемый CDN, потому зафиксированы content hashes. TG — репост, не независимое доказательство первичной публикации.

- [S1 — plugin-manager README, persistent state, permissions, failures](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/README.md).
- [S2 — runtime inspection README](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/extensions/tool-cordis/README.md).
- [S3 — UI slots README](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/ui-slots/README.md).
- [S4 — conversation slot declarations](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/ui-conversation/src/client/contract/slots.ts#L278).
- [S5 — common Host operations for UI/tools](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/references/user-actions.md).
- [S6 — actual plugin_manager tool schema and approval](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/src/tools.ts#L82).
- [S7 — Creator preset wiring](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/web-app/presets/cordis.patch.yml#L122); [Standard preset](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/web-app/presets/standard.patch.yml#L125).
- [S8 — HMR lifecycle and limits](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/hmr/README.md).
- [S9 — client store persistence limits](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/store/README.md).
- [S10 — manager implementation](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/src/index.ts#L1260); [package operation snapshots/recovery](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/src/operations.ts#L283).
- [Persistent MCP walkthrough](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/docs/user/develop/practice/dynamic-cordis.md), [tool catalog](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/docs/tool-catalog.md), [verification reference](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/references/verification.md).
- Публичные замечания: `notes.md`. Приватные evidence: provenance и hashes/blob ids, наблюдения кадров, исходные команды, 30 source hashes, скрипт и лог проверки. Их наличие по публичному task path не предполагается.

[S1]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/README.md
[S2]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/extensions/tool-cordis/README.md
[S3]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/ui-slots/README.md
[S4]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/ui-conversation/src/client/contract/slots.ts
[S5]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/references/user-actions.md
[S6]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/src/tools.ts
[S7]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/bundle/web-app/presets/cordis.patch.yml
[S8]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/hmr/README.md
[S9]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/client/store/README.md
[S10]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/boot/plugin-manager/src/index.ts
[C1]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/templates/decoration/package.json
[C2]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/templates/decoration/cordis.patch.yml
[C3]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/templates/decoration/index.js
[C4]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/templates/decoration/client.js
[C5]: https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/packages/preset/agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml
