---
name: html-artifacts
description: Генерация интерактивных HTML артефактов вместо markdown
---

# HTML Artifacts

Генерируй `.html` файлы когда контент выигрывает от layout, цвета, диаграмм, интерактивности.

## Когда делать HTML
- Сравнение 2+ вариантов — side-by-side
- Диаграммы, flowcharts, архитектурные схемы
- Дашборды, метрики, статусы
- Отчёты >100 строк
- Всё что юзер будет шарить или перечитывать

## Когда НЕ делать
- Короткие ответы, код, команды терминала
- Одноразовые саммари

## Правила
1. **Один файл .html** — CSS в `<style>`, JS в `<script>`, SVG inline
2. **Работает offline** — CDN только для Chart.js если нужны графики
3. **Системные шрифты** — `system-ui, sans-serif`
4. **Dark-first** — `prefers-color-scheme` для light mode
5. **Responsive** — `<meta name="viewport">`
6. **Readable за 5 сек** — заголовок, TL;DR, потом суть

## CSS база
```css
:root {
  --bg: #0e0e12; --surface: #16161c; --surface-2: #1c1c24;
  --border: #2a2a32; --ink: #f1f1f4; --ink-soft: #a8a8b3;
  --accent: #7c3aed; --ok: #22c55e; --warn: #f59e0b; --danger: #ef4444;
  --sans: system-ui, -apple-system, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #fafaf7; --surface: #fff; --border: #e7e5df; --ink: #1a1a1f; --ink-soft: #555; }
}
```

## Куда сохранять
1. `artifacts/` в корне проекта
2. `docs/artifacts/` если есть `docs/`

## После сохранения
1. Сказать путь
2. `xdg-open <file>` (Linux)
3. В Orchestra: `send_file(path, caption)` в Telegram

## Анти-паттерны (НИКОГДА)
- Cards с тенями на сером фоне
- Gradient hero section
- Emoji как заголовки секций
- Glass morphism, frosted blur
- Generic Tailwind aesthetic

## SVG правила
- `viewBox`, не фиксированные width/height
- `currentColor` для адаптации к теме
- `<text>` не paths — копируемый текст
- Arrow markers через `<defs><marker>`
