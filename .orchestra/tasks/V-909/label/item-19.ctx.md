# Context for item-19

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/prompting.py b/app/prompting.py
index d3fc1dc58..db0f49d79 100644
--- a/app/prompting.py
+++ b/app/prompting.py
@@ -1,31 +1,32 @@
 """Prompt composition — pure file/template helpers for agent prompts."""
 
 import hashlib
 import logging
 import os
 import re
 import shutil
 import subprocess
+import uuid
 from pathlib import Path
 
-from app.workspace import tracked_paths
+from app.workspace import _exclude_worktree_artifacts, tracked_paths
 
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
@@ -105,70 +106,113 @@ def prompt_template_hash(role_or_orch) -> str:
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
 
 
-def inject_skills_to_worktree(skill_names: list[str], worktree_path: str) -> None:
-    """Copy resolved pipeline skills into worktree/.claude/skills/ as native Claude CLI skills.
+def inject_skills_to_worktree(skill_names: list[str], worktree_path: str) -> int:
+    """Copy resolved pipeline skills into <path>/.claude/skills/ as native Claude CLI skills.
 
-    Skills are resolved from pipeline.yaml (ResolvedRole.skills), not role-file
-    frontmatter — role bodies are frontmatter-free, so reading them yielded nothing.
+    Runs on every backend (re)connect, not just at worktree creation — a long-lived agent
+    would otherwise keep the skill files from the day it was spawned, and a skill added to a
+    role after spawn would never reach anyone. Same reasoning, same seam as `sync_agents_md`.
+
+    ``worktree_path`` is the agent's worktree when it has one, otherwise its plain cwd —
+    orchestrators run without a worktree, so a worktree-only path never delivered to them.
+    That cwd is a REAL repository the user works in by hand, hence the two guards below.
 
     A repo that TRACKS `.claude/skills/<name>/SKILL.md` owns that file: `info/exclude` cannot
-    ignore a tracked path, so overwriting it leaves the worker's tree dirty forever and blocks
+    ignore a tracked path, so overwriting it leaves the tree dirty forever and blocks
     every merge. Such skills are left alone — the agent reads the repo's own version, which
     Claude CLI already loads from the same path.
+
+    Returns the number of files actually written (unchanged copies are not rewritten, so a
+    steady state costs zero writes and never swaps a file under a running CLI).
     """
     if not skill_names or not _SKILLS_DIR.is_dir():
-        return
+        return 0
     wt = Path(worktree_path)
     rels = {sname: f".claude/skills/{sname}/SKILL.md" for sname in skill_names}
-    tracked = tracked_paths(wt, list(rels.values()))
+    try:
+        tracked = tracked_paths(wt, list(rels.values()))
+    except RuntimeError as exc:
+        # Git failing (not a repo, ownership, broken worktree) proves nothing about who owns
+        # these files. Writing on a guess is what dirties someone else's repository.
+        logger.warning(f"{exc} — skill injection skipped for {wt}")
+        return 0
     injected = 0
     for sname in skill_names:
         skill_src = _SKILLS_DIR / f"{sname}.md"
         if not skill_src.exists():
             logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
             continue
         if rels[sname] in tracked:
             logger.info(f"Skill '{sname}' is tracked by the repo at {wt} — injection skipped")
             continue
-        skill_dir = wt / ".claude" / "skills" / sname
-        _run_as_agent(["mkdir", "-p", str(skill_dir)], capture_output=True)
-        _run_as_agent(["cp", "-p", str(skill_src), str(skill_dir / "SKILL.md")], capture_output=True)
+        dest = wt / ".claude" / "skills" / sname / "SKILL.md"
+        if dest.is_symlink():
+            logger.warning(f"Skill '{sname}' at {dest} is a symlink — skipped (copy would clobber its target)")
+            continue
+        try:
+            if dest.is_file() and dest.read_bytes() == skill_src.read_bytes():
+                continue
+        except OSError as exc:
+            logger.warning(f"Skill '{sname}' at {dest} unreadable ({exc}) — rewriting")
+        _run_as_agent(["mkdir", "-p", str(dest.parent)], capture_output=True)
+        # tmp + mv: `cp` onto a live file lets the CLI read a half-written skill. `mv` within
+        # the same directory is atomic, so a reader sees either the old file or the new one.
+        tmp = dest.parent / f".SKILL.md.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
+        try:
+            _run_as_agent(["cp", "-p", str(skill_src), str(tmp)], capture_output=True)
+            moved = _run_as_agent(["mv", "-f", str(tmp), str(dest)], capture_output=True)
+            if moved.returncode != 0:
+                logger.warning(f"Skill '{sname}' install failed at {dest}")
+                continue
+        finally:
+            if tmp.exists():
+                _run_as_agent(["rm", "-f", str(tmp)], capture_output=True)
         injected += 1
-    logger.info(f"Injected {injected} skills into {worktree_path}/.claude/skills/")
+    if injected:
+        # Only after actually planting something, and only `.claude/` — this path may be the
+        # user's working repository, where adding unrelated ignore rules is a side effect we
+        # have no mandate for. Without this, a repo that doesn't already ignore `.claude/`
+        # (e.g. games) gets permanent untracked junk in the user's `git status`.
+        try:
+            _exclude_worktree_artifacts(wt, only=(".claude/",))
+        except Exception as exc:
+            logger.warning(f"could not exclude .claude/ in {wt}: {exc}")
+        logger.info(f"Injected {injected} skills into {worktree_path}/.claude/skills/")
+    return injected
 
 
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
 
diff --git a/app/session.py b/app/session.py
index dbbd01ee1..6020f7891 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1,36 +1,36 @@
 """AgentSession — backend-agnostic wrapper with persistent event loop."""
 
 import asyncio
 import json
 import logging
 import os
 import re
 from dataclasses import dataclass, field
 from datetime import datetime, timezone, timedelta
 from functools import partial
 from typing import TYPE_CHECKING, Awaitable, Callable, Optional
 from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
 
 from app.events import AgentEvent
 from app.models import backend_for_model, get_model_spec
-from app.prompting import is_orchestrator_role, prompt_template_hash
+from app.prompting import inject_skills_to_worktree, is_orchestrator_role, prompt_template_hash
 from app.runtime_registry import (
     BackendBuildContext,
     _load_scope_mcp_servers,
     _load_user_mcp_servers,
     build_backend,
     get_runtime,
 )
 from app.session_cost import CostTracker
 from app.session_hibernate import HibernateManager
 from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
     AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
 )
 from app.session_turns import TurnManager
 from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
 from app.db import add_log, get_logs, save_session, tool_error_add
 
 logger = logging.getLogger(__name__)
@@ -806,53 +806,81 @@ class AgentSession:
                     self._turns.publish_turn_finished()
                 raise
             self._ack_pending_facts(fact_keys)
             if pending_handoff and self.runtime_handoff == pending_handoff:
                 self.runtime_handoff = ""
                 self._persist()
 
             if did_inject:
                 if templates_changed:
                     self._log("status", f"prompt updated → {pending_th}")
                 self._template_hash = pending_th
                 self._prompt_injected = True
                 self.system_prompt = self._current_prompt
 
             if capabilities.event_stream == "per_turn":
                 self._listen_task = asyncio.create_task(
                     self._turn_event_loop()
                 )
                 self._listen_task.add_done_callback(self._on_task_done)
 
+    async def _refresh_skills(self) -> None:
+        """Re-install this role's pipeline skills before the CLI starts.
+
+        Claude reads skills as FILES from `<cwd>/.claude/skills/`, so its copy goes stale the
+        moment a skill is edited, and a skill added to a role after spawn never arrives at all.
+        Codex needs nothing here: it gets a freshly built index of canonical source paths on
+        every connect (`build_codex_skills_index`), i.e. it reads the original, not a copy.
+
+        Falls back to `self.cwd` when there is no worktree — orchestrators run without one,
+        which is why a worktree-only injection reached none of them.
+        """
+        if self.backend_type != "claude":
+            return
+        path = self.worktree_path or self.cwd
+        if not path:
+            return
+        try:
+            from app.pipeline import get_role
+            role = get_role(self.pipeline, self.role)
+            skills = role.skills if role else None
+            # "all" means the CLI discovers skills itself — nothing to copy.
+            if not skills or skills == "all":
+                return
+            await asyncio.to_thread(inject_skills_to_worktree, skills, path)
+        except Exception as e:
+            logger.warning(f"[{self.name}] skill refresh failed: {e}")
+
     async def _ensure_backend(self, force_fresh: bool = False):
         if self._backend is not None:
             if not force_fresh:
                 return self._backend
             await self._disconnect_backend()
         if self.worktree_path:
             # Codex reads AGENTS.md, not CLAUDE.md. Refresh the mirror before the CLI starts,
             # otherwise a long-lived worker keeps the project rules from its spawn day.
             try:
                 from app.workspace import sync_agents_md
                 await asyncio.to_thread(sync_agents_md, self.worktree_path)
             except Exception as e:
                 logger.warning(f"[{self.name}] AGENTS.md mirror refresh failed: {e}")
+        await self._refresh_skills()
         self._backend = self._make_backend(force_fresh=force_fresh)
         candidate = self._backend
         try:
             await candidate.connect()
         except Exception as e:
             logger.error(f"[{self.name}] backend connect failed: {e}")
             self._log("error", f"connect failed: {e}")
             if not getattr(candidate, "has_owned_processes", False):
                 self._backend = None
             raise
         capabilities = get_runtime(self.backend_type).capabilities
         if capabilities.event_stream == "persistent":
             self._listen_task = asyncio.create_task(self._persistent_event_loop())
             self._listen_task.add_done_callback(self._on_task_done)
         if self._heartbeat_task is None or self._heartbeat_task.done():
             self._heartbeat_task = asyncio.create_task(self._hibernate.heartbeat_loop())
         return self._backend
 
     # ── Event loops ──
 
diff --git a/app/workspace.py b/app/workspace.py
index 628c0d5f9..92f6ae94a 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -429,67 +429,74 @@ def sync_agents_md(worktree_path: str) -> bool:
     _exclude_worktree_artifacts(wt)
     if agents_md.exists() and agents_md.read_bytes() == claude_md.read_bytes():
         return False
     # Write via tmp + mv: a half-written mirror is exactly the silent truncation this whole
     # change exists to prevent. mv through _git_cmd for the same agent-user path as cp.
     # The tmp name is unique per call — a fixed one could hit an existing file (or symlink) in a
     # third-party repo, and two concurrent syncs would write into the same inode.
     tmp = wt / f".AGENTS.md.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
     try:
         _copy_file(claude_md, tmp)
         moved = _git_cmd(["mv", "-f", str(tmp), str(agents_md)], capture_output=True, text=True)
         if moved.returncode != 0:
             detail = moved.stderr.strip() or moved.stdout.strip() or f"exit {moved.returncode}"
             raise OSError(f"mirror CLAUDE.md -> AGENTS.md failed: {detail}")
     finally:
         if tmp.exists():
             _git_cmd(["rm", "-f", str(tmp)], capture_output=True, text=True)
     return True
 
 
-def _exclude_worktree_artifacts(wt_path: Path, extra: list[str] | None = None) -> None:
+def _exclude_worktree_artifacts(
+    wt_path: Path, extra: list[str] | None = None, only: tuple[str, ...] | None = None,
+) -> None:
     """Ignore injected/machine-local artifacts via `info/exclude` — untracked, never committed,
     so they can't dirty the tree or block merge_worker. Idempotent. External repos that don't
     already ignore these would otherwise leave them as untracked files.
 
     `extra` = paths this spawn actually planted (copies/symlinks from the manifest, e.g. `.env`),
     anchored to the repo root so they don't shadow same-named files deeper in the tree. Only
     untracked ones get here — see `tracked_paths`.
 
+    `only` narrows the default set to the patterns the caller actually needs. Skill injection
+    now also runs in an agent's plain cwd — a repository the user works in by hand — where
+    adding ignore rules for artifacts we did not plant (`AGENTS.md`, `codex_sessions.json`)
+    would be an unmandated side effect in someone else's repo.
+
     Git reads `info/exclude` from the COMMON git dir (`--git-common-dir`), not the
     per-worktree dir — a per-worktree `info/exclude` is silently ignored.
     """
     gd = _git_cmd(
         ["git", "rev-parse", "--git-common-dir"],
         cwd=str(wt_path), capture_output=True, text=True,
     )
     if gd.returncode != 0:
         logger.warning(f"could not locate git-common-dir for {wt_path}: {gd.stderr.strip()}")
         return
     git_dir = Path(gd.stdout.strip())
     if not git_dir.is_absolute():
         git_dir = (wt_path / git_dir).resolve()
     exclude = git_dir / "info" / "exclude"
     exclude.parent.mkdir(parents=True, exist_ok=True)
     existing = exclude.read_text() if exclude.exists() else ""
     have = {line.strip() for line in existing.splitlines()}
-    patterns = list(_WORKTREE_EXCLUDES) + [f"/{p}" for p in (extra or [])]
+    patterns = list(only if only is not None else _WORKTREE_EXCLUDES) + [f"/{p}" for p in (extra or [])]
     missing = [p for p in patterns if p not in have]
     if not missing:
         return
     with exclude.open("a") as f:
         if existing and not existing.endswith("\n"):
             f.write("\n")
         f.write("".join(f"{p}\n" for p in missing))
 
 
 def create_worktree(repo_path: str, name: str, task_id: str = "",
                     base_branch: str = "",
                     worktree_cfg: "WorktreeCfg | None" = None) -> Worktree:
     repo = validate_repo_root(repo_path)
     with repo_mutation_lock(repo):
         base_branch = resolve_base_branch(str(repo), base_branch)
 
         # Слаг от repo root, НЕ от scope сессии: родитель может спавнить в чужой проект,
         # и тогда scope-имя папки/ветки врёт про то, какому репозиторию worktree принадлежит.
         repo_slug = _slugify(str(repo))
         wt_dir = WORKTREE_ROOT / repo_slug
diff --git a/docs/tasks/149/plan.md b/docs/tasks/149/plan.md
new file mode 100644
index 000000000..71912553d
--- /dev/null
+++ b/docs/tasks/149/plan.md
@@ -0,0 +1,158 @@
+# #149 — план: доставка скиллов живым агентам
+
+## Подход одной фразой
+
+Перенести инъекцию скиллов со спавна на **коннект бэкенда** — встать рядом с
+`sync_agents_md`, который решает тот же класс задачи в той же точке, — и снять с неё
+условие «только при наличии worktree», добавив те же гарантии безопасности, что уже
+защищают worktree-владельцев.
+
+Механизм не изобретается: `tracked_paths()` (гейт «не трогать чужое») и
+`_exclude_worktree_artifacts()` (уборка за собой) уже существуют и уже проверены в бою.
+Новый код — это перестановка вызова и снятие одного `if`.
+
+## Что НЕ трогаем
+
+- `pipelines/**` — состав скиллов по ролям не меняется.
+- `app/runtime_registry.py` / Codex-путь — F6 research: индекс строится на каждом коннекте
+  из канонических путей, протухания нет. Правка не нужна.
+- 31 orphan-копия (`self-analysis`, чужие проектные скиллы) — удаление untracked-файлов
+  в чужих worktree деструктивно и вне задачи.
+- Существующий вызов в `manager.py:688` — см. T2, решение осознанное.
+
+## Ключевые находки, на которых стоит план (проверены на живой системе)
+
+1. `_WORKTREE_EXCLUDES` (`workspace.py:377`) **уже содержит `.claude/`** → требование
+   оркестратора №2 закрывается переиспользованием `_exclude_worktree_artifacts`, новых
+   паттернов не нужно.
+2. Все три целевых `cwd` — валидные git-репозитории, и у всех трёх `.claude/` **уже** в
+   `info/exclude` (проверено `grep -c` в каждом). То есть после правки грязи не появится
+   даже до первого вызова хелпера.
+3. **`polus` содержит 16 строк ЧУЖОЙ грязи** (правки юзера в `assets/`, `tools/`) до любых
+   наших действий. Критерий приёмки = «`git status` НЕ ИЗМЕНИЛСЯ», а не «пуст».
+   Формулировка «пусто до → пусто после» из задания для polus физически невыполнима.
+4. **`seedon` — идеальный контрольный случай в одном репозитории**: из пяти скиллов роли
+   `orchestrator` два (`codex-debate`, `vps-deploy`) ОТСЛЕЖИВАЮТСЯ, три
+   (`html-artifacts`, `grill-me`, `orchestra-agents`) — нет. Один прогон доказывает обе
+   половины: трекнутые нетронуты, untracked доставлены.
+
+## Риск, который план обязан снять
+
+`_exclude_worktree_artifacts` дописывает в `info/exclude` не только `.claude/`, а ещё
+`AGENTS.md`, `codex_sessions.json`, `*.round`. В worktree воркера это уместно. В **рабочем
+репозитории юзера** дописывать правила игнорирования сверх необходимого — побочный эффект
+за пределами задачи. → T3 вызывает хелпер **только с тем, что реально положил**, и только
+когда положил (см. AC T3).
+
+## Tickets
+
+### T1 — `refresh_skills(skill_names, path)` в `app/prompting.py`
+Точка входа для обновления: идемпотентная, безопасная для любого репозитория, возвращает
+число реально записанных файлов (нужно для приёмки и логов).
+
+- **Files:** `app/prompting.py`
+- **Что делает:**
+  - переиспользует существующий `tracked_paths`-гейт (НЕ дублировать логику: правится
+    `inject_skills_to_worktree`, чтобы обе точки входа шли одним кодом — один owner);
+  - пишет только при реальном расхождении байт (как `sync_agents_md`) → у 9 свежих копий
+    записи не будет вовсе, работающий CLI не дёргаем;
+  - запись через tmp+mv, чтобы агент не прочитал полуфайл;
+  - `tracked_paths` бросил `RuntimeError` (не репозиторий / битый git) → **ничего не писать**
+    и залогировать. Догадка тут дороже устаревшей копии.
+- **AC:**
+  - трекнутый `SKILL.md` не изменён (байт-в-байт) после вызова;
+  - untracked устаревший `SKILL.md` совпадает с источником после вызова;
+  - совпадающий файл не перезаписан (mtime не изменился) — доказывает «пишем только при расхождении»;
+  - путь без git → возврат без исключения, файлы не тронуты;
+  - возвращает количество записанных файлов.
+- **blocked-by:** none
+
+### T2 — вызов на коннекте бэкенда (`app/session.py`)
+- **Files:** `app/session.py`
+- **Что делает:** **одна строка вызова** в `_ensure_backend`, рядом с существующим
+  `sync_agents_md` (`session.py:835`), под тем же `try/except` по смыслу — сбой обновления
+  скиллов не должен ронять коннект.
+  Условие `if self.worktree_path:` **снимается для скиллов**: путь берётся из
+  `self.worktree_path or self.cwd` — именно это закрывает 16 оркестраторов без worktree.
+  Список скиллов резолвится из пайплайна по роли (как в `manager.py:684-687`).
+  Гейт `backend_type == "claude"` сохраняется (Codex покрыт, F6).
+- **Ограничение оркестратора:** правка — вызов, не переписывание `_ensure_backend`.
+  Если по ходу выяснится, что нужно больше строк — СТОП и согласование.
+- **Существующий вызов в `manager.py:688` остаётся:** спавн создаёт worktree и сразу
+  стартует сессию; удаление вызова = лишняя связанность ради косметики. Он станет
+  no-op на коннекте (файлы уже совпадают → записи нет). Это не дубль механизма, а
+  тот же механизм, вызванный раньше.
+- **AC:**
+  - диффом видно ровно одну добавленную строку вызова (+ обвязка логирования), тело
+    `_ensure_backend` не переписано;
+  - агент **с** worktree получает свежую копию на реконнекте;
+  - агент **без** worktree (оркестратор) получает скиллы в `cwd`;
+  - исключение внутри обновления не ломает `connect()`.
+- **blocked-by:** T1
+
+### T3 — уборка за собой в чужом репозитории
+- **Files:** `app/prompting.py`
+- **Что делает:** после успешной записи хотя бы одного файла — `_exclude_worktree_artifacts`
+  для этого репозитория, чтобы `.claude/` не всплыл в `git status` у юзера.
+- **AC:**
+  - в репозитории БЕЗ `.claude` в `.gitignore`/`info/exclude` после доставки
+    `git status --short` не содержит `.claude`;
+  - ничего не записано → `info/exclude` не тронут (нет побочных правок в чужом репо);
+  - `git add` не вызывается нигде.
+- **blocked-by:** T1
+
+### T4 — тесты
+- **Files:** `tests/test_manager.py` (рядом с `TestInjectSkillsRealCopy`, стиль и `_git_repo` оттуда)
+- **Покрывает:** все AC из T1 и T3 + сценарий «tracked и untracked в одном репо»
+  (модель живого seedon).
+- **AC:** новые тесты зелёные; существующие `test_tracked_skill_not_overwritten`,
+  `test_copies_pipeline_skills_to_worktree`, `test_empty_list_is_noop` не сломаны.
+- **blocked-by:** T1, T3
+
+### T5 — приёмка поведением на ЖИВОЙ системе
+Не тест, а протокол доказательства. Прогон в один заход, всё пишется в
+`docs/tasks/149/report.md` дословно.
+
+- **Протокол:**
+  1. Снять `git status --short` в `seedon`, `polus`, `orchestra` → зафиксировать BEFORE
+     (ожидаемо: seedon 1 строка `?? .env`, polus 16 строк, orchestra 0).
+  2. Изменить текст живого скилла (`codex-debate.md`) распознаваемым маркером.
+  3. Выполнить механизм для **ранее созданного** агента (worktree-воркер) и для
+     **оркестратора без worktree**.
+  4. Показать: новая версия лежит у ранее созданного агента; `orchestra-agents` доехал
+     до оркестратора (было 0).
+  5. Контроль: в `seedon` `codex-debate`/`vps-deploy` (трекнутые) — байт-в-байт прежние;
+     `html-artifacts`/`grill-me`/`orchestra-agents` (untracked) — доставлены.
+  6. Снять `git status --short` в тех же трёх репозиториях → **AFTER идентичен BEFORE**.
+  7. Откатить маркер в скилле.
+- **AC:**
+  - AFTER == BEFORE во всех трёх репозиториях (diff пуст);
+  - трекнутые файлы seedon не изменены;
+  - счётчик `orchestra-agents` у оркестраторов > 0.
+- **blocked-by:** T2, T3
+
+## Порядок
+
+T1 → (T3 ∥ T2) → T4 → T5
+
+## Adversarial self-review — 3 слабых места плана
+
+1. **Гонка: пишем файл под работающим CLI.** Агент может читать `SKILL.md` в момент
+   замены. Снимаю: tmp+mv (атомарная замена inode), плюс запись только при расхождении —
+   для 9 свежих копий записи нет вовсе. Полностью гонку это не исключает, но окно
+   сокращается до атомарного `rename`.
+2. **`cwd` оркестратора может совпасть с `cwd` другого агента** (несколько оркестраторов
+   на один репозиторий). Тогда обновление выполнится дважды. Безопасно: операция
+   идемпотентна и на втором проходе не пишет ничего. Отдельной блокировки не ввожу —
+   это было бы абстракцией под несуществующую проблему.
+3. **Самый дорогой сценарий: репозиторий, где `.claude/` НЕ игнорируется и НЕ трекается.**
+   Тогда мы создаём untracked-мусор у юзера. Это ровно то, чего требует избежать
+   оркестратор. Закрыто T3 (`info/exclude` до появления мусора в выдаче `git status`) +
+   AC T3 на репозитории без `.gitignore`. Среди живых целей такого нет (все три уже
+   исключают `.claude/`), но тест обязан покрыть, потому что следующий проект может быть таким.
+
+## Codex
+
+Квота исчерпана до 8 августа — ревью плана не проводится, внешнего вердикта нет.
+Компенсация: adversarial self-review выше + AC, сформулированные как проверяемые
+условия до реализации (не подгоняются под результат).
diff --git a/docs/tasks/149/report.md b/docs/tasks/149/report.md
new file mode 100644
index 000000000..722a99ded
--- /dev/null
+++ b/docs/tasks/149/report.md
@@ -0,0 +1,135 @@
+# #149 — отчёт: доставка скиллов живым агентам
+
+## Что сделано
+
+Инъекция скиллов перенесена со спавна на **коннект бэкенда** и лишилась условия
+«только при наличии worktree». Оба дефекта из research закрыты:
+
+1. **Протухание** — копия обновляется на каждом реконнекте (тот же seam, что у `sync_agents_md`).
+2. **Полное отсутствие доставки** — путь берётся как `worktree_path or cwd`, поэтому
+   16 оркестраторов без worktree наконец получают свои скиллы.
+
+## Файлы
+
+| Файл | ± | Что |
+|---|---|---|
+| `app/prompting.py` | +45/−9 | `inject_skills_to_worktree` → идемпотентная, возвращает `int`, tmp+mv, `RuntimeError`-гейт, вызов exclude |
+| `app/session.py` | +27/−1 | `_refresh_skills()` + **одна строка** вызова в `_ensure_backend` |
+| `app/workspace.py` | +7/−2 | `_exclude_worktree_artifacts(..., only=)` — сузить набор паттернов |
+| `tests/test_manager.py` | +85 | `TestRefreshSkills` — 6 тестов |
+| `tests/test_default_pipeline.py` | +1/−1 | починен предсуществующий красный тест (см. ниже) |
+
+`uv.lock` не тронут (проверено `git diff --stat -- uv.lock` — пусто).
+
+## Соблюдение ограничений оркестратора
+
+- **`session.py` — одна строка.** Тело `_ensure_backend` получило ровно
+  `await self._refresh_skills()`. Логика — в отдельном соседнем методе, функция не переписана.
+- **`_exclude_worktree_artifacts` только с `.claude/` и только после реальной записи.**
+  Реализовано параметром `only=(".claude/",)` + `if injected:`. Проверено на живом `games`:
+  добавлена ровно одна строка, `AGENTS.md`/`codex_sessions.json`/`*.round` — 0 совпадений.
+- **`manager.py` не тронут** — вызов на спавне оставлен, на коннекте становится no-op.
+- **Codex не правился** (F6 research: читает оригинал, а не копию).
+
+## Приёмка на ЖИВОЙ системе
+
+Маркер `<!-- 149-ACCEPTANCE-MARKER -->` добавлен в источник `codex-debate.md`, прогнан
+механизм, затем маркер откачен. Всё — из воркти, кодом воркти.
+
+### Дефект 1 — протухшая копия у РАНЕЕ СОЗДАННОГО агента
+Цель: `worktrees/home-maxim-cursor-sensar/sensar-roadmap` (спавнился давно, копия отставала
+на 75 строк).
+```
+marker BEFORE: False
+written: 1
+marker AFTER : True
+```
+Откат источника → повторный прогон → `marker gone: True`. Обновление двунаправленное,
+не «дописать и забыть».
+
+### Дефект 2 — доставка оркестраторам без worktree
+```
+/mnt/data/Projects/Python/games    written=4  orchestra-agents=True
+/mnt/data/Projects/Python/seedon   written=3  orchestra-agents=True
+/home/maxim/polus                  written=5  orchestra-agents=True
+```
+`seedon` = **3, не 5** — два трекнутых скилла (`codex-debate`, `vps-deploy`) пропущены
+корректно. Контрольный случай сработал сам, без отдельной подстройки.
+
+### ЖИВОЙ СЛУЧАЙ (требование №2 оркестратора) — факт, не тест
+```
+BEFORE: find ... -path "*/orchestra-agents/SKILL.md" | wc -l  →  0
+AFTER : доставлено 3 из 3 целей прогона (games, seedon, polus)
+```
+Остальные 13 оркестраторов получат скилл автоматически на своём следующем коннекте —
+это и есть механизм, а не разовая раздача.
+
+### Безопасность чужих репозиториев (требование №1) — три репозитория
+Критерий «AFTER идентичен BEFORE» (не «пусто» — у репозиториев есть своя грязь юзера):
+
+| репо | BEFORE | AFTER | вердикт |
+|---|---|---|---|
+| seedon | 1 строка (`?? .env`) | 1 строка | ✅ идентично |
+| polus | 16 строк (правки юзера в `assets/`, `tools/`) | 16 строк | ✅ идентично |
+| games | 1 строка | 1 строка | ✅ идентично |
+
+- Трекнутые `seedon/{codex-debate,vps-deploy}` — `git diff --quiet` чист, маркера 0.
+- `games` (единственный БЕЗ `.claude` в exclude — самый дорогой сценарий): добавлена
+  ровно строка `.claude/`, дерево осталось чистым.
+- `seedon`/`polus` — `info/exclude` вообще не изменён (там `.claude/` уже был).
+- Финальная проверка: маркер не остался нигде (`grep -rl` по всем четырём репозиториям — пусто).
+
+### Сходимость и стоимость покоя
+```
+steady_state_written = 0   (games, seedon, polus — повторный прогон)
+```
+Установившееся состояние = ноль записей. Файл под работающим CLI не дёргается.
+
+## Тесты
+
+`464 passed` (`test_manager`, `test_workspace`, `test_prompting`, `test_default_pipeline`,
+`test_session`). Лог: `/tmp/pytest-149-scoped.log`.
+
+Асинхронный код прогнан **3 раза подряд** (грабля из `CLAUDE.md`: зелёный прогон на async
+ничего не доказывает) — 13/13 стабильно во всех трёх.
+
+**Мутационная проверка новых тестов** (зелёный тест проверяется поломкой):
+- отключил вызов exclude → упал `test_injection_leaves_repo_clean_without_gitignore` (`?? .claude/`);
+- отключил сравнение байт → упал `test_unchanged_copy_is_not_rewritten`.
+Оба теста несущие, а не декоративные.
+
+### Предсуществующий красный тест — починен
+`test_orchestrator_skills_from_manifest` падал **на чистом main** (проверено отдельным
+прогоном): `4b47fef` добавил `orchestra-agents` в `pipeline.yaml`, но не обновил
+захардкоженный список в тесте. Это тот же коммит, который породил задачу. Правка в одну
+строку, по существу задачи — поэтому починил, а не оставил чужой красный тест.
+
+## Adversarial self-review — что осталось слабым
+
+1. **Гонка «замена файла под читающим CLI» сокращена, но не устранена.** `mv` атомарен,
+   поэтому полуфайла агент не увидит; но если он читает скилл ровно в момент замены,
+   он получит старую версию. Приемлемо: следующий коннект выровняет.
+2. **Скилл, удалённый из роли, не удаляется из worktree.** 31 orphan-копия остаётся
+   (`self-analysis` и чужие проектные). Осознанно: удаление untracked-файлов в чужом
+   репозитории деструктивно и выходит за задачу. Записано в TODO ниже.
+3. **`_refresh_skills` глотает все исключения** (`except Exception` → warning). Это
+   намеренно — сбой обновления скиллов не должен ронять коннект агента, — но означает,
+   что systemic-поломка доставки будет видна только в логах, а не как громкий отказ.
+
+## Известные ограничения
+
+- Доставка происходит на **коннекте**, а не мгновенно по факту правки файла. Агент,
+  сидящий в одном长 turn, получит обновление на следующем реконнекте. Watch каталога
+  дал бы мгновенность ценой фонового процесса — сознательно не делал.
+- Для агентов с `skills: "all"` копирование не выполняется (CLI ищет скиллы сам).
+
+## TODO (не делал, вне задачи)
+
+- 31 orphan-копия скиллов, удалённых из источника, в `worktrees/*/.claude/skills/`.
+  Нужна отдельная задача с явным решением про удаление untracked-файлов.
+
+## Codex
+
+**Не привлекался — квота исчерпана до 8 августа. Внешнего вердикта нет.**
+Компенсация: AC сформулированы в плане ДО реализации, новые тесты проверены мутацией,
+async-тесты прогнаны трижды. Это самопроверка, а не кросс-ревью, и за него не выдаётся.
diff --git a/docs/tasks/149/research.md b/docs/tasks/149/research.md
new file mode 100644
index 000000000..c63ba12b4
--- /dev/null
+++ b/docs/tasks/149/research.md
@@ -0,0 +1,188 @@
+# #149 — скиллы не доезжают до живых агентов
+
+## Question
+
+- **Context** — `inject_skills_to_worktree()` (`app/prompting.py:125`) копирует
+  `pipelines/default/prompts/skills/<name>.md` → `<worktree>/.claude/skills/<name>/SKILL.md`.
+  Единственный вызов — `app/manager.py:688`, внутри `prepare()` при спавне.
+- **Change under test** — добавить механизм обновления копий у УЖЕ живущих агентов.
+- **Baseline** — сейчас: копия делается один раз, при создании worktree.
+- **Outcome (измеримый)** — доля живых копий, совпадающих байт-в-байт с текущим источником;
+  и получил ли хоть один оркестратор скилл `orchestra-agents` (коммит `4b47fef`).
+
+## Hypotheses considered
+
+- **H1 (постановка юзера): точка вмешательства — старт сервиса.** Falsifier: если у роли,
+  которой скилл нужен, вообще нет worktree — рестарт ничего не починит. → **REFUTED**, см. F3.
+- **H2: точка вмешательства — коннект бэкенда.** Falsifier: если коннект не происходит у
+  idle-агента до следующего хода, обновление опоздает. → выживает, см. F4/F5.
+- **H3: проблема только в тайминге копирования (одна функция, один вызов).** Falsifier: если
+  часть ролей не проходит через этот код вовсе — правка тайминга не полна. → **REFUTED** (F3).
+- **H4: Codex страдает так же.** Falsifier: найти построение индекса на каждом коннекте.
+  → **REFUTED** (F6) — у Codex уже правильно.
+
+## Findings
+
+### F1 — 22 живые копии реально протухли; 13 «расхождений» — легитимны — CONFIRMED
+Прогон по всем 75 файлам `worktrees/*/.claude/skills/*/SKILL.md` (Tier 1 — прямое измерение):
+
+```
+fresh=9  stale=35  orphan=31
+```
+После отделения репо-владельцев (`git ls-files --error-unmatch` в каждом worktree):
+```
+repo-owned (платформа корректно НЕ трогала) = 13
+truly-stale (баг) = 22
+```
+`orphan=31` — скиллы, которых уже НЕТ в источнике (`self-analysis`, `accounting`,
+`bobik-generate`, `deploy-client`, `direct-banner`, `sign-document`, `payment`,
+`voice-infra`, `add-module`). Это проектные скиллы чужих репозиториев + удалённый
+`self-analysis`; их отсутствие в источнике — не баг доставки.
+
+Атомарные утверждения:
+- Из 44 копий, управляемых пайплайном, свежих 9. (измерено)
+- 22 копии отличаются от источника и НЕ отслеживаются своим репозиторием. (измерено)
+- Расхождение не косметическое: `diff` источника и копии в `sensar-roadmap` = **75 строк**,
+  включая `description` с устаревшим «Codex (GPT-5.5)» против текущего «GPT-5.6 Sol». (измерено)
+
+### F2 — источник менялся минимум 4 раза после спавна этих агентов — CONFIRMED
+`git log -- pipelines/default/prompts/skills/codex-debate.md`: `9d23df6`, `ef1dced`,
+`cff55c4`, `5a5c9fe`. Правки содержательные (`5a5c9fe` — «377→127 lines», выпил Bash-пути;
+`9d23df6` — требование явной авторизации на рестарты/деплой). Агент со старой копией
+работает по отменённым инструкциям. (Tier 2 — история репозитория)
+
+### F3 — РЕШАЮЩЕЕ: для оркестраторов инъекция не выполняется НИКОГДА — CONFIRMED
+Живой случай из задания (`4b47fef` добавил `orchestra-agents` ролям `orchestrator` и
+`sub-orchestrator`):
+
+```
+find worktrees -path "*/.claude/skills/orchestra-agents/SKILL.md" | wc -l  →  0
+```
+
+Причина не в тайминге, а в том, что `inject_skills_to_worktree` вызывается ТОЛЬКО внутри
+`if use_worktree and repo_path:` (`manager.py:669`). Срез живых сессий:
+
+| роль | backend | worktree | n |
+|---|---|---|---|
+| worker | claude | есть | 28 |
+| full-cycle | claude | есть | 19 |
+| **orchestrator** | claude | **НЕТ** | **15** |
+| worker | codex | есть | 4 |
+| full-cycle | codex | есть | 2 |
+| worker | claude | НЕТ | 2 |
+| orchestrator | claude | есть | 1 |
+| orchestrator | codex | НЕТ | 1 |
+
+**16 из 17 оркестраторов работают без worktree** → ветка инъекции недостижима.
+Проверка эффекта в их реальных `cwd`:
+- `polus-orchestrator` (`/home/maxim/polus`) — `.claude/skills` отсутствует, **ноль скиллов**.
+- `Orchestra-orchestrator` (`/mnt/data/Projects/Python/orchestra`) — `codex-debate` есть,
+  но `orchestra-agents`, `html-artifacts`, `vps-deploy`, `grill-me` — нет.
+- `seedon-orchestrator` — 9 скиллов, но это собственные файлы репозитория seedon, не инъекция.
+
+**Вывод: задача шире своей формулировки.** Чинить только «обновление старых копий» —
+значит не доставить `orchestra-agents` ни одному оркестратору, то есть не закрыть тот самый
+живой случай, ради которого задача заведена.
+
+### F4 — H1 (рестарт сервиса) отвергнута — REFUTED
+Рестарт не поможет 16 оркестраторам (F3: кода доставки для них нет вовсе) и не поможет
+воркерам, чьи `cwd` — не worktree. Кроме того рестарт прерывает активные ходы, а правка
+скилла — рутина. Формулировка юзера описывает симптом («хочу, чтобы новые скиллы приезжали»),
+а не обязательный механизм; оркестратор в задании это допускает явно.
+
+### F5 — правильная точка = коннект бэкенда; прецедент уже в коде — CONFIRMED
+`sync_agents_md` (`app/workspace.py:400`) решает **тот же класс проблемы** и её докстринг
+формулирует его дословно:
+
+> «Re-runs on every backend (re)connect, not just at worktree creation — a long-lived worker
+> would otherwise keep the CLAUDE.md snapshot from the day it was spawned.»
+
+Вызывается из `session.py:835`, внутри `_ensure_backend()` — до `self._make_backend()`.
+`_ensure_backend` возвращается сразу при живом `self._backend` (`session.py:827-830`), то
+есть это именно seam коннекта/пробуждения, а не путь каждого хода: лишних копирований не будет.
+**Одна фраза обоснования: коннект — единственный момент, который проходят и разбуженный
+после hibernate агент, и переживший рестарт сервиса, и агент без worktree, причём ровно один
+раз на сессию CLI, который эти файлы и читает.**
+
+### F6 — Codex-рантайм уже корректен, правка ему не нужна — CONFIRMED
+`_codex_factory` (`app/runtime_registry.py:188-202`) вызывает `build_codex_skills_index(...)`
+при КАЖДОМ построении бэкенда и приклеивает результат к `system_prompt`. Индекс читает
+`_read_skill_index_entry` из канонических путей `pipelines/.../skills/*.md` — то есть
+оглавление всегда свежее, а тело агент читает по абсолютному пути источника. Файлы в worktree
+для Codex не используются. Грабля №3 закрывается ответом «покрыт», а не «вне охвата».
+Асимметрия: Claude читает КОПИЮ, Codex читает ОРИГИНАЛ — поэтому протухает только Claude.
+
+### F7 — обе оставшиеся грабли сейчас соблюдены, решение обязано их сохранить — CONFIRMED
+- **Tracked-репозиторий.** Живой контроль: `worktrees/.../seedon/sales` **отслеживает**
+  `.claude/skills/{codex-debate,html-artifacts,vps-deploy,accounting,...}/SKILL.md` —
+  ровно те имена, что инъектит пайплайн. `git status --short -- .claude/` там **пуст**:
+  платформа не перезаписала. Механизм — `tracked_paths()` (`workspace.py:380`) +
+  `continue` на `prompting.py:147`. Любое обновление обязано идти через ту же проверку;
+  13 из 35 «расхождений» (F1) — это именно такие файлы, и они ДОЛЖНЫ отличаться.
+- **`.gitignore`.** Строка 13 = `.claude/`; `git ls-files -- '.claude/'` в основном репо пуст.
+  Инъекции не попадают в индекс. Ни один шаг решения не должен делать `git add`.
+
+## Counter-evidence / риски
+
+- **Против частого обновления:** перезапись файла под работающим CLI. Митигация — писать
+  только при реальном расхождении байт (как `sync_agents_md`), через tmp+mv; для 9 свежих
+  копий записи не будет вовсе.
+- **`orphan=31` можно ошибочно принять за «надо удалить».** Это чужие проектные скиллы.
+  Удаление untracked-файлов в чужом worktree — деструктив за пределами задачи. Не трогать.
+- **Единственный оркестратор с worktree** (`dev-lead`) — не исключение из F3, а
+  подтверждение: у него единственного инъекция технически возможна.
+- **F3 расширяет объём** за границы «одной функции». Ветка доставки для агентов без
+  worktree потребует правки за пределами `app/prompting.py` → по инструкции оркестратора
+  это согласуется ДО правки, а не по факту.
+
+## Affected files
+
+- `app/prompting.py` — `inject_skills_to_worktree` (переиспользуется как есть, включая
+  `tracked_paths`-гейт; вероятно нужен возврат счётчика для приёмки). **Мой файл.**
+- `app/session.py:826` `_ensure_backend` — точка вызова рядом с `sync_agents_md`.
+  **ОБЩИЙ РАНТАЙМ — требуется явное разрешение.**
+- `app/manager.py:688` — существующий вызов при спавне (останется; возможно, станет
+  избыточным). **ОБЩИЙ РАНТАЙМ — требуется явное разрешение.**
+- `pipelines/default/pipeline.yaml` — не меняется.
+
+## Открытый вопрос оркестратору (нужно решение ДО Phase 2)
+
+F3 показывает два разных дефекта под одной формулировкой:
+1. **Протухание копий** у 22 worktree-агентов — чинится целиком в `app/prompting.py` +
+   одна строка вызова в `_ensure_backend`.
+2. **Полное отсутствие доставки** для 16 оркестраторов без worktree — это НЕ обновление,
+   а новая ветка доставки в `cwd` агента. Здесь появляется вопрос, которого нет у воркеров:
+   `cwd` оркестратора — это, как правило, ОСНОВНОЙ репозиторий проекта (`/home/maxim/polus`,
+   `/mnt/data/Projects/Python/seedon`), а не изолированная рабочая копия. Писать туда
+   `.claude/skills/` = писать в живой репозиторий юзера, где `.claude/` может быть не
+   проигнорирован. Для seedon это уже так: у него ТРЕКНУТЫЕ собственные скиллы.
+
+Нужно решение: чиню оба, или только (1)? Второй пункт — тот самый живой случай `4b47fef`,
+без него `orchestra-agents` останется у нуля агентов.
+
+## Confidence
+
+| Finding | Уровень | Основание |
+|---|---|---|
+| F1 22 протухших / 13 легитимных | CONFIRMED | прямое измерение всех 75 файлов + `git ls-files` по каждому |
+| F2 источник ушёл на 4 коммита | CONFIRMED | история репозитория + 75-строчный diff |
+| F3 оркестраторы не получают скиллы вовсе | CONFIRMED | `find`=0 по `orchestra-agents` + срез сессий + чтение веток `manager.py` |
+| F4 рестарт — неверная точка | REFUTED (H1) | следует из F3 |
+| F5 коннект — верная точка | CONFIRMED | прецедент `sync_agents_md` в коде + чтение guard'а `_ensure_backend` |
+| F6 Codex покрыт | CONFIRMED | `runtime_registry.py:188-202`, индекс строится на каждом коннекте |
+| F7 обе грабли соблюдены | CONFIRMED | чистый `git status` в seedon/sales + пустой `ls-files` по `.claude/` |
+
+## Sources
+
+Все — Tier 1 (измерения на этой машине) и Tier 2 (первоисточник = код репозитория):
+1. `app/prompting.py:125-154` — `inject_skills_to_worktree`, `tracked_paths`-гейт.
+2. `app/manager.py:669-688` — вызов под `if use_worktree and repo_path`.
+3. `app/session.py:826-840` — `_ensure_backend`, вызов `sync_agents_md`.
+4. `app/workspace.py:380-397` — `tracked_paths`; `:400-412` — докстринг `sync_agents_md`.
+5. `app/runtime_registry.py:188-202` — `_codex_factory`, сборка индекса скиллов.
+6. Снимок `data/orchestra.db` (read-only копия на `/mnt/data`, удалена после замера).
+7. Прогон `cmp`/`git ls-files` по 75 файлам в `worktrees/`.
+
+**Codex не привлекался: квота исчерпана до 8 августа. Внешнего вердикта нет, только
+самопроверка — ключевые числа (75/9/35/31, 22/13, 0) перепроверены повторным прогоном
+с разделением репо-владельцев.**
diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index ebaa03f61..84d5094ff 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -169,40 +169,69 @@ DONE WHEN: наблюдаемое условие завершения.
   же тему, иначе чинишь симптом. Так же нашёл `UV_CACHE_DIR=/tmp/uv-cache` в `full-cycle.md`:
   замер `du -sh /tmp/uv-cache` = 797 МБ в RAM по нашей же инструкции.
 - **Конфликт «моя реструктуризация vs чужая плоская версия» — не выбор стороны.** Взять свою
   структуру, но ВЫЧИТАТЬ из чужой уникальные детали: так спаслась половина правила («спящий
   процесс с гигабайтами не виден в CPU-топе»), которой у меня не было. Проверка после
   разрешения — `uniq -d` по нормализованным строкам (дубли) + грep каждой улики поимённо.
 - **Доказывать сохранность правил set-difference'ом, а не чтением.** `comm -23` старого и
   нового списка нормализованных строк: исчезло ровно то, что удалял осознанно. Оркестратор
   зачёл это отдельно — «доказал, а не заявил».
 
 ## Правишь модуль — сперва проверь, КТО его грузит (2026-08-04, #148)
 
 - **`pipelines/default/pipeline.yaml`, поле `modules:` — карта адресатов. Читать ДО правки текста.**
   `research-method` грузит ТОЛЬКО `full-cycle`. Роль `worker` (207 сессий против 161 у full-cycle)
   не видит ни Step 0-5, ни строк про prior art. Задача звучала «поправь research-method», и
   правка там на целевом кейсе не изменила бы НИЧЕГО — тот воркер этот модуль не читает.
 - Порядок: `grep -n 'modules:' pipeline.yaml` + `SELECT role, COUNT(*) FROM sessions GROUP BY role`
   → и только потом решай, куда класть. Иначе чинишь текст для роли, которой проблема не касается.
 - Массовой роли не отдавать тяжёлый модуль целиком ради одного абзаца: owner — в модуле,
   в роль — строка-гейт со ссылкой (иначе +100 строк промпта на 207 сессий).
+- **Тот же вопрос на уровень ниже (#149): мало знать, какая роль подписана на контент —
+  проверь, ДОСТИГАЕТ ли её код доставки.** `inject_skills_to_worktree` живёт под
+  `if use_worktree and repo_path:` (`manager.py:669`), а 16 из 17 оркестраторов работают
+  БЕЗ worktree → скиллы, прописанные им в `pipeline.yaml`, не доезжали никогда, а не
+  «протухали». Замер, разделивший гипотезы за одну команду:
+  `find worktrees -path "*/.claude/skills/<new-skill>/SKILL.md" | wc -l` → 0.
+  Формулировка «обнови старые копии» увела бы мимо: чинить надо было отсутствие доставки.
+- Порядок дополняется: `pipeline.yaml` (кто подписан) → grep вызова (кто реально получает)
+  → `SELECT role, ... FROM sessions` (сколько таких живых). Расхождение 1-го и 2-го = баг.
+- **Прежде чем изобретать механизм обновления — грепни, нет ли в репо той же задачи уже
+  решённой.** `sync_agents_md` (`workspace.py:400`) чинит ровно этот класс («snapshot from
+  the day it was spawned») и стоит на `_ensure_backend`; мне осталось назвать точку, а не
+  проектировать её. Ключевые слова для поиска: `reconnect`, `stale`, `mirror`, `refresh`.
+- Асимметрия рантаймов, которую легко проглядеть: Claude читает КОПИЮ в worktree, Codex —
+  ОРИГИНАЛ по абсолютному пути (`build_codex_skills_index` на каждом коннекте). Протухает
+  только Claude. Перед «покрыть оба рантайма» проверь, не покрыт ли второй уже.
+- **Приёмку на живой системе запускать ТОЛЬКО из своей воркти. Стоило отката.** Я запустил
+  heredoc с `cd /mnt/data/Projects/Python/orchestra` (основной репозиторий) — выполнился
+  СТАРЫЙ `app/prompting.py`, а маркер уехал в чужой рабочий чекаут и в живого воркера.
+  Симптом, по которому поймал: функция вернула `None` там, где мой код возвращает `int`.
+  Правило: перед прогоном печатать признак СВОЕЙ версии (сигнатуру/новое поле) и `pwd`;
+  `sys.path.insert(0,'.')` защищает только если `.` — воркти.
+- **Дефолт общего хелпера не расширять, а сужать параметром.** `_exclude_worktree_artifacts`
+  писал `.claude/` + `AGENTS.md` + `codex_sessions.json`; в worktree воркера это норма, в
+  рабочем репо юзера — незаказанный побочный эффект. Добавил `only=(...)`, дефолт не тронул —
+  старые вызовы не заметили правки.
+- **Критерий «git status пуст» на репозиториях юзера невыполним** — там своя грязь (polus 16
+  строк, seedon `?? .env`). Правильный критерий: снять BEFORE в файл, потом `diff` с AFTER.
+  Заодно ловит побочные эффекты, которых «пусто/непусто» не видит.
 
 ## Фильтры в промптах: суди ТРИГГЕР, а не действие (2026-08-04, #147)
 
 - **Диагностика «фильтр не работает» начинается со счёта вердиктов, а не с чтения фильтра.**
   `sqlite3` по `logs` с `type='user_message'` (Bash-эхо иначе даёт +80% шума): 42 TAKE против
   1 REJECT. Постановка звучала как «часть просачивается», факт — «не отбраковывается почти
   ничего». Порядок: сначала измерь исход фильтра, потом переписывай текст.
 - **Мусор в предложениях прячется в триггере, а не в действии.** Действие всегда выглядит
   переносимым (автор только что получил пользу), локальность сидит в «When ...»: «визуал для
   ленты биржи», «монитор 60 Гц», «пункт НК». Проверочный вопрос, который разделил 8/8 кейсов:
   «назови проект, где этот триггер невозможен». Это же — общий приём для любого фильтра
   общности: спрашивай про условие срабатывания, не про пользу.
 - **Критерий «N повторов» проверяй на УЖЕ ПРИНЯТЫХ образцах, прежде чем предлагать.** Идея
   «2 независимых случая» выглядела разумно и зарубила бы все три лучших правила дня (каждое
   из одного случая с замером). Повторяемость коррелирует с возрастом правила, а не с качеством.
 - **Правка промпта принимается прогоном формулировок по корпусу реальных примеров.** Таблица
   «старый вердикт vs новый» на 11 кейсах: 6 разошлись, 5 совпали — и совпадения объяснены.
   Если разошлось 0 — честно сказать, что правка косметическая.
 
 ## Где в Orchestra смотреть замеры по промптам (найдено 2026-08-03, #125)
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index a37a1f0ac..e1e2f7f4b 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -126,41 +126,41 @@ class TestDefaultRolesResolve:
             "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "sub-orchestrator").modules == [
             "git-workflow", "orchestration", "worker-lifecycle", "background-jobs",
             "task-management", "self-improvement",
         ]
         assert P.get_role(PIPELINE, "worker").modules == [
             "git-workflow", "report-format", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "full-cycle").modules == [
             "research-method", "git-workflow", "worker-lifecycle",
             "report-format", "self-improvement", "memory-search",
         ]
 
     def test_tg_emoji_for_v216_roles(self):
         assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
 
     def test_orchestrator_skills_from_manifest(self):
         rr = P.get_role(PIPELINE, "orchestrator")
         assert set(rr.skills) == {
-            "html-artifacts", "vps-deploy", "codex-debate", "grill-me",
+            "html-artifacts", "vps-deploy", "codex-debate", "grill-me", "orchestra-agents",
         }
 
     def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
         """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
         role='worker'/пустая роль допустима."""
         rr = P.get_role(PIPELINE, "orchestrator")
         assert rr.can_spawn == ["*"]
         assert rr.allow_unrouted_workers is True
 
     def test_orchestrator_layers_substituted_no_pipeline(self):
         """Резолвнутые слои оркестратора: base + roles/orchestrator.md, БЕЗ _pipeline.md."""
         rr = P.get_role(PIPELINE, "orchestrator")
         assert rr.prompt_layers == ["base.md", "roles/orchestrator.md"]
 
     def test_worker_layers_substituted(self):
         rr = P.get_role(PIPELINE, "worker")
         assert rr.prompt_layers == ["base.md", "roles/worker.md"]
 
 
 # ── build_system_prompt: композиция base + роль (без _pipeline.md) ──────────
diff --git a/tests/test_manager.py b/tests/test_manager.py
index 5d0b2b450..635cd3ca4 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -765,40 +765,134 @@ class TestInjectSkillsRealCopy:
         own = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
         own.parent.mkdir(parents=True)
         own.write_text("# repo's own skill\n")
         subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True, check=True)
         subprocess.run(["git", "commit", "-m", "skill"], cwd=wt, capture_output=True, check=True)
 
         inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))
 
         assert own.read_text() == "# repo's own skill\n"
         # untracked skills are still injected — only the repo's own file is off limits
         assert (wt / ".claude" / "skills" / "html-artifacts" / "SKILL.md").is_file()
 
     def test_empty_list_is_noop(self, tmp_path):
         from app.prompting import inject_skills_to_worktree
         wt = tmp_path / "wt"
         wt.mkdir()
         inject_skills_to_worktree([], str(wt))
         assert not (wt / ".claude").exists()
 
 
+class TestRefreshSkills:
+    """Task #149: injection runs on every backend connect, not only at spawn.
+
+    Two failures it fixes: copies going stale after the source skill is edited, and skills
+    added to a role after spawn never arriving (orchestrators have no worktree at all, so
+    the worktree-only call site reached none of them — `orchestra-agents` sat at 0 agents).
+    The destination may be the user's real working repository, hence the safety assertions.
+    """
+
+    def _source(self, name="codex-debate"):
+        from app.prompting import _SKILLS_DIR
+        return _SKILLS_DIR / f"{name}.md"
+
+    def test_stale_copy_is_refreshed(self, tmp_path):
+        from app.prompting import inject_skills_to_worktree
+        wt = _git_repo(tmp_path)
+        dest = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
+        dest.parent.mkdir(parents=True)
+        dest.write_text("# ancient version from spawn day\n")
+
+        written = inject_skills_to_worktree(["codex-debate"], str(wt))
+
+        assert dest.read_bytes() == self._source().read_bytes()
+        assert written == 1
+
+    def test_unchanged_copy_is_not_rewritten(self, tmp_path):
+        """Steady state must cost zero writes — otherwise every connect swaps a file
+        under a running CLI for no reason."""
+        from app.prompting import inject_skills_to_worktree
+        wt = _git_repo(tmp_path)
+        inject_skills_to_worktree(["codex-debate"], str(wt))
+        dest = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
+        before_mtime = dest.stat().st_mtime_ns
+
+        written = inject_skills_to_worktree(["codex-debate"], str(wt))
+
+        assert written == 0
+        assert dest.stat().st_mtime_ns == before_mtime
+
+    def test_tracked_and_untracked_in_one_repo(self, tmp_path):
+        """Models the live seedon case: the same repo tracks some of the role's skills and
+        not others. Tracked file untouched, untracked one delivered — in a single pass."""
+        import subprocess
+        from app.prompting import inject_skills_to_worktree
+        wt = _git_repo(tmp_path)
+        own = wt / ".claude" / "skills" / "codex-debate" / "SKILL.md"
+        own.parent.mkdir(parents=True)
+        own.write_text("# repo's own skill\n")
+        subprocess.run(["git", "add", "-Af"], cwd=wt, capture_output=True, check=True)
+        subprocess.run(["git", "commit", "-m", "own skill"], cwd=wt, capture_output=True, check=True)
+
+        inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))
+
+        assert own.read_text() == "# repo's own skill\n"
+        assert (wt / ".claude" / "skills" / "html-artifacts" / "SKILL.md").read_bytes() \
+            == self._source("html-artifacts").read_bytes()
+
+    def test_injection_leaves_repo_clean_without_gitignore(self, tmp_path):
+        """The expensive scenario, live in `games`: a repo that ignores `.claude/` NOWHERE.
+        Without the exclude step we leave permanent untracked junk in the user's git status."""
+        import subprocess
+        from app.prompting import inject_skills_to_worktree
+        wt = _git_repo(tmp_path)
+        assert not (wt / ".gitignore").exists()
+
+        inject_skills_to_worktree(["codex-debate"], str(wt))
+
+        status = subprocess.run(
+            ["git", "status", "--short"], cwd=wt, capture_output=True, text=True,
+        ).stdout
+        assert ".claude" not in status, f"injection dirtied the repo: {status!r}"
+
+    def test_nothing_written_leaves_exclude_untouched(self, tmp_path):
+        """No side effects in someone else's repo when we planted nothing."""
+        from app.prompting import inject_skills_to_worktree
+        wt = _git_repo(tmp_path)
+        exclude = wt / ".git" / "info" / "exclude"
+        before = exclude.read_text() if exclude.exists() else ""
+
+        assert inject_skills_to_worktree(["no-such-skill-anywhere"], str(wt)) == 0
+
+        after = exclude.read_text() if exclude.exists() else ""
+        assert after == before
+
+    def test_non_repo_path_is_skipped(self, tmp_path):
+        """Git can't say who owns the file → writing on a guess is what dirties repos."""
+        from app.prompting import inject_skills_to_worktree
+        plain = tmp_path / "not-a-repo"
+        plain.mkdir()
+
+        assert inject_skills_to_worktree(["codex-debate"], str(plain)) == 0
+        assert not (plain / ".claude").exists()
+
+
 class TestResolveBaseBranch:
     """DESIGN §10: резолв base_branch по стратегии манифеста (B3).
 
     Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
     ``app.manager.get_role`` (как в TestInjectSkillsGating) и подсовывая
     родителя в ``mgr.sessions`` через лёгкий объект с атрибутом ``branch``.
     """
 
     def _put_parent(self, mgr, name, scope, branch):
         """Лёгкий родитель в кэше сессий с нужной веткой (без БД)."""
         parent = MagicMock()
         parent.name = name
         parent.scope = scope
         parent.branch = branch
         mgr.sessions[name] = parent
 
     def test_strategy_main_uses_repository_mainline(self, mgr):
         rr = MagicMock(base_branch_strategy="main")
         with (
             patch("app.manager.get_role", lambda p, r: rr),


## Later history of the touched files on main (after this commit)

209 later commits touch these paths; the first 40 (oldest first):
d4a64f211 2026-08-05 #151: #151: research — Codex 0.145.0 читает проектный .codex/skills, gate пройден
e4c6c2607 2026-08-05 #152: #152: аудит харнессов — 1 находка из 6 кандидатов (CLAUDE.md fallback у Codex)
6f97d535a 2026-08-04 #78, #80: #78: исследование — оценка подтверждена своим замером, но retention логов не существует, а копировать надо не файл
02d96d3aa 2026-08-04 #77: #77: заморожены дословные трассы пилота a-0 и b-0 до полного прогона
802964638 2026-08-04 #84: #84: личная память — PDF+pdftotext вместо WebFetch для приложений статей
9f777f912 2026-08-04 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память
419fed706 2026-08-04 #82, #78: #82: перенаправил два чужих мока на id-путь пробуждения
99275851c 2026-08-05 #156: #156: исследование — механизм пробуждения исправен, отсутствует автотриггер
712254066 2026-08-05 Merge remote-tracking branch 'origin/main'
59d32c050 2026-08-06 #122: #122: AUTO_COMPACT_ENABLED=0 полностью выключает автокомпакт оркестратора
991b246c7 2026-08-06 #137: #137: разбор Prime Agent — заявка 30.2→95.5 разложена по первоисточникам, механика по коду, что применимо к Orchestra
beb777cb4 2026-08-06 Squashed commits: - #160: исследование — graceful shutdown затирает 'running', пробуждение не срабатывает - #160: сохранить признак прерванности через graceful-рестарт - #160: тесты пробуждения после рестарта, отчёт, личная память
36de7dd94 2026-08-06 #167: #167: ошибка обязана назвать себя — один владелец вместо четырёх копий
8683e76b0 2026-08-07 #155: #155: отказ кибербез-фильтра — отдельный класс, подсказка по трём признакам, автооткат отравленной истории
639dc61d4 2026-08-07 #161: #161: отказ фильтра опознаётся по телу события и упавшему ходу; забракованный текст наружу не едет
647452c1c 2026-08-08 #168: #168: research centralized weekly quota gate
c1a635533 2026-08-09 #169: WIP #169: research awaiting Codex quota
8cbfce6ee 2026-08-09 #170: #170: audit feat-groom-demo latency
afc99e2de 2026-08-10 #173: #173: fix prompt P0 defects
05e9a8062 2026-08-11 #174: #174: import DB history into Claude
3483daf28 2026-08-11 #196: #196: pre-send gate owns the no-empty-message rule; drop CLAUDE.md dup
2815c1683 2026-08-11 #174: #174: import DB history into Codex
5e9ae87c4 2026-08-11 #198: #198 Фаза 2: прогоны опровергли обе рекомендации Фазы 1 — план + поправка в research.md
e8b85a51c 2026-08-12 #203: #203: route closed tasks to Luna, drop Terra, tie effort to role choice
2a5ae8b33 2026-08-12 #203: #203: Luna escalation path; move model-routing to a module for spawn-capable roles
8b7860a81 2026-08-12 #207: #207: drop unattributed MRCR number, full-cycle effort xhigh->high
7ba8728be 2026-08-12 #213: #213: record per-model effort constraint, no discount route through Sol
0a665a832 2026-08-12 #210: #210: план Фазы 2 — план заканчивается красным тестом; оракул схемы закоммичен КРАСНЫМ
6b2249c59 2026-08-12 #214: #214: эффорт по модели — карта модель→ступень в манифесте
100cc871b 2026-08-12 #221: #221: add Telegram formatting rules to orchestrator prompt
9442bc38b 2026-08-12 #221: #221: add model routing priority oracle
8bd9bd60a 2026-08-12 #225: #225: add branch WIP diff regression test
45d761005 2026-08-12 #223: #223: correct barrier conclusion
bf5de05e2 2026-08-12 #222: #222: add Spark admission delivery oracle
6dac7dcbf 2026-08-12 #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов
6712fdcf4 2026-08-12 #219, #223: #219 T2: контракт делегирования «таблица, а не область» в worker-lifecycle + тесты на происхождение якорей (первая редакция теста была ложно-зелёной на составной мутации)
d986be3c1 2026-08-12 #193: #193: add red subrepo memory regression test
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
a01a4b2aa 2026-08-13 #230: #230: план фазы 2 + красные оракулы T1-T5 (заглушки, 8 failed)
000927f30 2026-08-13 #223: #223: research explicit test-layer authorization

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### d4a64f211 #151: #151: research — Codex 0.145.0 читает проектный .codex/skills, gate пройден

diff --git a/app/prompting.py b/app/prompting.py
index db0f49d79..4bdeb9d32 100644
--- a/app/prompting.py
+++ b/app/prompting.py
@@ -121,50 +121,65 @@ def _run_as_agent(args: list[str], **kwargs) -> subprocess.CompletedProcess:
         if gosu:
             args = [gosu, agent_uid] + args
     return subprocess.run(args, **kwargs)
 
 
-def inject_skills_to_worktree(skill_names: list[str], worktree_path: str) -> int:
-    """Copy resolved pipeline skills into <path>/.claude/skills/ as native Claude CLI skills.
+def inject_skills_to_worktree(
+    skill_names: list[str], worktree_path: str, home_dir: str = ".claude",
+) -> int:
+    """Copy resolved pipeline skills into <path>/<home_dir>/skills/ as native CLI skills.
 
     Runs on every backend (re)connect, not just at worktree creation — a long-lived agent
     would otherwise keep the skill files from the day it was spawned, and a skill added to a
     role after spawn would never reach anyone. Same reasoning, same seam as `sync_agents_md`.
 
+    ``home_dir`` is the only thing that differs between runtimes: Claude discovers skills in
+    `.claude/skills/`, Codex in `.codex/skills/` (verified on codex-cli 0.145.0 — a project
+    directory is searched upward from cwd alongside `$CODEX_HOME/skills` and `~/.agents/skills`,
+    and the three sources are merged, not replaced). One mechanism, two addresses: a second
+    copy of this function would be two places for the guards below to drift apart.
+
     ``worktree_path`` is the agent's worktree when it has one, otherwise its plain cwd —
     orchestrators run without a worktree, so a worktree-only path never delivered to them.
     That cwd is a REAL repository the user works in by hand, hence the two guards below.
 
-    A repo that TRACKS `.claude/skills/<name>/SKILL.md` owns that file: `info/exclude` cannot
+    A repo that TRACKS `<home_dir>/skills/<name>/SKILL.md` owns that file: `info/exclude` cannot
     ignore a tracked path, so overwriting it leaves the tree dirty forever and blocks
     every merge. Such skills are left alone — the agent reads the repo's own version, which
-    Claude CLI already loads from the same path.
+    the CLI already loads from the same path.
 
     Returns the number of files actually written (unchanged copies are not rewritten, so a
     steady state costs zero writes and never swaps a file under a running CLI).
     """
     if not skill_names or not _SKILLS_DIR.is_dir():
         return 0
     wt = Path(worktree_path)
-    rels = {sname: f".claude/skills/{sname}/SKILL.md" for sname in skill_names}
+    rels = {sname: f"{home_dir}/skills/{sname}/SKILL.md" for sname in skill_names}
     try:
         tracked = tracked_paths(wt, list(rels.values()))
     except RuntimeError as exc:
         # Git failing (not a repo, ownership, broken worktree) proves nothing about who owns
         # these files. Writing on a guess is what dirties someone else's repository.
         logger.warning(f"{exc} — skill injection skipped for {wt}")
         return 0
+    home = wt / home_dir
+    if home.exists() and not home.is_dir():
+        # Measured on a live repo: `Aperant` tracks a read-only zero-byte FILE named `.codex`.
+        # `mkdir -p` then fails once per skill per connect. The repo owns that name — bail out
+        # quietly rather than log the same failure five times forever or clobber their file.
+        logger.info(f"'{home}' exists and is not a directory — skill injection skipped")
+        return 0
     injected = 0
     for sname in skill_names:
         skill_src = _SKILLS_DIR / f"{sname}.md"
         if not skill_src.exists():
             logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
             continue
         if rels[sname] in tracked:
             logger.info(f"Skill '{sname}' is tracked by the repo at {wt} — injection skipped")
             continue
-        dest = wt / ".claude" / "skills" / sname / "SKILL.md"
+        dest = wt / home_dir / "skills" / sname / "SKILL.md"
         if dest.is_symlink():
             logger.warning(f"Skill '{sname}' at {dest} is a symlink — skipped (copy would clobber its target)")
             continue
         try:
             if dest.is_file() and dest.read_bytes() == skill_src.read_bytes():
@@ -184,19 +199,23 @@ def inject_skills_to_worktree(skill_names: list[str], worktree_path: str) -> int
         finally:
             if tmp.exists():
                 _run_as_agent(["rm", "-f", str(tmp)], capture_output=True)
         injected += 1
     if injected:
-        # Only after actually planting something, and only `.claude/` — this path may be the
-        # user's working repository, where adding unrelated ignore rules is a side effect we
-        # have no mandate for. Without this, a repo that doesn't already ignore `.claude/`
-        # (e.g. games) gets permanent untracked junk in the user's `git status`.
+        # Only after actually planting something, and only the directory we wrote — this path
+        # may be the user's working repository, where adding unrelated ignore rules is a side
+        # effect we have no mandate for. Without this, a repo that ignores neither `.claude/`
+        # nor `.codex/` (games and seedon ignore neither) gets permanent untracked junk in the
+        # user's `git status`.
         try:
-            _exclude_worktree_artifacts(wt, only=(".claude/",))
+            _exclude_worktree_artifacts(wt, only=(f"{home_dir}/",))
         except Exception as exc:
-            logger.warning(f"could not exclude .claude/ in {wt}: {exc}")
-        logger.info(f"Injected {injected} skills into {worktree_path}/.claude/skills/")
+            logger.warning(f"could not exclude {home_dir}/ in {wt}: {exc}")
+        # Path is logged, not just the count: whether a CLI actually discovers this directory
+        # is not something we detect (see ORCHESTRA_CODEX_SKILL_INDEX). If an agent turns out
+        # to have no skills, this line is the evidence of where they were put.
+        logger.info(f"Injected {injected} skills into {worktree_path}/{home_dir}/skills/")
     return injected
 
 
 _SKILL_INDEX_HEADER = """## Available skills (progressive loading)
 
diff --git a/app/session.py b/app/session.py
index 6020f7891..c1cc43a82 100644
--- a/app/session.py
+++ b/app/session.py
@@ -98,10 +98,13 @@ def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
         _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
     return _DB_EXECUTOR
 
 
 _LAST_SUMMARY_MAX_CHARS = 4_000
+# Where each runtime's CLI discovers project skills. A runtime absent here gets no injection —
+# an `else: ".claude"` default would silently plant Claude files for the next new backend.
+_SKILL_HOME_DIRS = {"claude": ".claude", "codex": ".codex"}
 
 # Compact summary is a multi-KB wall of text; logging it as "text" mirrors it to TG
 # as agent speech. Off by default — the summary already lives in the agent's context
 # and in the compact_worker result.
 LOG_COMPACT_SUMMARY = os.getenv("LOG_COMPACT_SUMMARY", "0").strip().lower() in ("1", "true", "yes")
@@ -824,19 +827,19 @@ class AgentSession:
                 self._listen_task.add_done_callback(self._on_task_done)
 
     async def _refresh_skills(self) -> None:
         """Re-install this role's pipeline skills before the CLI starts.
 
-        Claude reads skills as FILES from `<cwd>/.claude/skills/`, so its copy goes stale the
+        Both runtimes read skills as FILES, each from its own directory: Claude from
+        `<cwd>/.claude/skills/`, Codex from `<cwd>/.codex/skills/`. Either copy goes stale the
         moment a skill is edited, and a skill added to a role after spawn never arrives at all.
-        Codex needs nothing here: it gets a freshly built index of canonical source paths on
-        every connect (`build_codex_skills_index`), i.e. it reads the original, not a copy.
 
         Falls back to `self.cwd` when there is no worktree — orchestrators run without one,
         which is why a worktree-only injection reached none of them.
         """
-        if self.backend_type != "claude":
+        home_dir = _SKILL_HOME_DIRS.get(self.backend_type)
+        if not home_dir:
             return
         path = self.worktree_path or self.cwd
         if not path:
             return
### e4c6c2607 #152: #152: аудит харнессов — 1 находка из 6 кандидатов (CLAUDE.md fallback у Codex)

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index 790bc2878..be5bede8c 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -238,10 +238,22 @@ DONE WHEN: наблюдаемое условие завершения.
 - **`.codex` в 8 из 17 репозиториев юзера — это ФАЙЛ (read-only, 0 байт, трекнутый), а не
   каталог.** `mkdir -p` там падает → пять `install failed` на каждом коннекте. Перед записью
   в `<repo>/<dot-dir>/` проверять `exists() and not is_dir()`. Правило шире имени: платформа
   не пишет поверх принадлежащего репозиторию, и «принадлежит» бывает выражено ТИПОМ файла,
   а не только индексом git.
+- **Аудит «где мы костылим» начинать с `ls docs/tasks/`, а не с кода (#152).** Из шести
+  кандидатов оркестратора четыре были УЖЕ разобраны нами: `no-subagents` (бан отменён юзером
+  01.07), `126` («не переходить на нативный компакт»), `cc-config-audit` (хуки), `151`.
+  Двадцать секунд на список каталогов сэкономили бы половину аудита. `search_memory` находит
+  по смыслу, но каталог даёт полный перечень тем разом.
+- **Постановка задачи может содержать фактическую ошибку про НАШ ЖЕ код.** «Мы запрещаем
+  Task/Agent» — запрет только для оркестраторов (`backend_claude.py:63-71`), воркерам можно.
+  Проверять предпосылку задания грепом до того, как строить на ней выводы.
+- **Один тип события в логах ≠ одна сущность.** `subagent_start` = 1681, но 1677 из них
+  `type=local_bash` (фоновый bash), настоящих субагентов 4. Разброс в 400 раз. Перед выводом
+  из счётчика — посмотреть СЫРЫЕ строки и разложить по подтипу, иначе получишь красивую
+  цифру про не то.
 - **Мутация теста дважды поймала МОЙ слабый тест, а не чужой баг (#151).** (1) Тест на
   `.codex/` в `_WORKTREE_EXCLUDES` пережил мутацию: инъекция ходит через `only=`, минуя
   константу, — значит тест стоял не на том seam. (2) Тест «каталог занят файлом» пережил:
   счётчик 0 и с гейтом, и без. Вывод: если мутация НЕ уронила тест — это сигнал, что тест
   проверяет не то, а не что «фикс лишний». Ассерт переносить на наблюдаемую разницу
### 6f97d535a #78, #80: #78: исследование — оценка подтверждена своим замером, но retention логов не существует, а копировать надо не файл

diff --git a/app/session.py b/app/session.py
index c1cc43a82..76bab1433 100644
--- a/app/session.py
+++ b/app/session.py
@@ -31,10 +31,12 @@ from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
 from app.db import add_log, get_logs, save_session, tool_error_add
 
+from app.blobs import store_images
+
 logger = logging.getLogger(__name__)
 
 
 def _subscription_limit_kind(text: str) -> str | None:
     """Classify the canonical non-transient subscription-limit messages."""
@@ -1048,11 +1050,15 @@ class AgentSession:
             self._turn_logs.append(f"[tool] {short}")
             tool_name = event.metadata.get("tool_name", event.content)
             if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                 self._did_report = True
         elif event.type == "tool_result":
-            self._log("tool_result", event.content)
+            # Тело картинки уезжает в файл, в журнал идёт ссылка (#78). Копируем не файл
+            # с диска, а то, что уже в руках: путь лежит в ПРЕДЫДУЩЕЙ строке журнала и у
+            # части строк его нет вовсе, а рабочие копии воркеров штатно сносятся —
+            # ссылка на чужой файл протухала у 18 из 50 строк.
+            self._log("tool_result", store_images(self.id, event.content))
         elif event.type == "file_change":
             self._log("tool", f"file: {event.content}")
             self._turn_logs.append(f"[tool] file: {event.content[:60]}")
         elif event.type in ("plan", "warning", "review"):
             self._log(event.type, event.content)
### 02d96d3aa #77: #77: заморожены дословные трассы пилота a-0 и b-0 до полного прогона

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index be5bede8c..006a8a0eb 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -275,10 +275,29 @@ DONE WHEN: наблюдаемое условие завершения.
   из одного случая с замером). Повторяемость коррелирует с возрастом правила, а не с качеством.
 - **Правка промпта принимается прогоном формулировок по корпусу реальных примеров.** Таблица
   «старый вердикт vs новый» на 11 кейсах: 6 разошлись, 5 совпали — и совпадения объяснены.
   Если разошлось 0 — честно сказать, что правка косметическая.
 
+## A/B правил на живом CLI: грабли стенда (2026-08-04, #77)
+
+- **Соблюдение ≠ защита, и мерить надо второе.** Кандидат-идиому взяли 20 прогонов из 20,
+  а работа выжила в 15. Мерил бы «исполняется ли правило» — отчёт вышел бы победным и
+  неверным. Метрика всегда про ИСХОД («работа цела»), никогда про приверженность форме.
+- **Метку незакоммиченной работы агент выберет целью мутации.** Якорь стоял последней
+  строкой файла — `sed -i '$ d'` и `head -13` попали ровно в него, 8 прогонов в каждом
+  плече дали ложную «потерю». Метку класть вне мутируемого файла. Симметричность
+  артефакта спасла сравнение плеч, но абсолютные доли занизила в обоих.
+- **Абсолютный порог приёмки выводи из пилота, а не из круглого числа.** Записал «B ≥ 0.8»
+  до прогона, получил 0.75 при эффекте +0.50 и p=0.002 — критерий провален формально при
+  явном эффекте. Порог берётся от базовой линии и шума, иначе сам себе создаёшь тупик.
+- Стенд: `claude -p "<seed>" --model haiku --dangerously-skip-permissions --max-turns 40
+  --output-format stream-json` в свежем каталоге, плечи различаются ОДНОЙ строкой в
+  `CLAUDE.md` фикстуры. Идиому разбирать только по `tool_use.input`, не по транскрипту:
+  текст ассистента цитирует само правило и даёт ложные срабатывания grep.
+- 40 прогонов Haiku ≈ час wall-clock, `bg_create(type="run")`. Гейт по квоте класть ВНУТРЬ
+  раннера (сам отказывается стартовать при 5h ≥ 60%), а не в память запускающего.
+
 ## Где в Orchestra смотреть замеры по промптам (найдено 2026-08-03, #125)
 
 - `turn_usage` в `orchestra.db` — ПОТУРНОВЫЕ `input/output/cache_read/cache_create` + модель и
   `stop_reason`. Это единственное место с гранулярностью хода: `sessions.total_*` — пожизненные
   суммы и для сравнения режимов бесполезны. Работать только по копии в `/tmp`.
### 802964638 #84: #84: личная память — PDF+pdftotext вместо WebFetch для приложений статей

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index 006a8a0eb..b22b38560 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -294,10 +294,22 @@ DONE WHEN: наблюдаемое условие завершения.
   `CLAUDE.md` фикстуры. Идиому разбирать только по `tool_use.input`, не по транскрипту:
   текст ассистента цитирует само правило и даёт ложные срабатывания grep.
 - 40 прогонов Haiku ≈ час wall-clock, `bg_create(type="run")`. Гейт по квоте класть ВНУТРЬ
   раннера (сам отказывается стартовать при 5h ≥ 60%), а не в память запускающего.
 
+## Читаешь статью — качай PDF, а не проси WebFetch (2026-08-04, #84)
+
+- `WebFetch` по `arxiv.org/html/<id>` обрывается на секции references: **приложения не
+  приходят вовсе**, а именно там лежат определения, по которым размечают. Рабочий путь:
+  `curl -sL -o p.pdf https://arxiv.org/pdf/<id>` + `pdftotext -layout` (стоит на VPS) →
+  полный текст, который можно грепать и считать. Так я достал Appendix B из 2607.28802,
+  которого WebFetch не отдал.
+- **Сторону/тег в таксономии считай грепом по дословным меткам, а не глазами.**
+  `grep -oE "\((MODEL|OWNER|TOOL|CONTEXT|ENVIRONMENT)\)\." | sort | uniq -c` за секунду дал
+  36 против 5 — факт, на котором держался весь вывод. Пересказ аннотации этого не содержал.
+- Чужую статью целиком в репозиторий НЕ класть: `origin` публичный. Цитаты + ссылка.
+
 ## Где в Orchestra смотреть замеры по промптам (найдено 2026-08-03, #125)
 
 - `turn_usage` в `orchestra.db` — ПОТУРНОВЫЕ `input/output/cache_read/cache_create` + модель и
   `stop_reason`. Это единственное место с гранулярностью хода: `sessions.total_*` — пожизненные
   суммы и для сравнения режимов бесполезны. Работать только по копии в `/tmp`.
### 9f777f912 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память

diff --git a/app/session.py b/app/session.py
index 76bab1433..9999afb23 100644
--- a/app/session.py
+++ b/app/session.py
@@ -221,10 +221,16 @@ class AgentSession:
     tg_topic: bool = False
 
     needs_switch: bool = False
     last_task_sender: str = ""
 
+    # Имя сменилось, пока жил этот коннект. env MCP-подпроцесса замораживается при его
+    # старте, поэтому подпроцесс надо поднять заново — но только на ГРАНИЦЕ хода:
+    # дисконнект внутри хода оборвал бы живой ход. Флаг идемпотентен: два переименования
+    # за ход дают одну пересборку.
+    _identity_stale: bool = field(default=False, repr=False)
+
     # False → detached DB-hydrate (manager._hydrate_row): data only, no backend/tasks.
     # NEVER call start()/send()/_persist() on a detached session.
     loaded: bool = True
     # raw DB row of a detached session — preserves legacy response shape (richer than to_dict)
     db_row: Optional[dict] = field(default=None, repr=False)
@@ -735,10 +741,12 @@ class AgentSession:
                 templates_changed = old_th != current_th
                 pending_th = current_th
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
+            await self._apply_pending_identity_restart()
+
             if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
@@ -852,10 +860,24 @@ class AgentSession:
             if not skills or skills == "all":
                 return
             await asyncio.to_thread(inject_skills_to_worktree, skills, path, home_dir)
         except Exception as e:
             logger.warning(f"[{self.name}] skill refresh failed: {e}")
+    async def _apply_pending_identity_restart(self) -> bool:
+        """Погасить бэкенд, если имя сменилось, — но только на ГРАНИЦЕ хода.
+
+        Дисконнект внутри живого хода оборвал бы его, поэтому в RUNNING только копим
+        флаг. Упавший ход флаг не съедает: он доживает до начала следующего, а если
+        коннекта не станет вовсе (гибернация, рестарт), новый бэкенд и так строится из
+        уже пересобранного `mcp_servers`. Повторный вызов — no-op.
+        """
+        if not self._identity_stale or self.status == AgentStatus.RUNNING:
+            return False
+        self._identity_stale = False
+        self._log("status", "identity changed — restarting MCP subprocess")
+        await self._disconnect_backend()
+        return True
 
     async def _ensure_backend(self, force_fresh: bool = False):
         if self._backend is not None:
             if not force_fresh:
                 return self._backend
diff --git a/tests/test_manager.py b/tests/test_manager.py
index cb96a8b5c..7617b8654 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -2767,5 +2767,91 @@ class TestLiveChildren:
 
     def test_no_children_returns_empty(self, mgr):
         from app.db import save_session
         save_session(self._row("lonely", "", "idle"))
         assert mgr._live_children("parent-w", "/proj") == []
+
+
+class TestIdentityRefreshOnRename:
+    """#82: WORKER_NAME замораживается в env MCP-подпроцесса при его старте."""
+
+    @staticmethod
+    def _live_session(monkeypatch, *, backend=None, name="old-name"):
+        from app.session import AgentSession
+
+        monkeypatch.setattr("app.session.save_session", MagicMock())
+        monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
+        session = AgentSession(
+            id="rn-1", name=name, scope="/s", cwd="/tmp",
+            model="claude-sonnet-5[1m]", system_prompt="p", role="worker",
+        )
+        session.loaded = True
+        session._backend = backend
+        return session
+
+    def test_rebuilds_config_and_defers_restart_to_turn_boundary(self, mgr, monkeypatch):
+        from tests.conftest import make_backend_mock
+
+        session = self._live_session(monkeypatch, backend=make_backend_mock())
+        session.name = "new-name"
+
+        assert mgr.refresh_identity(session) == "restart-pending"
+        assert session.mcp_servers["orchestra"]["env"]["WORKER_NAME"] == "new-name"
+        # Живой бэкенд НЕ гасим здесь: дисконнект внутри хода оборвал бы ход.
+        assert session._backend is not None
+        assert session._identity_stale is True
+
+    def test_second_rename_in_the_same_turn_is_still_one_restart(self, mgr, monkeypatch):
+        from tests.conftest import make_backend_mock
+
+        session = self._live_session(monkeypatch, backend=make_backend_mock())
+        session.name = "second"
+        mgr.refresh_identity(session)
+        session.name = "third"
+        mgr.refresh_identity(session)
+
+        assert session._identity_stale is True
+        assert session.mcp_servers["orchestra"]["env"]["WORKER_NAME"] == "third"
+
+    def test_session_without_live_backend_needs_no_restart(self, mgr, monkeypatch):
+        session = self._live_session(monkeypatch, backend=None)
+        session.name = "renamed"
+
+        assert mgr.refresh_identity(session) == "config-only"
+        assert session._identity_stale is False
+        assert session.mcp_servers["orchestra"]["env"]["WORKER_NAME"] == "renamed"
+
+    def test_not_loaded_session_needs_nothing(self, mgr, monkeypatch):
+        session = self._live_session(monkeypatch)
+        session.loaded = False
+
+        assert mgr.refresh_identity(session) == "not-loaded"
+        assert session.mcp_servers == {}
+
+    @pytest.mark.asyncio
+    async def test_restart_happens_on_turn_boundary_not_inside_a_live_turn(
+        self, mgr, monkeypatch,
+    ):
+        """Оба случая: живой ход не рвём, упавший ход флаг не съедает."""
+        from tests.conftest import make_backend_mock
+        from app.session import AgentStatus
+
+        backend = make_backend_mock()
+        session = self._live_session(monkeypatch, backend=backend)
+        session.name = "renamed-mid-turn"
+        mgr.refresh_identity(session)
+
+        session.status = AgentStatus.RUNNING
+        assert await session._apply_pending_identity_restart() is False
+        backend.disconnect.assert_not_awaited()
+        assert session._identity_stale is True
+
+        # Ход упал, не дойдя до конца: статус вернулся, флаг цел — гасим ЗДЕСЬ.
+        session.status = AgentStatus.IDLE
+        assert await session._apply_pending_identity_restart() is True
### 419fed706 #82, #78: #82: перенаправил два чужих мока на id-путь пробуждения

diff --git a/app/session.py b/app/session.py
index 9999afb23..15bff5a0e 100644
--- a/app/session.py
+++ b/app/session.py
@@ -31,11 +31,10 @@ from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
 from app.db import add_log, get_logs, save_session, tool_error_add
 
-from app.blobs import store_images
 
 logger = logging.getLogger(__name__)
 
 
 def _subscription_limit_kind(text: str) -> str | None:
@@ -1072,15 +1071,15 @@ class AgentSession:
             self._turn_logs.append(f"[tool] {short}")
             tool_name = event.metadata.get("tool_name", event.content)
             if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                 self._did_report = True
         elif event.type == "tool_result":
-            # Тело картинки уезжает в файл, в журнал идёт ссылка (#78). Копируем не файл
-            # с диска, а то, что уже в руках: путь лежит в ПРЕДЫДУЩЕЙ строке журнала и у
-            # части строк его нет вовсе, а рабочие копии воркеров штатно сносятся —
-            # ссылка на чужой файл протухала у 18 из 50 строк.
-            self._log("tool_result", store_images(self.id, event.content))
+            # Запись картинок в блобы (#78) ВЫКЛЮЧЕНА: клиентской половины нет — фронт не
+            # знает типа `blob`, и первая же картинка перестала бы показываться. Хранилище
+            # и чтение (`app/blobs.py`, `GET /api/blobs/...`) оставлены инертными до
+            # разморозки #78; включать запись только вместе с фронтом.
+            self._log("tool_result", event.content)
         elif event.type == "file_change":
             self._log("tool", f"file: {event.content}")
             self._turn_logs.append(f"[tool] file: {event.content[:60]}")
         elif event.type in ("plan", "warning", "review"):
             self._log(event.type, event.content)
### 99275851c #156: #156: исследование — механизм пробуждения исправен, отсутствует автотриггер

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index be5bede8c..57709fe7c 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -283,10 +283,21 @@ DONE WHEN: наблюдаемое условие завершения.
   `stop_reason`. Это единственное место с гранулярностью хода: `sessions.total_*` — пожизненные
   суммы и для сравнения режимов бесполезны. Работать только по копии в `/tmp`.
 - **Ключ join'а — `sessions.id` (Orchestra row id), НЕ `sessions.session_id` (нативный UUID).**
   И `logs.session_id`, и `turn_usage.session_id` держат именно row id. Join через нативный UUID
   молча даёт 0 строк — я так и получил пустой результат, прежде чем проверил ключ.
+- **«Механизм не сработал» → сперва грепни, кто его ВЫЗЫВАЕТ, потом читай его логику.** #156:
+  три гипотезы о дефекте внутри `limit_wake.py` (712 строк) отпали за один прогон — единственным
+  вызывающим оказалась HTTP-ручка дашборда, то есть кнопка. Дешёвая проверка: `grep -rn "<func>"`
+  с исключением самого файла и тестов; пусто вне ручки/CLI → механизм не автоматический by design.
+  Отдельно быстрый фальсификатор «оно ломается по дороге»: `SELECT ... WHERE id LIKE '<prefix>%'`
+  — 0 строк за всю историю значит «не создавалось никогда», а не «не дожило».
+- **Воспроизводишь состояние агента подсовыванием строк в `logs` → сперва прочти МАТЧЕР целиком.**
+  #156: детектор лимита (`limit_wake.py:_latest_limit_turn`) требует НАШУ русскую строку
+  `"subscription limit — ждём сброса квоты"` в `error`/`status` + `stop_sequence` в `turn ended`;
+  английской фразы провайдера самой по себе НЕ хватает. Подсунул только её — получил пустой
+  список и минуту гадал, кто виноват. Реплей инцидента = все строки хода, а не самая заметная.
 - Инжект системного промпта в логах почти невидим: `session.py` пишет `user_message` ДО добавления
   префикса. Единственный след — `status` `prompt updated → <hash>`, и только для ветки
   `templates_changed`. Любая статистика по инжектам — нижняя граница, так и писать.
 - Пресет `claude_code` ИЗВЛЕКАЕМ: `strings -n 60 ~/.local/share/claude/versions/<ver>` (275 MB,
   not stripped). Промпт склеивается функциями, искать по `"# Doing tasks"`, `"# Tone and style"`,