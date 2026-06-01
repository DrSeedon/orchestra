# 🚀 ПЛАН ДЕПЛОЯ ORCHESTRA НА VPS КЛИЕНТА

**VPS**: 147.45.101.84 (Amsterdam), Ubuntu 24.04, 2 CPU, 3.8GB RAM, 12GB free
**Домен**: orchestra.zahoron.ru (DNS ещё НЕ прописан)
**Клиент**: zahoronru@gmail.com / Pro x20
**Репо**: https://github.com/DrSeedon/orchestra.git (публичная)

---

## ✅ Фаза 0: Подготовка кода (СДЕЛАНО)
1. ✅ Proxy параметризован — `os.environ.get()` в `manager.py` и `backend_claude.py`
2. ✅ cli_path параметризован — `shutil.which("claude") or CLAUDE_CLI_PATH env`
3. ✅ aiogram/aiohttp/python-multipart/python-dotenv добавлены в pyproject.toml
4. ✅ Dashboard Auth — cookie session в `app/auth.py`, login/logout, backward compat

## 🔧 Фаза 0.5: Security fixes (ПЕРЕД ДЕПЛОЕМ)

### 0.5.1 Internal token для всех API callbacks
**Проблема** (Codex blocking): `/api/*` endpoints (включая `/send`, `/api/sessions`, `/api/jobs`, `/api/tg/send_file`) доступны без auth снаружи.
**Фикс** (end-to-end):
1. `app/auth.py` → `requires_auth()`: убрать bypass для `/send`, проверять `X-Orchestra-Token` header ДО cookie-check на всех `/api/*` endpoints
2. `app/auth.py` → новая функция `check_internal_token(request) -> bool`: сравнивать `X-Orchestra-Token` с `ORCHESTRA_INTERNAL_TOKEN` env через `hmac.compare_digest`
3. `app/mcp_stdio.py` → `_api()`: добавлять `X-Orchestra-Token` header в КАЖДЫЙ HTTP-запрос к Orchestra API. Токен брать из `os.environ.get("ORCHESTRA_INTERNAL_TOKEN", "")` или `load_dotenv()` при старте
4. `app/mcp_stdio.py` получает токен через env — MCP subprocess env в `.claude/settings.json` (шаг 2.5) ИЛИ через `load_dotenv()` из `/opt/orchestra/.env`
5. AuthMiddleware: если `X-Orchestra-Token` валидный → пропустить без cookie. Если нет → проверять cookie как обычно

### 0.5.2 Защита /uploads/ от публичного доступа
**Проблема** (Codex blocking): uploads с файлами из dashboard/TG доступны без auth.
**Фикс**: убрать `/uploads/` из bypass auth.

### 0.5.3 Приоритет CLAUDE_CLI_PATH
**Проблема** (Codex suggestion): `shutil.which("claude") or env` → env игнорируется если claude в PATH.
**Фикс**: `os.environ.get("CLAUDE_CLI_PATH") or shutil.which("claude") or "claude"`

### 0.5.4 Cookie secure flag
**Проблема**: cookie без `secure=True` на HTTPS.
**Фикс**: при наличии `DASHBOARD_COOKIE_SECURE=1` в env → ставить `secure=True`.

### 0.5.5 Обновить .env.example
Добавить: `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `CLAUDE_CLI_PATH`, `ORCHESTRA_INTERNAL_TOKEN`, `DASHBOARD_COOKIE_SECURE`

### 0.5.6 GATE: commit + push Phase 0.5 ПЕРЕД деплоем
**Проблема** (Codex blocking): git clone принесёт старый код без security fixes.
**Фикс**: Phase 0.5 ДОЛЖНА быть закоммичена и запушена в `main` до шага 2.1 (git clone).
```bash
git add app/auth.py app/main.py app/mcp_stdio.py .env.example
git commit -m "security: internal token auth + fix auth bypass"
git push origin main
# Записать: DEPLOY_COMMIT=$(git rev-parse HEAD)
```
На VPS при clone проверить: `git log -1 --oneline` должен содержать security commit.

---

## Фаза 1: Подготовка VPS

> 🔑 **Конвенция**: команды по умолчанию выполняются от **root**. Блоки от `orchestra` помечены явно: `su - orchestra` или `sudo -u orchestra`.

### 1.1 Создание юзера `orchestra` (root)
```bash
useradd -m -s /bin/bash orchestra
mkdir -p /opt/orchestra
chown orchestra:orchestra /opt/orchestra
```

### 1.2 Установка Node.js 22 LTS (root)
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs
node --version  # v22.x
npm --version   # 10.x
```

### 1.3 Установка Claude CLI (root)
```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

### 1.4 Проверка uv (root — уже установлен v0.10.0)
```bash
uv --version  # ожидаем 0.10.0+
# Если нет: curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1.5 Авторизация Claude CLI (от имени юзера orchestra)
```bash
su - orchestra
claude login
# Генерирует URL → клиент (Александр) открывает в браузере
# Логинится через zahoronru@gmail.com
# Вводит код подтверждения в терминале
```
⚠️ **Клиент должен быть онлайн** для этого шага.

### 1.6 Claude global config
```bash
su - orchestra
mkdir -p /home/orchestra/.claude
cat > /home/orchestra/.claude/settings.json << 'EOF'
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Grep(*)",
      "Glob(*)",
      "mcp__orchestra__*"
    ],
    "deny": []
  }
}
EOF
```

### 1.7 Git config
```bash
su - orchestra
git config --global user.name "Orchestra"
git config --global user.email "zahoronru@gmail.com"
```

---

## Фаза 2: Деплой кода

### 2.1 Клонирование (публичная репа)
```bash
su - orchestra
git clone https://github.com/DrSeedon/orchestra.git /opt/orchestra
```

### 2.2 Установка зависимостей
```bash
cd /opt/orchestra
uv sync
# Проверить: ls /opt/orchestra/.venv/bin/python3
```

### 2.3 Настройка .env (root — создаёт файл и передаёт ownership)
```bash
INTERNAL_TOKEN=$(openssl rand -hex 32)
DASH_PASSWORD=$(openssl rand -base64 16)

cat > /opt/orchestra/.env << EOF
# No proxy needed — Amsterdam has direct Claude API access

# Dashboard Auth
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=${DASH_PASSWORD}
DASHBOARD_COOKIE_SECURE=1

# Internal token for MCP callback auth
ORCHESTRA_INTERNAL_TOKEN=${INTERNAL_TOKEN}
EOF
chown orchestra:orchestra /opt/orchestra/.env
chmod 600 /opt/orchestra/.env

echo "=== СОХРАНИ ЭТИ ДАННЫЕ ==="
echo "Dashboard: admin / ${DASH_PASSWORD}"
echo "Internal token: ${INTERNAL_TOKEN}"
```

### 2.4 Создание директорий
```bash
mkdir -p /opt/orchestra/data/uploads
mkdir -p /opt/orchestra/worktrees
chown -R orchestra:orchestra /opt/orchestra/data /opt/orchestra/worktrees
```

### 2.5 Инициализация .claude (проектный — ПЕРЕЗАПИСАТЬ из git)
```bash
# git clone уже принесёт .claude/, но нужно подправить пути и добавить token:
INTERNAL_TOKEN=$(grep ORCHESTRA_INTERNAL_TOKEN /opt/orchestra/.env | cut -d= -f2)
mkdir -p /opt/orchestra/.claude
cat > /opt/orchestra/.claude/settings.json << SETTINGS
{
  "mcpServers": {
    "orchestra": {
      "type": "stdio",
      "command": "/opt/orchestra/.venv/bin/python",
      "args": ["-m", "app.mcp_stdio"],
      "env": {
        "PYTHONPATH": "/opt/orchestra",
        "ORCHESTRA_URL": "http://127.0.0.1:8888",
        "ORCHESTRA_INTERNAL_TOKEN": "${INTERNAL_TOKEN}"
      },
      "alwaysLoad": true
    }
  }
}
SETTINGS
chown -R orchestra:orchestra /opt/orchestra/.claude
```

---

## Фаза 3: Systemd

### 3.1 Service file
```bash
cat > /etc/systemd/system/orchestra.service << 'EOF'
[Unit]
Description=Orchestra — AI Agent Orchestrator
After=network.target

[Service]
Type=simple
User=orchestra
WorkingDirectory=/opt/orchestra
ExecStart=/opt/orchestra/.venv/bin/python3 -u -m uvicorn app.main:app --host 127.0.0.1 --port 8888
Restart=always
RestartSec=5
TimeoutStopSec=2
KillSignal=SIGINT
Environment=PATH=/usr/local/lib/node_modules/.bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/orchestra

[Install]
WantedBy=multi-user.target
EOF
```
**Примечание**: PATH включает `/usr/local/lib/node_modules/.bin` для Claude CLI.

### 3.2 Sudoers для orchestra юзера
```bash
echo "orchestra ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart orchestra, /usr/bin/systemctl stop orchestra, /usr/bin/systemctl start orchestra, /usr/bin/systemctl status orchestra" > /etc/sudoers.d/orchestra
chmod 440 /etc/sudoers.d/orchestra
visudo -c  # проверить синтаксис
```

### 3.3 Запуск
```bash
systemctl daemon-reload
systemctl enable --now orchestra
systemctl status orchestra
curl -s http://127.0.0.1:8888/ | head -5
```

---

## Фаза 4: Nginx + SSL (когда DNS готов)

### 4.1 Проверить что nginx и certbot есть
```bash
nginx -v       # ожидаем 1.24+
certbot --version  # ожидаем 2.9+
# Если нет: apt install -y nginx certbot python3-certbot-nginx
```

### 4.2 Nginx config
```bash
cat > /etc/nginx/sites-available/orchestra << 'EOF'
server {
    listen 80;
    server_name orchestra.zahoron.ru;

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support (critical for dashboard live updates)
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        # Upload support
        client_max_body_size 50M;
    }
}
EOF
ln -sf /etc/nginx/sites-available/orchestra /etc/nginx/sites-enabled/orchestra
nginx -t && systemctl reload nginx
```

### 4.3 SSL
```bash
# Проверить DNS первым:
dig orchestra.zahoron.ru +short  # должен вернуть 147.45.101.84
certbot --nginx -d orchestra.zahoron.ru --non-interactive --agree-tos -m zahoronru@gmail.com
```

### 4.4 UFW (не нужно — 80/443 уже открыты)

---

## Фаза 5: TG Bot (позже, отдельная задача)
- Создать TG группу
- Настроить topics
- Прописать `TG_BRIDGE_TOKEN` + `TG_BRIDGE_GROUP` в .env
- Перезапуск сервиса

---

## Фаза 6: Валидация

### 6.1 Smoke test
```bash
# 1. Dashboard → login page (auth enabled):
curl -s http://127.0.0.1:8888/ | grep -q "login" && echo "OK: login page" || echo "FAIL"

# 2. Логин работает:
curl -s -X POST http://127.0.0.1:8888/login \
  -d "username=admin&password=PASS" -c /tmp/cookies.txt -L -o /dev/null -w "%{http_code}"
# Ожидаем 200 (redirect → dashboard)

# 3. Dashboard с cookie:
curl -s http://127.0.0.1:8888/ -b /tmp/cookies.txt | grep -q "Orchestra" && echo "OK: dashboard" || echo "FAIL"

# 4. SSE stream отдаёт:
curl -s -N http://127.0.0.1:8888/api/events -b /tmp/cookies.txt &
sleep 3 && kill %1

# 5. AUTH BYPASS TESTS (все должны НЕ вернуть 200):
# /send без auth → должен вернуть 302/401:
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8888/api/sessions/test/send \
  -H "Content-Type: application/json" -d '{"message":"test"}')
[ "$HTTP_CODE" != "200" ] && echo "OK: /send protected ($HTTP_CODE)" || echo "FAIL: /send OPEN!"

# /uploads без auth → должен вернуть 302/401:
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/uploads/)
[ "$HTTP_CODE" != "200" ] && echo "OK: /uploads protected ($HTTP_CODE)" || echo "FAIL: /uploads OPEN!"

# /api/* без auth → должен вернуть 302/401:
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/api/sessions)
[ "$HTTP_CODE" != "200" ] && echo "OK: /api protected ($HTTP_CODE)" || echo "FAIL: /api OPEN!"

# 6. INTERNAL TOKEN TEST:
INTERNAL_TOKEN=$(grep ORCHESTRA_INTERNAL_TOKEN /opt/orchestra/.env | cut -d= -f2)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/api/sessions \
  -H "X-Orchestra-Token: ${INTERNAL_TOKEN}")
[ "$HTTP_CODE" = "200" ] && echo "OK: internal token works" || echo "FAIL: internal token rejected ($HTTP_CODE)"
```

### 6.2 Worker test
- Создать тестового worker'а через dashboard
- Проверить что Claude CLI отвечает
- Проверить что worktree создаётся в /opt/orchestra/worktrees/
- Удалить тестового worker'а

---

## ⚠️ РИСКИ

| # | Риск | Severity | Митигация |
|---|------|----------|-----------|
| 1 | RAM 3.8GB — max 3 workers одновременно | Medium | Лимит workers, zabbix мониторинг (на VPS) |
| 2 | Disk 12GB — DB + worktrees растут | Medium | Cron: vacuum DB weekly, cleanup old worktrees |
| 3 | Claude CLI auth expires | Low | Re-login при ошибке |
| 4 | In-memory sessions — restart = разлогин | Low | Допустимо для MVP |
| 5 | Git clone public — код виден всем | Low | Можно сделать приватной позже |

---

## 📊 ПОРЯДОК ВЫПОЛНЕНИЯ

| # | Шаг | Время | Блокер |
|---|-----|-------|--------|
| 0 | Security fixes (Фаза 0.5) | 1 час | — |
| 0.5 | **GATE: commit + push Phase 0.5** | 5 мин | Phase 0.5 done |
| 1 | useradd + node + claude CLI | 10 мин | — |
| 2 | Claude auth | 5 мин | клиент online |
| 3 | git clone | 2 мин | Phase 0.5 pushed |
| 4 | uv sync + .env + dirs | 10 мин | — |
| 5 | systemd + запуск | 5 мин | — |
| 6 | Smoke test (включая auth bypass) | 15 мин | — |
| 7 | DNS (клиент) | ? | клиент прописывает A-запись |
| 8 | nginx + SSL | 5 мин | DNS ready |
| 9 | TG bot | 30 мин | отдельная задача |

**Итого активная работа**: ~1.5 часа (включая security fixes, без ожидания клиента)

---

## Codex Review
Ревью: `docs/deploy-amsterdam/CODEX_REVIEW.md`
**Статус**: APPROVED (Round 3) — all blocking FIXED, 5 minor suggestions remaining
