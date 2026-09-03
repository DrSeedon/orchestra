<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently “quarantine” currently means “please follow this symlink” 😏 The diff has six blocking issues around path safety, races, Git refs, partial application, and valid filenames, plus two operational concerns. No files were edited or tests run.

## Findings

### Blocking

1. **Reject symlinked quarantine project roots**

   **File:** `app/ia/project_distribution.py:252-257`  
   **Confidence:** 0.99

   An unmapped project is joined directly under `quarantine_root`, but a pre-existing `<quarantine_root>/<project_id>` symlink is later resolved as `repository_root`. The containment check then validates paths relative to the already-escaped target, so `--apply` can create records outside the quarantine tree.

2. **Validate the manifest path for containment**

   **File:** `app/ia/project_distribution.py:348-350`  
   **Confidence:** 0.98

   Record destinations are checked for path escape, but `manifest_path` is not. For a project with zero records, a symlinked `docs` or `kb` directory can make `_write_json()` create the manifest outside the repository.

3. **Close the check-then-replace race**

   **File:** `app/ia/project_distribution.py:341-350`  
   **Confidence:** 0.99

   After preflight, `if not destination.exists()` is followed by unconditional `os.replace()`. Another process can create the file between those operations and have it silently overwritten; the same race exists for the manifest. A lock or no-clobber creation plus revalidation is required.

4. **Enforce the captured destination ref before committing**

   **File:** `app/ia/project_distribution.py:321-326`  
   **Confidence:** 0.97

   `before_head` and `target_ref` are recorded but never rechecked. A concurrent checkout or commit can move the worktree to another branch/base after planning, and the distribution will write and commit there while reporting success.

5. **Handle partial application explicitly**

   **File:** `app/ia/project_distribution.py:439-441`  
   **Confidence:** 0.95

   Plans are applied sequentially. If a later materialization or commit fails, earlier repositories may already contain committed changes, while the caller receives only an exception and no partial-result receipt. This leaves the distribution incomplete and requires rollback or explicit resumable partial-state handling.

6. **Use NUL-delimited Git path output**

   **File:** `app/ia/project_distribution.py:355-364`  
   **Confidence:** 0.97

   `git diff --cached --name-only` is parsed with `splitlines()`, but Git quotes paths containing newlines or other unusual bytes. Since `stable_id` is derived from an unrestricted filename, a valid record filename containing a newline can be staged successfully but then fail to commit because the quoted representation is passed back as a literal path.

### Suggestion

7. **Make receipt output safe for managed repositories**

   **File:** `scripts/distribute_project_knowledge.py:55-61`  
   **Confidence:** 0.98

   `--receipt-path` is written after the apply/commit status check. Pointing it inside the canonical or destination repository can create an untracked file, overwrite a manifest, or leave the repository dirty while the command returns success. Reject managed-tree paths or include receipt persistence in the transaction.

### Question

8. **Should dry-run and verify contact live remotes?**

   **File:** `app/ia/project_distribution.py:142-150`  
   **Confidence:** 0.93

   `_remote_refs()` runs during planning even for `--dry-run` and `--verify`, and the subprocess has no timeout. An unavailable or interactive remote can therefore turn a local fixture check into a hang or failure; custom remote helpers are also executed. Make remote probing explicit and bounded if it is required for the receipt.

## Verdict

**❌ Incorrect — changes requested.** The implementation is not safe to apply because quarantine and manifest paths can escape, concurrent changes can be overwritten, and destination refs are not pinned during commit.

The quarantine currently has about as much perimeter security as a sign saying “foreign files, this way.”

## Round (2026-08-28T04:11:30Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

О, предыдущие дыры действительно заварили — теперь ломается уже взаимодействие фиксов 😏 Большинство прошлых находок исправлено, но остаются 4 блокирующих проблемы. Указанные тесты не запускал: ревью ограничено diff-файлом.

## Findings (blocking/suggestion/question)

### Prior findings

| Предыдущая находка | Статус |
|---|---|
| Quarantine symlink/path escape | **FIXED** |
| Manifest-parent symlink escape | **FIXED** |
| TOCTOU overwrite | **FIXED** |
| Destination ref/head/dirty-tree race | **FIXED** для одного Git-root |
| Partial apply reporting | **FIXED** для ошибок внутри `_materialize()` |
| NUL path parsing | **FIXED** |
| Unconditional/unbounded remote probing | **FIXED**: opt-in и timeout добавлены |
| Receipt inside managed Git tree | **FIXED** |

### New blocking findings

1. **Не применяйте отдельные snapshots к нескольким планам одного Git-root**

   **File:** `app/ia/project_distribution.py:543-548`  
   **Confidence:** 1.00

   Все orphan-проекты используют один `quarantine_root`, но каждый план сохраняет один и тот же `before_head`. После коммита первого проекта HEAD quarantine-репозитория меняется, поэтому второй план всегда получает `destination HEAD drift` и distribution завершается частично. То же происходит с `commit=False` из-за оставшегося dirty tree.

2. **Принудительно отключите Git prompts**

   **File:** `app/ia/project_distribution.py:108-109`  
   **Confidence:** 0.98

   `env.setdefault("GIT_TERMINAL_PROMPT", "0")` оставляет унаследованное значение `GIT_TERMINAL_PROMPT=1`. При `--probe-remotes` `ls-remote` тогда может запросить credentials; 30-секундный timeout лишь превращает prompt в задержку и ошибку, но не обеспечивает заявленный no-prompts режим.

3. **Оберните post-apply сбор результата в partial-result handling**

   **File:** `app/ia/project_distribution.py:563-565`  
   **Confidence:** 0.97

   После успешных `_materialize()` вызывается `_public_project()` уже вне `try`. Таймаут или ошибка `ls-remote`, `_head()` или другой after-snapshot может произойти после коммитов, но CLI вернёт обычный `2` без partial receipt, будто distribution не выполнен. Аналогично конфликт записи receipt на `scripts/distribute_project_knowledge.py:85-88` происходит уже после изменения репозиториев.

4. **Проверяйте неизменность локальных refs и config**

   **File:** `app/ia/project_distribution.py:404-408`  
   **Confidence:** 0.94

   `local_refs_before` и `local_config_sha256_before` только сохраняются в плане; после операции они не сравниваются с `local_refs_after` и `local_config_sha256_after`. Hook или concurrent actor может изменить другой local ref либо `.git/config`, при этом HEAD, текущая ветка и worktree останутся корректными, а команда всё равно сообщит об успешной distribution.

## Verdict

**❌ Incorrect — changes requested.** Предыдущие основные фиксы на месте, но несколько orphan-проектов в одной quarantine-репе сейчас гарантированно не проходят полный apply, а post-apply ошибки могут маскировать уже выполненные коммиты.

Quarantine теперь не пускает чужих через окно, зато свои проекты запирает друг с другом в одной двери.

## Round (2026-08-28T04:18:48Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Финальный раунд, а Git всё ещё умеет подложить сюрприз прямо в коммит 😏 Указанные тесты заявлены зелёными; я их не запускал и проверял только `/tmp/412-t1.diff`.

## Findings (blocking/suggestion/question)

### Prior blockers

| Предыдущая находка | Статус |
|---|---|
| Shared quarantine Git-root | **FIXED** — планы группируются и коммитятся одним locked group |
| Inherited `GIT_TERMINAL_PROMPT` | **FIXED** — значение принудительно равно `0` |
| Post-apply snapshot handling | **STILL BROKEN** для ошибок записи receipt |
| Local refs/config and remote comparison | **FIXED** |
| Более ранние path/no-clobber/NUL/managed-tree receipt blockers | **FIXED** |

### New blocking findings

1. **Проверяйте committed blobs на byte parity**

   **File:** `app/ia/project_distribution.py:469-474`  
   **Confidence:** 0.98

   `git add` применяет `.gitattributes`, clean filters и EOL-нормализацию, а pre-commit hook может дополнительно изменить и заново застейджить payload. После коммита проверяется только dirty status и refs/config, поэтому репозиторий может успешно закоммитить байты, отличные от source, хотя distribution вернёт успех.

2. **Запретите Git hooks нарушать local-only контракт**

   **File:** `app/ia/project_distribution.py:488-496`  
   **Confidence:** 0.96

   `git commit` запускается с обычными hooks. Hook может выполнить `git push`/`fetch` или изменить внешний state; `_FORBIDDEN_GIT` контролирует только прямые вызовы `_git` и не распространяется на дочерние команды hook. При выключенном `probe_remotes` такой push вообще не будет замечен.

3. **Считайте ошибки receipt-записи partial failure**

   **File:** `scripts/distribute_project_knowledge.py:90-94`  
   **Confidence:** 0.99

   После успешного apply `_write_receipt()` обрабатывается как partial только для `DistributionError`. `PermissionError`, `OSError` из `mkdir/open/write` и нехватка места уходят во внешний обработчик с exit code `2`, хотя destination-коммиты уже выполнены и partial receipt не сформирован.

4. **Отключите SSH-интерактивность, а не только Git prompts**

   **File:** `app/ia/project_distribution.py:108-117`  
   **Confidence:** 0.94

   `GIT_TERMINAL_PROMPT=0` и `GIT_ASKPASS=/bin/false` не запрещают SSH host-key/password/passphrase prompts. При `--probe-remotes` с SSH URL процесс может ждать ввода до timeout, поэтому заявленный non-interactive режим не гарантирован.

## Verdict

**❌ Incorrect — changes requested.** Остались блокирующие нарушения byte-preserving и local-only контрактов, плюс receipt I/O всё ещё может маскировать уже выполненную distribution.

Ворота quarantine заперли, но hook всё ещё ходит по территории с ключом от соседнего дома.
