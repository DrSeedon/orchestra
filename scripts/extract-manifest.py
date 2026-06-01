#!/usr/bin/env python3
"""Генератор моста upstream → манифест ``pipelines/default/pipeline.yaml``.

Сканирует upstream-источник истины (``app/prompts/roles/*.md`` с YAML-frontmatter),
строит из него манифест нашего формата (:class:`app.pipeline.PipelineConfig`) и либо
печатает YAML, либо сверяет с текущим ``pipelines/default/pipeline.yaml`` (``--check``).

Назначение: коллега правит роли только во frontmatter (его система), а наш default
получается из этого детерминированно — мост гарантирует, что default не дрейфует от
upstream вручную. Связка с ``tests/test_default_equals_upstream.py``: тот доказывает
поведенческую идентичность, мост — воспроизводимость манифеста.

Маппинг frontmatter → манифест:
  * ``name``               → ключ роли в ``roles:``.
  * ``icon``               → ``tg.emoji`` (нет icon → tg не выставляется).
  * ``label``/``when``/``not_for``/``description`` → одноимённые поля RoleSpec.
  * ``model``              → alias-резолв; ``sonnet/opus`` → первое слово (``sonnet``).
  * ``can_spawn``: НЕТ во frontmatter → ``["*"]`` (unlimited, как upstream None);
                   ``[]`` → терминал; список → как есть.
  * ``kind``               → orchestrator/sub-orchestrator ⇒ ``orchestrator``, иначе ``worker``.
  * ``modules``/``skills`` → как во frontmatter.

CLI:
  * ``python scripts/extract-manifest.py``            — печать YAML в stdout.
  * ``python scripts/extract-manifest.py -o PATH``    — запись YAML в файл.
  * ``python scripts/extract-manifest.py --check``    — сверка с текущим default;
    код возврата 1 при расхождении (для CI).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Импорт пакета app возможен и при запуске из корня репо, и из scripts/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.pipeline import PIPELINES_DIR, PipelineConfig  # noqa: E402

# Upstream-источник истины: роли с frontmatter.
UPSTREAM_ROLES_DIR = _REPO_ROOT / "app" / "prompts" / "roles"
DEFAULT_MANIFEST = PIPELINES_DIR / "default" / "pipeline.yaml"

# Оркестраторские роли (kind=orchestrator). Совпадает с app.session._ORCHESTRATOR_ROLES.
ORCHESTRATOR_NAMES = {"orchestrator", "sub-orchestrator"}

# Каноничный порядок ролей (order) — нет во frontmatter, фиксируем явно по упстриму.
ROLE_ORDER = ["orchestrator", "sub-orchestrator", "worker", "full-cycle", "reviewer", "watcher"]

# Описание пайплайна на уровне манифеста — нет во frontmatter, известная константа default.
PIPELINE_DESCRIPTION = (
    "Upstream pipeline v2.16 (orchestrator / sub-orchestrator / worker / "
    "full-cycle / reviewer / watcher). Behaviour 1:1 with mccalpink/orchestra main."
)

# defaults-блок манифеста (B3): известная константа default, не выводится из frontmatter.
DEFAULTS = {
    "model": "opus",
    "skills": [],
    "mcp_servers": [],
    "inherit_claude_md": True,
    "prompt_layers": {
        "orchestrator": ["base.md", "roles/{role}.md"],
        "worker": ["base.md", "roles/{role}.md"],
    },
    "worktree": {
        "symlinks": [],
        "copies": ["CLAUDE.md", ".mcp.json", ".env", ".worktreeinclude"],
    },
    "base_branch_strategy": "main",
    "docs_scaffold": False,
}


def _parse_frontmatter(text: str) -> dict:
    """YAML-frontmatter из тела роли (``---\\n...\\n---\\n<body>``). {} если нет.

    Семантика совпадает с :func:`app.manager._parse_role_frontmatter` (split на 3).
    """
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def _map_model(raw: str) -> str:
    """``sonnet/opus`` → первое слово (``sonnet``). Без слэша — как есть."""
    return raw.split("/")[0].strip()


def _build_role(name: str, fm: dict) -> dict:
    """Собрать запись роли манифеста из frontmatter одной upstream-роли."""
    kind = "orchestrator" if name in ORCHESTRATOR_NAMES else "worker"

    # can_spawn: поля нет → unlimited (["*"], как upstream None); иначе — как есть.
    if "can_spawn" in fm:
        can_spawn = list(fm["can_spawn"]) if isinstance(fm["can_spawn"], list) else ["*"]
    else:
        can_spawn = ["*"]

    role: dict = {
        "kind": kind,
        "label": fm.get("label", name),
        "order": ROLE_ORDER.index(name) if name in ROLE_ORDER else 100,
        "model": _map_model(str(fm["model"])) if "model" in fm else DEFAULTS["model"],
        "can_spawn": can_spawn,
        # orchestrator'ы допускают безролевых воркеров, воркеры — нет (kind-дефолт).
        "allow_unrouted_workers": kind == "orchestrator",
    }
    if fm.get("skills"):
        role["skills"] = list(fm["skills"])
    if fm.get("modules"):
        role["modules"] = list(fm["modules"])
    if fm.get("icon"):
        role["tg"] = {"emoji": fm["icon"]}
    for field in ("when", "not_for", "description"):
        if fm.get(field):
            role[field] = fm[field]
    return role


def build_manifest() -> dict:
    """Собрать полный dict манифеста default из upstream-ролей."""
    if not UPSTREAM_ROLES_DIR.is_dir():
        raise FileNotFoundError(f"upstream roles dir not found: {UPSTREAM_ROLES_DIR}")

    roles: dict[str, dict] = {}
    for path in sorted(UPSTREAM_ROLES_DIR.glob("*.md")):
        fm = _parse_frontmatter(path.read_text())
        if not fm:
            continue
        name = fm.get("name", path.stem)
        roles[name] = _build_role(name, fm)

    # Сортируем роли по order — стабильный детерминированный вывод.
    roles = dict(sorted(roles.items(), key=lambda kv: kv[1]["order"]))

    return {
        "name": "default",
        "description": PIPELINE_DESCRIPTION,
        "validation": "fail-open",
        "defaults": DEFAULTS,
        "roles": roles,
    }


def _validate(data: dict) -> None:
    """Self-валидация: прогнать через PipelineConfig. Упасть, если невалиден."""
    PipelineConfig(**data)  # pydantic: схема + граф can_spawn


def _normalized(data: dict) -> dict:
    """Нормализовать манифест для сравнения (через PipelineConfig → dump).

    Сравниваем СЕМАНТИКУ (резолвнутую модель), а не текстовое форматирование YAML:
    ключи/отступы/кавычки текущего файла не влияют на ``--check``.
    """
    return PipelineConfig(**data).model_dump()


def main() -> int:
    parser = argparse.ArgumentParser(description="Мост upstream-ролей → манифест default.")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="записать YAML в файл (по умолчанию — stdout)")
    parser.add_argument("--check", action="store_true",
                        help="сверить с текущим pipelines/default/pipeline.yaml; "
                             "код возврата 1 при расхождении")
    args = parser.parse_args()

    data = build_manifest()
    _validate(data)  # упадёт, если результат невалиден

    if args.check:
        if not DEFAULT_MANIFEST.is_file():
            print(f"FAIL: {DEFAULT_MANIFEST} не найден", file=sys.stderr)
            return 1
        current = yaml.safe_load(DEFAULT_MANIFEST.read_text())
        if _normalized(data) == _normalized(current):
            print("OK: сгенерированный манифест совпадает с текущим default.")
            return 0
        print("FAIL: сгенерированный манифест РАСХОДИТСЯ с текущим default.", file=sys.stderr)
        return 1

    out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    if args.output:
        args.output.write_text(out)
        print(f"записано в {args.output}")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
