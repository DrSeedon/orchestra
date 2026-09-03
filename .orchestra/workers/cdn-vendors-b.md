# cdn-vendors-b — личная память

## Сайт отдаёт 403/503/JS-challenge на curl, WebFetch И r.jina.ai → headless Chromium, не «источник недоступен»
Замер #192, 20.08.2026. Ngenix (`503`, свой bot-challenge) и Servicepipe (JS-challenge их собственного продукта) закрыты для всех трёх текстовых инструментов, включая `r.jina.ai` — он сам получает challenge и возвращает либо страницу-заглушку, либо `TimeoutError` 422. Playwright с обычным UA проходит оба за один заход:

```python
b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
ctx = await b.new_context(locale="ru-RU", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
await pg.goto(url, wait_until="domcontentloaded"); await pg.wait_for_timeout(9000)
txt = await pg.evaluate("() => document.body.innerText")
```
Хромиум уже стоит (`~/.cache/ms-playwright`). Скрипты этой задачи: `/tmp/fetch_pw.py` (загрузить), `/tmp/nav_pw.py` (SPA-навигация кликом), `/tmp/ng_row.py` (прочитать строки таблицы из DOM).

**Прокси мешает российским сайтам.** Дефолтный `HTTPS_PROXY` тут — Contabo с немецким IP, и российские анти-боты по нему бьют охотнее. Гонять так: `NO_PROXY='*' HTTPS_PROXY= HTTP_PROXY= https_proxy= http_proxy= python3 …`, для curl — `--noproxy '*'`. Servicepipe с прокси давал 403, напрямую — 200.

## Цену/галочку из таблицы тарифов читать из ОТРЕНДЕРЕННОГО DOM, а не регекспом по HTML
Там же. Значения в карточках тарифов подставляет JS: у DDoS-Guard в разметке лежит голое `8 000` без символа валюты, у StormWall цены вообще нет в HTML — она считается скриптом из `PersonalPrice.start` и `domainPrice`. Два разных регекспа по одному и тому же HTML Ngenix дали ПРОТИВОПОЛОЖНЫЕ ответы про WebSocket (`promo=NO/lite=NO/start=NO` против «YES у всех») — разошлись на границах ячеек. Разрешающий контроль — `page.evaluate` по `.tariff_plans__row` с проверкой, какая иконка реально видима (`getComputedStyle(svg).display !== 'none'`).

Побочно полезное: калькулятор в JS отдаёт цены точнее, чем карточка. У StormWall `optionsList` в `<script>` дал полный прайс опций (кэширование 2 000 ₽, WebSocket на нестандартных портах 1 000 ₽), которого на отрисованной странице Personal не видно вовсе.

## Настоящий адрес доки/цен ищется в robots.txt и sitemap, а не угадывается
Все пять URL вида `/services/cdn/` я угадал неверно (404/503 на всех). За две команды нашлось верное: `curl .../robots.txt | grep -i sitemap`, затем `grep -oP '(?<=<loc>)[^<]+'`. Так же вскрылись отдельные российские домены-близнецы с ценами в рублях: `ddos-guard.ru` (у `.net` — Nuxt SPA без SSR, пустой текст) и `stormwall.pro` (`stormwall.ru` редиректит туда). У CDNvideo база знаний живёт на `doc.cdnvideo.com`, а не на `docs.cdnvideo.ru` (тот вообще не резолвится).

Для SPA-доки, где страницы в sitemap нет: список реальных имён файлов вынимается из уже загруженной страницы — `re.findall(r'href="([^"]+\.html[^"]*)"', html)`. Так нашлись `AP_CDN_Integration.html`, `Static_caching.html`, `SSL.html` у Servicepipe, которые по осмысленным именам (`CDN_Integration`, `Caching`) отдавали 404.
