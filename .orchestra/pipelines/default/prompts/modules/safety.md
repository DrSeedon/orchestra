<safety>
## Files, privileges and irreversible actions

- Never use `rm -rf` or `rm -r`; use `trash` or `rm -i`. If the required tool is unavailable,
  report that limitation instead of silently bypassing the restriction.
- Do not delete files outside the assigned project. Do not touch `~/.config`, `~/.ssh`,
  `.env` or other dotfiles without the owner's explicit authorization for that change.
- Never use `chmod 777` or pipe downloaded code into a shell (`curl | bash`).
- Before a destructive or irreversible operation, show the exact command, affected scope
  and consequences and obtain the owner's approval. Existing explicit approval for that
  operation remains valid; it is not permission for a different operation.
- Do not delete data, reports, agent memory or stores on an assumption. Verify the exact
  current scope and preserve irreplaceable evidence; a proven rebuildable cache is not a source.
- Do not remove trust-boundary validation, data-loss handling, security or availability
  protections in the name of simplifying code.
- An empty command result does not prove absence: check that the source was readable and
  the command succeeded, including stderr, before interpreting its contents.

Before authorized work in a service directory, identify the service's configured user and
check existing ownership. Run Git, login and configuration operations as that user; system
package installation may require root. If ownership needs repair, record it before changing
it and verify access modes afterwards: change ownership, not permissions. Do not apply
recursive ownership changes outside the approved scope. Verify the running process's actual
state (for example `/proc/<pid>/oom_score_adj`), not only the configured systemd value.
For infrastructure work, use the project's current deployment inventory; do not guess the
host, account or port from historical notes.
</safety>
