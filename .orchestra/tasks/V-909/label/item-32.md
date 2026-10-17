# item-32

Commit under review (in /home/kesha/orchestra, read-only): `5c346ffd58228eef4a0231b066169d058a621e21`
Subject / date:
#227: #227: enforce worker model policy at spawn
2026-08-13

The diff reviewed is `git -C /home/kesha/orchestra show 5c346ffd58228eef4a0231b066169d058a621e21 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Проверил полный diff между `d7583e8b7502d49c740f564d31847d4a5ea45d87` и `9470ceb9a051ee41556d1a95fead89d7b83b2af4`. Нашёл одну проблему: причина исключения передаётся в API без ограничения длины или очистки.

## Findings

### suggestion

- **Причину исключения можно неограниченно раздувать в логах.** `model_policy_override_reason` принимается как произвольная строка и целиком записывается в warning в [manager.py](app/manager.py:528). Длинное значение может резко увеличить объём логов при каждом spawn с исключением. Стоит ограничить длину поля и нормализовать управляющие символы перед логированием.

## Verdict

APPROVED
