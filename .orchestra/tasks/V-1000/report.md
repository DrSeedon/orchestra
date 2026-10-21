# V-1000 — Gemini CLI on Jio Google AI Pro: доступ остановлен до пробы

Проверка: 2026-10-21, VPS/worktree `/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker`.

## Результат

`gemini` на VPS не установлен (`command -v gemini` не нашёл исполняемый файл). В npm registry опубликован `@google/gemini-cli@0.65.0` (`npm view @google/gemini-cli version`), Node.js 20.20.2 и npm 10.8.2 доступны. Значит CLI устанавливаем, но он не настроен для запуска здесь.

В `~/.gemini` отсутствуют стандартные `oauth_creds.json` и `google_accounts.json`; найденное состояние относится к `antigravity-cli`, а не подтверждает авторизацию Gemini CLI или Jio-аккаунта. Содержимое credential-файлов не читалось. Без интерактивного Google OAuth реальная проба невозможна; login не запускался и обход авторизации не предпринимался. API key не использовался.

Чтобы продолжить авторизацию на VPS, владелец должен выполнить в интерактивном SSH-терминале под своим обычным Unix-пользователем:

```sh
npx --yes @google/gemini-cli@0.65.0
```

Команду выполнить в интерактивном SSH-терминале на VPS под обычным Unix-пользователем. В onboarding выбрать вход через Google и войти именно в Google account, на котором активирован Jio-promo Google AI Pro. В браузере завершить показанный CLI OAuth flow и вернуться в тот же терминал. Это ожидаемое действие владельца; до его выполнения headless trial не запускался.

Есть существенное ограничение: прежнее исследование #249 содержит официальную документацию Google о прекращении обслуживания Gemini CLI для consumer Gemini Code Assist / Google AI Pro / Ultra с 18.06.2026, включая запрет нового `Login with Google`; при этом Standard/Enterprise остались поддержаны. Поэтому запуск команды может показать, что consumer login уже недоступен. Jio-анонс называл AI Pro преимущества в Gemini app, но не устанавливал исключение для CLI. Этот вывод и entitlement gap остаются актуальны; Jio-подписка сама по себе не доказывает доступ к Gemini CLI. Источники, уже проверенные в #249: [официальное уведомление о deprecation](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en), [анонс Jio Google AI Pro](https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/).

## Что из #249 остаётся в силе

Читал артефакты из истории main: `docs/tasks/249/google-source-matrix.md`, `research.md`, `experiment-protocol.md` и замороженный `plan.md` из коммитов `8001d4a`, `892884a`, `1f593c0` (в текущем дереве они лежат в `docs/tasks/249/`, а не `.orchestra/tasks/249/`). Сохраняют силу: consumer Gemini CLI был объявлен снятым; Jio→CLI/Code Assist entitlement не был подтверждён; Antigravity CLI был отдельным кандидатом без API key; его ранее измеренные свойства и ограничения относятся к Antigravity, не к Gemini CLI. В частности, прежний Antigravity batch потратил около 16 процентных пунктов weekly quota на 13 коротких результатов — это не оценка ёмкости Gemini CLI.

## Не измерено

Условие задания требует остановиться при необходимости интерактивного Google login. Поэтому нет headless task, данных о Gemini CLI model, wall time, tokens, лимитах или расходе подписки. Интеграционные швы Orchestra (ACP/app-server, quota gate, usage, MCP, sandbox) не анализировались; capacity и вывод «добавлять ли пул» по Gemini CLI остаются не измеренными. Продолжение возможно после интерактивной авторизации владельца и только если Google реально допускает Jio-account inference в Gemini CLI. Никаких изменений `app/`, платных API-вызовов или рестартов не было.
