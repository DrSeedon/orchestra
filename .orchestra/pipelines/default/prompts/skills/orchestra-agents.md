---
name: orchestra-agents
description: "Create an Orchestra orchestrator or permanent specialist, or move an agent between environments. Not for one-shot workers."
---

# Creating and moving Orchestra agents

Create an orchestrator or permanent specialist so it immediately receives project context and
the accumulated knowledge base instead of a blank slate that must be retrained.

Use this for:

- a new project that needs its own orchestrator;
- a recurring task class that needs a permanent specialist;
- moving an agent between environments (laptop ↔ VPS, one server ↔ another);
- "make one like mine" requests.

**Do not use this** for one-shot workers for a specific task: ordinary `spawn_worker` is enough,
and extra ceremony only gets in the way.

## Separate environments

**One Orchestra instance cannot see another instance's agents.** Each has its own database,
sessions, and list. `list_agents` and `list_orchestrators` show ONLY local agents. Before writing
to a "clone" or creating a copy, identify the environment; otherwise a message may go to a
similarly named but unrelated agent. Checking the recipient costs one call; an error loses a turn
and creates confusion in both environments.

For a remote instance, use the `vps-orchestra` skill; addresses and access details intentionally
do not belong in this file.

### 1. Identify what is needed

| Need | Role | Lifecycle |
|---|---|---|
| Project owner who manages workers | `orchestrator` (`is_orchestrator` flag) | persistent |
| Research, measurements, prompt edits | `full-cycle` | persistent |
| Implementation from a ready specification | `worker` | one-shot or persistent |
| Sub-team inside a large project | `sub-orchestrator` | persistent |

For an unfamiliar approach, choose `full-cycle` by default. If the owner explicitly assigned a
specialist another role, do not recreate it merely for a role label. The task defines method and
required evidence; having a module does not itself prove quality.

### 2. Orchestrator for a new project

Create an orchestrator through the session-creation API with `is_orchestrator: true`, not through
`spawn_worker`. Key request fields (`CreateSessionRequest` in `app/`):

```json
{
  "name": "<project>-orchestrator",
  "role": "orchestrator",
  "model": "opus",
  "cwd": "/path/to/project",
  "scope": "/path/to/project",
  "description": "lifecycle=persistent | project orchestrator"
}
```

`cwd` and `scope` are the project root, not a subdirectory; that is where `CLAUDE.md`, `TODO.md`,
and `.orchestra/` are loaded.

### 3. Permanent specialist

Use the session API with a stable name, project root, role, and a first task:

```python
create_session(
    name='<specialist-name>',
    role='full-cycle',
    model='sonnet',
    repo_path='/path/to/project',
    description='lifecycle=persistent | one-sentence role',
    task='<first task>',
)
```

### 4. Main rule: keep `system_prompt` empty

The runtime assembles the complete prompt from the role, modules, and personal memory. A custom
text is an optional overlay and is absent by default.

Write an overlay only for a boundary absent from the role, task, or `owned_dirs`: narrow
expertise (such as Python asyncio), a specific directory prohibition, or a quality bar above the
standard.

**Do not rewrite the role or shared quality rules in an overlay** — they already exist in the
assembled prompt, and the agent will follow your stale copy instead of the source. The source may
be updated while the copy silently diverges.

### 5. Move an agent between environments

Move **the recipe plus memory, not the session**. Conversation, accumulated context, and
`session_id` do not move; this is a property that rebuilds the agent from reproducible parts.

What actually moves:

| What | How |
|---|---|
| Personal memory | `.orchestra/workers/<name>.md` in the repository, arriving with `git pull` |
| Project rules | `CLAUDE.md`, through the same `git pull` |
| Codex-agent mirror | `AGENTS.md`, generated when the backend connects |
| Role and modules | From `.orchestra/pipelines/` in the repository |
| Conversation, `session_id` | **Does not move** |

**Key technique:** personal memory is injected by exact name matching. Give the agent the same
name in the new environment and it receives the accumulated base at its first spawn. Manual data
copying is unnecessary and is the common mistake.

Move in this order:

1. Ensure `.orchestra/workers/<name>.md` is committed and has reached the remote environment.
2. Send the recipe: exact name, role, model, `description`, and first task.
3. State explicitly that `system_prompt` is empty; otherwise the destination will invent one and
   conflict with the role.
4. Attach 1–2 example results so the receiving side understands the quality bar.

### 6. Deliberately erase history during a move

When moving an agent with a long life in the old environment, consider clearing its history
(`session_id`) instead of moving it.

The reason is tested in practice: an old session remembers stale state and acts on it confidently.
An agent with cleared history and a fresh handoff document errs less often than one remembering an
outdated configuration. Compaction does not solve this: it asks the session to summarize itself,
so stale beliefs move into the summary without their source.

Do this with the service STOPPED — a live server will overwrite the value from memory. Always
leave a handoff document: what is done, what is in progress, decisions made, and what not to touch.
Without it the agent has no support.

After creation, report one line: name, role, model, and environment. For a move, state what moved
(memory/rules) and what stayed (conversation).

## Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| Agent "does not know the project" | `cwd`/`scope` point below the project root | Recreate with the project root |
| Agent ignores part of the rules | Custom `system_prompt` conflicts with the role | Remove the overlay; keep it empty |
| Personal memory was not loaded | Name differs from `.orchestra/workers/<name>.md` | Rename the agent to exactly match the file |
| Codex agent sees old rules | `AGENTS.md` mirror was not refreshed | It is written on backend connect; reconnect |
| "Created an orchestrator, but it is a worker" | `is_orchestrator` flag was omitted | Create through `POST /api/sessions`, not `spawn_worker` |
| Message reached the wrong agent | Same name in different environments | Check the agent list of THAT instance |

## What not to do

- **Copy agent data manually** — memory is loaded by name; manual copying creates a second
  diverging version.
- **Write a detailed `system_prompt`** — it conflicts with the role, so the agent follows the
  copy instead of the source.
- **Move the whole session** — stale beliefs move with it and sound as confident as correct ones.
