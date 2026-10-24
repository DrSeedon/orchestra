# Сохранённые лицензии и атрибуция стороннего кода

Это сводка исследователя, не upstream-файл NOTICE. Исходные заголовки и
атрибуция в перечисленных Rapid-файлах сохранены без изменений.

| Скопированный материал | Первичный источник | Сохранённые лицензия / сведения |
|---|---|---|
| `rapid-0.0.11-main.py`, `rapid-0.0.11-utils-preprocess.py`, `rapid-0.0.11-utils-infer_engine.py`, `rapid-0.0.11-config.yaml` | Wheel [rapid-orientation 0.0.11](https://pypi.org/project/rapid-orientation/0.0.11/) | [LICENSE из wheel](licenses/rapid-0.0.11-LICENSE), [исходный METADATA header](licenses/rapid-0.0.11-METADATA-header.txt), включая Apache-2.0 и автора SWHL. Все четыре файла проверены на полное совпадение байтов с wheel |
| `rapid-main.py`, `rapid-readme.md` | [RapidAI/RapidOrientation](https://github.com/RapidAI/RapidOrientation), точные URL и хеши исходных снимков в `manifest.json` рядом | [LICENSE репозитория](licenses/RapidOrientation-LICENSE), Apache-2.0. Заголовки автора SWHL и ссылка на PaddleClas внутри preprocess-кода не удалены |

Wheel SHA256: `3d69e77c18ac05a3e9a157e9a26ecff49e8ef485913eaa57b0921b0419684be6`.
В wheel найден `rapid_orientation-0.0.11.dist-info/licenses/LICENSE`;
отдельный NOTICE среди его файлов не найден. Проверенный
`https://raw.githubusercontent.com/RapidAI/RapidOrientation/main/NOTICE` вернул
404. Поэтому вымышленный upstream NOTICE не добавлялся; настоящие исходные
заголовки, комментарии атрибуции и полный LICENSE оставлены вместе с копиями.
URL, archive members, SHA256 и дата сверки — [license manifest](licenses/manifest.json),
дословный вывод — [license source stdout](../logs/license-sources-stdout.txt).

Сведения о лицензиях кода других изученных движков:

| Проект | Первичный источник лицензии кода | Сохранённый текст |
|---|---|---|
| PaddleOCR | [Корневой LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE): Apache-2.0 | [PaddleOCR-LICENSE](licenses/PaddleOCR-LICENSE) |
| Tesseract | [Корневой LICENSE](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE): Apache-2.0 | [Tesseract-LICENSE](licenses/Tesseract-LICENSE) |

Эта проверка фиксирует лицензии указанных проектов/копий кода. Она не присваивает
Apache-2.0 всему содержимому `sources/`: документация API, страницы моделей,
ценовые таблицы и иные веб-источники используются как доказательства с указанием
URL; их собственные условия не заменяются лицензиями OCR-движков. Названия
лицензий библиотек также не устанавливают лицензию любых отдельных весов или
их зависимостей. Другие пакеты и модели в этом дополнении не устанавливались.
