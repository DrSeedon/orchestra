# V-1091: неочевидные факты для root

- Pinned upstream HEAD: `a2735a3eaf092eaaffb6dc17df25de33ef3bd048`, 2026-10-26T00:14:04Z; содержит именно свежую переработку motion/content и встроенный taste-skill MIT notice. Не переносить выводы на старое видео без установления его версии.
- В landing folder только один Markdown. Никаких скрытых bundled references/assets, скриптов, token config или runnable scaffold дерево не содержит. Tailwind/Framer/font/icon имена не означают установленную зависимость.
- Scope охватывает dashboards/components/reviews, хотя название landing-page-design. Отдельного runtime enforcement нет.
- Обязательный tagline: A2 допускает after hero, B11 запрещает directly under hero; слова допускают rAF-throttled scroll, checklist формулирует IO-only. Hover color конфликтует с animate-only transform/opacity. Эти расхождения не исправлялись.
- Реалистичные invented names/metrics не имеют provenance gate или обязанности помечать вымысел. Не путать эту норму с доказанными отзывами/результатами.
- `No attribution needed` в README не отменяет явно сохранённые MIT notice conditions для копий/существенных частей самого материала.
- MP4/GIF путь относится к соседнему design-to-motion, не landing. Из него рассмотрены только контекст, ingestion/fidelity и export. Figma PAT/API — условный путь по Figma input, flat screenshot допускается с ограничениями. Ни model generation, ни upload в X не предписаны.
- Современная official docs страница навыков доступна через redirect на learn.chatgpt.com; источники сохранены со SHA. Указание README вставлять SKILL в AGENTS описывает rules injection, не native folder discovery. Никакой установки не было.
- Core AGENTS здесь16356 B, strict <16384 оставляет27 B; L18801 B. Гипотетическая простая конкатенация35157 B. Ничего в core не дописано.
- В hub copy нет CLAUDE.md. Это зафиксировано, не чинится в research scope и не переносится как утверждение о root checkout.
- Native html-artifacts, исходное видео/пост, redesign companion, upstream credit repos не прочитаны. V-1090 не исследовался. Для сравнения есть report tables, comparison.tsv и source-manifest.json.
