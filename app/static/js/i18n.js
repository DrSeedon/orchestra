/* Русская локаль дашборда и переключатель RU/EN.
 *
 * Словарь один на весь интерфейс — и на серверные шаблоны, и на клиентские сценарии,
 * потому что надпись «Send» в кнопке шаблона и та же надпись в сгенерированном HTML
 * должны переводиться одинаково и править их надо в одном месте.
 *
 * Ключ словаря — сама английская строка, а не искусственный идентификатор. Отсюда
 * два свойства: английская локаль работает вообще без словаря (T возвращает вход),
 * и новая надпись видна в исходнике как есть. Цена — переименование надписи в коде
 * молча роняет перевод обратно в английский; ловится прогоном audit_screens.py.
 *
 * Механизм целиком клиентский, и это не случайность: шаблоны и JS дашборд читает с
 * диска живьём, а Python живёт в памяти до рестарта (см. _globals.html). Перевод на
 * стороне сервера доехал бы до экрана только после рестарта руками.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'orch_lang';
    var LANGS = ['ru', 'en'];
    var DEFAULT_LANG = 'ru';

    var RU = {
        // --- login.html ---
        '🎼 Orchestra — Login': '🎼 Orchestra — Вход',
        'AI Agent Orchestrator': 'Оркестратор ИИ-агентов',
        'Username': 'Имя пользователя',
        'Password': 'Пароль',
        'Login': 'Войти',

        // --- dashboard.html: шапка ---
        'New orchestrator': 'Новый оркестратор',
        'Show hidden tabs': 'Показать скрытые вкладки',
        'Proxy status': 'Состояние прокси',
        'Profiles': 'Профили',
        '🗂 Claude Profiles': '🗂 Профили Claude',
        'name': 'имя',
        'Add': 'Добавить',
        'Usage analytics': 'Аналитика расхода',
        '📄 Normal': '📄 Обычный',
        'Tool view: normal. Switch to compact view': 'Вид инструментов: обычный. Переключить на компактный',
        'Tool view: compact. Switch to normal view': 'Вид инструментов: компактный. Переключить на обычный',
        '📦 Compact': '📦 Компактный',
        'Restart Orchestra server': 'Перезапустить сервер Orchestra',
        'Client info': 'Сведения о клиенте',
        'Logout': 'Выйти',

        // --- dashboard.html: окно нового оркестратора ---
        'New Orchestrator': 'Новый оркестратор',
        'Name': 'Имя',
        'Project path': 'Путь к проекту',
        'Select or type path...': 'Выберите или введите путь…',
        'Browse projects': 'Обзор проектов',
        'Model': 'Модель',
        'Create Orchestrator': 'Создать оркестратора',

        // --- dashboard.html: аналитика ---
        'Usage Analytics': 'Аналитика расхода',
        'Orchestra control room · virtual API-equivalent cost':
            'Пульт Orchestra · расчётная стоимость в эквиваленте API',
        'Analytics period': 'Период аналитики',
        'Close analytics': 'Закрыть аналитику',
        '🤖 Agent activity ·': '🤖 Активность агентов ·',

        // --- dashboard.html: левая панель, чат, правая панель ---
        'FILES': 'ФАЙЛЫ',
        'TASKS': 'ЗАДАЧИ',
        'JOBS': 'ЗАДАНИЯ',
        'Open in file manager': 'Открыть в файловом менеджере',
        'Message...': 'Сообщение…',
        'Message {agent}...': 'Сообщение для {agent}…',
        'Stop': 'Остановить',
        'Send': 'Отправить',
        'After turn': 'После хода',
        'Compact context': 'Уплотнить контекст',
        'Restart CLI': 'Перезапустить клиент',
        'View system prompt': 'Посмотреть системную подсказку',
        'Agent and background-task activity': 'Активность агентов и фоновых заданий',
        'Role': 'Роль',
        'Cost': 'Стоимость',
        'Branch': 'Ветка',
        'Scope': 'Папка',
        'Desc': 'Описание',
        '⬇ Download': '⬇ Скачать',
        'Download file': 'Скачать файл',
        '🌐 Open': '🌐 Открыть',
        'Open in browser': 'Открыть в браузере',

        // --- tool-renderers.js: карточки инструментов, diff, поиск ---
        '🌐 Web search': '🌐 Веб-поиск',
        '🌐 Open page': '🌐 Открыть страницу',
        '🌐 Open {host}': '🌐 Открыть {host}',
        '🌐 Find {what}': '🌐 Найти {what}',
        'in page': 'на странице',
        'Open page': 'Открыть страницу',
        'Find in page': 'Найти на странице',
        'Browser action': 'Действие в браузере',
        'Waiting for query details…': 'Ожидание параметров запроса…',
        'running': 'выполняется',
        'done': 'готово',
        'failed': 'сбой',
        '▼ {n} more lines': '▼ ещё строк: {n}',
        '▼ {n} more files': '▼ ещё файлов: {n}',
        '📂 {n} files': '📂 файлов: {n}',
        ' ({n} lines)': ' (строк: {n})',
        '▼ expand': '▼ развернуть',
        '▲ collapse': '▲ свернуть',
        'file': 'файл',
        // Вид правки файла, который присылает Codex, — надпись на карточке, а не тип события
        'add': 'добавлен',
        'update': 'изменён',
        'delete': 'удалён',

        // --- app.js: общие состояния ---
        'Loading...': 'Загрузка…',
        'Loading…': 'Загрузка…',
        '⏳ Loading...': '⏳ Загрузка…',
        'Failed to load': 'Не удалось загрузить',
        '❌ Failed': '❌ Ошибка',
        'empty': 'пусто',

        // --- app.js: файлы, отправленные агентом ---
        '📥 Download': '📥 Скачать',
        '📥 Download all': '📥 Скачать все',
        '▼ Show all {n} files': '▼ Показать все файлы: {n}',
        '▲ Show fewer files': '▲ Свернуть список',

        // --- app.js: системная подсказка ---
        'No system prompt': 'Системной подсказки нет',
        'blocks': 'блоков',
        'files': 'файлов',
        'modules': 'модулей',
        'dynamic': 'динамических',
        'skills': 'навыков',
        'tokens': 'токенов',

        // --- app.js: создание и удаление оркестратора ---
        'Name and project path required': 'Нужны имя и путь к проекту',
        'Creating...': 'Создание…',
        'Delete "{name}" and all its workers?': 'Удалить «{name}» и всех его воркеров?',
        '📎 Drop files here': '📎 Перетащите файлы сюда',

        // --- app.js: прокси и модели ---
        'Proxy connected': 'Прокси подключён',
        'Proxy offline — no models available': 'Прокси недоступен — моделей нет',
        '🟢 Connected': '🟢 Подключён',
        '🔴 Offline': '🔴 Недоступен',
        '🔄 Refresh': '🔄 Обновить',
        'No models available.': 'Моделей нет.',
        'Models will appear after proxy connects.': 'Модели появятся после подключения прокси.',
        'Auto-retry every 60s': 'Повтор каждые 60 с',
        'Models ({n})': 'Моделей: {n}',
        'Usage & Limits': 'Расход и пределы',
        'Available in proxy admin panel': 'Доступно в панели управления прокси',
        'blocked': 'недоступна',

        // --- app.js: панель агента ---
        'Wait for idle': 'Дождитесь простоя',
        ' (CLI cost, includes cache)': ' (стоимость CLI, включая кеш)',
        'Context': 'Контекст',
        '{pct}% context': '{pct}% контекста',
        'Send path to chat': 'Отправить путь в чат',
        '{active} active · {total} total': 'активных: {active} · всего: {total}',
        ' (w/o cache)': ' (без кеша)',

        // --- app.js: роли и статусы агентов ---
        'orchestrator': 'оркестратор',
        'worker': 'воркер',
        'full-cycle': 'полный цикл',
        'reducer': 'сборщик',
        'reviewer': 'ревьюер',
        'executor': 'исполнитель',
        'idle': 'простаивает',
        'waiting': 'ждёт',
        'broken': 'сломан',
        'stopped': 'остановлен',
        'starting': 'запускается',
        'archived': 'в архиве',
        'error': 'ошибка',
        'completed': 'завершено',
        'active': 'активно',
        'expired': 'истекло',
        'cancelled': 'отменено',

        // --- app.js: плашка кеша ---
        'Running — cache refreshes every turn': 'Идёт ход — кеш обновляется каждый ход',
        'Running — Codex cache reference window ≈{ttl}m; actual ChatGPT TTL is not guaranteed':
            'Идёт ход — справочное окно кеша Codex ≈{ttl} мин; фактический TTL ChatGPT не гарантирован',
        'Codex cache state unknown · {past} past the ≈{ttl}m reference window; actual ChatGPT TTL is not guaranteed':
            'Состояние кеша Codex неизвестно · {past} сверх справочного окна ≈{ttl} мин; фактический TTL ChatGPT не гарантирован',
        'Cache cold — next turn ~20× дороже': 'Кеш остыл — следующий ход ~20× дороже',
        'Codex cache ≈{rem}m within a {ttl}m reference window; actual ChatGPT TTL is not guaranteed':
            'Кеш Codex ≈{rem} мин в справочном окне {ttl} мин; фактический TTL ChatGPT не гарантирован',
        'Cache {rem}m — после истечения ~20× дороже': 'Кеш {rem} мин — после истечения ~20× дороже',

        // --- app.js: проекты и задачи ---
        'PROJECTS': 'ПРОЕКТЫ',
        'Portfolio projects': 'Проекты портфеля',
        'PORTFOLIO / ROAD': 'ПОРТФЕЛЬ / ПЛАН',
        'Failed to load tasks': 'Не удалось загрузить задачи',
        'No tasks yet': 'Задач пока нет',
        'Insert #{par} into chat': 'Вставить #{par} в чат',
        'IN PROGRESS': 'В РАБОТЕ',
        'DONE': 'ГОТОВО',
        'NEW': 'НОВЫЕ',
        'BACKLOG': 'ОТЛОЖЕНО',
        'PAID': 'ОПЛАЧЕНО',
        'CANCELLED': 'ОТМЕНЕНО',
        'COMMITS': 'КОММИТЫ',
        'SYSTEM': 'СЛУЖЕБНОЕ',

        // --- app.js: фоновые задания ---
        'Failed to load jobs': 'Не удалось загрузить задания',
        'No background jobs': 'Фоновых заданий нет',
        'COMPLETED': 'ЗАВЕРШЕНО',
        'Cancel job': 'Отменить задание',
        'Type': 'Тип',
        'Target': 'Кому',
        'Status': 'Статус',
        'Pattern': 'Образец',
        'Path': 'Путь',
        'Host': 'Хост',
        'Interval': 'Интервал',
        'Message': 'Сообщение',
        'Created': 'Создано',
        'Expires': 'Истекает',
        's': 'с',

        // --- app.js: профили ---
        'name required': 'нужно имя',
        'No profiles.': 'Профилей нет.',
        'Delete': 'Удалить',
        'free': 'бесплатно',

        // --- chat.js: карточки вызовов инструментов ---
        'Image preview': 'Предпросмотр изображения',
        'Click to expand': 'Нажмите, чтобы развернуть',
        '📎 {n} files': '📎 файлов: {n}',
        '📝 {n} files': '📝 файлов: {n}',
        '{n} files': 'файлов: {n}',
        '📎 {n} items': '📎 записей: {n}',
        'Kill': 'Убить',
        'Logs': 'Журнал',
        'Info': 'Сведения',
        'Agents': 'Агенты',
        'Orchestrators': 'Оркестраторы',
        'Compact': 'Уплотнить',
        'Rename': 'Переименовать',
        'Merge': 'Влить',
        'Merged': 'Влито',
        'Cancel': 'Отменить',
        'BG': 'Фон',
        'BG Jobs': 'Фоновые задания',
        'job': 'задание',
        'Job': 'Задание',
        'description': 'описание',
        'description updated': 'описание обновлено',
        'todos': 'пунктов плана',
        'image': 'изображение',
        '🎨 generating image': '🎨 создаёт изображение',
        '{n} entries': 'записей: {n}',
        '{n} commits': 'коммитов: {n}',
        '{n} tokens': 'токенов: {n}',
        'using {tool}': 'работает инструментом {tool}',
        'working': 'работает',
        'killed': 'убит',
        'in': 'вх',
        'out': 'исх',
        'Task': 'Задача',
        'Tool calls': 'Вызовов инструментов',
        'Tokens': 'Токены',

        // --- chat.js: заголовки и результаты карточек ---
        '❌ Image generation failed': '❌ Не удалось создать изображение',
        '✅ Image generated': '✅ Изображение создано',
        '↻ Restoring generated image': '↻ Восстановление созданного изображения',
        '▦ Plan': '▦ План',
        'DESCRIPTION': 'ОПИСАНИЕ',
        'Status:': 'Статус:',
        'Project:': 'Проект:',
        'Price:': 'Стоимость:',
        'Assignee:': 'Исполнитель:',
        'Priority:': 'Приоритет:',
        'Task ID:': 'Номер задачи:',
        'Created:': 'Создана:',
        'Updated:': 'Изменена:',
        'Done:': 'Завершена:',
        'Paid at:': 'Оплачена:',
        '▼ {n} more': '▼ ещё {n}',
        '🖼 image': '🖼 изображение',
        '✅ sent': '✅ отправлено',
        '✅ {n} sent': '✅ отправлено: {n}',
        '✅ reported': '✅ зарегистрировано',
        '✅ loaded': '✅ загружено',
        '✅ {n} queries': '✅ запросов: {n}',
        '✅ spawned': '✅ создан',
        '📎 updated': '📎 обновлено',
        '↪ Message steered into the current Codex turn': '↪ Сообщение вставлено в текущий ход Codex',
        'Codex reconnecting': 'Codex переподключается',
        'Codex model rerouted': 'Модель Codex переключена',
        'Codex context compacted natively': 'Контекст Codex уплотнён штатно',
        'same thread': 'тот же тред',
        '🗜 Codex context compacted': '🗜 Контекст Codex уплотнён',
        'Background task': 'Фоновая задача',
        'Sub-agent': 'Субагент',
        '📋 System prompt': '📋 Системная подсказка',
        'Web search': 'Веб-поиск',
        '▲ collapse result': '▲ свернуть результат',
        '📝 Applying file changes': '📝 Применение изменений в файлах',
        'Viewing': 'Смотрит',
        'Viewed image': 'Просмотренное изображение',
        'Image unavailable': 'Изображение недоступно',
        '🖼 Image unavailable': '🖼 Изображение недоступно',
        '🎨 Generating image': '🎨 Создание изображения',
        '⏱ Waiting {n}s': '⏱ Ожидание {n} с',
        '🤖 Agent': '🤖 Агент',
        'File changes applied': 'Изменения в файлах применены',
        'File changes failed': 'Изменения в файлах не применены',
        '✓ Wait completed': '✓ Ожидание завершено',
        '🖼 [Image result]': '🖼 [Результат — изображение]',
        '❌ Send failed · 0 files accepted': '❌ Отправить не удалось · принято файлов: 0',
        '❌ Send failed': '❌ Отправить не удалось',
        'Loaded': 'Загружен',
        '✅ Tool loaded': '✅ Инструмент загружен',
        '✅ Bug reported': '✅ Ошибка зарегистрирована',
        '✅ Sent to TG': '✅ Отправлено в Telegram',
        '👁 Preview': '👁 Предпросмотр',
        '✅ Model changed': '✅ Модель изменена',
        '✅ Sent': '✅ Отправлено',
        '✅ Job created': '✅ Задание создано',
        '⏹ Cancelled': '⏹ Отменено',
        '✅ Done': '✅ Готово',
        'No files found': 'Файлы не найдены',
        '▼ more': '▼ ещё',
        '▦ Planning live': '▦ Планирует прямо сейчас',
        '⌁ Codex still working': '⌁ Codex ещё работает',
        '◇ Reasoning live': '◇ Рассуждает прямо сейчас',
        '◇ Reasoning': '◇ Рассуждение',
        'Current turn': 'Текущий ход',
        '± Live turn diff': '± Изменения текущего хода',
        '🖼 [Image]': '🖼 [Изображение]',
        'Review completed': 'Ревью завершено',
        'Review mode': 'Режим ревью',
        'Agent': 'Агент',
        'Platform': 'Платформа',
        'System': 'Система',
        'Critical': 'Критический',
        'High': 'Высокий',
        'Medium': 'Средний',
        'Low': 'Низкий',
        'Spawning {name}': 'Создаёт {name}',
        'Sending': 'Отправляет',
        'Drawing': 'Рисует',
        'chart': 'диаграмма',
        '📎 Sending {n} files': '📎 Отправляет файлов: {n}',
        'Todos': 'Пункты плана',
        '❌ Send failed · {n} files accepted': '❌ Отправить не удалось · принято файлов: {n}',
        '✅ Sent to TG · {n} files accepted': '✅ Отправлено в Telegram · принято файлов: {n}',
        'Tool failed': 'Инструмент не сработал',

        // --- usage.js: полоса расхода ---
        'Usage details and history': 'Подробности расхода и история',
        '⚠ Usage unavailable': '⚠ Данные о расходе недоступны',
        'Using cached data': 'Показаны сохранённые данные',
        '━ usage ┈ ideal pace': '━ расход ┈ ровный темп',
        // Ярлыки окон квоты: длительность, а не марка. windowLabel живёт в utils.js
        // (чужая территория задачи), поэтому переводится на месте показа.
        '5h': '5 ч',
        '7d': '7 д',
        '1w': '1 нед',
        '30d': '30 д',
        'Unknown': 'Неизвестно',
        'Unknown runtime': 'Неизвестный клиент',
        'Unclassified historical rows': 'Неклассифицированные исторические строки',
        'unknown': 'неизвестно',

        // --- analytics.js: аналитика расхода ---
        'Burn rate': 'Темп расхода',
        'Claude + Codex, stacked': 'Claude + Codex, с накоплением',
        'Dispatcher': 'Диспетчер',
        'Recovery': 'Восстановление',
        'Turns': 'Ходы',
        'Cache hit': 'Попадания в кеш',
        'Cold starts': 'Холодные старты',
        'TTL': 'Время жизни кеша',
        'Fleet': 'Парк агентов',
        'Observed cost': 'Наблюдаемая стоимость',
        'Cost / priced turn': 'Стоимость платного хода',
        'Agent drill-down': 'Разбор по агенту',
        'Priced / unaccounted': 'Платных / неучтённых',
        'Cache': 'Кеш',
        'Model mix': 'Состав моделей',
        'Delegation': 'Делегирование',
        'Native subagents': 'Встроенные субагенты',
        'Coverage': 'Покрытие',
        'Task linkage': 'Связь с задачами',
        'Voice': 'Голос',
        'Tool health': 'Состояние инструментов',
        'Structured telemetry': 'Структурная телеметрия',
        '4× signal': 'сигнал 4×',
        'Completed': 'Завершено',
        'Failed': 'Сбой',
        'Running': 'Выполняется',
        'Stopped': 'Остановлено',
        'CHECK': 'ПРОВЕРЬ',
        'OK': 'НОРМА',
        'FULL': 'ПОЛНО',
        'PART': 'ЧАСТЬ',
        '{priced} priced turns': 'платных ходов: {priced}',
        '{n} unaccounted': 'неучтённых: {n}',
        '{n} turns': 'ходов: {n}',
        '{n} cold starts': 'холодных стартов: {n}',
        'Opus · orchestrators': 'Opus · оркестраторы',
        'Sol · workers': 'Sol · воркеры',
        'Grok 4.5 · workers': 'Grok 4.5 · воркеры',
        'Own agent loop · free models': 'Свой цикл агента · бесплатные модели',

        // --- connection.js: названия источников сохранённых данных в баннере связи ---
        'orchestrators': 'оркестраторы',
        'sessions': 'сессии',
        'usage': 'расход',
    };

    var ATTRS = [
        ['data-i18n-title', 'title'],
        ['data-i18n-placeholder', 'placeholder'],
        ['data-i18n-aria-label', 'aria-label'],
        ['data-i18n-alt', 'alt'],
    ];

    var SWITCH_CSS =
        '#lang-switch{display:inline-flex;gap:2px;vertical-align:middle}' +
        '#lang-switch button{all:unset;cursor:pointer;padding:2px 6px;border-radius:6px;' +
        'font:600 10px/1.4 inherit;letter-spacing:.04em;color:#64748b;' +
        'border:1px solid rgba(71,85,105,.5);background:rgba(15,23,42,.5)}' +
        '#lang-switch button:hover{color:#cbd5e1}' +
        '#lang-switch button.is-active{color:#e2e8f0;background:#4f46e5;border-color:#4f46e5}';

    function readLang() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            if (LANGS.indexOf(stored) !== -1) return stored;
        } catch (e) {
            // приватный режим/запрещённое хранилище — язык по умолчанию, не падаем
        }
        // Язык по умолчанию может задать тот, кто открывает страницу, — сервер или
        // тестовый стенд. Явный выбор пользователя из хранилища всё равно главнее.
        if (LANGS.indexOf(window.__ORCH_LANG__) !== -1) return window.__ORCH_LANG__;
        return DEFAULT_LANG;
    }

    var lang = readLang();

    // Надпись с числом или именем внутри — одна запись словаря с местами подстановки
    // `{имя}`: разрезать её на куски нельзя, порядок слов в русском другой.
    function fill(text, params) {
        if (!params) return text;
        return text.replace(/\{(\w+)\}/g, function (whole, key) {
            return Object.prototype.hasOwnProperty.call(params, key)
                ? String(params[key])
                : whole;
        });
    }

    function T(text, params) {
        if (typeof text !== 'string' || !text) return text;
        if (lang !== 'ru') return fill(text, params);
        if (Object.prototype.hasOwnProperty.call(RU, text)) return fill(RU[text], params);
        var trimmed = text.trim();
        if (trimmed !== text && Object.prototype.hasOwnProperty.call(RU, trimmed)) {
            return fill(text.replace(trimmed, RU[trimmed]), params);
        }
        return fill(text, params);
    }

    function applyI18n(root) {
        var scope = (root && root.querySelectorAll) ? root : document;
        // Переводим только собственные текстовые узлы: у <h2>🤖 Agent activity · <span/></h2>
        // запись через textContent снесла бы вложенный span вместе с его содержимым.
        scope.querySelectorAll('[data-i18n]').forEach(function (el) {
            el.childNodes.forEach(function (node) {
                if (node.nodeType !== Node.TEXT_NODE) return;
                var key = node.nodeValue.trim();
                if (!key) return;
                var value = T(key);
                if (value !== key) node.nodeValue = node.nodeValue.replace(key, value);
            });
        });
        ATTRS.forEach(function (pair) {
            scope.querySelectorAll('[' + pair[0] + ']').forEach(function (el) {
                var current = el.getAttribute(pair[1]);
                if (current) el.setAttribute(pair[1], T(current.trim()));
            });
        });
    }

    function setLang(code) {
        if (LANGS.indexOf(code) === -1 || code === lang) return;
        try {
            localStorage.setItem(STORAGE_KEY, code);
        } catch (e) {
            return;  // сохранить выбор нельзя — перезагрузка вернула бы прежний язык
        }
        location.reload();
    }

    function renderSwitch() {
        var mount = document.getElementById('lang-switch');
        if (!mount) return;
        mount.textContent = '';
        LANGS.forEach(function (code) {
            var button = document.createElement('button');
            button.type = 'button';
            button.dataset.lang = code;
            button.textContent = code.toUpperCase();
            button.title = code === 'ru' ? 'Русский язык интерфейса' : 'English interface';
            button.setAttribute('aria-pressed', code === lang ? 'true' : 'false');
            if (code === lang) button.className = 'is-active';
            button.addEventListener('click', function () { setLang(code); });
            mount.appendChild(button);
        });
    }

    function boot() {
        var style = document.createElement('style');
        style.id = 'lang-switch-style';
        style.textContent = SWITCH_CSS;
        document.head.appendChild(style);
        applyI18n(document);
        renderSwitch();
    }

    document.documentElement.lang = lang;
    window.T = T;
    window.applyI18n = applyI18n;
    window.orchLang = function () { return lang; };
    window.orchSetLang = setLang;
    window.orchDict = RU;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
