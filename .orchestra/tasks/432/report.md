# #432 — результат замера context scout

## Ограничения этого прогона — читать до цифр

- **Кластеров задач 2, не 3**: пары пришли из задач [364, 396].
  Кластерный бутстрап пересэмплирует ЗАДАЧИ, поэтому при 2 кластерах интервал
  [`$0.06583`, `$0.13642`] узок артефактно и как доказательство не годится.
- Знаменатель бюджетный, а не выбранный: 21 из 24 триад
  не запускались (потолок пула Codex), обрезан хвост заранее замороженного порядка.
- **Качество не измерено:** обе руки дали 0 успехов по hidden oracle на всех измеренных парах, то есть сравнивались два способа провалиться. Вопрос «окупается ли разведка по РЕЗУЛЬТАТУ» этим прогоном не отвечен — отвечена только ЦЕНА.
- Попарно:
  - task 364 r1 (BABA): A=`$0.10830` model_failure · B=`$0.16401` model_failure · B/A=1.514
  - task 364 r2 (BABA): A=`$0.12220` model_failure · B=`$0.13470` model_failure · B/A=1.102
  - task 396 r1 (ABAB): A=`$0.07447` model_failure · B=`$0.10739` model_failure · B/A=1.442


Статус: **INCOMPLETE**. Числовой вывод: **эффекта сверх собственного шума не обнаружено**.

## Счёт

- Правило подсчёта дословно: `Count one main pair for each frozen task×repetition with exactly one completed A slot and completed B_scout and B_main slots; 12 tasks × 2 repetitions = 24 pairs. An inconclusive attempt is counted only in inconclusive_attempts and is never substituted for or added to its later completed slot.`
- Слотов: 100 запланировано, 25 завершено; main-пар: 3 (A=inline, B=scout+main).
- Знаменатель фактический против планового: измерено **3** пар из 24 плановых; 21 триад обрезано потолком пула Codex и ОТБРОШЕНО целиком (правило остановки 4), а не засчитано провалом.
- Полная цена A: `$0.30497376` API-equivalent USD.
- Полная цена B = scout + main: `$0.40609976` API-equivalent USD.
- Разница B−A: `$0.10112600`; парный кластерный 90% CI: [`$0.06583400`, `$0.13641800`].
- Успешные hidden-oracle исходы A/B: 0/0; разница B−A 0, 90% CI [0, 0].

## Собственный шум

A/A: median relative cost noise `0.190564`, p90 `0.536814`. Paired median saving `-0.441991`. Разница меньше шума трактуется как отсутствие эффекта.

## Проверки и сбои

- Одинаковый hidden oracle и команда сравниваются внутри каждой пары.
- availability_failure: 0; harness_failure: 0; model_failure: 6.
- inconclusive попыток после provider start: 1; они переиграны и не добавлены в main denominator.
- production sessions: 502 → 504.
- Сырые построчные данные: `scripts/recon429/run-g3-resumable/raw-slots.jsonl`, SHA-256 `2be969900a5589e88acb36f4226d147ad9c7469f23a563f0d4ea7f6266981562`.

## Граница применимости

Результат относится к замороженным 12 repository-local задачам Orchestra и всему пакету `scout + handoff`; он не переносится на live SQLite/API/web/visual/user-input задачи без отдельного замера.
