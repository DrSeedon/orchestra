"""Заменить в style.css hex-цвета, точно равные токену design-system.css, на var(--токен).

Значение не меняется — меняется только источник: правило берёт цвет из токена.
Блоки .voice-* пропускаются (их ведёт feat-voice-input).
    python3 .orchestra/tasks/V-876/tokenize_css.py app/static/css/style.css
"""
import re
import sys

SURFACE = {"#0a0e17": "--bg", "#0f172a": "--surface", "#1e293b": "--surface-2", "#334155": "--surface-3"}
BORDER = {"#1e293b": "--border-soft", "#334155": "--border", "#475569": "--border-strong"}
COMMON = {
    "#f1f5f9": "--ink-strong", "#e2e8f0": "--ink", "#cbd5e1": "--ink-body", "#a6b3c6": "--ink-soft",
    "#8595ab": "--ink-faint", "#6b7c93": "--ink-faintest", "#94a3b8": "--ink-muted", "#64748b": "--ink-dim",
    "#22c55e": "--ok", "#4ade80": "--ok-soft", "#86efac": "--ok-ink",
    "#eab308": "--warn", "#f59e0b": "--warn-strong", "#fbbf24": "--warn-ink",
    "#ef4444": "--danger", "#f87171": "--danger-soft", "#fca5a5": "--danger-ink",
    "#818cf8": "--accent", "#6366f1": "--accent-strong", "#c7d2fe": "--accent-ink", "#a5b4fc": "--accent-mute",
    "#38bdf8": "--accent-alt", "#a78bfa": "--accent-violet", "#475569": "--border-strong",
}
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
counts = {"replaced": 0, "kept": 0}


def token_for(prop: str, hex_value: str):
    h = hex_value.lower()
    if "border" in prop or "outline" in prop:
        return BORDER.get(h) or COMMON.get(h)
    if prop == "color" and h == "#475569":
        return "--ink-ghost"
    return SURFACE.get(h) or COMMON.get(h)


def fix_decl(m):
    prop, value = m.group(1), m.group(2)
    def sub(h):
        token = token_for(prop.lower(), h.group(0))
        if token:
            counts["replaced"] += 1
            return f"var({token})"
        counts["kept"] += 1
        return h.group(0)
    return f"{prop}:{HEX.sub(sub, value)}"


def fix_rule(m):
    selector, body = m.group(1), m.group(2)
    if "voice" in selector or selector.strip().startswith(":root"):
        return m.group(0)
    return selector + "{" + re.sub(r"([\w-]+)\s*:([^;{}]+)", fix_decl, body) + "}"


if __name__ == "__main__":
    path = sys.argv[1]
    css = open(path).read()
    css = re.sub(r"([^{}]+)\{([^{}]*)\}", fix_rule, css)
    open(path, "w").write(css)
    print(counts)
