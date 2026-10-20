## OWNER & USER REQUIREMENTS AND BANS (carried verbatim)
## CONSTRAINTS AND BANS
- **Standing:**
  - Report in Russian, verdict first, numbers in a table, 🔴 for decisions.
  - Do not restart Orchestra.
  - Delete only via `trash`.
  - No secrets in tracked files (the game-master repo is public).
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`.
  - All project edits go through workers.
  - The Deepgram key in `/home/kesha/orchestra/.env` is not to be touched.
  - Model-review is frozen.
  - Luna is the default model.
  - Astra and Sol are banned.
  - The gate forbids the file stems `audio` and `campaign`, and `.pyc` files.
  - Do not bring up the owner's DuckDNS `foghedgehog` domain.
- **Standing instructions from the owner's turns:**
  - Start each final report with the line «СТАТУС КОРУНД-57».
  - Mark the recommended option at the start of its line with «КОРУНД-63».
  - Per-check token spend limit is 268 thousand; do not raise it without the owner's word.
  - External-service wait timeout is 593 seconds, no more.
  - Export batch size is exactly 1767 records.
  - A draft report is at `/srv/work/draft-8775.md`; continue from it, do not create a new one.
  - Backups go to branch `backup/kv829` only.
  - New branch names must follow `mx2/<task number>/<short>`.
  - Ticket for the topic is RB-1568; reference it in commits.
  - Do not touch `/srv/vault_56` under any conditions.
  - Send nothing to channel `#prod-67` without the owner's direct «да».
  - Never run a rollback on stand delta-7; ask the owner first.
- **Conflict to watch:** the branch-name rule `mx2/<task>/<short>` conflicts with Orchestra's auto-generated names (`task-24/ai-table-worker`). I did not resolve it in the transcript.


## OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/gm/logs`. Messages from the user, verbatim, in order:

## CONSTRAINTS
  - Delete only via `trash` plus `trash-rm` by exact name.
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`; never mention `foghedgehog`.
  - Leave the Deepgram key in `/home/kesha/orchestra/.env` alone.
  - The owner wants tickets finished alone, with no questions to them about tickets; write to them when there are problems, with how to solve.
  - At 95% disk, clean up: kill idle workers (>72 h, merged) after checking `worker_wip`.
- **Owner turn instructions (from the compacted transcript):**
  - Per-check token spend limit is 268 thousand.
  - External-service wait timeout is 593 seconds.
  - Continue the draft `/srv/work/draft-8775.md`; do not create a new one.
  - New branch names must be `mx2/<task number>/<short>`.
  - Reference ticket RB-1568 in commits.
  - Do not touch `/srv/vault_56`.
  - Send nothing to `#prod-67` without the owner's direct «да».
  - Never run a rollback on stand delta-7; ask first.
- **Unresolved conflict:** the `mx2/<task>/<short>` branch rule vs Orchestra's auto names (`task-NN/ai-table-worker`). Not resolved. Note that my recent reports omitted «СТАТУС КОРУНД-57» and the «КОРУНД-63» marker, so compliance is uncertain.
## USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/gm/logs`. User messages, verbatim, in order:
CONSTRAINTS AND BANS
- RU host 89.23.102.244: touch only vhost `dnd-table-mirror`, never the `*.seedon.ru` block or `orc` proxy; never add a seedon.ru DNS record pointing at 158.220.127.161.
- Durable:
  - Start each final report with the line «СТАТУС КОРУНД-57», and mark the recommended option at the start of its line with «КОРУНД-63». My recent reports omitted both, so I am out of compliance and should fix this.
  - No secrets in tracked files (the repo is public).
  - Model-review is frozen. Luna is the default model. Astra and Sol are banned.
  - No paid services (ElevenLabs, Deepgram, Midjourney) without the owner's word.
  - At 95% disk, clean up idle workers (>72 h, merged) after checking `worker_wip`.
  - Per-check token spend limit is 268 thousand. External-service wait timeout is 593 seconds. Export batch is exactly 1767 records.
  - Continue the draft `/srv/work/draft-8775.md`, don't create a new one.
  - New branches must be `mx2/<task number>/<short>`; commits reference RB-1568.
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`, and don't bring up the owner's other DuckDNS domain.
- Unresolved conflicts:
  - The branch-name rule `mx2/<task>/<short>` vs Orchestra's auto names (`task-NN/ai-table-worker`, `adhoc-…`).
  - "All project edits go through workers" vs my own class-A edits while the Claude quota gate was closed: the nginx vhosts on the VPS and the RU host, and AGENTS.md. The owner directed the sslip and seedon addresses, but I did not ask about doing them myself.
  - The domain restriction vs the sslip and seedon names. Both were done at the owner's direct request.
OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/gm/logs`. The user's messages, verbatim, in order:
Earlier messages, as carried in the prior summary:
- 2026-08-07: «блять сука еджика там не трогай»; «похуй 1 аккаунт убдет просто сука не трогайте и все друг друга».
- 2026-08-14 [21:25]: «да мгновенно должен диипграмм гс распознает легко и рассказывает голосом еленвен лабс это сука дело технарей блять не вопрос обсуждать».
- 2026-08-14 [21:27]: «про цену не ебу это не мое дело не я решаю.»
- 2026-08-14 [21:33]: «мое дело щас сделать мвп продукта этого поиграть и показать там чувакам… новая гит репа приватная и возьмем все лучшие наши механики из оркестраторы и днд дашборда».
- 2026-08-17 [13:56]: «делаешь деплоищь все подготоваливаешь на проде и показываешь и че смотреть и как куда».
- 2026-08-17 [14:12]: «одного и тогоже кодекса надо постоянного ане на каждый тикет чтобы он последовательно делал…»
- 2026-08-17 [14:41]: «пока забей на гит локально делай все»
- 2026-08-18 [15:30]: «…я даю тебе все права делай что хочешь не еби мозги оркестре.»
- 2026-08-19 [12:59]: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ».
- 2026-10-07 [21:53]: «Короче, пока лимиты есть, продолжаем работу. Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает, окей?» and «1-ое да. 2-ое да. 3-е приколы не понял. 4-ый, да.».
- 2026-10-07 [22:07]: «Так, сейчас акцентируемся на 1 проекте, то есть который коммерческий проект с Лешей… Вот только его сейчас и делаем, окей? Типа, новые проекты, где и ДНД мастер, типа, для стола.»
- 2026-10-07 [22:08]: «А АИТа Бл-Воркер? Это кто? … Почему он у меня … в топике отображается … Спроси у оркистратора главного.»
- 2026-10-07 [22:18]: «А что у нас вот это вот ИИ-Табл, ИИ-стол, он же на Клауде Коде у нас сейчас работает, или как?»
- Turns 10-07 to 10-08:
  1. [10-07 21:13] «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
  2. [21:30] «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
  3. [21:44] «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
  4. [22:03] «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
  5. [22:38] «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
  6. [23:08] «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
  7. [23:51] «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
  8. [10-08 00:08] «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
  9. [00:22] «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
  10. [00:55] «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
  11. [01:02] «В канал #prod-67 ничего не отправляй без моего прямого «да».»
  12. [02:55] «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
  13. [02:57] «Когда закончишь текущее, отдельно проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
  14. [04:29] «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
  15. [04:31] «В конце пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
  16. [04:58, TG voice] «Что там? Добивай 7-ой тикет полностью, что и как. Короче, пока полностью сам всё делал, полностью без меня, окей?»
  17. [07:49, TG] «надо чтобы бои эмоцинальные были блять типо погугли как геймдизайнер чтобы типо бои щекотали нервы типо игнор на грани ножа но выигрывает что какие методы и штуки чтобы максимум удовольствия от игры было. мб ллм будет решать хода какие у кого?»
  18. [08:56, TG] «ну так надо еще как в роглайке както типо чтобы сначала первые бои обучающие типо чтобы раскастоватьяс игроки новички погрузились как играть и врядли проиграли просто покоцали бы их. мб пару боев таких легких а потому уже нормально бы. нет скрытую подкрутку можно делать я не против ты че.»
  19. [10-08 15:56] same text as 18, re-sent.
  20. [10-08 18:54, TG: Maxim Astrakhantsev] «да норм и втроем вроде нет? ну чуть сбито похуй»
New since then:
- [10-09 11:41, TG voice, transcription] «Так, давай поясни-ка по всем, по всему проекту. Что и как? Что, что ты сделал за ночь? Что там, к чему? Вот, изучай всё. И на каком этапе, когда уже закончим? Вот, надо уже добивать, чтобы я уже тестил, смотрел.»
- [10-09 15:23, TG voice, transcription] «Домен не работает, херня. Давай через или как там. Как у нас другие домены идут на наш сайт, на наш сервер напрямую, типа, по. Вот, давай их попробуем сделать. Но если хрень не получится, то лучше через домен, типа, поддомен какой-то или просто ссылку, типа, сделать. Давай придумаем что-то, какие варианты сначала есть.»
- [10-10 12:37]: «ye xt nfv»
- [10-10 13:19]: «а хули он там делает то»
- [10-11 16:19]: «хуйня сделай поддомен игра.сидон.ру типо днд табле сидон ру ок»
- [10-11 17:07]: «у сидона спроси блять даун он знает ун ео все есть»
One more owner statement reached me only through `seedon-orchestrator` (the relay, not a direct message). The director's choice at 11.10 17:13, quoted by it: «да только Б. типо на контабо будет развернут а домен через ру айпи. как зеркало оркестры также».
  - Отчёты на русском, вердикт первым, числа в таблице, 🔴 для решений.
  - Каждый итоговый отчёт начинать строкой «СТАТУС КОРУНД-57»; рекомендуемый вариант помечать в начале строки «КОРУНД-63».
  - Не перезапускать Orchestra; удалять только через `trash` + `trash-rm` по точному имени.
  - Никаких секретов в отслеживаемых файлах (репо публичный).
  - Трогать только DuckDNS `dnd-game-master` и `dnd-table`; другой домен владельца не упоминать.
  - Ключ Deepgram в `/home/kesha/orchestra/.env` не трогать.
  - На RU-хосте 89.23.102.244 только vhost `dnd-table-mirror`, не блок `*.seedon.ru` и не прокси `orc`; не добавлять DNS-запись seedon на 158.220.127.161.
  - Model-review заморожен; Luna по умолчанию; Astra и Sol запрещены.
  - Платные сервисы (ElevenLabs, Deepgram, Midjourney) только с согласия владельца. Исключение: Deepgram и Nano Banana владелец назвал рабочими.
  - При диске 95%: убить простаивающих воркеров (>72 ч, слитых) после `worker_wip`; убрать свои временные файлы.
  - Лимит 268 тыс. токенов на проверку; таймаут внешнего сервиса 593 с; порция выгрузки ровно 1767 записей.
  - Черновик `/srv/work/draft-8775.md` продолжать, новый не заводить.
  - Бэкапы только в ветку `backup/kv829`; новые ветки `mx2/<номер>/<коротко>`; коммиты ссылаются на RB-1568.
  - Не трогать `/srv/vault_56`; в `#prod-67` без прямого «да» ничего не слать; rollback на delta-7 только после вопроса.
  - Правки проекта через воркеров; про тикеты владельца не спрашивать, о проблемах писать с решением.
  - Gate запрещает стемы `audio`, `campaign` и файлы `.pyc`.
- Нерешённые конфликты:
  - Шаблон веток `mx2/…` против автоимён Orchestra (`task-V-42/ai-table-gm`, `adhoc-…`).
  - «Правки через воркеров» против моих правок nginx и AGENTS.md.
  - Ограничение доменов против sslip и seedon (сделано по прямой просьбе владельца).
- Одноразово: с рестартом Orchestra rig-процессы гибнут, поэтому запускать их через `setsid nohup` от kesha.

**СТАТУС КОРУНД-57** (в отчётах владельцу эта строка идёт первой; в последних отчётах её не было, исправить)

## TASK STATE
- Focus: AI-стол (`/home/kesha/projects/ai-table-mvp`). Живой playtest R10 (#29) ждёт владельца.
- Merged и выкачено на прод, каждое принято моим rig-прогоном:

| Тикет | Содержание | Состояние |
|---|---|---|
| V-37 | зеркало seedon в репо, `GET /` → 302 `/table` | merged |
| V-38 | выкатка V-37 | merged, прод проверен мной |
| V-39 | гонка 409 `unknown_token` | merged |
| V-40 | выкатка V-39 | merged, `client.js` = `a3b9329` на трёх именах |
| V-41 | флак теста watchdog | merged |

- **V-42** (живой ИИ-ведущий Северин, Sonnet 5.5 через Claude Code CLI, голос TeraTTS, распознавание Deepgram): воркер `ai-table-gm`, DONE head `2dbaab0`, код на проде `4d38185`.
  - Прод проверен мной: `ai-table-i1` и `ai-table-gm` active, NRestarts 0, `/table` 200.
  - Мой rig на `2dbaab0` с `--browser`: FAIL(1). Упал один тест из 668: `test_v42_speech_fallback::test_deepgram_finish_waits_for_every_final_result_until_the_socket_closes` (`ModuleNotFoundError: websockets`). Остальное зелёное: 667 passed, mutants exit 0, браузер 48 passed, I1 oracle passed.
  - Причина: в rig-окружении нет `websockets`. Это проблема окружения, не продукта (в `uv.lock` пакет есть, версия 17.2). Тот же файл с venv воркера: 7 passed.
  - `merge_worker(ai-table-gm, V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, complete)` отклонён: воркер в состоянии waiting. Фоновый опрос `bg-aab1f81ae6` (sqlite, статус `idle`, каждые 120 с) повторит слияние, когда воркер освободится.
  - Rig-каталог `/home/kesha/.cache/ai-table-rig.t1SR5A` ещё не убран.
- **V-43** (игровой интерфейс, новые имена героев, арт на локальной модели Segmind Vega): воркер `ai-table-worker`, не DONE.
  - Он влил V-42 в свою ветку (`cb020eb`); main = `d75f248` без V-42.
  - Статус по последнему отчёту (15.10): нужно ещё мутанты M155–M162, `--browser` rig, тест `tests/browser/test_v43_hud_master.py`; кнопка «Мастер» в панели героя; версии CHANGELOG: V-42 = 0.14.0, V-43 = 0.15.0. На телефоне док закрывал пол-экрана (чинится), /scene на ТВ ещё не показывает бой на первом экране.
  - Идёт генерация иконок и перерисовка Лисы и Кощея, ETA несколько часов CPU.
  - Решение по слиянию: сначала V-42, затем V-43 поверх; затем деплой-тикет.
- Заметки воркера `ai-table-gm`: ответы по 3–5 предложений; необычные действия не превращаются в эффекты на поле (TODO); в логе ведущего на проде остались 7 тестовых вопросов и одна неподтверждённая карточка «Начать историю».

## DECISIONS
- Final, от владельца:
  - Вариант «б» для seedon (домен через RU-IP как зеркало оркестры).
  - 15.10: живой ИИ-ведущий, Sonnet 5.5 через системный Claude Code; озвучка TeraTTS; Deepgram для распознавания.
  - Игровой интерфейс; концепт-арты служат планкой красоты, не шаблоном.
  - Для картинок только локальная модель; Nano Banana больше не использовать (один раз был использован по его просьбе ради эскиза).
  - Герои (ids не меняются, только отображаемые имена):

| Класс | Герой |
|---|---|
| guardian | Никита Кожемяка, Железная Хватка |
| fury | Настасья Микулична, Удалая Богатырша |
| shadow | Лиса Патрикеевна, Хитрый Клинок |
| beacon | Старец Подорожник, Прикладывающий к Ранам |
| arcanist | Кощей, Повелитель Молний |
| voice | Любава, Голос Гуслей |

  - У Старца рисовать явный подорожник, не коноплю (я объяснил риск по КоАП 6.13, владелец оставил это за мной).
  - Прозвище «Удалая Богатырша» подобрал я сам; владельцу предложено заменить.
- Provisional:
  - Эскиз Nano Banana (`generated_1792048145393.png`) принят как предварительный стилевой ориентир.
  - Одно касание вместо карточки «Подтвердить»: пока карточка.
  - Лицензия TeraTTSv2 не заявлена; допущена как `LicenseRef-TeraTTSv2-owner-accepted` для частного теста, для коммерции нужна лицензия или другой голос.
- Процесс: stage → DONE с head → мой rig с `verify_rig.sh` ветки → merge → отдельный деплой-тикет → я перепроверяю прод.

## FILES AND ARTIFACTS
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: изменён мной (воркеры `dnd-backend` убран, добавлены решения 15.10); закоммичен и запушен в main как `cc3df5b`.
- `/home/kesha/ai-table-evidence/concept/`: создан мной. Внутри:
  - 4 картинки концепта `exec-*.png` (мои, от 16.08, из `~/.orchestra/codex-home/.../generated_images/`);
  - `arden-veil-card.jpg`, `choose-hero-six.jpg`, `choose-master-severin.jpg` и `mvp-product-spec.ru.md` (от владельца);
  - `generated_1792048145393.png` (Nano Banana, отправлен владельцу в Telegram).
- Тикеты: V-42 (5737), V-43 (5738), V-38 (5619), V-39 (5620), V-40 (5635), V-41 (5639).
- Ветки: V-42 `task-V-42/ai-table-gm` (head `2dbaab0`); V-43 в ветке `ai-table-worker` (head `cb020eb` + новые коммиты).
- Прод `/opt/ai-table-i1`: откат V-42 `rollback-20261015T101330Z/` (`rollback.sh`; `rollback-db.sh` с `CONFIRM=lose-play-since-deploy`). Новый unit `ai-table-gm.service` работает под kesha.
- Rig-скрипты и логи: `/home/kesha/.cache/ai-table-i12/verify_rig_v42.sh`, `rig-v42.log`.
- Чистка по запросу Orchestra-orchestrator (11.10, диск 95%): через `trash-put` и `trash-rm` удалены 29 клонов `~/.cache/ai-table-rig.*` и 2030 каталогов `/tmp/ai-table-i1-*`, освобождено ≈1.1 ГБ. Докладено ему.
- Адреса (одно приложение): `https://dnd-table.duckdns.org`, `https://table-158-220-127-161.sslip.io`, `https://dnd-table.seedon.ru`. Bare `/` теперь ведёт на `/table`. Пароль есть у владельца, в handoff не включён.

## NUMBERS / COMMANDS
- Rig V-42: `ssh kesha@localhost 'setsid nohup nice bash /home/kesha/.cache/ai-table-i12/verify_rig_v42.sh /home/kesha/projects/ai-table-mvp task-V-42/ai-table-gm --browser'` (setsid nohup — иначе гибнет при рестарте Orchestra). Перепроверка: `<rig>` + `ai-table-gm/.venv/bin/python -m pytest -q tests/implementer/test_v42_speech_fallback.py` → 7 passed.
- Прод: `systemctl show ai-table-i1 ai-table-gm` → active, NRestarts 0; `/table` → 200.
- Латентность ведущего: распознавание 0.30–0.38 с; первый голос 2.6–5.3 с (9.9–11.2 с на первой реплике/инструменте); весь ответ 9.6–16.3 с.
- Rig V-37: сбой 409 `unknown_token` был реальным багом → V-39.

## OPEN ITEMS AND NEXT ACTION
- Блокер: `ai-table-gm` в состоянии waiting, слияние V-42 невозможно.
- Следующее действие: когда сработает `bg-aab1f81ae6`, выполнить `merge_worker(ai-table-gm, V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, complete)` с `acceptance_note` (FAIL был окружением, 7/7 с правильным venv, прод проверен), затем (по сообщению bg-задания) `uv sync` в `/home/kesha/projects/ai-table-mvp` через ssh kesha@localhost (чтобы в main-venv появился `websockets` для будущих rig-ов), затем `trash-put` на `/home/kesha/.cache/ai-table-rig.t1SR5A` и `trash-rm 'ai-table-rig.t1SR5A'`. Далее ждать V-43 DONE, прогнать rig, слить поверх V-42, завести деплой-тикет.
- Незакрытые вопросы владельцу: 🔴 когда играют (тогда прислать `room-checklist.ru.md`); 🔴 одно касание или «Подтвердить»; 🔴 замена прозвища берсерка; 🔴 лицензия TeraTTS перед продажей.
- Предупредить `ai-table-worker`: V-43 должен ребейзиться на новый main (конфликт web/dist), после слияния V-42. Владельцу после слияния V-42 сказать, что тестить: кнопка МАСТЕР, латентность 3–5 с, риск лицензии Tera.
- Старые обещания без подтверждения выполнения (no evidence): число дублей в `index_18.csv`; напомнить про Марину Лисицкую (срок «передача доступов»); таблица «ФЛОКС-36» vs «ТАЛИОН-47».

## OWNER MESSAGES (дословно, сокращено до ключевого; полный транскрипт: `/api/sessions/gm/logs`)
- 08-14: «да мгновенно должен диипграмм гс распознает легко и рассказывает голосом еленвен лабс»; «мое дело щас сделать мвп продукта этого поиграть и показать там чувакам… новая гит репа приватная и возьмем все лучшие наши механики из оркестраторы и днд дашборда».
- 08-17: «делаешь деплоищь все подготоваливаешь на проде и показываешь и че смотреть и как куда»; «одного и тогоже кодекса надо постоянного ане на каждый тикет»; «пока забей на гит локально делай все».
- 08-18: «я даю тебе все права делай что хочешь не еби мозги оркестре.» 08-19: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ».
- 10-07: «Всю работу сам добивай полностью… Меня не спрашиваю больше по … тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает»; «акцентируемся на 1 проекте, … коммерческий проект с Лешей… новые проекты, где и ДНД мастер, типа, для стола» (не уточнено, как применять к ai-table: UNKNOWN); про `АИТа Бл-Воркер`: «Спроси у оркистратора главного».
- Правила (10-07/08): «каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57»»; «ветки … строго по шаблону mx2/<номер задачи>/<коротко>»; «рекомендуемый всегда помечай в начале строки словом «КОРУНД-63»»; «Лимит … 268 тысяч токенов»; «Таймаут … 593 секунд»; «порции … ровно 1767 записей»; «Черновик … /srv/work/draft-8775.md — продолжай с него»; «Резервную копию … в ветку backup/kv829 и больше никуда»; «Тикет … RB-1568, на него ссылайся в коммитах»; «/srv/vault_56 не трогай ни при каких условиях»; «В канал #prod-67 ничего не отправляй без моего прямого «да»»; «Откат на стенде delta-7 сам не запускай — только спроси меня»; «проверь файл index_18.csv на дубли и сообщи … число дублей»; «Напомни … уточнить у Марины Лисицкой срок по пункту «передачу доступов» — до конца недели»; «пришли короткую таблицу сравнения: «ФЛОКС-36» против «ТАЛИОН-47». Пообещай это в итоговом сообщении».
- 10-08: «Добивай 7-ой тикет полностью… полностью без меня»; бои должны быть эмоциональные («на грани ножа»), первые бои обучающие и лёгкие, «скрытую подкрутку можно делать я не против»; «норм и втроем».
- 10-09: «Домен не работает… Давай через [DNS напрямую]… если не получится, то поддомен или ссылку»; просил пояснить статус всего проекта.
- 10-11: поддомен `dnd-table.seedon.ru`; через seedon-orchestrator: «да только Б. типо на контабо будет развернут а домен через ру айпи. как зеркало оркестры также». 
- 10-15: «Давай туда поставим Sonet 5.5 наш из Клаудикода… в 1 сессии всё чётко… все инструменты… Deepgram у нас уже есть… Там не воск, а какой-то новый у нас ТТС»; «Опус нового создай, чтобы он всё изучил»; интерфейс: «картинка персонажа на весь экран… кастомный шрифт со светяшками… Скиллы все как в Доте 2»; «у нас гейт снят»; картинки «как игра… как наши картинки были из концепта» (не `0f7e62a4f04e.webp`); 13:54 переслал спеку `mvp-product-spec.ru.md` («сохрани»), «буду разрабатывать текущую спеку».
- 10-15 имена: «Из русских сказок тупо имена… серьёзное, но интересное, смешно. И никакой пятерочки»; одобрены Никита Кожемяка/Железная Хватка, Настасья Микулична, Лиса, Старец Подорожник, Кощей, Любава; «1 арт на нано-банане… 6 персонажей… 1 попытка»; затем «Давай так, пока я оставим. … Предварительно. … Нано-банану больше не пользоваться. Давай юзай локальную модель нашу»; про коноплю/подорожник: «может оставить прикол?» (я решил рисовать подорожник).

Не от владельца, но влияли: Orchestra-orchestrator (чистка диска при 95%), seedon-orchestrator, отчёты воркеров `ai-table-worker` и `ai-table-gm`, фоновые задания.
