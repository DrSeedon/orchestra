# V-1120 — проверяемые источники

Все страницы проверялись 29.10.2026. Если точная дата публикации не дана страницей, ниже стоит «дата не установлена», а не дата индексации поисковиком. Сводный вывод и таблица тезисов — в [report.md](report.md). Короткие цитаты приведены для проверки конкретного места; переводы — наши. Перепечатки используются только для атрибуции, не для подтверждения технических правил.

## Первичные материалы Anthropic

| ID | URL; автор; дата/редакция | Что подтверждает и чего не подтверждает |
|---|---|---|
| A1 | [Safeguards warnings and appeals](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals); Anthropic Help Center; точная дата не установлена, страница сообщает относительное обновление | Разные основания санкций: повторные нарушения, создание аккаунта из неподдерживаемого места, нарушения условий. Отличает аккаунт от приостановленной организации. Не раскрывает балльную матрицу или предвестник через logout. |
| A2 | [Usage Policy, архив](https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944); Anthropic; Effective **15.09.2025** | Раздел Do Not Abuse our Platform в браузере раскрыт кнопкой. Запрещает обход бана другим аккаунтом и доступ в нарушение региональной политики. Общие мониторинг/санкции не доказывают слух. |
| A3 | [Privacy Policy](https://www.anthropic.com/legal/privacy); Anthropic; Effective **10.09.2026** | §§1–2: технические сведения, IP/приблизительная география, ОС/устройство, использование, платёжные данные; цели безопасности и предотвращения злоупотреблений. Из факта сбора нельзя вывести вес и знак признака. |
| A4 | [Where can I access Claude?](https://support.claude.com/en/articles/8461763-where-can-i-access-claude); Anthropic Help Center; страница показывает **16.03.2026**. Также [обновление ограничений продаж](https://www.anthropic.com/news/updating-restrictions-of-sales-to-unsupported-regions); Anthropic; **04.09.2025** | Перечень поддерживаемых мест и отдельные ограничения по контролю организаций. Подтверждают реальность региональной политики; не устанавливают местонахождение владельца и конкретный сигнал, использованный в его случае. |
| A5 | [Log in to your Claude account](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account); Anthropic Help Center; точная дата не установлена | Google/email вход, применение аккаунта на разных устройствах, переключение индивидуальной/рабочей организации, различие с API. Не утверждает антибан-преимущества мобильного канала. |
| A6 | [Consumer Terms](https://www.anthropic.com/legal/consumer-terms); Anthropic; Effective **08.10.2025** | §2 запрещает передавать свой аккаунт/credentials другим; §3 отдельно регулирует допустимый доступ и автоматизацию с исключениями. Несколько устройств одного пользователя и передача другим людям — не одна категория. |
| A7 | [How do I sign up for the Max plan?](https://support.claude.com/en/articles/11049752-how-do-i-sign-up-for-the-max-plan); Anthropic Help Center; точная дата не установлена | Instructions for new users предлагают выбор Max при onboarding. Нет опубликованного обязательного ожидания или предварительного Pro. Это не обещание, что любой платёж пройдёт проверку. |
| A8 | [Claude Code CHANGELOG, закреплённая редакция](https://github.com/anthropics/claude-code/blob/0e1f4789406477380b267a01f3ddd50b0211e5b3/CHANGELOG.md); Anthropic; [коммит 27.10.2026 20:23:56 UTC](https://github.com/anthropics/claude-code/commit/0e1f4789406477380b267a01f3ddd50b0211e5b3) | Версии 2.1.117/126/129/133/136 исправляли истечение и конкурентную порчу OAuth; 2.1.277 — logout при одновременной старой сборке; 2.1.287 — различение отозванного токена от общего 401. Даты отдельных релизов этим исследованием не устанавливались. Исправление в changelog не означает его наличие в работающем процессе Orchestra. |
| A9 | [Troubleshoot Claude error messages](https://support.claude.com/en/articles/12466728-troubleshoot-claude-error-messages); Anthropic Help Center; точная дата не установлена | Достижение пятичасового/недельного/model-specific лимита даёт сообщение о reset; ошибки входа имеют отдельную диагностику, включая cookies и status. Не раскрывает ни штраф за исчерпание, ни причину конкретного прошлого сброса. |
| A10 | [Why Claude switched models with Fable 5/5.1](https://support.claude.com/en/articles/15363606-why-claude-switched-models-in-your-conversation-with-fable-5-or-fable-5-1); Anthropic Help Center; **28.09.2026** | Реальные классификаторы запросов, fallback, ложные срабатывания, проверка всего контекста, в том числе памяти. Это не раскрытие штрафа за частоту работы на Fable. |
| A11 | [Identity verification on Claude](https://support.claude.com/en/articles/14328960-identity-verification-on-claude); Anthropic Help Center; **11.08.2026** | Проверки при отдельных возможностях и целостности платформы; не определяет запрос проверки как «наблюдательный период» и не даёт гарантии исхода. Здесь не предлагается владельцу новая верификация. |
| A12 | [Advanced setup — System requirements](https://code.claude.com/docs/en/setup#system-requirements); Anthropic Claude Code Docs; точная дата страницы не установлена | Официальная поддержка Ubuntu/Debian/Alpine и других ОС. Разрешённость Linux не даёт данных о закрытых весах и не доказывает их отсутствие. |
| A13 | [How do I log out of all active sessions?](https://support.claude.com/en/articles/10310342-how-do-i-log-out-of-all-active-sessions); Anthropic Help Center; точная дата не установлена | Веб-сессия 28 дней с обновлением при активности раз в час; глобальный выход и отзыв авторизации CLI. API keys отдельно. Не переносить срок веб-cookie на CLI access token. |
| A14 | [Authentication](https://code.claude.com/docs/en/authentication); Anthropic Claude Code Docs; точная дата не установлена | Причины повторного setup/login prompt, credential precedence, config directories, продление login, поведение env setup-token после `/login`. Не содержит связи logout с подготовкой бана. |
| A15 | [Verify payment method](https://support.claude.com/en/articles/11818288-why-am-i-being-asked-to-verify-my-payment-method); Anthropic Help Center; **16.03.2026** | Подтверждает наличие отдельного платёжного verification prompt. Не доказывает ранжирования карт и не требует новых действий от владельца. |
| A16 | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance); Anthropic Claude Code Docs; точная дата не установлена | Различает native Claude Code/собственный вход пользователя и продукты, обслуживающие других пользователей. Упоминает обычное индивидуальное использование CLI/Agent SDK; неизменённый CLI на сторонней платформе не равнозначен перепродаже подписки. |
| A17 | [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview); Anthropic Claude Code Docs; точная дата не установлена | SDK запускает бинарник Claude Code; отдельно ограничено предложение сторонними разработчиками claude.ai login/лимитов в собственных продуктах без согласования. Само наличие SDK в зависимостях не устанавливает нарушение. |

Короткие буквальные цитаты (для каждого источника суммарно менее 25 слов):

- **A1:** “Account creation from an unsupported location”. Перевод: создание аккаунта из неподдерживаемого места.
- **A2:** “Circumvent a ban through the use of a different account”. Перевод: обход бана с использованием другого аккаунта. Прочитано в раскрытом разделе архивной политики.
- **A7:** “During the onboarding process, select the Max plan option.” Перевод: при начальной настройке выберите Max.
- **A8, v2.1.133:** “Fixed parallel sessions all dead-ending at 401 after a refresh-token race wiped shared credentials”. Перевод: исправлен одновременный отказ параллельных сессий с 401 после гонки обновления credentials.
- **A13:** “this creates a session with a duration of 28 days”. Перевод: создаётся сессия длительностью 28 дней.
- **A14:** “Expired sign-in: your earlier sign-in expired and Claude Code can’t refresh it.” Перевод: предыдущий вход истёк и клиент не может его обновить.

### Будущие редакции — не подмена действовавших правил

- [AUP, текущий URL](https://www.anthropic.com/legal/aup), Anthropic: **Effective Nov 12, 2026**.
- [Supported Regions Policy](https://www.anthropic.com/legal/supported-regions), Anthropic: **Effective Nov 12, 2026**; сюда перенаправляет старый `/supported-countries`.
- [2026 Usage Policy update](https://www.anthropic.com/news/2026-usage-policy-update), Anthropic: опубликовано **08.10.2026**. Дата анонса и дата вступления редакции — разные даты.

Текущие URL полезны как ссылки на владельца политики, но их будущий текст не использован как доказательство конкретной действовавшей санкции. Архивная AUP взята через штатную кнопку See version history, а не придуманный адрес.

## Первоисточники публичного слуха и свидетельств

| ID | URL; публичный автор; дата | Статус / существенная оговорка |
|---|---|---|
| T | [Data Secrets /10237](https://t.me/data_secrets/10237), [публичный виджет](https://t.me/data_secrets/10237?embed=1&mode=tme); Data Secrets; **29.10.2026 08:13:16 UTC** | Найдены дата и прямая ссылка на NodeSeek. Короткая цитата: «якобы получает стартовые баллы». |
| N | [NodeSeek /949485](https://www.nodeseek.com/post-949485-1); **Doone**, **26.09.2026 02:58:07 UTC** | DOM `time[datetime]`, доступ через браузер. Короткая цитата: “用量过大通常只会触发频率限制（Rate Limit），而非直接封号。” Перевод: большой объём обычно вызывает ограничение частоты, а не прямой бан. Наблюдение автора, не официальное правило. |
| X1 | [X /2115293730941067637](https://x.com/Mashiro_0619/status/2115293730941067637); **真白大小姐 / @Mashiro_0619**, **28.10.2026 04:05 UTC** | Публичный браузер показал 18 пунктов. Короткая цитата: “观察期的典型特征是掉登录”. Перевод: типичный признак периода наблюдения — потеря входа. В том же пункте числа введены как пример, не измеренные пороги. |
| X2 | [X /2115501814090969583](https://x.com/make_claude/status/2115501814090969583); **make claude / @make_claude**, **28.10.2026 17:51 UTC** | Перегруппированный близкий список; основной текст не называет исходное исследование. Короткая цитата: “中国社区逆向拆解了Claude的封号机制”. Перевод: китайское сообщество разобрало механизм банов Claude. Это заявление автора, не подтверждённое reverse engineering. |
| F1 | [LINUX DO /2530127](https://linux.do/t/topic/2530127); **Totoria**, **06.07.2026 01:36 по странице** | Более ранняя гипотеза scoring. Короткая цитата: “以上信息仅作为参考，都是个人整理，不一定准确。” Перевод: информация для справки, личное обобщение, не обязательно точное. |
| F2 | [V2EX /1230133](https://www.v2ex.com/t/1230133), также [доступный хост](https://jp.v2ex.com/t/1230133); **rdvcc**, **27.07.2026**, ответы №17–18 | Короткая цитата: “这些信息，全部都是凭经验猜测，没有任何实证。” Перевод: сведения — догадки по опыту, без эмпирических доказательств. Не работник Anthropic, по собственному пояснению. |
| P1 | [anthropics/claude-code #24317](https://github.com/anthropics/claude-code/issues/24317); **pfallonjensen**, **09.02.2026 03:13:29 UTC** | Клиент 2.1.37/macOS; описывает повторные входы с несколькими процессами. На дату проверки closed/completed; комментарии о продолжении симптома есть после закрытия. Существование report не валидирует каждый комментарий. |
| P2 | [#76561](https://github.com/anthropics/claude-code/issues/76561); **SevenX77**, **11.07.2026 02:04:04 UTC** | WSL/ext4, символические ссылки и конкурентная запись. На дату проверки open. Это специальная файловая схема, не установленная схема Orchestra. |
| P3 | [#61923](https://github.com/anthropics/claude-code/issues/61923); **wdouglascampbell**, **24.05.2026 01:44:23 UTC** | Windows/VS Code, 400 refresh → 401 inference → login UI. Диагноз rotation — гипотеза автора; closed/not_planned не означает ни опровержение, ни подтверждение. |
| P4 | [#80380](https://github.com/anthropics/claude-code/issues/80380); **ammbot**, **23.07.2026 00:50:49 UTC** | Тело исправлено автором: исходный диагноз про static token отозван, фактически использовался Keychain login. Короткая цитата: “Withdrawn by author — root cause turned out to be local”. Дата исправления отдельно не установлена. |

## Нормативные технические источники

- **RFC 6749**, D. Hardt (редактор), октябрь 2012: [§5.2, invalid_grant](https://www.rfc-editor.org/rfc/rfc6749#section-5.2). Код ошибки покрывает истечение, отзыв и другие причины; сам по себе не обозначает бан. `evidence/rfc6749-invalid-grant.stdout.txt` — действительный вывод извлечения публичного текста.
- **RFC 9700**, T. Lodderstedt, J. Bradley, A. Labunets, D. Fett, январь 2025: [§4.14.2](https://www.rfc-editor.org/rfc/rfc9700#section-4.14.2). Описывает общие механизмы rotation/replay detection и отзыв refresh token. Это не спецификация закрытой реализации Anthropic. `evidence/rfc9700-refresh.stdout.txt` — действительный вывод извлечения строк из раздела.

## Перепечатки и коммерческий контекст

- [AI Code With, 29.10.2026](https://aicodewith.ai/zh/blog/claude-account-ban-reasons-claude-code-api-key): использован для поиска точных ссылок X1/X2. Тесты стороннего API из статьи не выполнялись. Сайт сам оговаривает отсутствие официального раскрытия баллов.
- [Fishason/Claude-anti-ban](https://github.com/Fishason/Claude-anti-ban/blob/main/README.md), [история 23.06.2026](https://github.com/Fishason/Claude-anti-ban/activity): рекламный интерес, без доказанной принадлежности к цепочке Telegram. Его проценты, обещания и сетевые советы не приняты за результаты этого исследования.
- Социальные зеркала [teapawt](https://teapawt.org/_ExploreAI/reposts), [Sotwe](https://www.sotwe.com/maxforai) и агрегатор [SoPilot](https://sopilot.net/hot-tweets?tweetId=2000379707494433156) дали поисковые зацепки. Счётчики просмотров, относительные даты и агрегаторские идентификаторы не использованы как доказательства; после открытия X опора перенесена на оригиналы. Отсутствие полного текста в web-инструменте не замещено догадкой.

## Предел атрибуции

Подтверждена ссылка **T → N**. Найден самый ранний близкий полный текст **X1**, затем **X2**. Нет подтверждённой ссылки T → X1/X2 и нет подтверждённого исходного эксперимента до X1. Более ранние F1/F2 показывают историю гипотезы, но не доказывают авторство полного октябрьского списка. Нельзя называть весь найденный набор независимыми подтверждениями одной «утечки».
