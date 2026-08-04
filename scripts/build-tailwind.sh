#!/usr/bin/env bash
# Собрать статический CSS вместо Play-CDN Tailwind (#57/#64).
#
# Запускать после того, как в шаблонах или JS появились НОВЫЕ классы Tailwind:
#   bash scripts/build-tailwind.sh
# Результат — app/static/css/vendor/tailwind.css, он коммитится.
#
# Забыть запуск не страшно: tests/test_tailwind_css.py падает, если в исходниках есть
# класс, которого нет в собранном CSS.
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes tailwindcss@3.4.17 \
  -c tailwind.config.js \
  -i app/static/css/tailwind.src.css \
  -o app/static/css/vendor/tailwind.css \
  --minify
