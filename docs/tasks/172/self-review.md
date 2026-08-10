# #172 — строгая Sol self-review

**Статус:** research ready; внешний Codex verdict отсутствует.

`codex_review` был вызван один раз для `docs/tasks/172/research.md` и завершился до старта
review job:

```text
weekly_quota_upgrade_required: New Codex worker turn blocked: the FastAPI readiness server does not provide worker-weekly-v1. Deploy the compatible FastAPI server before this MCP client; stop/model change remain available.
```

По условию задачи повтор, другая модель и обход readiness не применялись.

## Проверки против собственных выводов

1. **Суммы пересчитаны из исходных компонент.** Нижние границы сходятся арифметически:
   orchestrator `40 638 + 3 093 + 76 013 + 18 886 = 138 630 B`; sub-orchestrator
   `40 989 + 3 155 + 76 013 + 18 886 = 139 043 B`; worker `118 462 B`; full-cycle
   `134 569 B`. Для full-cycle с memory: `84 652 + 76 013 + 18 886 = 179 551 B`, после
   reload `129 655 + 76 013 + 18 886 = 224 554 B`.
2. **Tool tax проверен на фактическом Codex subset.** Первый подсчёт registry дал 36 tools;
   это не равно доступным Sol tools. `ORCHESTRA_FULL_MCP_TOOLS` содержит 34: `send_chart` и
   `resolve_merge_operation` исключены. В итоговой таблице использованы только эти 34.
3. **Нижняя граница tool tax не выдана за полный wire payload.** `name + description +
   inputSchema` = 18 886 B; compact transport с `outputSchema` = 23 651 B. Видимость
   `outputSchema` непосредственно моделью не доказана, поэтому обе цифры названы отдельно.
4. **Memory finding ограничен реально существующей веткой.** Дубль появляется, только если
   `old_prompt.startswith(formatted_base)`; изменение base обходит этот путь. Частота в prod не
   измерена. Измерение доказывает воспроизводимость и размер на текущем worker, не incidence rate.
5. **Bootstrap finding проверен по startup order и первому send.** `auto_resume_all()` идёт до
   `ensure_bootstrap()`; новая DB row затем грузится лениво. Без
   `/workspace/project/prompts/orchestrator.md` backend первого turn получает сохранённый prompt
   75 B, потому что native `session_id` ещё пуст и user refresh не срабатывает. На следующем
   turn `_current_prompt` уже может быть доставлен как user refresh.
6. **Resume proposal оставлен UNCERTAIN.** Наличие двух каналов видно в source, но применение
   новых `developerInstructions` к уже созданному thread не проверялось на текущем app-server.
   Поэтому research требует отдельный behavioral probe до любой правки.
7. **Mass-rewrite hypothesis отвергнута собственным counter-test.** Exact same-run duplication
   составляет только 61 B/68 B в найденных ролях; крупные пары смысловые. Они оставлены
   отдельными A/B arms, а measured safety/gate правила перечислены в разделе «Что оставить».
8. **Scope проверен.** Исторические `docs/tasks/**` использованы только как evidence; HTML/Jinja
   templates не подаются модели; Claude/Grok/OpenCode transport перечислен как граница, но не
   включён в Sol tax. Активные prompt/code files не менялись.

## Verdict

Research пригоден для Phase 1 gate: load-bearing факты либо подтверждены current source и
воспроизводимым измерением, либо явно помечены `LIKELY`/`UNCERTAIN`. Внешнего approval нет;
готовность здесь — только строгий Sol self-review, не `Codex approved`.
