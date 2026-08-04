/** Конфиг Tailwind для статической сборки CSS.
 *
 *  Раньше эти же настройки лежали инлайном в dashboard.html и применялись Play-CDN
 *  сборщиком прямо в браузере: 407 КБ компилятора работали на каждой загрузке, чтобы
 *  получить 16 КБ правил (#57: 366 мс главного потока, 39% работы до первой строки чата).
 *  Теперь CSS собирается один раз — `bash scripts/build-tailwind.sh`.
 *
 *  ВАЖНО: сборщик ищет классы по тексту исходников из `content`. Класс, собранный в
 *  рантайме из кусков (`'text-' + color`), сюда не попадёт — таких в проекте нет
 *  (проверено), и появляться им нельзя: пишите классы целиком. Забытый класс ловит
 *  tests/test_tailwind_css.py.
 */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/static/js/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      // Подняты бледные оттенки: на фоне #0a0e17 стандартные не проходят WCAG AA
      colors: { slate: {
        400: '#a6b3c6',
        500: '#8595ab',
        600: '#6b7c93',
      } },
    },
  },
};
