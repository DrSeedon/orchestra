"""Detect model output that looks like an unexecuted tool call."""

import re


UNEXECUTED_TOOL_CALL_WARNING = (
    "⚠ НЕ ВЫПОЛНЕНО — похоже на вызов инструмента, напечатанный текстом"
)

_FENCED_CODE_RE = re.compile(
    r"(?P<fence>```|~~~)[\s\S]*?(?:(?P=fence)|\Z)",
)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_TOOL_TAG_PATTERNS = (
    re.compile(r"<invoke\s+name\s*=", re.IGNORECASE),
    re.compile(r"</invoke\s*>", re.IGNORECASE),
    re.compile(r"<parameter\s+name\s*=", re.IGNORECASE),
    re.compile(r"</parameter\s*>", re.IGNORECASE),
    re.compile(r"<function_calls(?:\s[^>]*)?>", re.IGNORECASE),
)


def looks_like_unexecuted_tool_call(text: str) -> bool:
    """Require two tool-XML signals outside Markdown code."""
    prose = _FENCED_CODE_RE.sub("", text or "")
    prose = _INLINE_CODE_RE.sub("", prose)
    return sum(bool(pattern.search(prose)) for pattern in _TOOL_TAG_PATTERNS) >= 2


def mark_unexecuted_tool_call(text: str) -> str:
    if not looks_like_unexecuted_tool_call(text):
        return text
    return f"**{UNEXECUTED_TOOL_CALL_WARNING}**\n\n{text}"
