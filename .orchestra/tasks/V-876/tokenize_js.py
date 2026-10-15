"""Заменить hex-цвета во ВСТРОЕННЫХ CSS-объявлениях JS (style="…", cssText) на var(--токен).

Трогаются только конструкции вида `color:#xxxxxx` внутри строки — там var() работает.
Объекты JS (`color: '#…'`), SVG-атрибуты (`fill="#…"`) и canvas не трогаются:
там значение не CSS, и var() не подставится.
    python3 .orchestra/tasks/V-876/tokenize_js.py FILE [--skip-lines A-B]
"""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from tokenize_css import token_for  # noqa: E402  (та же таблица значений → токенов)

DECL = re.compile(
    r"(?<![\w.-])((?:background(?:-color)?|color|border(?:-(?:top|right|bottom|left))?(?:-color)?|outline|fill|stroke)\s*:\s*)"
    r"([^;\"'`<>{}\n]*)"
)
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
counts = {"replaced": 0}

path = sys.argv[1]
skip = range(0)
if "--skip-lines" in sys.argv:
    a, b = sys.argv[sys.argv.index("--skip-lines") + 1].split("-")
    skip = range(int(a), int(b) + 1)


def fix(m):
    prop = m.group(1).split(":")[0].strip().lower()
    def sub(h):
        token = token_for(prop, h.group(0))
        if token:
            counts["replaced"] += 1
            return f"var({token})"
        return h.group(0)
    return m.group(1) + HEX.sub(sub, m.group(2))


lines = open(path).read().split("\n")
for i, line in enumerate(lines, 1):
    if i in skip or line.lstrip().startswith("//"):
        continue
    lines[i - 1] = DECL.sub(fix, line)
open(path, "w").write("\n".join(lines))
print(path, counts)
