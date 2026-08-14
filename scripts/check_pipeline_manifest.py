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


def _manifest_model_ids(data: dict) -> set[str]:
    """Versioned ids owned by the manifest — short aliases like ``opus`` are not copies."""
    ids: set[str] = set()

    def _take(value: object) -> None:
        if isinstance(value, str) and ("-" in value or "[" in value):
            ids.add(value)
        elif isinstance(value, list):
            for item in value:
                _take(item)

    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        _take(defaults.get("model"))
    for spec in (data.get("roles") or {}).values():
        if not isinstance(spec, dict):
            continue
        _take(spec.get("model"))
        effort = spec.get("effort")
        if isinstance(effort, dict):
            for key in effort:
                if key != "default":
                    _take(key)
    policy = data.get("worker_model_policy")
    if isinstance(policy, dict):
        _take(policy.get("always_allowed"))
        _take(policy.get("denied"))
        _take(policy.get("alternatives"))
        guarded = policy.get("quota_guarded")
        if isinstance(guarded, dict):
            _take(guarded.get("model"))
    return ids


def disagreements(manifest_path: Path) -> list[str]:
    """Пути, которых манифест требует, а на диске нет; плюс процитированные id моделей.

    Пустой список = согласовано. Цитата id в промпте — та же дыра, что скобка
    ``(xhigh)`` в #207: копия расходится с владельцем (#209).
    """
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
    prompt_root = root / "prompts"
    model_ids = _manifest_model_ids(data)
    if prompt_root.is_dir() and model_ids:
        for md in sorted(prompt_root.rglob("*.md")):
            text = md.read_text()
            for mid in sorted(model_ids):
                if mid in text:
                    rel = md.relative_to(root)
                    errors.append(f"{rel}: quotes manifest model {mid!r}")
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
