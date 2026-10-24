# Метод и журнал ограничений V-1070

Дата сверки источников: 24.10.2026 UTC. Исследователь один; дополнительных работников,
CLI провайдеров и запросов inference нет. Сетевые GET — только публичная документация,
репозитории, каталог OpenRouter и пакеты исследовательской зависимости. Боевые данные не читались.

## Воспроизведение

В корне выданной копии выполнены команды ниже. Их stdout/stderr сохранены дословно
в указанных файлах; Python experiments завершились exit 0. PATH всегда указывает на
provisioned uv 0.11.28. Настоящий импортированный app записан в `logs/runner.txt` и
`logs/boundary-probe-stdout.txt`, публичный отчёт не содержит абсолютного пути стенда.

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
uv --version
uv run --frozen python -c 'import app, PIL, sys; print("app:", app.__file__); print("python:", sys.version); print("pillow:", PIL.__version__)'
uv run --frozen python .orchestra/tasks/V-1070/collect.py
uv pip install --python .venv/bin/python --target .orchestra/tasks/V-1070/deps 'rapid-orientation==0.0.11'
nice -n 15 uv run --frozen python .orchestra/tasks/V-1070/experiment.py
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 nice -n 15 uv run --frozen python .orchestra/tasks/V-1070/rapid_experiment.py
uv run --frozen python .orchestra/tasks/V-1070/boundary_probe.py
TMPDIR="$PWD/.orchestra/tasks/V-1070/tmp" PYTHONDONTWRITEBYTECODE=1 nice -n 15 uv run --frozen python -m pytest tests/test_harness_vision.py -q --basetemp=.orchestra/tasks/V-1070/tmp/pytest -o cache_dir=.orchestra/tasks/V-1070/tmp/pytest-cache
```

Соответствие командам: `runner.txt`, `collect-stdout.txt`, `rapid-setup.txt`,
`experiment-stdout.txt`, `rapid-experiment-stdout.txt`, `boundary-probe-stdout.txt`,
`pytest-stdout.txt` в `logs/`. `source-followup-stdout.txt` — дополнительные GET через
`collect.fetch` на официальные Markdown-страницы и публичный каталог; URL/ошибки/хеши
есть в `sources/manifest.json`. Anthropic/OpenRouter отклонили прямой urllib GET с 403;
их страницы прочитаны web-инструментом, его дословный ответ — `sources/web-evidence.json`.
OpenAI Markdown получен напрямую; HTML-дубликаты удалены для компактности.

`reproduce.sh` воспроизводит локальные опыты и тесты с сохранёнными публичными источниками;
исследовательские версии зафиксированы отдельно в `requirements-research.txt`.
Сборка package environment — подготовка с доступом к PyPI, сами опыты и тесты offline.
Система/Python продукта/uv.lock не менялись; экспериментальные пакеты были в `deps/`
этой задачи и удалены после измерений. Исходные библиотеки из locked `.venv` не заменены.
Синтетический корпус — наша генерация Pillow 11.3.0, classifier — изолированный Pillow
12.3.0 и ONNX Runtime CPU. Параметры задаются `rapid-experiment.yaml`: intra/inter=1;
OMP/OpenBLAS=1. OpenCV отдельно не ограничивали. Все тяжёлые операции последовательны,
nice=15; RSS процессов измерен, cgroup/MemoryMax не менялся и не проверялся.

## Семантическое чтение

Сначала исследователь открыл через `view_image(detail=original)` три compact-листа,
затем half-листы и оригиналы №1/5/9, затем full-листы; отдельно повёрнутый №9,
EXIF-нормализованный №9 и WebP №9. После уменьшения высоты цифрового бейджа повторно
просмотрены окончательные half/full-листы: бейдж больше не пересекает заголовок.
Изменение не касалось выбранных полей. Compact до изменения уже не имел пересечения.

Эталон известен автору генератора: оценка НЕ слепая. Три семейства макетов с четырьмя
почти одинаковыми вариантами не равны 12 независимым реальным скриншотам. Обзор
оценён для 12 элементов, три точных поля — только для представителей №1/5/9.
В `semantic-observations.json` сохранены принятые чтения и отказы от точного ID;
полный эталон для сторонней проверки — `ground-truth.json`. Отказ означает
«исследователь не берётся отличить O/0/I/1 в этом размере», а не доказанную
неспособность любой модели прочитать строку. Ни Claude, ни Luna, ни новый Sol/Astra
в качестве оценщика не вызывались. Это не измерение их accuracy или billed usage.

## Неочевидное, обнаруженное по ходу

Первый classifier-прогон неверно сопоставил метку с физическим CCW-поворотом.
Его дословный stdout оставлен как `logs/rapid-initial-convention-stdout.txt`.
Все шесть «ошибок» были взаимной перестановкой 90/270. Финальный критерий —
np.rot90(input, returned_angle/90) совпадает с исходными пикселями. По этому
критерию 12/12 верны, и метка является CCW-коррекцией. Это исправление протокола,
не улучшение модели и не результат 6/12 accuracy. Семантически №9 с CCW90 также
осмотрен; направление чтения восстановленного EXIF-изображения проверено.

В wheel 0.0.11 три входа — один и тот же center crop, не три случайных ракурса:
проверено np.array_equal для всех 12 cases. Публичный callable не возвращает
confidence. Для исследования top score и margin извлечены из уже существующего
выхода того же ONNX, без нового оценщика/softmax; суммы ≈1. Это не калибровка.
Совпадение этих весов с текущим PaddleOCR PP-LCNet_x1_0_doc_ori НЕ установлено;
wheel README ссылается на более ранний PaddleClas classifier. Хеш модели и
дословные исходники wheel сохранены, бинарный файл не включён в результат.

CPU numbers — один проход, без прогрева для encoder, три вызова на ориентацию
после одной инициализации для classifier. Это стоимость в данном удалённом
стенде, не benchmark VPS/ноутбука. Версии/байты/RSS воспроизводимы; время шумит.
Доля образов в пользовательской активности неизвестна: приватные журналы,
истории и screenshots не выгружались даже для построения выборки.

## Узкое дополнение перед приёмкой

По замечанию root уточнено: scope/publication guard в hub-строке — намерение
кода, не гарантия отсутствия ПД или приватных данных организации в автоматически
добавляемых корневых файлах. Это общая граница вывода; приватные файлы, реальные
пути и обстоятельства отдельного случая не изучались и сюда не переносились.

Для проверки лицензий выполнено только получение публичных текстов/метаданных:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 uv run --frozen python .orchestra/tasks/V-1070/license_sources.py
```

Дословный stdout: `logs/license-sources-stdout.txt`. Без установки прочитан
wheel именно rapid-orientation 0.0.11, сверён его PyPI SHA256, извлечены полный
LICENSE и исходный metadata header; проверено побайтовое совпадение четырёх
сохранённых файлов с wheel. Первичные лицензии PaddleOCR/Tesseract сохранены
отдельно. URL/хеши — `sources/licenses/manifest.json`; атрибуция и границы
лицензионного вывода — `sources/THIRD_PARTY_NOTICES.md`. Новых inference и опытов
не было; исходные численные результаты и runner/boundary-логи не менялись.
