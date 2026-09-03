# #267 — managed Grok home и `auth.json`: фикс не нужен

Постановка 13.08 («файл пропал, симлинк на пустое») — контекст. Причина пропажи уже в `CLAUDE.md`: `grok login --device-auth` даёт токен без `refresh_token`, CLI сам удаляет `~/.grok/auth.json` по истечении. Сторож-восстановитель отменён. Здесь — только оставшиеся три вопроса.

`~/.grok/` не писался. Пробы — scratch `/tmp/grok-200-267` (после прогонов в `trash`). Живой `~/.grok/auth.json` после всех проб: тот же inode `8679979`, size `1804`, mtime `1786699489`; `grok models` по-прежнему `You are logged in with grok.com` / `grok-4.6`.

## 1. Как связан managed home

Это **симлинк**, не копия. Намеренно.

```135:155:app/backend_grok.py
    `auth.json` is symlinked rather than copied so token refreshes stay shared with the
    user's login instead of silently expiring in a private copy.
    ...
    if auth_link.is_symlink():
        if auth_link.readlink() == real_auth:
            return home
        auth_link.unlink()
    elif auth_link.exists():
        # A real file here would shadow the user's credentials and rot independently.
        auth_link.unlink()
    auth_link.symlink_to(real_auth)
```

Живое (14.08 11:14 UTC):

| путь | тип | факт |
|---|---|---|
| `/home/kesha/.grok/auth.json` | regular, mode 600, 1804 байт | `auth_mode=oidc`, есть `refresh_token` (len=86), `expires_at=2026-08-14T15:24:49Z`, `create_time=2026-08-14T09:24:49Z` |
| `/home/kesha/orchestra/data/grok-home/auth.json` | symlink с **13.08 10:04** | `-> /home/kesha/.grok/auth.json` |
| worktree `data/grok-home/` | нет | воркер ходит в главный чекаут |

Целевой файл переписан логином `--oauth` сегодня в 09:24 UTC. Симлинк от вчера не пересоздавался и всё равно живой: `grok models` видит 4.6. Переиздание токена **по пути пользователя** симлинк переживает — он ключуется путём, не inode.

Тест уже фиксирует контракт: `tests/test_backend_grok.py::test_grok_home_is_isolated_and_disables_claude_compat_mcp` (symlink + тот же target). Нет файла → `test_grok_home_fails_loud_without_credentials` (`RuntimeError` / `grok login`).

Как CLI пишет refresh (из строк бинаря `grok 1.0.3`, не из прогона): дефолт **atomic write** (`storage.rs:230` «disk full during atomic write, falling back to in-place write»), плюс `auth.json.lock` («sibling may be mid-refresh»). Проактивно за 300 с до `expires_at` (`GROK_AUTH_EARLY_INVALIDATION_SECS`) и на 401. Живой auto-refresh **не провоцировал**: форс через настоящий `refresh_token` мог бы ротировать его и положить прод.

Проверка `rename()` на Linux: `rename(tmp, managed/auth.json)` **заменяет симлинк регулярным файлом**, целевой user-файл не обновляется. Следующий `ensure_grok_home()` такой regular **удаляет** и снова линкует на user-файл — то есть выбросил бы как раз свежие токены. Это гипотеза про путь worker-refresh, не наблюдение. Менять симлинк на копию из-за неё нельзя: копию `ensure_grok_home` и так сносит, плюс она протухает отдельно — ровно то, от чего симлинк защищает.

## 2. Что видит агент, когда токен мёртв

Не пустое падение. Два громких слоя.

**Файла нет** (то, что сделал истёкший device-auth): `ensure_grok_home()` в `_build_env()` → `RuntimeError: Grok credentials not found at ~/.grok/auth.json. Run grok login first.` Сессия в чат пишет `connect failed: …` (`app/session.py:1429-1430`). Процесс CLI не стартует.

**Файл есть, логина нет** (scratch: битый/просроченный oidc, dangling symlink, пустой `GROK_HOME`):

| команда | stdout/ACP | exit |
|---|---|---|
| `grok models` | `You are not authenticated.` + только `grok-4.5` (без 4.6) | 0 |
| `grok -p "…"` | `Not signed in. To authenticate without a browser, run: grok login --device-code` | 1 |
| ACP `initialize` | успех, `defaultAuthMethodId=null`, в каталоге только 4.5 | процесс жив |
| ACP `session/new` | `{"error":{"code":-32000,"message":"Authentication required","data":"no auth method id provided"}}` | — |

`session/new` — это `connect()` воркера после спавна процесса. `GrokProtocolError` → снова `connect failed: session/new: Authentication required`. Не idle-ход без текста.

Если процесс потом умрёт: `_process/exited` даёт `turn_end` с `stderr_tail` и `ok=False`. `_prompt/failed` — `AgentEvent("error", …)`.

Пустое падение, которое в постановке («первым делом `/api/usage`»), на этом шве не воспроизводится. Спавн по-прежнему может создать IDLE до первого `connect` (#249) — это уже существующий lifecycle, не дыра симлинка.

## 3. Фикс

**Не нужен.** Отрицательный результат.

- Симлинк — правильная связь: переживает переиздание токена по пути `~/.grok/auth.json` (замер сегодня).
- Пропажа файла — не баг managed home, а истечение `--device-auth`. Лечится логином `--oauth`, не копией и не сторожем.
- Отказ уже громкий на обоих входах (нет файла / файл мёртвый).
- Копия вместо симлинка сделала бы хуже: `ensure_grok_home` её удаляет; refresh в копии не доезжал бы до пользовательского логина.

Прод не менялся.

## Замечание не в объёме правки

`docs/grok-field-guide.md:32` всё ещё учит `grok login --device-auth`. Это противоречит `CLAUDE.md` и ровно тот логин, который удаляет файл. Не правил — чужой гид, в задаче отказ от фикса кода.

## Что не проверял и почему

- Живой auto-refresh за 5 мин до `expires_at` (~15:19 UTC 14.08) — ждать нельзя; форс с настоящим `refresh_token` мог ротировать прод.
- Запись refresh *через* `GROK_HOME` (atomic rename vs follow-symlink) — без живого refresh не наблюдается. Гипотеза и Linux-симуляция выше.
