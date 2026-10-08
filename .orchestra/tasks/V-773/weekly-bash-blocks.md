# Bash-команды, которые блокировал бы новый классификатор

Окно UTC: 2026-10-01T08:42:47+00:00 — 2026-10-08T08:42:47+00:00. Bash rows: 17334; разобрано command: 17334; неразобранный content: 0. Полные tool payloads не выгружаются в отчёт; список ниже содержит только сигнатуры новых правил.

Классификация и число вызовов:
- find_delete: 2
- recursive_rm: 37
- regex_blowup: 24
- rmdir_parents: 1
- unparsed_rm: 3

Новые блокируемые сигнатуры с числом вызовов:
- find_delete × 1: find <target> -name '*.jpg' -delete
- find_delete × 1: find <target> [options] -delete
- rmdir_parents × 1: rmdir -p <path outside the session worktree>
- unparsed_rm × 3: rm -i <selected files> <<< y
