# Report — #cost-tokens: store RAW cache tokens, recompute cost_cached on-the-fly

## What
БД хранила готовую цену `cost_usd_cached` (по цене-на-момент-турна), но НЕ сырые cache-токены →
при смене `TOKEN_PRICES` (Opus $15/$75 → $5/$25) пересчитать историю было нельзя. Теперь сырые
cache-токены хранятся полно, а `cost_usd_cached` пересчитывается on-the-fly из текущих цен. Смена
цены → корректный автоматический пересчёт всей истории (где есть сырые токены).

## Files (+56/−6)
| File | ±lines | Change |
|------|--------|--------|
| `app/db.py` | +12/−2 | миграция +2 колонки (additive, idempotent); save_session setdefault + INSERT + ON CONFLICT |
| `app/session.py` | +6 | 2 поля `total_cache_read/create_tokens` + `_to_db_dict` + `to_dict` |
| `app/session_cost.py` | +2 | накопление cache-токенов в total (как input/output) |
| `app/manager.py` | +8 | `_hydrate_row` restore (+2); `_load_from_db` restore ВСЕХ totals (fix resume-gap) |
| `app/routes/system.py` | +28/−4 | `_cost_cached_for()` recompute + fallback; `_get_agents_cost` использует |
| `tests/test_cache_tokens.py` | +200 (new) | 11 тестов, все AC |

## Tickets done (6/6)
- **T1** миграция — колонки additive DEFAULT 0, идемпотентно, старые строки целы. ✓ AC
- **T2** накопление cache-токенов в total; старый turn без ключей → += 0, не падает. ✓ AC
- **T3** persist/restore — round-trip 350/15, legacy-dict setdefault→0, `_hydrate_row` restore. ✓ AC
- **T4** recompute on-the-fly (формула = backend_claude.py:396); fallback если нет цены ИЛИ нет
  сырых токенов; смена цены реально репрайсит историю. ✓ AC
- **T5** fix resume-gap — `_load_from_db` восстанавливает все 6 totals как `_hydrate_row` (сверено
  regex'ом: одинаковый набор). ✓ AC
- **T6** тесты + Codex + commit. ✓ AC

## Recompute rule (system.py `_cost_cached_for`)
```python
prices = TOKEN_PRICES.get(model)
has_raw = cache_read > 0 or cache_create > 0
if prices and has_raw:
    cost_cached = (input*p_in + cache_read*p_in*0.1 + cache_create*p_in*1.25 + output*p_out)/1e6
else:
    cost_cached = stored cost_usd_cached   # старые строки / codex / нет кеша
```
Row никогда не дропаем/не зануляем. `cost_usd` (SDK) — не трогали.

## Tests
- `tests/test_cache_tokens.py` — **11 passed**. Покрывает: миграция+идемпотентность, накопление+
  backward-compat, round-trip+legacy+hydrate, recompute-new / reprice / old-fallback / no-price-fallback.
- Narrow suite (db/session/p4_cost/manager + новый) — **205 passed, 3 failed**.
- 3 failures — **PRE-EXISTING** (async-timing flakiness): те же падают на base-ветке без моих правок
  (проверено `git stash`). Мои изменения регрессий не вносят.
- Полный `pytest` — заблокирован (test-lock держит test-sonnet5), гоняю по освобождении.

## Codex review
- **План**: Proceed. Ужесточил fallback-правило (recompute только при наличии цены И сырых токенов),
  поймал codex/OpenCode edge (нет в TOKEN_PRICES → fallback). Всё учтено. → `codex-review-plan.md`.
- **Импл (diff)**: **Approved, 0 blocking/suggestion/question.** Миграция additive/idempotent, 3 SQL-
  binding места на месте, формула = backend, `cost_usd` не тронут, no double-counting. → `codex-review-impl.md`.

## Adversarial self-review
1. Double-counting stored vs recomputed — НЕТ: recompute ЗАМЕНЯЕТ значение, stored только fallback.
2. Fallback на новой сессии без кеша (короткий турн) — вернёт stored, но stored там и так корректный
   (0 или мелочь). Приемлемо.
3. `TOKEN_PRICES[model]=None` для codex → `.get()` + проверка → fallback, без KeyError. Покрыто тестом.

## Breaking
Нет. Старые сессии: колонки DEFAULT 0 → recompute пропускается → показывается хранимая цена (как было).

## Notes / TODO
- Побочный баг resume-gap (`_load_from_db` терял totals при resume) — **починен** в этой задаче (T5).
- app.js `cost_usd_cached` не использует — фронт не трогали (blast radius = только system.py).
- Полный pytest прогнать по освобождении test-lock (narrow-прогон уже чист).
