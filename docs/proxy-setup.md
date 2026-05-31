# Orchestra — Резервные HTTP прокси

Два Squid-прокси на зарубежных VPS как fallback к основному Hiddify (`127.0.0.1:12334`).

## Прокси

| Сервер | IP:Port | Провайдер | Статус |
|--------|---------|-----------|--------|
| Fornex NL | `89.127.206.225:3128` | Fornex | ✅ active |
| Timeweb NL | `147.45.101.84:3128` | Timeweb | ✅ active |

**Авторизация (одинаковая для обоих):**
- User: `orchestra`
- Password: `***REMOVED***`

## Проверка работы

```bash
# Timeweb (проверено с нашей машины)
curl -x http://orchestra:***REMOVED***@147.45.101.84:3128 https://httpbin.org/ip
# → {"origin": "147.45.101.84"}

# Fornex (проверено локально с сервера)
ssh root@89.127.206.225
curl -x http://orchestra:***REMOVED***@127.0.0.1:3128 https://httpbin.org/ip
# → {"origin": "89.127.206.225"}
```

> ⚠️ **Примечание про Fornex**: С нашей машины прямой тест через curl не работает
> потому что весь трафик идёт через VPS Tunnel (127.0.0.1:12338) → Ёжик VPN.
> Squid на Fornex работает корректно — подтверждено локальным тестом с сервера.
> В Python-коде использовать `httpx` напрямую с proxy URL — он работает.

## Использование в Orchestra

### .env

```env
# Основной прокси (Hiddify local)
HTTPS_PROXY=http://127.0.0.1:12334

# Резервные (если основной недоступен)
PROXY_FALLBACK_1=http://orchestra:***REMOVED***@89.127.206.225:3128
PROXY_FALLBACK_2=http://orchestra:***REMOVED***@147.45.101.84:3128
```

### Python — выбор прокси с fallback

```python
import httpx
import os

PROXIES = [
    os.getenv("HTTPS_PROXY", "http://127.0.0.1:12334"),
    "http://orchestra:***REMOVED***@89.127.206.225:3128",
    "http://orchestra:***REMOVED***@147.45.101.84:3128",
]

def get_working_proxy(test_url: str = "https://api.anthropic.com") -> str:
    for proxy in PROXIES:
        try:
            r = httpx.get("https://httpbin.org/ip", proxy=proxy, timeout=5)
            if r.status_code == 200:
                return proxy
        except Exception:
            continue
    raise RuntimeError("All proxies unavailable")
```

### Anthropic SDK с fallback-прокси

```python
import anthropic
import httpx

proxy_url = get_working_proxy()
client = anthropic.Anthropic(
    http_client=httpx.Client(proxy=proxy_url)
)
```

## Конфигурация Squid на серверах

- Порт: `3128`
- Авторизация: htpasswd (`/etc/squid/passwd`)
- Config: `/etc/squid/squid.conf`
- Логи: `/var/log/squid/access.log`
- Firewall: UFW inactive (Timeweb правило добавлено; Fornex — UFW inactive, порт открыт)

### Проверка на сервере

```bash
# Fornex
ssh root@89.127.206.225
systemctl status squid
tail -f /var/log/squid/access.log

# Timeweb
ssh root@147.45.101.84
systemctl status squid
tail -f /var/log/squid/access.log
```

### Перезапуск Squid

```bash
systemctl restart squid
```

## Дата настройки

2026-05-31 — начальная настройка (Squid + htpasswd auth)
