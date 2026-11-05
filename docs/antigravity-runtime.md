# Antigravity runtime: OAuth и смена аккаунта

Интеграция использует официальный `agy` версии **не ниже 1.1.12**. Inference,
каталог и квоты проходят через CLI. Боевой роутинг включается отдельно после
логина владельца, проверки eligibility и разрешённого минимального canary.

```sh
ssh orchestra-vps
cd /home/kesha/orchestra
bash scripts/antigravity-login.sh --agy-bin agy --model gemini-4-argon-high
```

Команда требует интерактивного терминала: пройдите browser-code OAuth в CLI.
Сначала создаётся staging HOME (0700), затем проверяются версия, `models` и
обе группы `/quota`. При успехе один `os.replace` публикует credential (0600) в
`data/antigravity-auth-home/.gemini/antigravity-cli/antigravity-oauth-token`.
Любая ошибка до публикации сохраняет предыдущий файл; staging удаляется всегда.
Generation — SHA-256 тех же байтов, отдельного generation-файла нет.

Проверить exact keys в `/api/usage` (подставьте локальный порт Orchestra):

```sh
curl --fail --silent http://127.0.0.1:8000/api/usage |
  .venv/bin/python -c 'import json,sys; q=json.load(sys.stdin)["antigravity"]; print({k:q[k] for k in ("gemini-weekly","3p-weekly")})'
```

`gemini-weekly` используется Gemini, `3p-weekly` — Claude/GPT. Значения
`remaining_fraction` независимы; `null` означает отсутствие данных.
Не выводите содержимое credential или MCP-конфигов в журнал.

Смена аккаунта применяется на следующем ходе **без пересоздания Orchestra worker**.
При другой generation начинается **новый native conversation**. Каждый worker
имеет HOME `data/antigravity-homes/<ORCHESTRA_SESSION_ID>` и собственный workspace
через `--add-dir`. Это изоляция состояния, а не sandbox от процессов того же Unix user.
Снимок credential копируется перед ходом и удаляется после выхода/interrupt.

После аварийного завершения сначала убедитесь, что затронутый worker остановлен.
Удалите только его производную копию (подставьте точный ID):

```sh
rm -- data/antigravity-homes/WORKER_ID/.gemini/antigravity-cli/antigravity-oauth-token
```

Canonical credential при такой уборке не удаляется. Не перезапускайте
`telegram-bot-api`. При credential/eligibility отказе повторите штатный login;
автоматических платных fallback или повторов inference нет.

Источник контракта: `ac39a669a:docs/tasks/249/plan.md`, frozen тесты #249/#279.
Дополнение пользователя от 2026-11-05: Argon 4 и Flash 3.8 на high/medium/low,
alias `agy-argon`, поддержка новых версий CLI, включая 1.5.0.
