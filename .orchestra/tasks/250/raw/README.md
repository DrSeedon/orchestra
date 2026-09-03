# Raw A/B outputs

Each numbered directory is one fresh model cell and contains the exact prompt, Codex JSONL events, stderr, final message, git diff, produced test, and run metadata. `run-summary.json` is the mechanical roll-up.

The raw files contain only the synthetic fixture/task, commands run inside its isolated repository, generated test, and local scratch paths. Before commit, `eval/verify_artifacts.py` scanned every raw line with the project's configured secret-form regexes; `artifact-check.txt` records `PASS raw secret-form scan: []`. A second literal scan found no authorization headers, internal-token fields, proxy values, API-key fields, or token assignments.

No raw output was hand-edited after the model calls. Sanitization is by construction plus the recorded negative scans, not by deleting unfavorable outputs.
