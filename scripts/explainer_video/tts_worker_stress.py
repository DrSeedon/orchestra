"""RUAccent JSON worker: phrase list on stdin → stress-marked phrase list on stdout."""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path


def stress_text(text: str, accentizer) -> str:
    """Automatically mark unannotated spans; manually marked whitespace tokens are authoritative."""
    result, pending = [], []
    for part in re.split(r"(\s+)", text):
        if part and not part.isspace() and "+" in part:
            if pending:
                result.append(accentizer.process_all("".join(pending)))
                pending.clear()
            result.append(part)
        else:
            pending.append(part)
    if pending:
        result.append(accentizer.process_all("".join(pending)))
    return "".join(result)


def main() -> None:
    phrases = json.load(sys.stdin)
    if not isinstance(phrases, list) or not all(isinstance(text, str) for text in phrases):
        raise SystemExit("expected a JSON list of phrase strings")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from ruaccent import RUAccent
    except ModuleNotFoundError as exc:
        if exc.name == "ruaccent":
            print("RUACCENT_NOT_INSTALLED", file=sys.stderr)
            raise SystemExit(2) from exc
        raise

    home = Path(os.environ.get("ORCHESTRA_TTS_HOME", Path.home() / ".local/share/orchestra-tts"))
    accentizer = RUAccent()
    with contextlib.redirect_stdout(sys.stderr):
        accentizer.load(
            omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False,
            device="CPU", workdir=str(home / "ruaccent-model"),
        )
        accented = [stress_text(text, accentizer) for text in phrases]
    print(json.dumps(accented, ensure_ascii=False))


if __name__ == "__main__":
    main()
