# 30 namespace → 18 записей каталога (заготовка, требует сверки человеком)

Данные: боевая `orchestra.db` (read-only) + каталоги
`/home/kesha/orchestra/data/storage-preflight-final-20260908/tasks/projects/`.
Число каталогов в Git-хранилище (30) совпадает со строками `tm_projects` (30) — это
и есть причина, по которой лишние строки нельзя удалить: они порождаются из Git.

Колонка «tag» — **предложение**, а не факт. Строки, где склейка спорная, помечены **?**.

| namespace (canonical_id) | локальный id в `tm_projects` | scope | задач | предлагаемый tag |
|---|---|---|---|---|
| `home-kesha-orchestra-8b68cd9600cc` | `/home/kesha/orchestra` | `/home/kesha/orchestra` | 427 | **orchestra** (write) |
| `orchestra` | `git:orchestra` | — | 375 | orchestra |
| `vps-orchestra` | `orchestra` | — | 5 | orchestra |
| `orchestra-15ebb64920a9` | `Orchestra` | — | 1 | orchestra |
| `mnt-data-projects-python-orchestra-13dc8d0cd9fb` | `git:mnt-data-projects-python-orchestra-13dc8d0cd9fb` | — | 1 | orchestra **?** |
| `vps-seedon` | `seedon` | `/home/kesha/projects/seedon` | 233 | **seedon** (write) |
| `seedon` | `git:seedon` | — | 202 | seedon |
| `seedon-ab14b1ec414e` | `Seedon` | — | 2 | seedon |
| `scope-home-kesha-projects-comfy-image-pipeline-eda5417930f8` | `scope:/home/kesha/projects/comfy-image-pipeline` | `/home/kesha/projects/comfy-image-pipeline` | 65 | **comfy-image-pipeline** (write) |
| `scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9` | `git:scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9` | — | 113 | comfy-image-pipeline |
| `scope-opt-cog-second-brain-ae141e685f2e` | `scope:/opt/cog-second-brain` | `/opt/cog-second-brain` | 5 | **cog-second-brain** (write) |
| `cog-second-brain-77dd306ac2a0` | `git:cog-second-brain-77dd306ac2a0` | — | 82 | cog-second-brain |
| `mnt-data-cursor-cog-second-brain-ebf4c5a1c0e2` | `git:mnt-data-cursor-cog-second-brain-ebf4c5a1c0e2` | — | 2 | cog-second-brain |
| `vps-kesha-tg-bot` | `kesha-tg-bot` | `/home/kesha/projects/kesha-tg-bot` | 23 | **kesha-tg-bot** (write) |
| `kesha-tg-bot` | `git:kesha-tg-bot` | — | 27 | kesha-tg-bot |
| `scope-home-kesha-katya-work-4d99f07b63b0` | `scope:/home/kesha/katya-work` | `/home/kesha/katya-work` | 45 | **katya-work** (write) |
| `dnd-game-master` | `dnd-game-master` | `/home/kesha/projects/dnd-game-master` | 45 | **dnd-game-master** (write) |
| `scope-home-kesha-projects-vpn-service-8c275eacd1e2` | `scope:/home/kesha/projects/vpn-service` | `/home/kesha/projects/VPN-Service` | 8 | **vpn-service** (write) |
| `vpn-service-7c16d6f598b1` | `git:vpn-service-7c16d6f598b1` | — | 12 | vpn-service |
| `polus` | `git:polus` | — | 25 | polus |
| `sensar-5e197e867bb2` | `git:sensar-5e197e867bb2` | — | 21 | sensar |
| `parsing-hub` | `git:parsing-hub` | — | 17 | parsing-hub |
| `stargate-tactics` | `git:stargate-tactics` | — | 11 | stargate-tactics |
| `university` | `git:university` | — | 1 | university **?** |
| `university-9d38443e2220` | `git:university-9d38443e2220` | — | 2 | university **?** |
| `family-tree` | `git:family-tree` | — | 1 | family-tree (archived) |
| `inscryption-ai` | `git:inscryption-ai` | — | 1 | inscryption-ai (archived) |
| `tradingcryptobot` | `git:tradingcryptobot` | — | 1 | tradingcryptobot (archived) |
| `webview-c212de852078` | `git:webview-c212de852078` | — | 1 | webview (archived) |
| `zahoron-mobile` | `git:zahoron-mobile` | — | 1 | zahoron-mobile (archived) |

Сумма задач: 1755 — совпадает с `SELECT COUNT(*) FROM tm_tasks`.

## Что человеку надо решить в этой таблице

1. `mnt-data-projects-python-orchestra-…` (1 задача) — это наша Orchestra или чужая копия?
2. `university` и `university-9d38443e2220` — один университет или два разных?
3. `scope:/home/kesha/projects/vpn-service` хранит scope `…/VPN-Service` с заглавными.
   Файловая система регистрозависима — при переносе в каталог сохранить **точную** строку.
4. Живой scope `/home/kesha/projects/University` (1 активная сессия) в `tm_projects`
   отсутствует, в этой таблице его поэтому нет. Нужна ли ему запись каталога?

## Конфликты номеров внутри предложенных тегов (измерено)

| tag | конфликтующих `#N`/`V-N` | задач |
|---|---|---|
| orchestra | 231 | 469 |
| seedon | 149 | 300 |
| comfy-image-pipeline | 20 | 40 |
| kesha-tg-bot | 13 | 26 |
| vpn-service | 8 | 16 |
| cog-second-brain | 2 | 4 |
| university | 1 | 2 |
| **итого** | **424** | **857 из 1755** |

Запрос, которым получено:

```sql
with tag(project_id, t) as (values ('/home/kesha/orchestra','orchestra'), ...)
select t, count(*) colliding_refs, sum(n) tasks_involved from (
  select tag.t t, tm_tasks.ref_prefix rp, tm_tasks.par_number pn, count(*) n
  from tm_tasks join tag on tag.project_id=tm_tasks.project_id
  group by 1,2,3 having n>1) group by t;
```

Отдельно по `V-`: `V-1` в трёх проектах, `V-2`…`V-8` и `V-10` в двух, `V-9` в трёх.
`V-` — это `origin` записи, а не «глобальная VPS-нумерация».
