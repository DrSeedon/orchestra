# research-auto-work

- В model eval сначала проверяй успешность provider call (`loop_ok`/status), затем классифицируй artifact; failed call имеет отдельный availability outcome. Offline correction пришпиливай к immutable source и ломай парной мутацией summary+receipt.
- Worktree наследует боевой `.env`: для provider-стендов передавай только точный нужный ключ контроллеру, а tool-side запускай через bwrap с равенством полному env allowlist и явным запретом proxy variables.
