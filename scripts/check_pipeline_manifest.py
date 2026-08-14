#!/usr/bin/env python3
"""Сверка манифеста пайплайна с файлами промптов на диске.

``pipelines/<name>/pipeline.yaml`` правится руками — генератора нет
(``app/prompts/`` удалён, ``scripts/extract-manifest.py`` снесён). Этот скрипт
не пишет YAML. Он только проверяет, что каждая роль и каждый модуль из
манифеста лежат в ``prompts/``. ``--check`` краснеет на расхождении и
зеленеет, только когда сверка реально что-то обошла.

    python scripts/check_pipeline_manifest.py --check
    python scripts/check_pipeline_manifest.py --check --manifest PATH
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = _REPO_ROOT / "pipelines" / "default" / "pipeline.yaml"


def disagreements(manifest_path: Path) -> list[str]:
    """Пути, которых манифест требует, а на диске нет. Пустой список = согласовано."""
    if not manifest_path.is_file():
        return [f"manifest not found: {manifest_path}"]
    data = yaml.safe_load(manifest_path.read_text()) or {}
    roles = data.get("roles")
    if not isinstance(roles, dict) or not roles:
        return [f"{manifest_path}: no roles to check"]
    root = manifest_path.parent
    errors: list[str] = []
    for name, spec in roles.items():
        role_file = root / "prompts" / "roles" / f"{name}.md"
        if not role_file.is_file():
            errors.append(f"role {name!r}: missing {role_file}")
        modules = (spec or {}).get("modules") or []
        if not isinstance(modules, list):
            errors.append(f"role {name!r}: modules is not a list")
            continue
        for mod in modules:
            mod_file = root / "prompts" / "modules" / f"{mod}.md"
            if not mod_file.is_file():
                errors.append(f"role {name!r} module {mod!r}: missing {mod_file}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="сверить манифест с prompts/; код 1 при расхождении",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="путь к pipeline.yaml (по умолчанию pipelines/default/pipeline.yaml)",
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    errors = disagreements(args.manifest)
    if errors:
        print("FAIL: manifest disagrees with prompt files:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print(f"OK: {args.manifest} agrees with prompt files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
