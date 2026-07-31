"""Prompt composition — pure file/template helpers for agent prompts."""

import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Single source of prompts = pipelines/default/prompts/ (app/prompts/ removed —
# no legacy fallback). These helpers feed dashboard prompt view, role icons,
# skill injection, and the template hash — all off the default pipeline.
_PROMPTS_DIR = Path(__file__).parent.parent / "pipelines" / "default" / "prompts"
_MODULES_DIR = _PROMPTS_DIR / "modules"
_SKILLS_DIR = _PROMPTS_DIR / "skills"

_ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")


def is_orchestrator_role(role: str) -> bool:
    return role in _ORCHESTRATOR_ROLES


def safe_format_prompt(template: str, **kwargs: str) -> str:
    """Substitute only known identity placeholders, leaving other {braces} intact."""
    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)


def read_prompt(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def parse_role_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    body = parts[2].strip()
    return meta, body


def _load_modules(module_names: list[str]) -> str:
    parts = []
    for name in module_names:
        p = _MODULES_DIR / f"{name}.md"
        if p.exists():
            parts.append(p.read_text().strip())
        else:
            logger.warning(f"Module '{name}' not found at {p}")
    return "\n\n".join(parts)


def role_prompt_file(role: str) -> str:
    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
    Falls back to 'worker' role if role file not found."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if role_path.exists():
        meta, body = parse_role_frontmatter(role_path.read_text())
        if body:
            modules = meta.get("modules", [])
            if modules:
                body = body + "\n\n" + _load_modules(modules)
            return body
    if role != "worker":
        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
        if fallback.exists():
            meta, body = parse_role_frontmatter(fallback.read_text())
            if body:
                modules = meta.get("modules", [])
                if modules:
                    body = body + "\n\n" + _load_modules(modules)
                return body
    return ""


def role_can_spawn(role: str):
    """Return the can_spawn whitelist for a role, or None if unrestricted."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return None
    meta, _ = parse_role_frontmatter(role_path.read_text())
    if "can_spawn" not in meta:
        return None
    val = meta["can_spawn"]
    if not isinstance(val, list):
        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
        return None
    return [str(x) for x in val]


def get_role_icons() -> dict[str, str]:
    roles_dir = _PROMPTS_DIR / "roles"
    icons = {}
    if roles_dir.is_dir():
        for f in sorted(roles_dir.glob("*.md")):
            meta, _ = parse_role_frontmatter(f.read_text())
            if meta:
                name = meta.get("name", f.stem)
                icon = meta.get("icon", "")
                if icon:
                    icons[name] = icon
    return icons


def prompt_template_hash(role_or_orch) -> str:
    """Hash only the static template files (base.md + role.md + skills).
    Accepts role string or legacy bool (is_orchestrator)."""
    if isinstance(role_or_orch, bool):
        role = "orchestrator" if role_or_orch else "worker"
    else:
        role = role_or_orch
    content = read_prompt("base.md") + role_prompt_file(role)
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _run_as_agent(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run command as agent user if ORCHESTRA_AGENT_UID set (cap_drop=ALL workaround)."""
    agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
    if agent_uid:
        gosu = shutil.which("gosu")
        if gosu:
            args = [gosu, agent_uid] + args
    return subprocess.run(args, **kwargs)


def inject_skills_to_worktree(skill_names: list[str], worktree_path: str) -> None:
    """Copy resolved pipeline skills into worktree/.claude/skills/ as native Claude CLI skills.

    Skills are resolved from pipeline.yaml (ResolvedRole.skills), not role-file
    frontmatter — role bodies are frontmatter-free, so reading them yielded nothing.
    """
    if not skill_names or not _SKILLS_DIR.is_dir():
        return
    wt = Path(worktree_path)
    for sname in skill_names:
        skill_src = _SKILLS_DIR / f"{sname}.md"
        if not skill_src.exists():
            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
            continue
        skill_dir = wt / ".claude" / "skills" / sname
        _run_as_agent(["mkdir", "-p", str(skill_dir)], capture_output=True)
        _run_as_agent(["cp", "-p", str(skill_src), str(skill_dir / "SKILL.md")], capture_output=True)
    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")


_SKILL_INDEX_HEADER = """## Available skills (progressive loading)

The entries below are an index, not loaded instructions. When a request matches a skill description, you MUST read that skill file completely before acting. Do not read unrelated skill files. Skills apply only to the current request."""


def _read_skill_index_entry(path: Path) -> tuple[str, str, Path]:
    text = path.read_text(encoding="utf-8")
    meta, _ = parse_role_frontmatter(text)
    name = meta.get("name") if isinstance(meta, dict) else None
    description = meta.get("description") if isinstance(meta, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("missing frontmatter name")
    if "\n" in name or "\r" in name:
        raise ValueError("frontmatter name must be one line")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("missing frontmatter description")
    return name.strip(), " ".join(description.split()), path.resolve()


def build_skills_index(
    required_skill_files: list[Path],
    optional_skill_files: list[Path],
) -> str:
    """Generate a progressive skill catalog from canonical source files.

    Required files are explicit pipeline role configuration and fail backend
    construction on any read/frontmatter error. Optional project files are ambient:
    malformed entries are logged and omitted.
    """
    entries: list[str] = []
    seen: set[str] = set()
    for required, paths in (
        (True, required_skill_files),
        (False, optional_skill_files),
    ):
        for path in paths:
            try:
                name, description, resolved = _read_skill_index_entry(Path(path))
            except (OSError, UnicodeError, ValueError) as exc:
                if required:
                    logger.error("Required skill '%s' is invalid: %s", path, exc)
                    raise ValueError(f"required skill '{path}' is invalid: {exc}") from exc
                logger.warning("Skipping optional skill '%s': %s", path, exc)
                continue
            if name in seen:
                continue
            seen.add(name)
            entries.append(f"- `{name}` — {description} — `{resolved}`")
    if not entries:
        return ""
    return _SKILL_INDEX_HEADER + "\n\n" + "\n".join(entries)


def _project_skill_files(worktree_path: str) -> list[Path]:
    """Return project skills whose live files still match committed HEAD."""
    try:
        worktree = Path(worktree_path).resolve()
        skills_candidate = worktree / ".claude" / "skills"
        if skills_candidate.is_symlink():
            logger.warning("Project skill root is a symlink: %s", skills_candidate)
            return []
        skills_root = skills_candidate.resolve()
    except (OSError, RuntimeError) as exc:
        logger.warning("Project skill root cannot be resolved in %s: %s", worktree_path, exc)
        return []
    if not skills_root.is_relative_to(worktree):
        logger.warning("Project skill root escapes worktree: %s", skills_root)
        return []
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", ".claude/skills/*/SKILL.md"],
            cwd=worktree,
            capture_output=True,
        )
    except OSError as exc:
        logger.warning("Project skill discovery failed in %s: %s", worktree, exc)
        return []
    if tracked.returncode != 0:
        logger.debug("No Git project skills in %s", worktree)
        return []
    try:
        relative_paths = tracked.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        logger.warning("Project skill paths are not UTF-8 in %s: %s", worktree, exc)
        return []

    result: list[Path] = []
    for relative in sorted(path for path in relative_paths if path):
        candidate = worktree / relative
        if candidate.is_symlink():
            logger.warning("Skipping project skill symlink: %s", candidate)
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            logger.warning("Skipping missing project skill '%s': %s", candidate, exc)
            continue
        if not resolved.is_relative_to(skills_root) or not resolved.is_file():
            logger.warning("Skipping project skill outside canonical root: %s", resolved)
            continue
        try:
            clean = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", relative],
                cwd=worktree,
                capture_output=True,
            )
        except OSError as exc:
            logger.warning("Skipping project skill '%s': diff failed: %s", candidate, exc)
            continue
        if clean.returncode != 0:
            detail = (
                "diff failed"
                if clean.returncode > 1
                else "working file differs from committed HEAD"
            )
            logger.warning("Skipping project skill '%s': %s", candidate, detail)
            continue
        result.append(resolved)
    return result


def build_codex_skills_index(
    pipeline_name: str,
    skill_names: list[str] | str,
    worktree_path: str,
) -> str:
    """Build the live skill index for a Codex backend.

    Pipeline files are explicit/required. Project discovery is added separately
    below; keeping the resolver here ensures both sources share one output format.
    """
    from app.pipeline import PIPELINES_DIR, _is_safe_component

    # Empty pipeline (legacy sessions, ad-hoc workers) → no pipeline skills.
    # Project discovery below still runs. Don't fail the whole send.
    if not pipeline_name:
        pipeline_name = "default"
    if not _is_safe_component(pipeline_name):
        raise ValueError(f"unsafe pipeline name '{pipeline_name}'")
    pipelines_root = PIPELINES_DIR.resolve()
    skills_candidate = pipelines_root / pipeline_name / "prompts" / "skills"
    if skills_candidate.is_symlink():
        raise ValueError(f"unsafe pipeline skill root symlink '{skills_candidate}'")
    skills_root = skills_candidate.resolve()
    if not skills_root.is_relative_to(pipelines_root):
        raise ValueError(f"unsafe pipeline skill root '{skills_root}'")

    required: list[Path] = []
    if skill_names == "all":
        for candidate in sorted(skills_root.glob("*.md")):
            if candidate.is_symlink():
                raise ValueError(f"unsafe pipeline skill path (symlink): '{candidate}'")
            path = candidate.resolve()
            if not path.is_relative_to(skills_root):
                raise ValueError(f"unsafe pipeline skill path '{path}'")
            required.append(path)
    else:
        for name in skill_names:
            if not _is_safe_component(name):
                raise ValueError(f"unsafe skill name '{name}'")
            candidate = skills_root / f"{name}.md"
            if candidate.is_symlink():
                raise ValueError(f"unsafe pipeline skill path (symlink): '{candidate}'")
            path = candidate.resolve()
            if not path.is_relative_to(skills_root):
                raise ValueError(f"unsafe pipeline skill path '{path}'")
            required.append(path)

    return build_skills_index(required, _project_skill_files(worktree_path))
