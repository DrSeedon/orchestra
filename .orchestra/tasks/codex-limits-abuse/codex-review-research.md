## Summary
Документ в целом полезный, но в ключевых технических тезисах есть провалы в точности источника: два блока уже сейчас конфликтуют с актуальными публичными значениями лимитов и с верифицируемостью части source-code выводов, поэтому его в таком виде лучше не считать финальным для принятия решений по политике эксплуатации CLI.
Набор рисков в основном управляемый: поправить кванты лимитов, убрать формулировки про «жёсткие/уверенные» выводы без покрытия и явно разнести факт/гипотезу по всем спорным пунктам; пока этого нет — статус не «чистый».

## Findings (blocking/suggestion/question)

<!-- blocking -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:10`
Факт: в «Итогах по лимитам» зафиксирован диапазон `75–450`, `100–550`, `200–1300` и т.п. как «сейчас/текущий». Это не соответствует текущей публичной картинке страниц тарифов (в срезе на `2026-07-18` по этому документу значимые значения иные), плюс в самом тексте дальше признаётся, что есть мягкая переменная часть лимита. Блокер: ошибка в опорных числах ломает основу всех расчётов. Уверенность: высокая.

<!-- blocking -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:61,67`
Тезис о «фиксированных» лимитах под 5× подаётся как более жёсткий, чем отражают источники, где есть формулировки «shared 5h window, may apply ...». Нужна строгая оговорка: это наблюдаемая шкала, но не обещанный математический cap; иначе это прямое переобобщение, способное привести к неверному risk-моделированию. Уверенность: средняя-высокая.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:11`
Пункт про weekly абсолюты корректный по общей интуиции («may apply»), но сейчас формулировка может читаться как «есть/будет» конкретный лимит, хотя в источнике его величины действительно не перечислены. Нужно явно перечислить отсутствие публичных величин по всем моделям и что это поведение вероятностное/персонализированное. Уверенность: высокая.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:91,99`
Интерпретация локальной метрики «7d main + отдельный spark bucket» как недостаточный/контроверсный признак относительно недельного лимита верна, но сейчас вывод близок к «по сути это не weekly». Один срез недостаточен для strong conclusion, нужна формулировка «показало поведение за окно наблюдения, не равносильно сбросу по документируемой недели». Уверенность: высокая.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:97,105`
По Plus/Pro «unlimited/безлимит» есть риск смешения тарифных маркетинговых формулировок с практической квотой. Нужно прямо писать: «unlimited» в плане не равно отсутствию лимитов, а в ChatGPT-ветке применяются конкретные лимиты моделей/окно; по API-деньгам/токенам — отдельная модель экономики. Уверенность: высокая.

<!-- question -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:113,127-143,186`
Заявления о split backends (`chatgpt.com/backend-api/...` vs `api.openai.com/...`) и вывод о «no supported text-chat to API-key flag» опираются на источники, но в файле нет верифицируемого подтверждения по каждому переходу/ветке исполнения именно в версии локально используемого CLI без дополнительных условий среды. Нужна либо репликация через воспроизводимый snippet (лог запроса/код с конкретной версией), либо маркировка как «inferred from source + runtime checks». Уверенность: средняя.

<!-- blocking -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:24-29,46`
Есть жёсткая формулировка про 160/3h и fallback «mini» без явного подтверждения в открытых ссылках из списка (по минимуму есть один зафиксированный 160/3h-порог, но не ясно источник для fallback-логики в том же блоке). Это риск ложной уверенности в конкретной политике failover, лучше снизить до «наблюдаемое поведение/непроверенный вывод» и убрать «гарантия». Уверенность: средняя.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:15-16,170-176,205-219`
Классификация рисков по multi-account rotation / relay / automation / custom providers в целом адекватна, но формулировки местами скатываются в quasi-юридический вердикт. Для внутреннего use-case лучше держать split:
- что прямо запрещено (по ToS/Usage policy),
- что подозрительно и может блокироваться,
- что не доказано как практика массовых банов/преднамеренно успешных обходов.
Уверенность: высокая.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:170,214-219,205`
По бан/предупреждениям корректно, что нет массовых подтверждённых кейсов как доказанного ядра, но есть место для сильного улучшения: не смешивать «нет подтверждения» с «возможность исключена». Развести в отчёте `evidence: confirmed`, `unconfirmed`, `anecdotal`, и для Reddit/X явно указывать confidence/достоверность канала. Уверенность: высокая.

<!-- suggestion -->
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-abuse/docs/tasks/codex-limits-abuse/research.md:244-257`
Рекомендации по настройке ChatGPT-auth Codex CLI хороши по тону, но добавьте два обязательных пункта:
- не включать инструкции по обходу/маскированию и ротации,
- добавить контрольный чек-лист «если лимит исчерпан: graceful degradation + логирование + escalation».
Также лучше добавить правило: пересмотрать лимиты не реже еженедельно, потому что источники уже меняются на интервалах. Уверенность: высокая.

## Verdict
NOT APPROVED — есть блокирующие фактические расхождения по лимитам и части утверждений о «жёсткости/универсальности» лимитов, которые прямо влияют на безопасность/правильность решения.
Чтобы одобрить, нужно:
1) обновить диапазоны и маркеры certainty на `в текущих публичных условиях как на 2026-07-18`,
2) убрать/смягчить неподтверждённые конкретики по backend behavior и fallback,
3) четко разделить доказанные факты, вероятностные интерпретации и аномальные наблюдения.

## Round (2026-07-18T11:10:25Z)

## Re-review status
`git diff -- docs/tasks/codex-limits-abuse/research.md` returns empty and `git status --short` shows `?? docs/tasks/codex-limits-abuse/` (untracked). Прогон по diff-формату по смыслу выполнен, но сравнение идёт с текущим рабочим деревом как новому файлу.

Prior findings status (Round 1 → Round 2):

1) Blocking: Pro 5× numbers mismatch — WITHDRAWN
Доказанный источник теперь совпадает: таблица в документе соответствует официальным диапазонам, которые вы указали (включая Luna 250–1400), поэтому прежнее расхождение снято.

2) Blocking: fixed caps interpretation in the same block — FIXED
Документ теперь явно пишет «snapshot/на ориентирах, не гарантированных hard cap», плюс отмечает token economy и отсутствие публикуемого абсолютного weekly значения.

3) Blocking: 7d local bucket misread as definitive (vs 5h/weekly docs) — FIXED
Ограничение теперь зафиксировано как локальное наблюдение на 1 окне, с явным caveat о rolling/calendar механике и универсальности.

4) Blocking: 160/3h + fallback claims не доказаны — WITHDRAWN
Теперь есть явно привязка к `help.openai.com/en/articles/20001354` (160/3h Instant + fallback, и reasoning allowance fallback упоминание), при сохранении точной сферы (Instant/Thinking/5.6 context).

5) Suggestion: source-code выводы недостаточно доказаны / не верифицируемы — FIXED
Введён важный квалификатор: commit-pinned inference + local auth checks, без packet-capture; это убирает прежний overclaim.

6) Suggestion: multi-account/legal framing overreaches — FIXED
Терминология корректнее стала: policy-supported account switching vs целенаправленное quota-sharding с high risk.

7) Suggestion: ban/risk conclusion overstates certainty — FIXED
Сохранена развилка `refuted as rule / cases UNCERTAIN`, без подмены отсутствия кейсов на отсутствие рисков.

8) Suggestion: Reddit/X evidence gaps — FIXED
Уровни confidence и gap-нотация сохранены, прямых выводов из непрочитанных тредов не выведено.

9) Suggestion: recommendations for CLI ops — FIXED
Добавлены graceful-degradation/escalation/weekly recheck, без инструкций по обходу.

10) Blocking list: “STILL BROKEN” items — NONE
Новых доказуемых blockers по фактам/юрисдикционным рискам не выявлено после правок.

11) NEW BUG (процессный): no tracked diff available for this file at review time
Новая находка: файл сейчас untracked, поэтому «проверка diff» в строгом git-терминах не показывает изменённые строки. Нужно `git add`/залогировать в ветке для полноценного diff-рецензирования по изменению.

## New findings
- `/docs/tasks/codex-limits-abuse/research.md:16` geo-риск по Russia теперь лучше поддержан: в текущем списке supported countries России нет, и там же есть предупреждение о блокировке вне списка; это соответствует вашей формулировке.
- Тональность в блоках `CONFIRMED/LIKELY/UNCERTAIN` адекватнее, чем прямой категоричности в отношении circumvention.
- Если нужна формальная готовность к код-ревью pipeline, первым шагом стоит зафиксировать этот файл в git, иначе future-инкрементный diff невозможен.

## Verdict
APPROVED
