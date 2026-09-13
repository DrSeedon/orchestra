---
name: laptop-access
description: Проверить ноутбук владельца или его проекты с VPS через обратный SSH-туннель.
---

# Доступ к ноутбуку

Единственный маршрут для агентов платформы — SSH через обратный туннель.
Ноутбук сам поддерживает соединение с VPS; его system-level ssh-tunnel-vps.service
проверен active/running 13.09.2026. Инструмент run_on_laptop агентам платформы недоступен.

## Проверка соединения

На VPS проверить локальный listener:

```bash
ss -ltnH 'sport = :2222'
```

Рабочая команда (13.09.2026, хост maxim-911aird, пользователь maxim):

```bash
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -p 2222 maxim@127.0.0.1 'hostname; pwd'
```

Для разрешённой работы заменяй только удалённую команду; пути с пробелами заключай
в кавычки. Пользователь ноутбука — maxim, не VPS-пользователь kesha.
Пустой успешный вывод ss означает отсутствие listener, а ошибка самой проверки
не доказывает его отсутствие. Refused/timeout означает недоступное соединение:
сообщи владельцу наблюдаемый отказ. Сон, выключение и потеря сети возможны, но по
одной ошибке причина не установлена. Permission denied означает проблему
аутентификации, а не доказанный сон: проверь пользователя и указанный ключ.
Туннель поднимается с ноутбука; не перенастраивай и не перезапускай его с VPS.

## Реальные границы

Это удалённый shell с правами аккаунта maxim, не whitelist команд и не фильтр
метасимволов. SSH удерживает аутентификацию и защищает транспорт; доступ к объектам
ограничивает ОС ноутбука. Разрешённость действий задают поручение и правила проекта,
а не наличие рабочего соединения. Установка, перезапуск и изменение конфигурации
допустимы лишь когда явно входят в согласованное поручение.
Бережное обращение с ноутбуком — [AGENTS.md Orchestra, «Границы полномочий»](/home/kesha/orchestra/AGENTS.md).
Не копируй эти нормы в скилл. Доступ сам по себе не поручает запускать другие агенты
или продолжать чужие сессии. Долгие разрешённые команды — по background-jobs платформы.

## Карта каталогов

Снимок ноутбука: 2026-09-13T14:00:29.258676+00:00. Это имена каталогов, не утверждение,
что каждый является самостоятельным проектом. Маркер .git проверен без чтения
истории/remote: файл может обозначать worktree или submodule. Перед работой проверь
существование выбранного пути; снимок не обещает его неизменности.

### /mnt/data/Projects/Python/

| Каталог | Маркер .git |
|---|---|
| `ai-proxy-manager` | каталог |
| `Alexey-Projects` | не найден |
| `Aperant` | каталог |
| `BallisticSim` | не найден |
| `civsim` | не найден |
| `Claude-Code-Game-Master` | каталог |
| `claude-plugins-official` | каталог |
| `claude-server` | каталог |
| `CursorUsageAnalyzer` | каталог |
| `DnD-Music-MCP` | каталог |
| `E-CommerceBench` | каталог |
| `games` | каталог |
| `inscryption-ai` | каталог |
| `inscryption-ai-public` | каталог |
| `kesha-tg-bot` | каталог |
| `LLM` | не найден |
| `OF-Parser` | не найден |
| `orchestra` | каталог |
| `orchestra-architecture-audit` | файл |
| `orchestra-astra-usage` | файл |
| `orchestra-backups` | не найден |
| `orchestra-bash-latency-20260905` | файл |
| `orchestra-codex-state-compat` | файл |
| `orchestra-day-20260907` | файл |
| `orchestra-db-research` | файл |
| `orchestra-design-gallery` | файл |
| `orchestra-enterprise` | каталог |
| `orchestra-handoff-context-window` | файл |
| `orchestra-html-skill` | файл |
| `orchestra-instruction-guard` | файл |
| `orchestra-knowledge-delivery` | файл |
| `orchestra-local-workflow` | файл |
| `orchestra-model-text-control-flow` | файл |
| `orchestra-receipt-audit` | файл |
| `orchestra-remove-dead-compat` | файл |
| `orchestra-retire-legacy-review` | файл |
| `orchestra-service-lifecycle` | файл |
| `orchestra-service-lifecycle-baseline` | файл |
| `orchestra-simplify-review` | файл |
| `orchestra-stability-recovery` | файл |
| `orchestra-storage` | файл |
| `orchestra-storage-baseline` | файл |
| `orchestra-sync-20260912` | файл |
| `orchestra-worker-autonomy` | файл |
| `Parsing` | каталог |
| `PhotoServer` | каталог |
| `seedon` | каталог |
| `slay-the-spire-analysis` | не найден |
| `space-sim` | каталог |
| `stargate-tactics` | каталог |
| `test-project` | каталог |
| `TradingCryptoBot` | каталог |
| `TTS` | не найден |
| `Vitaliy-Projects` | не найден |
| `VoiceType` | каталог |
| `VPN-Service` | каталог |
| `web_portfolio` | каталог |
| `WebView` | каталог |
| `wmod` | каталог |
| `world-state` | не найден |

### /mnt/data/Projects/Unity/

| Каталог | Маркер .git |
|---|---|
| `AIMedical` | каталог |
| `AISwapFace` | каталог |
| `Bashilov Story` | не найден |
| `Birusa2026` | каталог |
| `DefaultProjectUnity` | каталог |
| `POLUS` | не найден |
| `Test` | не найден |
| `WinterGame` | каталог |

Vault: /mnt/data/Рабочий стол/Cursor/COG-second-brain — существование проверено
в том же снимке. Ноутбучная папка orchestra — checkout; работающий экземпляр Orchestra
этой платформы находится на VPS. Доступ к checkout не разрешает деплой или рестарт.
