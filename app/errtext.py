"""Единственный владелец правила «ошибка обязана назвать себя».

Целое семейство исключений стрингуется в ПУСТУЮ строку: `httpx.ReadTimeout`,
`ConnectTimeout`, `PoolTimeout`, `TimeoutError`, `CancelledError`,
`ConnectionResetError`, `BrokenPipeError`, `KeyboardInterrupt`. Поэтому
`f"connect failed: {e}"` печатает `connect failed: ` — юзер получает в TG
сообщение, оборванное на двоеточии, а причина известна и остаётся в процессе.

Модуль держится на голой stdlib СПЕЦИАЛЬНО: его импортирует и `app.mcp_stdio`,
который запускается отдельным процессом и не тянет остальной пакет.

Правило жило в четырёх независимых копиях (`_exception_text`, `_bug_error`,
`_text`+ручной фолбэк, инлайн `str(e) or type(e).__name__`) — они успели
разойтись в мелочах (`.strip()` есть не везде). Одна мысль = один owner.
"""


def err_text(exc: BaseException) -> str:
    """`ClassName: детали`, либо голое `ClassName`, когда деталей нет.

    Висячее двоеточие не печатается никогда: `TimeoutError: ` выглядит как
    обрезанная передача, а не как факт таймаута.
    """
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
