# #364 — исследование GigaEmbeddings 480M на retrieval-корпусе Orchestra

## Вопрос

- **Контекст:** продовый `search_memory` использует bge-m3 int8 ONNX, 1024d, CLS,
  без префиксов, и hybrid RRF.
- **Change under test:** заменить только векторное представление на
  `ai-sage/Giga-Embeddings-instruct-480M-0826`, соблюдая её собственный pooling/prompt.
- **Baseline:** MRR 0.4893, R@3 64%, R@5 75% на замороженном корпусе и 28 запросах #134.
- **Измеримый исход:** MRR/R@3/R@5, парный t по per-query RR и сравнение |ΔMRR| с
  split-half шумом baseline, 20 000 повторов. Победа кандидата требует положительного
  Δ, |t| > 2.052 и Δ выше медианного собственного шума; критерий задан до прогона.

## Гипотезы и фальсификаторы

| гипотеза | что её опровергает | результат |
|---|---|---|
| H1: русскоязычная GigaEmbeddings улучшит retrieval нашего русского техкорпуса | ΔMRR ≤ 0 либо Δ не выходит за шум/парный t | **REFUTED на этом стенде**: Δ −0.0167, t −0.334, шум 0.1048 |
| H2: на frozen n=28 наблюдаемая разница останется внутри собственного шума ≈0.10 MRR | |ΔMRR| > шум и |t| > 2.052 | **CONFIRMED только для этого сравнения**: |Δ| 0.0167, в 6.3 раза меньше шума |
| H3: GigaEmbeddings заметно ухудшит retrieval | отрицательный Δ выходит за шум и |t| > 2.052 | **REFUTED**: знак отрицательный, но величина статистически неразличима |

## Findings

1. **Baseline воспроизведён точно — CONFIRMED (tier 1, direct measurement).**
   MRR 0.4892857143, R@3 0.6428571429, R@5 0.75 на snapshot
   `92808d6b…35ab2` и queries `516b0755…bd0a` [1].
2. **GigaEmbeddings на том же полном retrieval-пути дала MRR 0.4726190476,
   R@3 0.6071428571, R@5 0.75 — CONFIRMED (tier 1).** ΔMRR −0.0166666667,
   paired t −0.3338243239, df=27 [1].
3. **Стенд не различает эти два результата — CONFIRMED для фиксированной выборки (tier 1).**
   Split-half baseline, 20 000 повторов: median 0.1047619048, p90 0.2476190476,
   p95 0.2952380952. Контроль полностью совпал с #135; |Δ| меньше median noise в 6.3 раза [1][2].
4. **Решение «не менять» — CONFIRMED условиями заранее заданного gate.** Кандидат не
   показал положительного эффекта выше шума и не приблизился к t-порогу; утверждение
   «Giga хуже вообще» из этих данных не следует [1].
5. **Mean pooling, L2 и query-only instruction взяты из модели, а не угаданы — CONFIRMED
   (tier 2, primary sources).** README и Pooling config ревизии `2d0c1a9…` совпадают:
   1024d, mean, normalize, raw documents, instructed queries [3][4].

## Counter-evidence и ограничения

- Giga улучшила RR на 5 отдельных запросах, ухудшила на 7, не изменила на 16 [1].
  Это не поддерживает однонаправленную историю ни о победе, ни о провале модели.
- Свежий backup текущего `vec.db` не годится для неизменяемой выборки: три gold chunk_id
  уже отсутствуют. Поэтому вывод относится к pinned corpus #134, а не доказывает качество
  на будущем составе индекса.
- Публичный checkpoint BF16 исполнялся в FP16 из-за GTX 1650 compute capability 7.5;
  pooling/L2 выполнялись в FP32. Это снижает уверенность в переносе точных рангов на BF16 GPU,
  но наблюдаемая Δ в 6.3 раза меньше разрешения стенда.
- Значение ruMTEB 70.98 и лидерство среди <500M опубликованы самой карточкой модели [3];
  этот self-reported benchmark не использован как доказательство на нашем корпусе.

## Затронутые файлы, риски, edge cases

- Добавлены только task artifacts и одна строка в тематическую KB; production code не менялся.
- Смена модели потребовала бы `SCHEMA_VERSION` bump и полного rebuild, но это явно вне #364.
- Главный риск интерпретации — назвать отрицательный знак «ухудшением». Правильный вывод:
  разница неразличима при n=28 и шуме 0.1048.

## Sources

1. `docs/tasks/364/bench/results.json` — direct measurement: per-query RR, summaries,
   hashes, paired t, split-half 20 000.
2. `docs/tasks/135/research.md` §6 — исходный контроль split-half: 0.1048 / 0.2476 / 0.2952.
3. [Hugging Face model card, pinned revision](https://huggingface.co/ai-sage/Giga-Embeddings-instruct-480M-0826/blob/2d0c1a92716eef0e5b6972df85b5883eb5b4f57a/README.md).
4. [Hugging Face pooling config, pinned revision](https://huggingface.co/ai-sage/Giga-Embeddings-instruct-480M-0826/blob/2d0c1a92716eef0e5b6972df85b5883eb5b4f57a/1_Pooling/config.json).
