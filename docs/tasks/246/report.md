# #246 — validation of task project scope

## Live-data check before the gate

The live database was copied with `sqlite3.Connection.backup()` from
`/home/kesha/orchestra/data/orchestra.db` to a temporary database and queried only there.

- Total tasks: 331.
- Tasks whose `tm_projects` row has no registered `scope`: 8 across `Orchestra`, `Seedon`,
  and `orchestra`.
- Of those, 5 are not cancelled.
- Tasks attached to projects with a registered scope: 323.

The existing unscoped rows are therefore preserved for `task_get` and `task_update`. The new
gate applies only to creation.

## Contract

- `task_create(project=...)` accepts a registered scope or the id of a project that has a
  registered scope. Unknown and legacy unscoped projects are rejected before a task or project
  row is created. The error lists all allowed scopes. A token matching one project's id and a
  different project's scope is ambiguous and fails closed on create, get, update, and list.
- Omitting `project` resolves the caller's injected `scope` to its registered project.
- `task_get` and `task_update` resolve explicit registered ids or scopes through the same selector;
  unknown values fail, while exact legacy unscoped ids remain usable so the 8 existing rows can
  still be inspected or corrected.
- The creation check and insert run inside the same `BEGIN IMMEDIATE` transaction in
  `api_create_task`, avoiding a validation/insert race.

## Mixed-version window

The new MCP omits the `project` JSON field when the caller omits it. With an old in-memory route,
that request fails loudly with HTTP 422 and cannot create a blank/sentinel project. Old MCP
processes continue to send their explicit `project`; the new route validates it. Defaulted
creation becomes available after the Python service loads the new route, while already connected
MCP processes gain the optional tool argument only after reconnecting.
