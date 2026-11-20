# SkillCache v1 — архитектура, пул из 10 капсул и правила самообучения

- **Назначение:** сокращать 5–20 рутинных детерминированных вызовов (почта, Директ, сон, wellness, статус ЭДО/1С, YouTube-метаданные, preflight VPS, сводка Авито, CDP-DOM) до 1 верифицированного вызова `capsule_run` / `scripts/orch-capsule-run`.
- **Граница безопасности:** манифест не принимает URL, пути, токены или команды. Доступ выдает только хост (`ORCHESTRA_SKILLCACHE_CONFIG` `0600`). Все ответы проверяются `source.attest(...)` и контрольной суммой SHA-256, секреты режутся.
- **Пул (10 активных капсул):** `kesha-mail`, `direct-reports`, `xiaomi-sleep`, `browser-control`, `morning-digest`, `wellness-dashboard`, `edo-1c-status`, `youtube-reader`, `vps-health-preflight`, `avito-stats`.
- **2-гейтовая квалификация (`scripts/orch-capsule-run qualify`):** запуск в Linux libseccomp-песочнице (`baseline`, мутированный `counterexample` с другими датами/ID/окнами, `reject_stale` — замороженный результат обязан упасть в `verification_failed`).
- **Самообучение и ремонт:** после ручной цепочки из >=5 детерминированных шагов агент оформляет капсулу и контрпримеры; при `stale` (SHA-256 файла скилла/схемы) или `deopt` на шаге `k` чинит только шаг `k` (`vN -> v(N+1)`). Tier C (`explainer-craft`, `grill-me`, `game-ui-design`, `codex-debate`, `teach-me`) не кешировать.
