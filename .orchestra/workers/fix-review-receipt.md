# fix-review-receipt

- `systemd-run --user --scope -p MemoryMax=2G nice -n 15 <command>` задаёт лимит и приоритет; `-p Nice=15` у scope отвергается как `Unknown assignment` до старта команды.
