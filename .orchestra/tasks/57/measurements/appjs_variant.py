"""#57 — вариант app.js «сколько стоит принудительная раскладка на каждое сообщение».

Ничего в репозитории не меняется: исходник читается, преобразуется В ПАМЯТИ и отдаётся
браузеру через route-перехват. Это симуляция точечной правки, чтобы поставить в таблицу
измеренную цену, а не оценку на глаз.

Что меняется — ровно три вещи, все в горячем пути вставки сообщения:
  1. `chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80` (9 копий в addChatEntry)
     и то же выражение в `_chatAtBottom` — читаются через кеш, обновляемый раз в кадр;
  2. `chat.scrollTop = chat.scrollHeight` в тех же 9 местах — сводится к одному вызову за кадр.
Чтение геометрии сразу после вставки узла заставляет браузер считать раскладку синхронно,
и так на каждое сообщение — здесь это делается раз в кадр.
"""
import pathlib

SRC = pathlib.Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-front"
                   "/app/static/js/app.js")

HELPERS = """
let __wabV = null, __scrollRaf = 0;
function __wabCached(chat) {
  if (__wabV === null) {
    __wabV = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    requestAnimationFrame(() => { __wabV = null; });
  }
  return __wabV;
}
function __scrollSoon(chat) {
  if (__scrollRaf) return;
  __scrollRaf = requestAnimationFrame(() => { __scrollRaf = 0; chat.scrollTop = chat.scrollHeight; });
}
"""

READ = "const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;"
WRITE = "if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;"
AT_BOTTOM = "return !chat || chat.scrollHeight - chat.scrollTop - chat.clientHeight < _CHAT_BOTTOM_GAP;"


def build():
    src = SRC.read_text()
    n_read = src.count(READ)
    n_write = src.count(WRITE)
    n_bottom = src.count(AT_BOTTOM)
    if n_read < 5 or n_write < 5 or n_bottom != 1:
        raise SystemExit(f"исходник не тот: read={n_read} write={n_write} bottom={n_bottom}")
    src = src.replace(READ, "const wasAtBottom = __wabCached(chat);")
    src = src.replace(WRITE, "if (!anchor && !_insertedBeforeStream && wasAtBottom) __scrollSoon(chat);")
    src = src.replace(AT_BOTTOM, "return !chat || __wabCached(chat);")
    return HELPERS + src, {"read": n_read, "write": n_write, "bottom": n_bottom}


if __name__ == "__main__":
    body, counts = build()
    print(counts, len(body))
