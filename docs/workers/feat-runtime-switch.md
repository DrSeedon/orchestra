# feat-runtime-switch

- В worktree Orchestra `VIRTUAL_ENV` указывает на `/home/kesha/orchestra/.venv`; для точечных прогонов использовать `uv run --active ...`, иначе uv создаёт лишнюю `.venv` внутри worktree.
- Перед формулировкой `Codex approved` открыть `codex-review-*.md` и проверить содержательный `Verdict`; exit 0/background completion при `bwrap`/read failure означает «вердикта нет», даже если job формально успешна.
