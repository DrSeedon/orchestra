# V-1087 — публичные условия ChatGPT Plus → Free и Claude Max 20x → 5x

Дата проверки: **2026-10-25**. Только публичные страницы OpenAI/Anthropic, открытые без авторизации. Это срез полученных документов, а не гарантия доступности для конкретного аккаунта или неизменности условий. Изменяемые справочные страницы не являются архивным доказательством состояния на любую другую дату. Личная статистика, регион оплаты, даты списаний и доступные аккаунту предложения здесь не исследовались. Рекомендации о покупке отсутствуют.

## Таблица условий

`price` — базовая месячная USD-цена веб-подписки до применимых налогов; не сумма конкретного регионального счёта. `publishedcapacity` не означает фиксированное число токенов. В строках OpenAI окна относятся к **Codex**, а не ко всем функциям ChatGPT.

| provider | plan | price | billingunit | publishedcapacity | windows | includedproducts | modelrestrictions | effectivedowngrade | cancel | date | sourceURL | unknowns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | ChatGPT Plus | $20 | пользователь / месяц; годового Plus нет | Расширенный Codex; оценки по моделям ниже | Codex: 5h + weekly; для продолжения нужны оба остатка | ChatGPT; Codex; Work; API оплачивается отдельно | Шире Free; конкретные модели зависят от продукта/rollout | Plus → Free после оплаченного периода при обычной отмене | Через исходную платформу; ≥24h до следующего счёта | 2026-10-25 | [Plus][O1], [Codex][O2], [отмена][O3] | Абсолютная weekly-квота; фактические reset/end timestamps; региональная цена |
| OpenAI | ChatGPT Free | $0 | нет платы за подписку | Ограниченный Codex; публичного постоянного числа задач нет | Сопоставимая числовая таблица 5h/7d для Free не найдена | ChatGPT; ограниченные Codex/Work; Codex Cloud не включён | Pricing: GPT-6 Luna Standard в desktop, по rollout; документы не полностью согласованы | Применяется после окончания Plus | Отменять плату Free не требуется; отдельные покупки не входят в $0 | 2026-10-25 | [Pricing][O2], [доступ Codex][O4], [Free FAQ][O5] | Точная ёмкость, доступ CLI/IDE и модель конкретного Free-аккаунта |
| Anthropic | Claude Max 20x | $200 | пользователь / месяц; только monthly | 20 × Pro per-session | 5h; общая weekly; отдельная weekly Fable | Claude web/mobile/desktop; Claude Code; API-credit benefit отдельно | Opus и Sonnet включены; 20x не означает безлимит | 20x → 5x в конце текущего billing period | Обычная отмена: paid до конца периода, затем Free; ≥24h до renewal | 2026-10-25 | [Max][A1], [pricing][A2], [Claude Code][A3], [отмена][A4] | Абсолютные/относительные weekly-квоты, остаток после смены плана |
| Anthropic | Claude Max 5x | $100 | пользователь / месяц; только monthly | 5 × Pro per-session | 5h; общая weekly; отдельная weekly Fable | Те же основные продукты, включая Claude Code; меньший API-credit benefit | Opus и Sonnet включены; публичного запрета Opus именно для 5x нет | Получатель downgrade после конца периода 20x | Те же правила отмены Max | 2026-10-25 | [Max][A1], [pricing][A2], [Claude Code][A3], [отмена][A4] | Число задач/часов, коэффициенты списания, модельные ограничения при изменении политики |

## Цена, налоги и даты платежей

OpenAI публикует Plus за $20/month; API не входит. В условиях предусмотрено начисление обязательных налогов. Есть локализованные цены и валюты, а App Store/Google Play ведут собственный биллинг. Поэтому локальную цену нельзя получать простым пересчётом $20 по курсу. Конкретная ставка VAT/sales tax и итоговая сумма без юрисдикции неизвестны. [Plus][O1], [Terms of Use — Paid accounts][O6], [Multi-currency billing][O7].

У Anthropic $100/$200 относятся к веб-подпискам Max; мобильная цена может отличаться. Pricing явно исключает применимые налоги из показанной цены. Налоговая юрисдикция определяется billing address; для self-service Max адрес берётся из платёжного метода. Единой мировой ставки нет. [Max][A1], [pricing][A2], [billing address and tax calculation][A5].

Для месячного ChatGPT дата следующего счёта повторяет дату подписки; изменить invoice date нельзя. Это не дата сброса Codex. Фактические `next_bill`, `paid_access_end`, часовой пояс и канал оплаты родитель установит локально; из названия плана они не выводятся. [Invoice dates][O8], [Codex resets][O9].

## Claude: ёмкость, модели и продукты

**5h и 7d.** Множители 5x/20x опубликованы относительно Pro **за сессию**, с reset каждые пять часов. У Max есть общая недельная квота всех моделей: день/время недельного reset закреплены за аккаунтом независимо от начала подписки или использования. Числовых weekly-объёмов и обещания `weekly(20x) = 4 × weekly(5x)` в проверенных документах нет. Anthropic оставляет возможность дополнительных модельных, месячных и иных ограничений. [What is the Max plan?][A1].

Claude, Claude Code и Desktop расходуют общий лимит; отдельная установка/поверхность не создаёт дополнительную квоту. Контекстное окно — отдельное ограничение длины одного разговора, не пятичасовой/недельный бюджет. На расход влияют модель, effort, длина/сложность диалога и функции. [Usage and length limits][A6].

**Claude Code включён в оба Max**, в terminal и поддерживаемых IDE, с общими лимитами Claude. Текущая статья отдельно указывает weekly Fable. При достижении 5h возможна небольшая ограниченная завершающая часть уже идущего ответа, с расходом weekly; это rollout, не право начинать новые запросы сверх лимита. API-аутентификация и платное продолжение — другие способы оплаты, а не дополнительная подписочная квота. [Use Claude Code with Pro or Max][A3].

**Opus/Sonnet на 5x и 20x.** Таблица Anthropic ставит `Yes` обеим семьям на обоих Max. Она не публикует отдельного коэффициента ёмкости Opus против Sonnet. Для Fable отдельно показано 50% weekly limits на обоих Max; из одинакового процента не следует одинаковый абсолютный объём. Основные продукты сохраняются при 20x → 5x. [Claude pricing — Models and usage][A2].

Текущие Claude Code docs описывают `opus`/`sonnet`, `opusplan` (Opus для планирования, Sonnet для исполнения) и default Opus 5.5 для Max; aliases/доступ зависят от версии клиента и провайдера. Следовательно, различие tier нельзя подменять утверждением «5x только Sonnet». [Model configuration][A7]. Более высокий effort увеличивает токены и быстрее расходует лимит. [Model, effort and thinking settings][A8].

Поиск возвращал старый фрагмент статьи о Code с Opus 4, 225/900 сообщениями, 50–200/200–800 prompts и переключением Opus→Sonnet при 20%/50%. В открытой текущей редакции статьи [A3] этих правил нет. Они **не приняты как текущие гарантии**. Это особенно важно при чтении старых отчётов и поисковых snippets.

### Отдельные API-кредиты Max

Проверенная текущая документация публикует monthly API credits: **$100 для Max 5x, $200 для Max 20x**. Требуются активный допустимый план, семь дней для новых подписчиков и claim через привязку Console organization. Кредиты выдаются по billing cycle, не переносятся на следующий и расходуются раньше купленных. Они **не применяются к интерактивному Claude Code** (terminal/IDE/desktop/web), Claude/Cowork extra usage и не меняют подписочные лимиты. При cancel/refund/ineligible downgrade новые выдачи прекращаются, уже выданные действуют до expiry. Документ не даёт отдельной точной процедуры пересчёта уже выданного баланса при 20x → 5x; меньший будущий номинал не равен возврату денег. [Monthly API credits][A9].

`Usage credits` для продолжения после исчерпания подписки — отдельная покупка по API rates с собственным балансом/лимитом расходов. При включении они позволяют продолжать после 5h, общей weekly или Fable weekly; обычные reset продолжаются. Наличие monthly API benefit не делает это продолжение бесплатным. [Manage usage credits][A10]. Ничего не включалось и не покупалось.

## Codex Free против Plus

Pricing включает Codex/Work в ChatGPT-планы, но у Free описывает GPT-6 Luna Standard в desktop с оговоркой rollout. Plus перечисляет web/CLI/IDE/iOS, cloud integrations и GPT-6.1 Sol/Luna. Help подтверждает Codex для Free, но исключает Codex Cloud из Free/Go. **Нельзя обещать прежний маршрут Orchestra/CLI или прежнюю модель на Free** только на основании общей фразы «Codex included». [Codex pricing][O2], [Using Codex with your ChatGPT plan][O4].

Есть несогласованность публичных страниц: [ChatGPT pricing][O10] всё ещё показывает ограниченный GPT-5.6 Terra для Free в Work/Codex desktop, а [Codex pricing][O2] — GPT-6 Luna subject to rollout. Это не доказательство отсутствия доступа вообще; и не подтверждение равенства Free и Plus. Исчерпывающий актуальный список моделей/поверхностей конкретного аккаунта публично не установлен.

Оценки **локальных сообщений за 5h на Plus**: Astra 5–45; GPT-6.1 Sol 15–160; GPT-6 Sol 15–150; GPT-6 Luna 350–3000. Это диапазоны типичных задач, не минимально гарантированный пакет и не взаимно независимые лимиты. Work и Codex делят allowance; при действующих 5h и weekly нужны оба остатка. Новая 5h-сессия начинается первым запросом после завершения предыдущего окна. Числового weekly-пакета и соответствующей таблицы Free нет. Модель, контекст, effort и инструменты меняют расход; переключение модели не восстанавливает общий бюджет. [Managing usage with GPT-6 Astra][O11].

### Reset и credits — разные механизмы

| Механизм | Plus | Free / ограничения |
| --- | --- | --- |
| Обычный scheduled reset | Применимы 5h и weekly; проверяются раздельно | Точное расписание/объём Free не установлены публичной сравнительной таблицей |
| Banked reset | Разовый выданный benefit; восстанавливает допустимые основные окна текущего плана, не увеличивает их навсегда | Доступность, срок и допустимые планы зависят от конкретной акции; перенос benefit при downgrade не обещан |
| Automatic/global reset | Применяется к выбранным аккаунтам/лимитам без redemption | «Global» не означает все аккаунты; будущие выдачи не гарантированы |
| Purchased instant reset | Только eligible personal Plus/Pro; применяется немедленно, нельзя отложить | Free/Go не допускаются; одинаковый план не гарантирует предложение |
| Usage credits | Отдельный PAYG-баланс после included usage | Покупка разрешена лишь ограниченной группе Free/Go; наличие прежнего баланса не доказывает право на новые покупки |

Banked и automatic reset не являются деньгами/API credits. У banked reset проверяются expiry и покрываемые окна; уже полное окно не перезапускается. Изменение usage reset не меняет дату оплаты подписки. Источник: [How resets work in Codex][O9].

Купленный reset восстанавливает 5h/weekly немедленно даже при оставшемся allowance; переносит обычную weekly-квоту вперёд, а не добавляет отдельный пакет. Новый weekly-период начинается первым запросом Work/Codex после reset, следующий reset — через семь дней от него. Общий запрет возврата таких покупок имеет отдельные правила; текущая статья говорит, что возврат обычно не предлагается. Единой публичной фиксированной цены reset нет: она показывается eligible аккаунту. [Paid resets][O12].

Usage credits расходуются после included allowance, не повышают его и не переводят Free в Plus. Покупки/функции зависят от аккаунта, региона и плана; Free/Go могут использовать существующий баланс, если это доступно. Срок купленных credits — 12 месяцев; они нетрансферабельны, обычно невозвратны с правовыми/одобренными исключениями. Это не API credits и не wallet USD. После downgrade нельзя обещать ни все прежние функции за credits, ни автоматическое обнуление баланса: статья такого универсального правила не даёт. [Flexible usage credits][O13].

## Что меняется в ChatGPT при Plus → Free

Снижаются повышенные model/tool limits, приоритет в нагрузку и скорость; Plus даёт более широкий выбор моделей/reasoning и расширенные инструменты. API entitlement при этом не теряется: его изначально нет в Plus. [What is ChatGPT Plus?][O1].

По таблице Free: Scheduled tasks, Sites и Voice with video отсутствуют; Work ограничен desktop; меньше memory/context и uploads/analysis, нет доступа к некоторым более сильным моделям. Codex становится ограниченным. Сохраняются Projects, Search, обычный Voice, Skills/Plugins; эти функции нельзя целиком записывать в потери. Таблица не всегда выводит все значения Plus в текстовом представлении, поэтому отсутствие Free означает именно статус Free, а не обещание прежней доступности каждому Plus. [ChatGPT pricing][O10].

Free сохраняет веб-поиск, анализ данных, загрузки, использование существующих GPTs и генерацию изображений, с более строгими отдельными лимитами инструментов. Обычные everyday text chats описаны как unlimited с anti-abuse safeguards: это не безлимит Codex, изображений или всех моделей. В отдельных странах Free может показывать рекламу. [Free Tier FAQ][O5]. Расширенный deep research Plus сменяется ограниченным Free; генерация изображений тоже ограниченнее/медленнее. [ChatGPT pricing][O10]. Ограничение image generation **внутри Codex Free** в [Codex pricing][O2] не следует переносить на изображения в обычном ChatGPT.

**Старые GPTs:** текущая справка запрещает создание/публикацию новых GPTs на всех personal plans, включая Plus. Значит, «потеряем создание GPTs из-за перехода» сейчас неточно. Ранее созданные GPTs остаются доступны для использования; редактирование зависит от плана/permissions. Кроме downgrade, есть отдельный объявленный процесс retirement/migration GPTs, поэтому бессрочное сохранение этой возможности не обещается. [GPTs in ChatGPT][O14].

## Downgrade, cancel, refund, next bill и access end

| Переход/событие | Когда меняется доступ | Следующий счёт / возврат | Источник |
| --- | --- | --- | --- |
| ChatGPT Plus → Free, обычная отмена | Paid сохраняется до конца текущего оплаченного периода | Автопродление останавливается; отмена ≥24h до следующей billing date; автоматического возврата нет | [Canceling ChatGPT][O3] |
| Claude Max 20x → 5x | Downgrade в конце текущего billing period | Меньший тариф действует со следующего периода; возврат части текущего 20x не обещан | [Claude pricing — Managing your plan][A2], [refund][A11] |
| Claude Max → Free, обычная отмена | Paid до конца периода, затем Free | ≥24h до renewal; cancel не удаляет chats/projects/files | [Cancel Max][A4], [Claude pricing][A2] |
| ChatGPT refund | Покрытый возвращаемым платежом paid-доступ обычно заканчивается раньше | Отдельная проверка права; не равнозначен обычному cancel | [Refund policy][O15] |
| Claude refund | Требует отдельной процедуры/проверки; paid до обычного конца после refund не обещается | По общему правилу платежи невозвратны, кроме Consumer Terms/закона | [Request a refund][A11] |

**OpenAI refund:** для неиспользованной индивидуальной покупки возможен discretionary refund при обращении в течение семи дней, при выполнении условий; это не гарантия. После семи дней нет автоматического prorated discretionary refund. EU/UK/Turkey: prorated refund при отмене в течение 14 дней покупки. Korea: полный при запросе ≤7 дней без использования, иначе prorated; доступ прекращается сразу по запросу. Web/Google Play — запрос OpenAI; Apple — Apple. Одобренный web refund обрабатывается 5–7 рабочих дней, Google Play — до 10; срок банка отдельно. [Refund policy][O15].

**Anthropic refund:** общая невозвратность, исключения Consumer Terms/закона. EEA/UK — возможен refund в течение 14 дней, prorated по использованию. Apple-покупку рассматривает только Apple; refund request сам не отменяет renewal. Android — проверка Anthropic Support. Не следует переносить автоматический prorated refund при переходе Max → Team на Max 20x → 5x: это разные случаи. [Request a refund for a paid Claude plan][A11].

Web-путь отмены OpenAI: Settings → Billing → Cancel plan; Claude: Settings → Billing → Cancel. Подписки магазинов отменяются через исходный Apple/Google канал. Эти пути приведены как документированные правила, **никакие действия с подписками не выполнены**. [OpenAI cancellation][O3], [Claude cancellation][A4]. Старое поисковое описание OpenAI «day after next billing date» не принято вместо открытой текущей формулировки «end of current billing period»; точный timestamp не вычислялся.

## Ёмкостная арифметика 20x → 5x, отдельно от цены

Ниже — условная математическая модель для последующего сопоставления родителем, **не измерение и не вывод о нашем аккаунте**.

1. Пусть `P5h` — опубликованная относительная сессионная база Pro при одинаковых условиях. Тогда номинально `C20,5h = 20P5h`, `C5,5h = 5P5h`, то есть `C5,5h/C20,5h = 1/4`: уменьшение на 75%, а не на 50%. Это арифметика множителей per-session из [Max docs][A1], не гарантия четырёхкратного числа задач.
2. Для **одинакового взвешенного расхода** `D5h` и неизменной политики доля окна на 5x была бы `u5 ≈ 4u20`. Иллюстрации: 10% → 40%; 25% → 100%; 40% → 160% (запрос сверх номинального окна). Среднее за месяц не заменяет пики отдельных 5h-окон. Данные о блокировках/неудовлетворённом спросе нельзя восстановить из одного процента уже выполненного расхода.
3. Для weekly нужен независимый знаменатель `C5,7d`. Он публично не установлен; подставлять `C20,7d/4` без локального подтверждения нельзя. Проверка в принципе требует одновременно `D5h ≤ C5,5h`, `D7d ≤ C5,7d`, а для ограничиваемой модели — также её собственного остатка. Модельный состав и effort должны быть сопоставимы.
4. Нельзя считать расход по `input + cache_read + cache_write + output` с одинаковыми весами. Публичная документация подтверждает, что повторно используемый cached project content меньше расходует подписочный лимит, а после простоя cache может истечь и содержимое снова учитывается полностью. **Точные подписочные веса cache read/write/input/output не опубликованы**. Поэтому здесь не назначается ни `cache_read = 0`, ни API-цена в качестве веса подписки. Это сохраняет различие дешёвого повторного чтения и реально расходуемой новой работы. [Usage limit best practices][A12].
5. Четырёхкратное сокращение номинального allowance само по себе не доказывает четырёхкратное сокращение полезной работы. Для независимого сценария родителю понадобятся только локальные агрегаты: пики 5h, weekly, модель/effort, cache composition, параллельная активность разных поверхностей, блокировки и эффект resets. В этот публичный файл такие данные не включены. Формулу API-equivalent USD нельзя использовать вместо измеренного изменения подписочного usage.

## Проверка и незакрытые вопросы

Публичные страницы открыты через web retrieval; ссылки ниже ведут на официальные источники, а не поисковую выдачу. Поисковые snippets не использованы вместо открытых текущих редакций. Проверены все четыре записи схемы, источники основных чисел, различие 5h/weekly, модели, кредиты/reset, правила доступа/возврата и отсутствие личных данных. Статическая локальная проверка структуры и форм секретов описана в `validation.md` рядом.

Не установлены: фактическая ёмкость нашего аккаунта, налоговая ставка/цена в его регионе, точные даты renewal/access end/reset, eligibility на Free/credits/акции, судьба конкретного banked reset при downgrade, пересчёт текущего usage при смене Max tier и точные weekly/cache коэффициенты. Продуктовые тексты могут расходиться в rollout; известные противоречия отмечены выше. Никакой выбор плана из этого отчёта не следует.

Изменён только исследовательский Markdown; Python/app не запускался и не импортировался, поэтому пути импортированного `app` нет. Pytest и live-проверки не требуются для изменения документации и не выполнялись. Git commit/push в hub copy запрещены и `.git` отсутствует; перенос и коммит на `task-V-1087/research-subscription-plans` выполняет платформа после завершения работника. Локальный commit не заявляется.

## Официальные источники

Все ссылки проверены 2026-10-25. Старый URL `developers.openai.com/codex/pricing/` перенаправляет на O2.

[O1]: https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus
[O2]: https://learn.chatgpt.com/docs/pricing
[O3]: https://help.openai.com/en/articles/7232927-canceling-your-chatgpt-subscription
[O4]: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
[O5]: https://help.openai.com/en/articles/9275245-chatgpt-free-tier-faq
[O6]: https://openai.com/policies/terms-of-use/
[O7]: https://help.openai.com/en/articles/10421635-multicurrency-billing
[O8]: https://help.openai.com/en/articles/8156167-invoice-dates-for-chatgpt-and-api-billing
[O9]: https://help.openai.com/en/articles/20001498-how-resets-work-in-codex
[O10]: https://chatgpt.com/pricing/
[O11]: https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex
[O12]: https://help.openai.com/en/articles/20001507-paid-weekly-work-and-codex-rate-limit-resets
[O13]: https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans
[O14]: https://help.openai.com/en/articles/8554407-gpts-in-chatgpt
[O15]: https://help.openai.com/en/articles/7232895-how-do-i-request-a-refund-for-my-chatgpt-subscription
[A1]: https://support.claude.com/en/articles/11049741-what-is-the-max-plan
[A2]: https://claude.com/pricing
[A3]: https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
[A4]: https://support.claude.com/en/articles/8325617-cancel-your-pro-or-max-subscription
[A5]: https://support.claude.com/en/articles/12997130-understanding-your-billing-address-and-tax-calculation
[A6]: https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
[A7]: https://code.claude.com/docs/en/model-config
[A8]: https://support.claude.com/en/articles/8664678-change-the-model-effort-and-thinking-settings
[A9]: https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans
[A10]: https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans
[A11]: https://support.claude.com/en/articles/12386328-request-a-refund-for-a-paid-claude-plan
[A12]: https://support.claude.com/en/articles/9797557-usage-limit-best-practices
