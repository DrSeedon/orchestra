"""Prompt composition — pure file/template helpers for agent prompts."""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from app.workspace import _exclude_worktree_artifacts, tracked_paths

logger = logging.getLogger(__name__)

# Single source of prompts = pipelines/default/prompts/ (app/prompts/ removed —
# no legacy fallback). These helpers feed dashboard prompt view, role icons,
# skill injection, and the template hash — all off the default pipeline.
_PROMPTS_DIR = Path(__file__).parent.parent / "pipelines" / "default" / "prompts"
_MODULES_DIR = _PROMPTS_DIR / "modules"
_SKILLS_DIR = _PROMPTS_DIR / "skills"

_ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")
_WORKER_MEMORY_BLOCK = re.compile(r"\n*<worker-memory>.*?</worker-memory>", re.DOTALL)


def is_orchestrator_role(role: str) -> bool:
    return role in _ORCHESTRATOR_ROLES


def safe_format_prompt(template: str, **kwargs: str) -> str:
    """Substitute only known identity placeholders, leaving other {braces} intact."""
    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)


def load_worker_memory(name: str, role: str, scope: str) -> str:
    """Load persistent memory from docs/workers/{name}.md or docs/workers/{role}.md.

    Workers write their learned rules here; the file survives kill/respawn/compact
    and is re-read whenever the prompt is (re)assembled.
    """
    base = Path(scope)
    for filename in (f"{name}.md", f"{role}.md" if role else None):
        if not filename:
            continue
        path = base / "docs" / "workers" / filename
        if path.is_file():
            try:
                content = path.read_text().strip()
                if content:
                    logger.info(f"Loaded worker memory: {path} ({len(content)} chars)")
                    return content
            except Exception as e:
                logger.warning(f"Failed to read worker memory {path}: {e}")
    return ""


def refresh_worker_memory(prompt: str, name: str, role: str, scope: str) -> str:
    """Re-read personal memory from disk and swap it into an already-assembled prompt.

    The prompt is assembled once (spawn / _load_from_db) but re-injected on every
    resume and compact, so without this the agent keeps receiving the memory as it
    was at the last server restart — measured in #137 as 11 of 13 live sessions
    carrying a stale block, the worst missing 61% of its own file.
    """
    mem = load_worker_memory(name, role, scope)
    block = f"<worker-memory>\n{mem}\n</worker-memory>" if mem else ""
    if _WORKER_MEMORY_BLOCK.search(prompt):
        # Replacement is a callable on purpose: memory is arbitrary user text and a
        # plain string would have its backslash escapes (\1, \g) expanded by re.
        # The pattern eats the leading newlines, so put the separator back with it.
        sep = f"\n\n{block}" if block else ""
        return _WORKER_MEMORY_BLOCK.sub(lambda _: sep, prompt, count=1).rstrip()
    return f"{prompt}\n\n{block}".rstrip() if block else prompt


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


def get_role_icons() -> dict[str, str]:
    """Role icons from the manifest (`roles.<name>.tg.emoji`) of the default pipeline.

    Role .md bodies are frontmatter-free, so the old `icon:` read returned {} on every
    call. `scripts/extract-manifest.py` maps frontmatter `icon` → `tg.emoji`, so the
    manifest is where that field lives now — and `load_pipeline` is cached, unlike the
    per-request directory scan this replaced.
    """
    from app.pipeline import DEFAULT_PIPELINE, load_pipeline

    cfg = load_pipeline(DEFAULT_PIPELINE)
    return {name: spec.tg.emoji for name, spec in cfg.roles.items() if spec.tg and spec.tg.emoji}


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


def inject_skills_to_worktree(
    skill_names: list[str], worktree_path: str, home_dir: str = ".claude",
) -> int:
    """Copy resolved pipeline skills into <path>/<home_dir>/skills/ as native CLI skills.

    Runs on every backend (re)connect, not just at worktree creation — a long-lived agent
    would otherwise keep the skill files from the day it was spawned, and a skill added to a
    role after spawn would never reach anyone. Same reasoning, same seam as `sync_agents_md`.

    ``home_dir`` is the only thing that differs between runtimes: Claude discovers skills in
    `.claude/skills/`, Codex in `.codex/skills/` (verified on codex-cli 0.145.0 — a project
    directory is searched upward from cwd alongside `$CODEX_HOME/skills` and `~/.agents/skills`,
    and the three sources are merged, not replaced). One mechanism, two addresses: a second
    copy of this function would be two places for the guards below to drift apart.

    ``worktree_path`` is the agent's worktree when it has one, otherwise its plain cwd —
    orchestrators run without a worktree, so a worktree-only path never delivered to them.
    That cwd is a REAL repository the user works in by hand, hence the two guards below.

    A repo that TRACKS `<home_dir>/skills/<name>/SKILL.md` owns that file: `info/exclude` cannot
    ignore a tracked path, so overwriting it leaves the tree dirty forever and blocks
    every merge. Such skills are left alone — the agent reads the repo's own version, which
    the CLI already loads from the same path.

    Returns the number of files actually written (unchanged copies are not rewritten, so a
    steady state costs zero writes and never swaps a file under a running CLI).
    """
    if not skill_names or not _SKILLS_DIR.is_dir():
        return 0
    wt = Path(worktree_path)
    rels = {sname: f"{home_dir}/skills/{sname}/SKILL.md" for sname in skill_names}
    try:
        tracked = tracked_paths(wt, list(rels.values()))
    except RuntimeError as exc:
        # Git failing (not a repo, ownership, broken worktree) proves nothing about who owns
        # these files. Writing on a guess is what dirties someone else's repository.
        logger.warning(f"{exc} — skill injection skipped for {wt}")
        return 0
    home = wt / home_dir
    if home.exists() and not home.is_dir():
        # Measured on a live repo: `Aperant` tracks a read-only zero-byte FILE named `.codex`.
        # `mkdir -p` then fails once per skill per connect. The repo owns that name — bail out
        # quietly rather than log the same failure five times forever or clobber their file.
        logger.info(f"'{home}' exists and is not a directory — skill injection skipped")
        return 0
    injected = 0
    for sname in skill_names:
        skill_src = _SKILLS_DIR / f"{sname}.md"
        if not skill_src.exists():
            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
            continue
        if rels[sname] in tracked:
            logger.info(f"Skill '{sname}' is tracked by the repo at {wt} — injection skipped")
            continue
        dest = wt / home_dir / "skills" / sname / "SKILL.md"
        if dest.is_symlink():
            logger.warning(f"Skill '{sname}' at {dest} is a symlink — skipped (copy would clobber its target)")
            continue
        try:
            if dest.is_file() and dest.read_bytes() == skill_src.read_bytes():
                continue
        except OSError as exc:
            logger.warning(f"Skill '{sname}' at {dest} unreadable ({exc}) — rewriting")
        _run_as_agent(["mkdir", "-p", str(dest.parent)], capture_output=True)
        # tmp + mv: `cp` onto a live file lets the CLI read a half-written skill. `mv` within
        # the same directory is atomic, so a reader sees either the old file or the new one.
        tmp = dest.parent / f".SKILL.md.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            _run_as_agent(["cp", "-p", str(skill_src), str(tmp)], capture_output=True)
            moved = _run_as_agent(["mv", "-f", str(tmp), str(dest)], capture_output=True)
            if moved.returncode != 0:
                logger.warning(f"Skill '{sname}' install failed at {dest}")
                continue
        finally:
            if tmp.exists():
                _run_as_agent(["rm", "-f", str(tmp)], capture_output=True)
        injected += 1
    if injected:
        # Only after actually planting something, and only the directory we wrote — this path
        # may be the user's working repository, where adding unrelated ignore rules is a side
        # effect we have no mandate for. Without this, a repo that ignores neither `.claude/`
        # nor `.codex/` (games and seedon ignore neither) gets permanent untracked junk in the
        # user's `git status`.
        try:
            _exclude_worktree_artifacts(wt, only=(f"{home_dir}/",))
        except Exception as exc:
            logger.warning(f"could not exclude {home_dir}/ in {wt}: {exc}")
        # Path is logged, not just the count: whether a CLI actually discovers this directory
        # is not something we detect (see ORCHESTRA_CODEX_SKILL_INDEX). If an agent turns out
        # to have no skills, this line is the evidence of where they were put.
        logger.info(f"Injected {injected} skills into {worktree_path}/{home_dir}/skills/")
    return injected


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
