# V-1226 — индекс источников unslop

Сторонний текст сюда не скопирован: только адреса, хэши и наш пересказ. Скрипты не запускались,
skill не устанавливался, MCP не подключался. Тексты SKILL/README прочитаны как данные.

## Закрепление

| Что | Значение |
|---|---|
| Репозиторий | https://github.com/heydamir/unslop |
| Закреплённый commit (HEAD `main` на 2026-11-02) | `a6f121eee5f29c2f74976b75456feae8b66afb3a` (2026-11-01T16:46:09Z) |
| Как получен SHA | `https://github.com/heydamir/unslop/commits/main.atom` → HTTP 200, первый `<entry>`; REST API отказал (rate limit, без токена — по правилам задачи) |
| Архив | `https://codeload.github.com/heydamir/unslop/tar.gz/a6f121eee5f29c2f74976b75456feae8b66afb3a` → HTTP 200, 1 437 916 байт |
| sha256 архива | `3c7d9812acc6fe6b3b581826d6cdd4176e315416c6f7e5ab805c9ade332a8450` |
| Файлов в архиве | 21 |
| Сырые данные (приватно, на хабе, вне worktree, не коммитятся) | `/tmp/v1226-src/` (архив, распаковка `x/`, `commits.atom`, `cc-by-4.0.txt`) |

## Файлы на закреплённом commit (байты)

| Путь | Байт | Прочитан |
|---|---|---|
| `skills/unslop/SKILL.md` | 31 327 | целиком |
| `skills/unslop/references/signs.md` | 7 038 | целиком |
| `skills/unslop/references/tokens.md` | 6 494 | целиком |
| `skills/unslop/references/refs.md` | 2 458 | целиком |
| `skills/unslop/references/visuals.md` | 8 306 | целиком |
| `skills/unslop/references/effects.md` | 4 864 | начало (glyph-эффект; к дашборду не относится) |
| `skills/unslop/scripts/snapshot.mjs` | 6 503 | статически: Playwright + системный Chrome, `fetch` ресурсов страницы для инлайна. НЕ запускался |
| `skills/unslop/scripts/story.mjs` | 23 209 | статически: локальный http-сервер, Playwright, `execFileSync("ffmpeg")`. НЕ запускался |
| `skills/unslop/agents/openai.yaml` | 196 | целиком (метаданные для Codex) |
| `examples/dashboard.html`, `examples/hero.html` | 12 074 / 5 091 | не открывались в браузере |
| `references/refs/*.webp` (5 шт.) | — | не просматривались: правила/примеры важнее картинок для этого вывода |
| `LICENSE` | 18 657 | сверен с эталоном |
| `CITATION.cff`, `README.md` | 546 / 3 572 | целиком |

## Лицензия именно этого commit

- `LICENSE` = текст CC BY 4.0 legalcode. Проверка: `https://creativecommons.org/licenses/by/4.0/legalcode.txt`
  (HTTP 200) совпадает с файлом после нормализации пробелов (`diff` пуст). sha256 LICENSE
  `9ba9550ad48438d0836ddab3da480b3b69ffa0aac7b7878b5a0039e7ab429411`.
- Тот же ярлык в `SKILL.md` frontmatter (`license: CC-BY-4.0`) и `CITATION.cff`.
- Условие NonCommercial отсутствует: README прямо разрешает коммерческое использование при указании автора.
- Требования при копии/адаптации (CC BY 4.0 §3(a)): имя автора (Damir Sokolovsky, @heydamir),
  ссылка на лицензию, ссылка на источник, пометка об изменениях. Автор дополнительно просит
  сохранять кредит в копиях и (для story-видео) подпись `unslop by @heydamir`.
- Для чистого пересказа идей (без копирования текста) лицензия авторского права обычно не
  требуется, но атрибуция ниже — дешёвая и честная. Юридическую оценку я не даю.

Шаблон атрибуции, если какой-то фрагмент будет адаптирован в наш skill:
`Адаптировано по unslop, Damir Sokolovsky (@heydamir), https://github.com/heydamir/unslop
@a6f121e, CC BY 4.0 https://creativecommons.org/licenses/by/4.0/ — изменено: <что>.`
