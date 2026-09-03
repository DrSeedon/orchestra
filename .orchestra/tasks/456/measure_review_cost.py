#!/usr/bin/env python3
"""Measure the frozen #456 prompt and corpus with OpenAI's o200k_base tokenizer."""

from __future__ import annotations

import json
import re
from pathlib import Path

import tiktoken


ROOT = Path(__file__).resolve().parent


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"section not found: {heading}")
    return match.group(1).strip()


def metrics(text: str, encoding: tiktoken.Encoding) -> dict[str, int]:
    return {
        "characters": len(text),
        "words": len(re.findall(r"\S+", text)),
        "o200k_base_tokens": len(encoding.encode(text)),
    }


def main() -> None:
    protocol = (ROOT / "evaluation-protocol.md").read_text(encoding="utf-8")
    packet = (ROOT / "evaluation-packet.md").read_text(encoding="utf-8")
    encoding = tiktoken.get_encoding("o200k_base")
    result = {
        "tokenizer": f"tiktoken {tiktoken.__version__} o200k_base",
        "stop_rule": metrics(section(protocol, "Frozen STOP rule"), encoding),
        "nine_case_packet": metrics(packet, encoding),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "review-cost.json").write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
