## Summary

Naturally, three green requests did not magically certify the whole scheduler. 🔬 Claims (1), (2), and (4) hold: `--local` does not document relaxed flood limits, the probe proves only a three-message 1.05-second burst, Telegram still documents 20 group messages/minute, and current stale telemetry/optional behavior matches the research. [Telegram FAQ](https://core.telegram.org/bots/faq), [local Bot API README](https://github.com/tdlib/telegram-bot-api).

The proposed implementation is not ready, however: its timeout and preview-admission semantics can lose important traffic or block agent text. Live logs and telemetry were not independently inspected, per scope.

## Findings

1. **blocking: Exclude rate-window waits from the 75-second reliable deadline**

   The design says important calls wait for a rolling-window reservation and honor the first `retry_after` ([research.md:183](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:183)), but `_tg_run_call` wraps reservation, API attempts, network delays, and flood waits in one 75-second timeout ([tg_bridge.py:910](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:910), [tg_bridge.py:1025](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:1025)). After a 20-message burst, the next reservation can wait about 40 seconds; one 30-second timeout or moderate `retry_after` then exhausts the total deadline and increments `reliable_lost`. Rate/flood waiting must be outside that deadline, or the deadline policy must be redesigned.

2. **blocking: Preview admission is not isolated from the text producer**

   The research treats the image lane as isolated ([research.md:145](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:145)), but `stream_logs` awaits preview submission inline ([tg_bridge.py:2724](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:2724), [tg_bridge.py:2804](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:2804)). If reliable admission waits when 16 reservations are full, subsequent agent text is not processed; if admission raises backpressure, both preview helpers swallow `Exception` and return `False` ([tg_bridge.py:2524](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:2524), [tg_bridge.py:2614](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:2614)), so the stream cursor advances and the preview is lost. The design needs a nonblocking producer handoff with explicit durable admission and unswallowed backpressure.

3. **blocking: Define error-selective retry for the ordered image marker**

   F6 preserves the marker’s one-attempt boundary but promises retries only for media edits ([research.md:203](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:203)). Currently the marker is `ordered=True` but not important ([tg_bridge.py:1651](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:1651)); consequently, an explicit `TelegramRetryAfter` immediately returns `None` after one attempt ([tg_bridge.py:946](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:946)). An explicit 429 is unambiguous and safe to retry, unlike a network timeout. The marker needs separate semantics: wait/retry on 429, but avoid blind retry after ambiguous delivery.

4. **suggestion: Reserve headroom for calls outside the limiter**

   A 20-reservation window consumes the entire documented group budget, while the paper itself acknowledges chat-wide topic-icon operations outside this authority ([research.md:226](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:226)). Therefore it does not strictly “preserve the group ceiling” system-wide. Either those operations must eventually share the reservation authority, or #102 should reserve documented headroom and explicitly state the reduced tracked-call cap.

5. **suggestion: State 1.05 seconds exactly, not “one second”**

   The measured gaps were 1.0513/1.0503 seconds, but the proposed rule says “one-second minimum spacing” ([research.md:181](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:181)). Since the conclusion is explicitly limited to the measured candidate, specify `_TG_GROUP_INTERVAL = 1.05`; otherwise an implementer can reasonably choose an unmeasured 1.00 seconds.

## Verdict

**Revise before implementation.** The Telegram-limit conclusions, conservative interpretation of the three-message probe, expiry direction, and current stream classification are sound. The rate-window timeout interaction and incomplete preview isolation/retry contract are blocking because they can lose important payloads or starve text.

Right now it is a 20-seat reservation system that forgot both the driver and the photo queue. 🚌

## Round (2026-07-29T09:43:27Z)

## Re-review status — Round 2

Чудеса случаются: все пять замечаний действительно разобраны, а не переименованы. 🥊 `research.md` целиком untracked; `app/tg_bridge.py` не изменён.

1. **FIXED** — внешний 75-секундный deadline удалён из плана; rate/flood waits больше не превращают важные сообщения в `reliable_lost`.

2. **FIXED** — preview handoff теперь nonblocking и bridge-owned до продвижения stream cursor; `_TgDeliveryOverloaded` обязан проходить наружу.

3. **FIXED** — marker получает selective retry: явный 429 повторяется, ambiguous timeout/network/server не повторяется.

4. **RESOLVED DISAGREEMENT** — tracked-only формулировка приемлема. Доказательств для 18/20 или 19/20 нет; выдумывать запас неправильно. Внешнее вмешательство честно обозначено, rejected reservation и `retry_after` дают обратную связь.

5. **FIXED** — везде указан измеренный интервал `1.05s`, а не абстрактная секунда.

## New findings

- **NEW BUG — suggestion:** [research.md:184](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/102/research.md:184) утверждает, что интервал `1.05s` даст `60/min`; фактически `60 / 1.05 ≈ 57.14/min`. Вывод про превышение 20/min остаётся верным, но число нужно исправить.

## Verdict

**Approved with one non-blocking correction.** Новых рисков потери payload, повторяющихся 429 или starvation текста не найдено. План согласуется с текущими delivery и stream call sites и готов к реализации после исправления арифметики.

Один калькулятор всё-таки пережил ревью — хорошо хоть Telegram ему отправлять не доверили. 🧮
