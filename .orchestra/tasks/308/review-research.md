<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Отчёт в целом добросовестно подтверждает подлинность проекта, возраст, stars, RC-only статус, отсутствие GitHub releases/tags, one-shot характер Codex/Claude Code bridges и основные parity gaps с Orchestra. Арифметика согласуется: weekly totals дают 11 792, возраст импортированной истории — около 64 дней, значения `research.md` совпадают с `evidence.json`.

Однако security-сравнение содержит опасное обобщение: DSH не предоставляет единый cross-platform OS sandbox для всех filesystem effects. Есть kernel-backed confinement для shell и отдельный trusted-code fence для filesystem tools, причём последний прямо не считается security boundary и сохраняет TOCTOU. Также smoke недостаточно воспроизводим, а вывод о `SLICE` сильнее представленных доказательств.

## Findings

### blocking: `docs/tasks/308/research.md:168-170,189,202` — security boundary завышена и объединяет два разных механизма

Отчёт утверждает:

> «DSH имеет реальный sandbox seam… Local provider выбирает Linux bubblewrap с Landlock fallback, macOS Seatbelt и Windows ACL/restricted token»

> «Это полезнее текущей Orchestra worktree isolation»

> «security design сильнее Orchestra по filesystem enforcement»

> «cross-platform fail-closed filesystem enforcement with status»

Это корректно для запуска shell-команд через sandbox executor, но некорректно как общее описание filesystem enforcement DSH. Опубликованная Web composition одновременно монтирует `dsh-bash-sandbox` и отдельный `dsh-fs-sandbox` ([published-default-config.yml](/var/tmp/dsh308.ayJak0/published-default-config.yml:86), [published-default-config.yml](/var/tmp/dsh308.ayJak0/published-default-config.yml:358)). Второй механизм:

- проверяет только `writeText`/`editText`, а reads пропускает всегда ([fs-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/fs/fs-sandbox/README.md:5));
- прямо назван «policy fence, not a kernel boundary» ([fs-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/fs/fs-sandbox/README.md:19));
- сохраняет признанный resolve-to-syscall TOCTOU ([fs-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/fs/fs-sandbox/README.md:21));
- не защищает от adversarial host processes ([fs-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/fs/fs-sandbox/README.md:43)).

Даже kernel-backed shell sandbox ограничивает только file effects; network и process visibility остаются открытыми ([bash-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/shell/bash-sandbox/README.md:22), [bash-sandbox README](/var/tmp/dsh308.ayJak0/repo/packages/shell/bash-sandbox/README.md:83)).

Нужная коррекция: разделить в отчёте:

1. kernel-backed shell confinement;
2. trusted-code filesystem mutation fence;
3. отсутствие общего process/network/runtime boundary.

Вердикт «DSH сильнее» допустим только в более узкой формулировке — например, что DSH имеет более оформленную policy/enforcement архитектуру для shell и штатных FS tools, но не единый cross-platform security boundary. Это blocking из-за потенциально опасной security-гарантии.

### suggestion: `docs/tasks/308/research.md:30,95-104,260` — “exact README npx path” не проверен по предзарегистрированному критерию

Отчёт говорит:

> «точный `npx`-путь README дважды завис»

> «точная README-команда `npx @deepseek-ai/dsh web` не оказалась воспроизводимой»

Но зафиксированные попытки были:

- две команды `npx --yes @deepseek-ai/dsh@0.1.0-rc.6 --help`;
- одна `npx --yes @deepseek-ai/dsh@0.1.0-rc.6 web`, остановленная через 120 секунд ([evidence.json](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/evidence.json:367)).

Это не дословная README-команда: добавлены `--yes` и pinned version, а два длительных прогона проверяли `--help`, не `web`. Кроме того, предрегистрация дала Web до 15 минут ([evidence.json](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/evidence.json:366)), тогда как Web-проба была прекращена через 120 секунд ([evidence.json](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/evidence.json:385)). Поэтому она не может считаться FAIL по собственному критерию.

Нужная коррекция: либо назвать результат «pinned npx install/help path stalled; 120-second Web probe inconclusive», либо повторить дословную README-команду с полным 15-минутным бюджетом.

### suggestion: `docs/tasks/308/research.md:30,116-126` — provider/auth вывод чрезмерно сводит consumer routes к двум product adapters

Отчёт утверждает:

> «consumer subscriptions доступны только косвенно через отдельно подключаемые one-shot Codex/Claude Code adapters»

При этом опубликованная зависимость содержит другие subscription-oriented providers:

- GitHub Copilot с token auth и OAuth ([github-copilot.js](/var/tmp/dsh308.ayJak0/pi-ai/package/dist/providers/github-copilot.js:8));
- Kimi Code с явно названным `Kimi Code (subscription)` OAuth ([kimi-coding.js](/var/tmp/dsh308.ayJak0/pi-ai/package/dist/providers/kimi-coding.js:6));
- Qwen/Xiaomi Token Plan routes ([qwen-token-plan.js](/var/tmp/dsh308.ayJak0/pi-ai/package/dist/providers/qwen-token-plan.js:5), [xiaomi-token-plan-ams.js](/var/tmp/dsh308.ayJak0/pi-ai/package/dist/providers/xiaomi-token-plan-ams.js:5));
- OpenCode Go, код которого отдельно классифицирует subscription limits.

Отчёт прав в более узком выводе: DSH adapter не инжектит credential store и не запускает OAuth login, поэтому OAuth-only `openai-codex` скрыт ([llm-pi-ai README](/var/tmp/dsh308.ayJak0/repo/packages/llm/llm-pi-ai/README.md:190)). Также не найден эквивалент persistent ChatGPT/Claude.ai worker.

Нужная коррекция: различить:

- consumer/subscription-oriented provider protocols в pi-ai;
- реально достижимые DSH routes через вручную переданный token/API-key;
- встроенный interactive OAuth login;
- persistent native product sessions.

Иначе headline недооценивает provider surface, хотя основной parity-вывод относительно Orchestra, вероятно, сохранится.

### suggestion: `docs/tasks/308/research.md:24,307-316` — evidence.json не является воспроизводимым «полным журналом»

Отчёт называет `evidence.json`:

> «Полный машинно-читаемый журнал чисел и критериев»

Но файл содержит в основном нормализованные итоги и описания команд. Для smoke отсутствуют raw npm logs, stderr, process-tree observations, exit status двух hang-проб, timestamps и hashes артефактов. Для source measurements отсутствуют точные команды/path filters; поле `commands.source_metrics` — лишь описание `git ls-files plus rg/wc` ([evidence.json](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/evidence.json:500)). M5–M9 также не перечисляют точные source paths/line anchors внутри JSON.

Нужная коррекция: либо переименовать его в normalized evidence summary, либо приложить raw logs и дословные команды с hashes. Сейчас сторонний reviewer не может независимо воспроизвести 129 rows, 259 876 production lines, npx hang или targeted absence searches только из заявленных артефактов.

### suggestion: `docs/tasks/308/research.md:18,28,214,220-246,328` — `SLICE` не полностью следует из evidence

Отчёт убедительно отвергает `FULL`: auth/lifecycle/control-plane gaps реальны. Он также отвергает «поддельный/пустой проект». Но из этого логически не следует, что перенос именно предложенных slices окупится.

В частности:

- P1 предполагает ценность byte-equivalent replay invariant, но не показывает текущую частоту или стоимость hidden-input дефектов Orchestra.
- P2 частично заимствует design, security-границы которого сам отчёт переоценивает.
- P3 — benchmark DSH, а не перенос slice.
- Оценка `3–7 engineer-days каждый` объявлена planning range без измерительной базы.

Нужная коррекция: понизить `SLICE — высокая уверенность` до «FULL rejected; три candidate pilots заслуживают отдельной проверки» либо добавить evidence текущей боли Orchestra и ожидаемой ценности каждого pilot. Высокая уверенность поддержана для parity gap, но не для ROI выбранных slices.

### suggestion: `docs/tasks/308/research.md:252` — stars и commit count не доказывают отсутствие demo-эффекта

Утверждение:

> «141,869 stars … и 12,293 reachable commits показывают … реальную разработку, а не demo»

Commit history действительно опровергает freshly generated пустышку. Stars показывают популярность, но не зрелость или техническую подлинность; импортированная история сама по себе также не доказывает качество публичного продукта. Более точная формулировка: кодовая база крупная и имеет существенную достижимую историю; exceptional stars показывают интерес.

## Verdict

**NEEDS WORK — 1 blocking security overclaim, 5 suggestions.**

Подлинность, counters, возраст/release arithmetic и отсутствие Codex/Claude Code adapters из published default подтверждены. Их one-shot lifecycle также подтверждён исходниками. Главный вывод против `FULL` устойчив, но security comparison необходимо исправить до принятия отчёта; npx и `SLICE` требуют более осторожной интерпретации.

## Round (2026-08-17T09:16:14Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior BLOCKING security finding is resolved. The report now correctly separates kernel-backed shell confinement from the trusted-code filesystem mutation fence and explicitly records unrestricted reads, TOCTOU, and absent process/network boundary. No remaining blocking issue found.

The revised auth, one-shot adapter, FULL/REJECT, SLICE ROI, stars/activity, and exact `npx` conclusions are supported by the cited evidence.

## Findings

### blocking

None.

### suggestion: `evidence.json:393-399` contradicts the corrected smoke classification

The report correctly calls the 120-second pinned Web probe:

> “INCONCLUSIVE: bounded 120 с при заранее заявленном лимите 15 мин” ([research.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/research.md:97))

But `evidence.json` still records the same attempt as `"result": "FAIL"` ([evidence.json](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-deepseek-harness/docs/tasks/308/evidence.json:393)). Change that normalized status to `INCONCLUSIVE`; the exact command’s PASS remains independently verified at 509 seconds, and its recorded raw-log/HTML hashes match the surviving artifacts.

### suggestion: `research.md:105` slightly over-interprets unlike probes as “variance”

The exact README Web command passed, while earlier trials differed in command, version pinning, runtime, cache/home, and duration. Those results establish mixed cold-install behavior, but not a measured variance distribution. “Observed inconsistent cold-install outcomes” would be more precise than:

> “evidence cold-install variance/npm path instability”

This does not affect the adoption verdict.

## Verdict

**APPROVED WITH NON-BLOCKING SUGGESTIONS.**

Prior findings status:

- Security overclaim: **FIXED**
- Exact README smoke: **FIXED**
- Subscription/provider understatement: **FIXED**
- Evidence described as complete raw archive: **FIXED**
- Unsupported high-confidence SLICE ROI: **FIXED**
- Stars/commits interpreted as maturity: **FIXED**

No remaining crash, corruption, or security blocker.
