I couldn’t inspect the repository: all three read-only command attempts failed before execution with:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

No files were modified. The available resource tools provide no repository access, so I can’t substantiate the call path, gate formula, release behavior, or edge cases with `file:line` evidence.

Please rerun this investigation once the command sandbox is working; answering now would require inventing code details.