# #364 — GigaEmbeddings 480M против bge-m3 на корпусе Orchestra

## Вердикт

**Не меняем модель.** На фиксированном стенде GigaEmbeddings получила MRR 0.4726 против
0.4893 у продовой bge-m3: ΔMRR = −0.0167, парный t = −0.334. Абсолютная разница 0.0167
в 6.3 раза меньше медианного собственного шума MRR 0.1048. Это не доказательство, что
GigaEmbeddings хуже; это честный результат **«разницы не видно на нашем стенде»**.

| арм | MRR | R@3 | R@5 | ΔMRR против прода | t (df=27) | вердикт |
|---|---:|---:|---:|---:|---:|---|
| bge-m3 int8 ONNX + hybrid RRF (прод) | 0.4893 | 64.3% | 75.0% | +0.0000 | +0.000 | baseline |
| GigaEmbeddings 480M + hybrid RRF | 0.4726 | 60.7% | 75.0% | −0.0167 | −0.334 | разницы не видно; не меняем |

**Собственный шум baseline MRR, split-half 20 000:** медиана |разрыва| = **0.1048**,
p90 = 0.2476, p95 = 0.2952. Расчёт выполнен только по baseline RR, seed=135; он цифра
в цифру воспроизвёл контроль #135. Порог двухстороннего t-теста: |t| > 2.052.

## Что именно измерено

- Выборка не менялась: `docs/tasks/134/bench/queries.json`, n=28,
  sha256 `516b0755416b763233df0d8c5835b16c875284144e55be9ca6e91d0f4d4dbd0a`.
- Переиспользованы retrieval/scoring primitives исходного
  `docs/tasks/134/bench/retrieval_bench.py`, sha256
  `5175a900e5d3ab14cb6ea2fe17c4f80d34958451421ac1f64419ca584fee2d84`:
  те же vector/FTS ноги, RRF_K=60, candidate pool и top-5.
- Корпус — замороженная SQLite-копия #134, sha256
  `92808d6b4170daf3e5c8784377c1e0a48dfebc60a9c53c3dbf514a2b49135ab2`.
  Свежий `vec.db` сначала был снят через `sqlite3.Connection.backup`, но отвергнут как
  несопоставимый: в нём уже отсутствовали три gold chunk_id неизменяемой выборки
  (`4041`, `3164036`, `3163026`). Замороженный snapshot #134 сам был снят тем же
  `backup()` и точно воспроизводит эталон.
- Кандидатная БД создана из snapshot через `sqlite3.Connection.backup`, не `cp`.
  В ней заменены только векторы всех 9 448 file-чанков и 8 435 log-чанков;
  тексты, FTS и RRF остались прежними. `PRAGMA integrity_check` → `ok`.
- Продовый положительный контроль воспроизведён до запуска кандидата:
  MRR 0.4892857143, R@3 0.6428571429, R@5 0.75.
  Baseline ONNX зафиксирован ревизией `a4136c5…` и sha256
  `17dbde8d0da550b94f5b8840e4305a0374d700a5c844d65b3bc9646369c559ce`.

## Контракт GigaEmbeddings

Зафиксирована ревизия Hugging Face
`2d0c1a92716eef0e5b6972df85b5883eb5b4f57a`; sha256 `model.safetensors` —
`9ce03c6c5ae02baebb42ce3015b6f3e628c5fec7b7745bc2490f6ff961a654a5`.
Карточка и `1_Pooling/config.json` задают:

- размерность 1024;
- mean pooling по непаддинговым токенам + L2-нормализация;
- документы без префикса;
- запрос: `Instruct: Given a query, retrieve relevant passages\nQuery: {text}`.

Pilot на трёх документах подтвердил четыре вектора 1024d, нормы
0.99999998–1.00000004 и первое место релевантного документа. Полный прогон:
Transformers 4.57.0, PyTorch 2.10.0+cu128, GTX 1650, batch=16, max_length=512.
GTX 1650 не поддерживает BF16, поэтому зафиксированный BF16 checkpoint исполнялся в FP16,
а mean/L2 считались в FP32. Это ограничивает перенос вывода на иное железо, но не создаёт
основания менять модель: наблюдённая разница и без того лежит глубоко внутри шума стенда.

## Проверка против подгонки

Из 28 запросов Giga улучшила RR на 5, ухудшила на 7 и не изменила на 16. Улучшения и
ухудшения разнонаправленны; итоговый t далек от порога. Выборка после раскрытия результата
не расширялась, gold не редактировался, дополнительный prompt-arm не подбирался.

## Артефакты и границы

- `docs/tasks/364/bench/results.json` — обе per-query RR-последовательности, сводка,
  provenance, paired t и split-half 20 000.
- `docs/tasks/364/bench/giga_bench.py` — воспроизводимый wrapper над харнессом #134,
  SQLite-backup, resumable reindex и расчёт статистик.
- `data/bench364/` — некоммитящиеся model/DB/log artifacts на реальном диске, не `/tmp`.
- `app/rag.py`, `SCHEMA_VERSION` и продовый индекс не менялись. Внедрение не выполнялось.

## Review

**Luna, 2 раунда — APPROVED.** Round 1 подтвердил числа и scoped-вердикт, но нашёл
blocking safety gap: `--resume` допускал один файл как source и candidate. Wrapper исправлен:
exact path, symlink и hardlink aliases отвергаются до writable open. Также добавлены строгая
идентичность 28 paired rows/provenance hashes и pin baseline ONNX. Round 2 отметил все четыре
findings как `FIXED`, новых блокеров нет; evidence quote дословно найден в этом отчёте.
Полный артефакт: `docs/tasks/364/review-research.md`.
