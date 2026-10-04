# V-688 — видео в dashboard и тяжёлые GIF

Распознавание MP4, WebM и MOV добавлено в чатовые media previews, карточки `send_file`/`send_files`, результаты чтения файлов и просмотр файлов. Превью создаётся как `<video muted playsinline preload="metadata">`, остаётся на паузе и открывает общий lightbox по клику. Lightbox показывает `<video controls>` без `muted`, закрывается по Escape и клику на фон; при закрытии очищает `src`. Просмотр файла в файловом браузере показывает тот же браузерный `<video controls>` в модальном окне. Изображения продолжают открываться как `<img>`.

## GIF: причина и замер

На коммите V-686 `dc881f5e` взят именно `.orchestra/tasks/V-686/media/dashboard-live.gif`: 4,544,124 байта, 880×417, 329 кадров с длительностью кадра 130 мс. До изменения карточки `send_file` и результат чтения файла запрашивали полный GIF с `t=Date.now()`: перерисовка меняла URL, а исходный `FileResponse` не выставлял Cache-Control. Это каждый раз отправляло и декодировало все 329 кадров, хотя для карточки достаточно постера.

Существующий `_render_image_preview` на том же файле за 309.4 мс на холодном процессе создал WebP первого кадра 640×303 размером 12,974 байта — в 350 раз меньше оригинала. Превью-карточки теперь используют `preview=640` со стабильным URL; для открытия анимации lightbox запрашивает оригинал. Ответы preview и исходных медиа получают `Cache-Control: no-cache`, ETag и Last-Modified. В установленной Starlette 1.1.0 `FileResponse` выставляет валидаторы, но не делает conditional GET: это подтвердил просмотр `FileResponse.__call__` и HTTP-пробник. `/api/files/raw` теперь сам отвечает 304 при совпавшем If-None-Match (или актуальном If-Modified-Since), а при изменении файла со старым ETag отдаёт 200 с новым телом.

## Проверки

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_frontend.py::test_raw_video_supports_range_and_full_download tests/test_frontend.py::test_raw_image_preview_is_bounded_webp_and_original_stays_untouched tests/test_frontend.py::test_raw_html_response_has_sandbox_csp tests/test_frontend.py::test_raw_non_html_response_has_no_artifact_csp -q`: 5 passed. HTTP-тест проверяет диапазон `bytes=10-19` → 206, точный `Content-Range` и тело, полный запрос без Range → 200 и всё тело, повтор с ETag и Last-Modified → 304 без тела, запись нового содержимого по тому же пути со старым ETag → 200 и новый файл. Такой же 304/перезапись проверяются для WebP-preview.
- Playwright/Chromium на изолированном стенде из `git archive` с overlay проверяемого кода: отдельная temp-БД и хранилище задач, `env -i`, временный HOME, без `.env`, без TG/LLM-переменных, PATH содержит только временную директорию с Git, порт 18997. Вызов из UI открыл MP4 H.264/AAC длительностью 36.1 с. Браузер проиграл его при `muted=false`, перемотал и подтвердил позицию 3.0 с; реальные запросы к endpoint вернули 206 и `Content-Range`. PNG открылся в прежнем image lightbox, GIF preview загрузился как WebP, Escape закрыл оба lightbox. Dashboard держит SSE, поэтому ожидание `networkidle` не завершается; проверка использовала DOM-ready и ожидания элементов.
- Скриншот настоящего плеера: [video-player.png](video-player.png).
- `node --check app/static/js/app.js` и `node --check app/static/js/chat.js` прошли.

`FileResponse` Starlette 1.1.0 реализует Range, но не условный 304; маршрут сохранил Range и добавил условную валидацию. `system.py` изменён для `Cache-Control: no-cache`, поэтому активному процессу dashboard нужен рестарт, чтобы загрузить заголовки и 304-валидацию. Живой Orchestra и порт 8888 не запускались и не перезапускались.
