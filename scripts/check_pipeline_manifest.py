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
import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = _REPO_ROOT / "pipelines" / "default" / "pipeline.yaml"

# Numeric examples (task ids, API arguments, CSS values) are not evidence.  This
# deliberately small vocabulary catches prose that presents money, rates, sample
# counts, or measured thresholds as facts without turning every number into a
# citation requirement.
_MEASURED_WORDS = re.compile(
    r"(?i)measur|замер|empir|corpus|median|медиан|cost|price|стоим|стоит|"
    r"цена|доля|процент|ratio|соотнош|окуп|sample|выборк|размер диффа"
)
_MEASURED_VALUE = re.compile(
    r"(?:\$\s*\d|\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s*[×x]|"
    r"\b\d+\s+(?:of|из|against|против)\s+\d+|\b\d+\s*/\s*\d+|"
    r"\b(?:p\d+|n\s*=\s*\d+)|"
    r"[<>]\s*\d+\s*(?:строк|lines|КБ|KB|токен))",
    re.IGNORECASE,
)
_SOURCE_MARKER = re.compile(
    r"(?:#\d+|source\s*[:=]|источник\s*[:=]|https?://|docs/tasks/)",
    re.IGNORECASE,
)
_PROCEDURAL_VALUE = re.compile(r"(?i)trivial\s*\(\s*[<>]\s*\d+\s*lines?")

# The routing table and round policy have one semantic owner.  Roles/modules carry only
# this pointer so a future edit cannot leave one audience on the old mandatory-Sol rule.
_REVIEW_POLICY_POINTER = "Apply the review decision gate in the `codex-debate` skill"
_REVIEW_POLICY_ACTORS = ("orchestrator", "sub-orchestrator", "worker", "full-cycle")
_REVIEW_POLICY_ANCHORS = (
    "## Review decision gate — canonical policy",
    "The author never self-certifies risk or oracle strength",
    "**High-risk is evidence-derived, not author-declared.**",
    "**NO MODEL REVIEW**",
    "**one fresh Luna review**",
    "**one targeted Sol escalation**",
    # Ревью перестало быть обязательным, а замена недоступного Codex другой моделью
    # запрещена (#346, решение юзера 19.08). Якоря снятого контракта заменены якорями
    # нового: вычеркнуть их значило бы оставить проверку без утверждения на этом месте.
    "**Ревью доступно, но не обязательно",
    "Codex недоступен → ревью НЕ делается",
    "Замену ревьюеру не искать",
    "**Docs / fact extraction**",
    "**One round by default.**",
)
_STALE_REVIEW_POLICY = (
    "Codex review MANDATORY for complex tasks",
    "Размер диффа основанием для пропуска ревью не является ни в каком случае",
    "Codex follows the worker role's review gate",
    "runs required Codex review",
    "Second opinion (Codex)",
    "Codex review the plan + tickets",
    # Отрицательная половина #346: ни обязательность, ни маршрут «поднять Opus вместо
    # Codex» не должны вернуться ни в один промпт — тот маршрут стоил четырёх платных
    # ревьюеров за день. Совпадает со списком `forbidden` в
    # tests/test_default_pipeline.py::test_review_is_optional_and_has_no_substitute_reviewer.
    "review is mandatory regardless of size",
    "targeted Opus cross-family review",
    "cross-family verdict unavailable",
    "Opus запускается свежей reviewer-сессией",
    "review route unavailable",
)


def _review_policy_errors(
    root: Path,
    data: dict,
) -> list[str]:
    """Keep review routing enforceable, single-owned, and delivered to every decision maker."""
    errors: list[str] = []
    prompt_root = root / "prompts"
    canonical = prompt_root / "skills" / "codex-debate.md"
    if not canonical.is_file():
        return [f"review policy owner missing: {canonical}"]
    canonical_text = canonical.read_text()

    for anchor in _REVIEW_POLICY_ANCHORS:
        count = canonical_text.count(anchor)
        if count != 1:
            errors.append(
                f"prompts/skills/codex-debate.md: review policy anchor must occur once: "
                f"{anchor!r} (found {count})"
            )

    roles = data.get("roles") or {}
    consumer_sources: list[str] = []
    if "worker" in roles:
        consumer_sources.append("roles/worker.md")
    if "full-cycle" in roles:
        consumer_sources.append("roles/full-cycle.md")
    if "orchestrator" in roles or "sub-orchestrator" in roles:
        consumer_sources.append("modules/orchestration.md")
    for rel in consumer_sources:
        path = prompt_root / rel
        if not path.is_file():
            errors.append(f"review policy consumer missing: {path}")
            continue
        count = path.read_text().count(_REVIEW_POLICY_POINTER)
        if count != 1:
            errors.append(
                f"prompts/{rel}: review gate pointer must occur once "
                f"(found {count})"
            )

    for role in _REVIEW_POLICY_ACTORS:
        spec = roles.get(role)
        if spec is None:
            continue
        if not isinstance(spec, dict):
            errors.append(f"review policy actor {role!r}: invalid manifest entry")
            continue
        skills = spec.get("skills") or []
        if "codex-debate" not in skills:
            errors.append(f"role {role!r}: codex-debate skill is required for review decisions")

    for md in sorted(prompt_root.rglob("*.md")):
        text = md.read_text()
        rel = md.relative_to(root)
        for stale in _STALE_REVIEW_POLICY:
            if stale in text:
                errors.append(f"{rel}: stale review policy wording: {stale!r}")
        if md != canonical:
            for anchor in _REVIEW_POLICY_ANCHORS:
                if anchor in text:
                    errors.append(
                        f"{rel}: duplicates canonical review policy anchor {anchor!r}"
                    )

    return errors


def _is_measured_claim(line: str) -> bool:
    """Одно определение «строка утверждает замер» — для прозы и для содержимого примера."""
    if _PROCEDURAL_VALUE.search(line):
        return False
    if not _MEASURED_VALUE.search(line):
        return False
    return bool(
        _MEASURED_WORDS.search(line)
        or re.search(r"(?i)\b(?:rounds?|раунд|diff|дифф|threshold|порог)\b", line)
    )


def _prompt_metric_errors(prompt_root: Path) -> list[str]:
    """Require an inline source on empirical numeric claims, not all numbers.

    Fenced blocks are shown output, not assertions: a reference answer has to look like a
    real answer, so its numbers stay bare instead of carrying a citation in every cell.
    The block as a whole is still on the hook — an example running on invented numbers
    teaches inventing them — so it must name its source somewhere inside (#349).
    """
    errors: list[str] = []
    for md in sorted(prompt_root.rglob("*.md")):
        fence_open = 0  # 0 = вне забора, иначе номер строки, которой забор открыт
        fence_value = fence_source = False
        for line_no, line in enumerate(md.read_text().splitlines(), 1):
            if line.lstrip().startswith("```"):
                if fence_open:
                    if fence_value and not fence_source:
                        rel = md.relative_to(prompt_root.parent)
                        errors.append(
                            f"{rel}:{fence_open}: example block shows measured numbers "
                            f"without naming their source"
                        )
                    fence_open = 0
                else:
                    fence_open, fence_value, fence_source = line_no, False, False
                continue
            if fence_open:
                # Незакрытый забор проглотил бы остаток файла — итог считается после цикла.
                fence_value = fence_value or _is_measured_claim(line)
                fence_source = fence_source or bool(_SOURCE_MARKER.search(line))
                continue
            if _is_measured_claim(line) and not _SOURCE_MARKER.search(line):
                rel = md.relative_to(prompt_root.parent)
                errors.append(
                    f"{rel}:{line_no}: measured numeric claim lacks inline source marker"
                )
        if fence_open and fence_value and not fence_source:
            rel = md.relative_to(prompt_root.parent)
            errors.append(
                f"{rel}:{fence_open}: example block shows measured numbers "
                f"without naming their source"
            )
    return errors


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
        _take(policy.get("alternatives"))
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
    if prompt_root.is_dir():
        errors.extend(_prompt_metric_errors(prompt_root))
    review_users = [
        name for name, spec in roles.items()
        if isinstance(spec, dict) and "codex-debate" in (spec.get("skills") or [])
    ]
    if review_users:
        errors.extend(_review_policy_errors(root, data))
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
