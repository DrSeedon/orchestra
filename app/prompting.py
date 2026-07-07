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


def skills_catalog() -> str:
    """Build catalog of available skills from skills/ directory for orchestrator."""
    if not _SKILLS_DIR.is_dir():
        return ""
    entries = []
    for f in sorted(_SKILLS_DIR.glob("*.md")):
        meta, _ = parse_role_frontmatter(f.read_text())
        name = meta.get("name", f.stem)
        desc = meta.get("description", "").strip().replace("\n", " ")
        entries.append(f"- `{name}` — {desc}")
    if not entries:
        return ""
    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)


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


def roles_catalog() -> str:
    """Build a catalog of available worker roles from roles/ directory frontmatter."""
    roles_dir = _PROMPTS_DIR / "roles"
    if not roles_dir.is_dir():
        return ""
    entries = []
    for f in sorted(roles_dir.glob("*.md")):
        meta, _ = parse_role_frontmatter(f.read_text())
        if not meta or meta.get("name") == "orchestrator":
            continue
        name = meta.get("name", f.stem)
        label = meta.get("label", name)
        model = meta.get("model", "any")
        desc = meta.get("description", "").strip().replace("\n", " ")
        when = meta.get("when", "").strip()
        not_for = meta.get("not_for", "").strip()
        skills_list = meta.get("skills", [])
        entry = f"### `{name}` ({label}) — model: {model}\n{desc}"
        if when:
            entry += f"\n- ✅ **When**: {when}"
        if not_for:
            entry += f"\n- ❌ **Not for**: {not_for}"
        if skills_list:
            entry += f"\n- 🔧 **Skills**: {', '.join(skills_list)}"
        entries.append(entry)
    if not entries:
        return ""
    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)


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
