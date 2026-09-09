#!/usr/bin/env python3
"""Check ordinary local Markdown links in the active KB; prose has no required schema."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

_LINK = re.compile(r'\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def check(root: Path) -> list[str]:
    errors = []
    if not root.is_dir():
        return [f'{root}: KB directory does not exist']
    for path in sorted(root.rglob('*.md')):
        fenced = False
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.lstrip().startswith(('```', '~~~')):
                fenced = not fenced
                continue
            if fenced:
                continue
            # Code examples and exact search literals are not navigable Markdown links.
            text = re.sub(r'`+[^`]*`+', '', line)
            for match in _LINK.finditer(text):
                raw = match.group(1).strip('<>')
                destination = urlsplit(raw)
                if destination.scheme or destination.netloc or not destination.path:
                    continue
                target = path.parent / unquote(destination.path)
                if not target.exists():
                    errors.append(f'{path}:{number}: missing link target: {raw}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.orchestra/kb'))
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        parser.exit(1, '\n'.join(errors) + '\n')
    print('KB links OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
