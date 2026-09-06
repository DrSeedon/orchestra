"""Маскирование значений секретов — единственный владелец правила (#224).

Зовётся с ДВУХ швов выдачи, и это не дублирование, а два разных канала:
`db.add_log` (единственный INSERT в `logs`) и `live_broker.publish` (эфемерный SSE,
который в БД не пишется вовсе). Маскирование на одном оставляет второй открытым.

Границу значения задаёт ФОРМА (кавычки/пробел), а НЕ класс символов: URL, DSN и cookie
содержат `:` `@` `?` `&` `=` `;` `%`, а base64 кончается на `=` — по алфавиту ключа они
маскировались бы частично или никак.
"""

import re

# Bearer/Basic и PEM уже описаны в runtime_history (leaf-модуль, ничего из app не тянет).
# Переиспользуем ПАТТЕРНЫ, а не функцию: замена у нас своя, с длиной и хвостом.
from app.runtime_history import _AUTH_VALUE, _PEM_PRIVATE_KEY

_MIN_LEN = 12          # короче — не трогаем: шум забьёт журнал
_TAIL_FROM = 16        # хвост отдаём только когда 4 символа — малая доля значения

# ЕДИНСТВЕННЫЙ список имён. И регулярка, и быстрый предфильтр строятся из него —
# держать их двумя списками нельзя: копия разойдётся и предфильтр начнёт молча
# отбрасывать то, что правило поймало бы.
# Суффиксы ловят любой префикс (OPENROUTER_API_KEY, YOUGILE_PASSWORD, GROK_TOKEN);
# явные имена суффиксом не ловятся, но матчатся по границе `_`/`-`, поэтому
# SENTRY_DSN и SESSION_COOKIE попадают, а DSNAME — нет.
_SECRET_WORDS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
    "COOKIE", "CREDENTIAL", "PRIVATE_KEY", "PASSPHRASE", "DATABASE_URL",
    "CONNECTION_STRING", "DSN", "AUTH_TOKEN", "API_HASH", "YANDEX_DIRECT_LOGIN",
)
_SUFFIX = "(?:" + "|".join(w.replace("_", "[_-]?") for w in _SECRET_WORDS) + ")"
_EXPLICIT = _SUFFIX  # исторические имена: правило одно, список один
# `_HASH` суффиксом НЕ берём: TEMPLATE_HASH/_TEMPLATE_HASH — хеши содержимого, не секреты
# (33 вхождения в живой БД). Поэтому в списке стоит только API_HASH.
_KEY = rf"[A-Za-z0-9_\-]*(?:{_SUFFIX}|{_EXPLICIT})"

_NAMED = re.compile(
    rf"""(?<![A-Za-z0-9_])            # начало имени; `-` разрешён: `--api-hash`
    (?P<key>{_KEY})
    (?P<gap>["']?\s*[:=]\s*)          # закрывающая кавычка ключа в JSON + разделитель
    (?:  "(?P<dq>(?:\\.|[^"\\\r\n])*)"   # в двойных кавычках; \" НЕ заканчивает значение
      | '(?P<sq>(?:\\.|[^'\\\r\n])*)'    # в одинарных, так же
      | (?P<bare>[^\s,}}\r\n]+)          # без кавычек — до пробела/запятой/}}/конца строки
                                        # `;` НЕ разделитель: cookie и connection string
                                        # штатно его содержат, обрезание оставляло хвост.
                                        # Осознанный размен: в шелл-строке `TOKEN=v; cmd`
                                        # точка с запятой попадёт внутрь маски. Это портит
                                        # диагностику на один символ, а обратный выбор
                                        # оставлял бы половину секрета в журнале.
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# Дешёвый предфильтр: `publish` зовётся на КАЖДЫЙ partial-чанк SSE, и полный regex-проход
# стоит ~284 мкс на килобайт — на потоке это заметный CPU. Подстрочный поиск идёт на C и
# дешевле на порядок. Слова берём ИЗ ТОГО ЖЕ списка — последний сегмент имени присутствует
# в тексте всегда, когда правило срабатывает (`API[_-]?KEY` матчит только строки с `key`),
# поэтому предфильтр гарантированно надмножество, а не «вторая копия правила».
_QUICK_WORDS = tuple({w.split("_")[-1].lower() for w in _SECRET_WORDS} | {"bearer", "basic"})


def _mask_value(value: str) -> str | None:
    """Маска для значения, либо None — если значение слишком короткое, чтобы его трогать."""
    n = len(value)
    if n < _MIN_LEN:
        return None
    if n < _TAIL_FROM:
        return f"[secret len={n}]"
    return f"[secret len={n} tail={value[-4:]}]"


# Ссылка-приглашение MTProto-прокси Telegram: параметр `secret=` там ПУБЛИЧНЫЙ — он и есть
# то, чем делятся. Маскирование ломало рабочую ссылку и делало её бесполезной (владелец
# 06.09: «убери на фронте баг этот»). Исключение узкое: только эта форма URL, только внутри
# её границ; любой другой `secret=` в тексте маскируется по-прежнему.
_TG_PROXY_LINK = re.compile(
    r"(?:https?://t\.me/proxy|tg://proxy)\?[^\s\"'<>]+", re.IGNORECASE,
)


def _named_repl(m: re.Match) -> str:
    for group, quote in (("dq", '"'), ("sq", "'"), ("bare", "")):
        value = m.group(group)
        if value is None:
            continue
        masked = _mask_value(value)
        if masked is None:
            return m.group(0)
        return f"{m.group('key')}{m.group('gap')}{quote}{masked}{quote}"
    return m.group(0)


def _auth_repl(m: re.Match) -> str:
    scheme = m.group(1)
    token = m.group(0)[len(scheme):].strip()
    masked = _mask_value(token)
    return f"{scheme} {masked}" if masked else m.group(0)


def mask_secrets(text: str) -> str:
    """Заменить значения секретов на `[secret len=N tail=XXXX]`, сохранив длину и хвост.

    Fail-soft по построению: не-строку и пустое возвращаем как есть — маскирование
    никогда не должно ронять запись лога или доставку события.
    """
    if not text or not isinstance(text, str):
        return text
    lowered = text.lower()
    if not any(word in lowered for word in _QUICK_WORDS):
        return text
    # PEM первым: он самый крупный и содержит внутри что угодно.
    text = _PEM_PRIVATE_KEY.sub(
        lambda m: f"[secret pem len={len(m.group(0))}]", text
    )
    # Границы считаем ПОСЛЕ подстановки PEM: она сдвигает смещения.
    keep = [m.span() for m in _TG_PROXY_LINK.finditer(text)]
    if keep:
        def _repl(m: re.Match) -> str:
            start = m.start()
            if any(a <= start < b for a, b in keep):
                return m.group(0)
            return _named_repl(m)
        text = _NAMED.sub(_repl, text)
    else:
        text = _NAMED.sub(_named_repl, text)
    return _AUTH_VALUE.sub(_auth_repl, text)
