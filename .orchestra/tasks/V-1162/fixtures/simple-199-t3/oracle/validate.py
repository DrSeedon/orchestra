from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load(path: Path):
    candidate = path / "src" / "error_text.py"
    if not candidate.exists():
        candidate = path / "error_text.py"
    spec = importlib.util.spec_from_file_location("candidate_error_text", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ordered_once(text: str, parts: tuple[str, ...]) -> bool:
    positions = [text.find(part) for part in parts]
    return all(pos >= 0 for pos in positions) and positions == sorted(positions) and all(
        text.count(part) == 1 for part in parts
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    module = load(args.candidate)

    plain = ValueError("plain failure")
    assert module.err_text(plain) == "plain failure"

    root = LookupError("root cause marker")
    middle = RuntimeError("middle cause marker")
    middle.__cause__ = root
    outer = ValueError("outer failure marker")
    outer.__cause__ = middle
    rendered = module.err_text(outer)
    assert ordered_once(
        rendered,
        ("outer failure marker", "middle cause marker", "root cause marker"),
    )

    context_only = ValueError("outer with context")
    context_only.__context__ = RuntimeError("implicit context marker")
    rendered_context = module.err_text(context_only)
    assert "outer with context" in rendered_context
    assert "implicit context marker" not in rendered_context
    print("PASS: plain, nested explicit cause order, and context exclusion")


if __name__ == "__main__":
    main()
