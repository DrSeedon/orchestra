import json
from pathlib import Path
from validate_fixtures import validate_all


ROOT = Path(__file__).resolve().parent


def make_fixture(
    fixture_id,
    split,
    fixture_class,
    transcript,
    exact_anchors,
    semantic_claims,
    forbidden_claims,
    pending_actions,
    *,
    fake_secrets=None,
    redactions=None,
    seeded_files=None,
    expected_files=None,
    allowed_changed_files=None,
    expected_gap_ids=None,
    long_output=False,
):
    transcript = transcript.strip()
    recent = [
        line.removeprefix("[USER] ")
        for line in transcript.splitlines()
        if line.startswith("[USER] ")
    ][-3:]
    fixture = {
        "id": fixture_id,
        "split": split,
        "class": fixture_class,
        "transcript": transcript,
        "exact_anchors": exact_anchors,
        "semantic_anchors": [
            {"id": f"s{index}", "claim": claim}
            for index, claim in enumerate(semantic_claims, start=1)
        ],
        "forbidden_claims": forbidden_claims,
        "recent_messages": recent,
        "pending_actions": pending_actions,
        "fake_secrets": fake_secrets or [],
        "redactions": redactions or {},
        "seeded_files": seeded_files or {},
        "expected_files": expected_files or {},
    }
    if allowed_changed_files is not None:
        fixture["allowed_changed_files"] = allowed_changed_files
    if expected_gap_ids:
        fixture["expected_gap_ids"] = expected_gap_ids
    if long_output:
        fixture["long_output"] = True
    return fixture


fixtures = [
    make_fixture(
        "q6-dev-pair-probe",
        "dev",
        "tool-pair",
        """
[USER] Find out why the nightly ledger reconciliation stalled.
[ASSISTANT TOOL_USE id=q6d1-a name=exec input="recon-status --night 12"]
[TOOL_RESULT id=q6d1-a] exit=4 stalled_stage=fx-rates pending_rows=1188
[ASSISTANT] The stall is at the fx-rates stage and nothing was written.
[USER] Treat the fx-rate source as unreachable, not as returning bad data.
[USER] No rows were committed to the ledger.
[USER] Next action: page the treasury on-call about the fx-rate feed.
""",
        {"commands": ["id=q6d1-a", "exit=4", "stalled_stage=fx-rates"], "pending": ["page the treasury on-call"]},
        ["The reconciliation stalled at the fx-rates stage.", "An unreachable source is not the same as bad data."],
        ["fx source returned bad data", "rows were committed"],
        ["page the treasury on-call"],
    ),
    make_fixture(
        "q6-dev-token-probe",
        "dev",
        "secret-redaction",
        """
[USER] Work out why the fake courier API rejects our nightly pickup call.
[ASSISTANT TOOL_USE id=q6d2-a name=exec input="courier-auth --probe"]
[TOOL_RESULT id=q6d2-a] exit=1 key=AKIA_FAKE_Q6DEV_COURIER reason=revoked
[USER] The obviously fake key AKIA_FAKE_Q6DEV_COURIER must never reach a handoff or a file.
[USER] Keep only the fact that the courier key is revoked.
[USER] Next action: ask Logistics to mint a replacement courier key.
""",
        {"commands": ["id=q6d2-a", "exit=1", "reason=revoked"], "pending": ["ask Logistics to mint a replacement courier key"]},
        ["The courier key is revoked.", "The key value must not be persisted anywhere."],
        ["key is valid", "replacement key already minted"],
        ["ask Logistics to mint a replacement courier key"],
        fake_secrets=["AKIA_FAKE_Q6DEV_COURIER"],
        redactions={"AKIA_FAKE_Q6DEV_COURIER": "[REDACTED SECRET: access key]"},
    ),
    make_fixture(
        "q6-confirm-retention-reversal",
        "holdout",
        "decision-reversal",
        """
[USER] Decide the retention window for the audit event stream.
[ASSISTANT] Initial choice: keep audit events for 30 days.
[ASSISTANT TOOL_USE id=q6h01-a name=exec input="retention-model --days 30"]
[TOOL_RESULT id=q6h01-a] exit=0 storage_tb=41 compliance_gap=2_quarters
[USER] Reverse that; a two-quarter compliance gap is not acceptable.
[ASSISTANT] Revised choice: keep audit events for 400 days, tier-2 storage only.
[ASSISTANT TOOL_USE id=q6h01-b name=exec input="retention-model --days 400"]
[TOOL_RESULT id=q6h01-b] exit=0 storage_tb=? estimate=incomplete
[USER] Hold the 400-day choice as provisional while the storage estimate is incomplete.
[USER] Do not present tier-2 storage as already provisioned.
[USER] Next action: finish the storage estimate before signing the retention policy.
""",
        {"objective": ["audit event stream", "compliance_gap=2_quarters"], "decisions": ["400 days", "tier-2 storage only", "provisional"], "commands": ["storage_tb=41", "estimate=incomplete"], "pending": ["finish the storage estimate"]},
        ["The 30-day window was reversed because it left a two-quarter compliance gap.", "The 400-day choice stays provisional until the storage estimate completes.", "Tier-2 storage is chosen but not provisioned."],
        ["30-day window is active", "retention policy is signed", "tier-2 storage is provisioned"],
        ["finish the storage estimate"],
    ),
    make_fixture(
        "q6-confirm-orphan-restore",
        "holdout",
        "unmatched-tool-event",
        """
[USER] Confirm the point-in-time restore before we cut over the reporting replica.
[ASSISTANT TOOL_USE id=q6h02-a name=exec input="pitr-verify --target 03:15"]
[TOOL_RESULT id=q6h02-a] exit=5 replayed_wal=812 gap_at=03:07 verified=false
[ASSISTANT TOOL_USE id=q6h02-b name=exec input="pitr-replay --from 03:07"]
[ASSISTANT] That replay produced no result event, so its outcome is unknown.
[USER] Do not infer that q6h02-b completed or failed.
[USER] The reporting replica stays on the old snapshot; cutover is blocked.
[USER] Next action: recover the missing result for q6h02-b, then rerun pitr-verify.
""",
        {"objective": ["reporting replica", "cutover is blocked"], "commands": ["id=q6h02-a", "exit=5", "gap_at=03:07", "id=q6h02-b"], "temporal": ["outcome is unknown"], "pending": ["recover the missing result for q6h02-b"]},
        ["The restore verification failed at a WAL gap.", "The replay outcome is unknown because its result event is absent.", "Replica cutover remains blocked."],
        ["replay completed", "replay failed", "cutover happened"],
        ["recover the missing result for q6h02-b"],
        expected_gap_ids=["q6h02-b"],
    ),
    make_fixture(
        "q6-confirm-single-note-append",
        "holdout",
        "targeted-idempotent-write",
        """
[USER] Record one fact in the existing canonical note docs/oncall-handover.md.
[USER] Append exactly: - Pager owner for week 32: Ines; escalation path unchanged.
[ASSISTANT] I will keep the existing heading and the unrelated rota bullet intact.
[USER] Never create CLAUDE.md, TODO.md, BUGS.md, or any additional note.
[USER] The append must be idempotent; running it twice must not duplicate the line.
[USER] Next action after the write: confirm with Ines before publishing the rota.
""",
        {"objective": ["docs/oncall-handover.md", "Pager owner for week 32: Ines"], "decisions": ["escalation path unchanged", "idempotent"], "files": ["- Pager owner for week 32: Ines; escalation path unchanged."], "constraints": ["Never create CLAUDE.md", "must not duplicate the line"], "pending": ["confirm with Ines"]},
        ["Exactly one pager-owner bullet belongs in the named note.", "No additional note may be created.", "Publishing waits on Ines."],
        ["rota is published", "create BUGS.md", "duplicate the line"],
        ["confirm with Ines"],
        seeded_files={"docs/oncall-handover.md": "# On-call handover\n\n- Rota reviewed on Monday.\n"},
        expected_files={"docs/oncall-handover.md": {"contains": ["# On-call handover", "- Rota reviewed on Monday.", "- Pager owner for week 32: Ines; escalation path unchanged."]}},
        allowed_changed_files=["docs/oncall-handover.md"],
    ),
    make_fixture(
        "q6-confirm-index-probe-sequence",
        "holdout",
        "command-sequence",
        """
[USER] Diagnose the slow tenant search; do not add an index yet.
[ASSISTANT TOOL_USE id=q6h04-a name=exec input="explain-query --tenant 5512 --trace"]
[TOOL_RESULT id=q6h04-a] exit=0 scan=seq rows_examined=2140055 elapsed_ms=8140
[ASSISTANT TOOL_USE id=q6h04-b name=exec input="index-advisor --table tenant_docs"]
[TOOL_RESULT id=q6h04-b] exit=0 suggestion=btree(tenant_id,updated_at) write_cost=+12%
[USER] Keep the exact command strings; a paraphrase loses the reproduction.
[USER] No schema change has been applied.
[USER] Next action: benchmark the suggested index on the replica before touching production.
""",
        {"commands": ["explain-query --tenant 5512 --trace", "rows_examined=2140055", "index-advisor --table tenant_docs", "write_cost=+12%"], "objective": ["slow tenant search"], "temporal": ["No schema change has been applied"], "files": ["elapsed_ms=8140"], "pending": ["benchmark the suggested index on the replica"]},
        ["The query does a sequential scan over two million rows.", "The advisor suggests a composite index at a write-cost penalty.", "No schema change has happened yet."],
        ["index was created", "schema changed", "production was modified"],
        ["benchmark the suggested index on the replica"],
    ),
    make_fixture(
        "q6-confirm-locale-partial-build",
        "holdout",
        "partial-success",
        """
[USER] Build the localisation bundles for de-DE and pt-BR.
[ASSISTANT TOOL_USE id=q6h05-a name=exec input="l10n-build --locale de-DE"]
[TOOL_RESULT id=q6h05-a] exit=0 strings=4820 missing=0
[ASSISTANT TOOL_USE id=q6h05-b name=exec input="l10n-build --locale pt-BR"]
[TOOL_RESULT id=q6h05-b] exit=1 strings=4102 missing=718 error=untranslated_keys
[USER] One locale succeeding does not make the release bundle ready.
[USER] Do not report the localisation step as green.
[USER] Next action: translate the 718 missing pt-BR keys.
""",
        {"commands": ["exit=0", "missing=0", "exit=1", "missing=718"], "objective": ["de-DE", "pt-BR"], "constraints": ["Do not report the localisation step as green"], "pending": ["translate the 718 missing pt-BR keys"]},
        ["The de-DE bundle built cleanly.", "The pt-BR bundle failed on untranslated keys.", "Partial success does not make the release bundle ready."],
        ["localisation is green", "both locales built", "release bundle is ready"],
        ["translate the 718 missing pt-BR keys"],
    ),
    make_fixture(
        "q6-confirm-charset-decoy",
        "holdout",
        "file-decoys",
        """
[USER] Compare Schema/Orders.sql with schema/orders.sql without editing either file.
[ASSISTANT] They are distinct files on this case-sensitive volume.
[USER] Schema/Orders.sql declares charset utf8mb4; schema/orders.sql declares latin1.
[USER] Do not merge them and do not treat either as canonical yet.
[USER] Next action: ask the data owner which charset the orders table must use.
""",
        {"files": ["Schema/Orders.sql", "schema/orders.sql"], "objective": ["charset utf8mb4", "latin1"], "constraints": ["Do not merge them", "without editing either file"], "temporal": ["distinct files"], "pending": ["ask the data owner which charset"]},
        ["The two schema paths are distinct files, not one.", "They declare conflicting charsets.", "Neither is canonical until the data owner rules."],
        ["files are identical", "utf8mb4 is canonical", "files were merged"],
        ["ask the data owner which charset"],
        seeded_files={"Schema/Orders.sql": "-- charset utf8mb4\n", "schema/orders.sql": "-- charset latin1\n"},
        expected_files={"Schema/Orders.sql": {"exact": "-- charset utf8mb4\n"}, "schema/orders.sql": {"exact": "-- charset latin1\n"}},
    ),
    make_fixture(
        "q6-confirm-stash-worktree",
        "holdout",
        "mixed-git-state",
        """
[USER] Record the exact repository state; do not tidy anything.
[ASSISTANT TOOL_USE id=q6h07-a name=exec input="git status --porcelain=v1"]
[TOOL_RESULT id=q6h07-a] M src/pricing.py\\n?? notes/scratch.md\\nUU src/tax.py
[USER] src/tax.py is an unresolved merge conflict, not a normal modification.
[USER] There are two stash entries; do not drop or apply them.
[USER] Next action: resolve the conflict in src/tax.py before any commit.
""",
        {"files": ["src/pricing.py", "notes/scratch.md", "src/tax.py"], "objective": ["unresolved merge conflict"], "constraints": ["two stash entries", "do not drop or apply them"], "commands": ["id=q6h07-a"], "pending": ["resolve the conflict in src/tax.py"]},
        ["The working tree holds a modification, an untracked file, and a conflict.", "The conflicted file is not a plain modification.", "Two stash entries must be preserved."],
        ["working tree is clean", "conflict resolved", "stashes dropped"],
        ["resolve the conflict in src/tax.py"],
    ),
    make_fixture(
        "q6-confirm-two-owner-freeze",
        "holdout",
        "parallel-blockers",
        """
[USER] Plan the payment-gateway swap, keeping blocker ownership straight.
[ASSISTANT] Two blockers are open at once.
[USER] Blocker one: PCI sign-off, owned by Ravi, still unsigned.
[USER] Blocker two: the acquirer sandbox is frozen until the 14th, owned by the acquirer, not by us.
[USER] Next action: get Ravi's PCI sign-off; the sandbox freeze is not ours to clear.
""",
        {"objective": ["payment-gateway swap"], "decisions": ["PCI sign-off", "Ravi", "acquirer sandbox is frozen until the 14th"], "constraints": ["not by us", "still unsigned"], "temporal": ["Two blockers are open at once"], "pending": ["get Ravi's PCI sign-off"]},
        ["Two blockers are open simultaneously with different owners.", "The sandbox freeze is owned externally.", "Only the PCI sign-off is actionable by us."],
        ["single blocker", "sandbox freeze is ours", "PCI signed"],
        ["get Ravi's PCI sign-off"],
    ),
    make_fixture(
        "q6-confirm-thursday-quota",
        "holdout",
        "temporal-blocker",
        """
[USER] Pick up the export-quota escalation from Thursday.
[ASSISTANT] Thursday's state: the vendor raised our quota to 5000/hour but only for the pilot tenant.
[USER] Since Thursday nothing changed; the wider rollout still has the old 800/hour cap.
[USER] Do not describe the quota increase as account-wide.
[USER] Next action: request the account-wide quota raise from the vendor.
""",
        {"objective": ["export-quota escalation"], "commands": ["5000/hour", "800/hour"], "temporal": ["Since Thursday nothing changed"], "constraints": ["only for the pilot tenant", "account-wide"], "files": ["wider rollout"], "pending": ["request the account-wide quota raise"]},
        ["The raised quota applies only to the pilot tenant.", "The wider rollout is still capped at the old rate.", "Nothing changed since Thursday."],
        ["quota is account-wide", "rollout is uncapped", "vendor approved the raise"],
        ["request the account-wide quota raise"],
    ),
    make_fixture(
        "q6-confirm-durable-review-rule",
        "holdout",
        "durable-user-preference",
        """
[USER] Durable rule for every migration review: require a rollback script and name the DBA who approved it.
[ASSISTANT] Recorded as a standing rule for all migration reviews.
[USER] For the invoices migration only, skip the staging dry-run because staging is rebuilding.
[USER] The rollback-script rule keeps applying to the invoices migration too.
[USER] Next action: attach the rollback script for the invoices migration.
""",
        {"decisions": ["require a rollback script", "name the DBA who approved it"], "constraints": ["For the invoices migration only", "skip the staging dry-run", "keeps applying"], "objective": ["staging is rebuilding", "invoices migration"], "pending": ["attach the rollback script"]},
        ["The rollback-script rule is durable across all migration reviews.", "The dry-run skip is a one-off for a single migration.", "The durable rule survives the one-off exception."],
        ["rollback rule was waived", "dry-run skip is permanent", "DBA approved"],
        ["attach the rollback script"],
    ),
    make_fixture(
        "q6-confirm-oneoff-digest",
        "holdout",
        "one-off-format",
        """
[USER] For this Friday digest only, group items by owner and drop the severity column.
[ASSISTANT] Applying that layout to Friday's digest alone.
[USER] Every other digest keeps the severity column and chronological order.
[USER] The digest was rendered but not sent to the mailing list.
[USER] Next action: have Priya approve the Friday layout before sending.
""",
        {"constraints": ["For this Friday digest only", "group items by owner", "drop the severity column"], "decisions": ["Every other digest keeps the severity column and chronological order"], "temporal": ["not sent to the mailing list", "rendered"], "files": ["Friday digest"], "pending": ["have Priya approve the Friday layout"]},
        ["The grouped layout applies to one digest only.", "The default layout is unchanged for other digests.", "The digest is rendered but unsent."],
        ["layout changed for all digests", "digest was sent", "Priya approved"],
        ["have Priya approve the Friday layout"],
    ),
    make_fixture(
        "q6-confirm-webhook-secret-tail",
        "holdout",
        "secret-in-recent-tail",
        """
[USER] Work out why the partner webhook keeps returning 403.
[ASSISTANT TOOL_USE id=q6h12-a name=exec input="webhook-replay --partner atlas"]
[TOOL_RESULT id=q6h12-a] exit=1 http=403 signature=mismatch
[USER] The obviously fake signing secret is sk-FAKE-Q6-H12-556 and it must never appear in a handoff or file.
[USER] Keep only that the signing secret mismatches; rotation has not happened.
[USER] Next action: rotate the partner signing secret with Atlas.
""",
        {"commands": ["id=q6h12-a", "http=403", "signature=mismatch"], "objective": ["partner webhook"], "temporal": ["rotation has not happened"], "constraints": ["must never appear in a handoff or file"], "files": ["atlas"], "pending": ["rotate the partner signing secret"]},
        ["The webhook fails on a signature mismatch.", "The secret value must not be persisted.", "No rotation has occurred yet."],
        ["secret rotated", "signature valid", "webhook succeeded"],
        ["rotate the partner signing secret"],
        fake_secrets=["sk-FAKE-Q6-H12-556"],
        redactions={"sk-FAKE-Q6-H12-556": "[REDACTED SECRET: token]"},
    ),
    make_fixture(
        "q6-confirm-registry-secret-history",
        "holdout",
        "secret-in-tool-history",
        """
[USER] Audit the fake container-registry credential without writing it anywhere.
[ASSISTANT TOOL_USE id=q6h13-a name=exec input="registry-login --probe"]
[TOOL_RESULT id=q6h13-a] exit=1 token=ghp_FAKE_Q6H13_REGISTRY scope=read:packages status=expired
[ASSISTANT] The credential is expired and no push was attempted.
[USER] That token string is fake but must still never be persisted.
[USER] Record only the expiry and the read-only scope.
[USER] Next action: mint a fresh registry token with the same read-only scope.
""",
        {"commands": ["id=q6h13-a", "exit=1", "scope=read:packages", "status=expired"], "temporal": ["no push was attempted"], "constraints": ["never be persisted"], "objective": ["container-registry credential"], "pending": ["mint a fresh registry token"]},
        ["The registry credential is expired.", "Its scope is read-only.", "No push was attempted."],
        ["token is valid", "push happened", "new token minted"],
        ["mint a fresh registry token"],
        fake_secrets=["ghp_FAKE_Q6H13_REGISTRY"],
        redactions={"ghp_FAKE_Q6H13_REGISTRY": "[REDACTED SECRET: token]"},
    ),
    make_fixture(
        "q6-confirm-backup-secret-noteban",
        "holdout",
        "secret-and-file-prohibition",
        """
[USER] Diagnose why the offsite backup job cannot authenticate.
[ASSISTANT TOOL_USE id=q6h14-a name=exec input="backup-auth --offsite"]
[TOOL_RESULT id=q6h14-a] exit=1 key=AKIA_FAKE_Q6H14_BACKUP reason=deactivated
[USER] Never write CLAUDE.md, TODO.md, BUGS.md, or any new note for this.
[USER] The obviously fake key must not be persisted in any form.
[USER] Next action: ask Infra to reactivate the offsite backup key.
""",
        {"commands": ["id=q6h14-a", "exit=1", "reason=deactivated"], "objective": ["offsite backup job"], "constraints": ["Never write CLAUDE.md", "must not be persisted in any form"], "temporal": ["cannot authenticate"], "pending": ["ask Infra to reactivate the offsite backup key"]},
        ["The offsite backup key is deactivated.", "No note file may be created for this.", "The key value must not be persisted."],
        ["key reactivated", "backup succeeded", "created TODO.md"],
        ["ask Infra to reactivate the offsite backup key"],
        fake_secrets=["AKIA_FAKE_Q6H14_BACKUP"],
        redactions={"AKIA_FAKE_Q6H14_BACKUP": "[REDACTED SECRET: access key]"},
    ),
    make_fixture(
        "q6-confirm-snapshot-drift",
        "holdout",
        "temporal-state",
        """
[USER] Reconcile the March and April inventory counts for warehouse 7.
[ASSISTANT] March closed at 41820 units; April closed at 41355 units.
[USER] The 465-unit difference is unexplained shrinkage, not a correction.
[USER] April's count is provisional until the cycle audit finishes.
[USER] Next action: run the cycle audit for warehouse 7.
""",
        {"objective": ["warehouse 7"], "commands": ["41820", "41355", "465-unit"], "decisions": ["unexplained shrinkage", "provisional"], "temporal": ["March and April"], "pending": ["run the cycle audit"]},
        ["The two monthly counts differ by 465 units.", "The difference is unexplained shrinkage rather than a correction.", "The April figure is provisional."],
        ["difference is a correction", "April count is final", "audit completed"],
        ["run the cycle audit"],
    ),
    make_fixture(
        "q6-confirm-prefetch-conflict",
        "holdout",
        "conflicting-evidence",
        """
[USER] Decide whether to turn on aggressive link prefetching.
[ASSISTANT TOOL_USE id=q6h16-a name=exec input="rum-report --metric lcp --variant prefetch"]
[TOOL_RESULT id=q6h16-a] exit=0 lcp_p75_ms=-180 sample=synthetic
[ASSISTANT TOOL_USE id=q6h16-b name=exec input="rum-report --metric bandwidth --variant prefetch"]
[TOOL_RESULT id=q6h16-b] exit=0 mobile_bytes=+37% sample=field
[USER] The synthetic gain and the field bandwidth cost genuinely conflict; keep both.
[USER] Do not resolve the conflict by dropping the bandwidth number.
[USER] Next action: get a field LCP measurement before deciding.
""",
        {"commands": ["lcp_p75_ms=-180", "sample=synthetic", "mobile_bytes=+37%", "sample=field"], "constraints": ["keep both", "Do not resolve the conflict"], "objective": ["aggressive link prefetching"], "pending": ["get a field LCP measurement"]},
        ["Synthetic latency improves while field bandwidth worsens.", "Both measurements must be retained.", "The decision waits on a field latency measurement."],
        ["prefetch is enabled", "bandwidth cost is negligible", "conflict resolved"],
        ["get a field LCP measurement"],
    ),
    make_fixture(
        "q6-confirm-noisy-scan",
        "holdout",
        "long-tool-output",
        """
[USER] Find the one real finding in the dependency scan; the rest is noise.
[ASSISTANT TOOL_USE id=q6h17-a name=exec input="dep-scan --all"]
[TOOL_RESULT id=q6h17-a] {{LONG_OUTPUT}}
[TOOL_RESULT id=q6h17-a] CRITICAL package=libsheet version=2.3.1 cve=CVE-2026-3311 fix=2.3.4
[USER] Only the libsheet finding matters; do not echo the informational lines.
[USER] No dependency has been upgraded yet.
[USER] Next action: upgrade libsheet to 2.3.4 on a branch.
""",
        {"commands": ["package=libsheet", "version=2.3.1", "cve=CVE-2026-3311", "fix=2.3.4"], "constraints": ["do not echo the informational lines"], "temporal": ["No dependency has been upgraded yet"], "objective": ["dependency scan"], "pending": ["upgrade libsheet to 2.3.4"]},
        ["Exactly one critical dependency finding matters.", "The informational scan lines are noise.", "No upgrade has been applied."],
        ["libsheet upgraded", "all findings critical", "scan is clean"],
        ["upgrade libsheet to 2.3.4"],
        long_output=True,
    ),
    make_fixture(
        "q6-confirm-unit-mismatch",
        "holdout",
        "numeric-qualifiers",
        """
[USER] Compare the two ingest thresholds without normalising the units away.
[ASSISTANT] Stream A is capped at 250 MB per minute; stream B at 4 GB per hour.
[USER] Keep both units exactly as written; do not convert them to a common unit.
[USER] The caps are close but not equal, and neither has been changed.
[USER] Next action: confirm with Platform which cap governs the merged stream.
""",
        {"commands": ["250 MB per minute", "4 GB per hour"], "constraints": ["Keep both units exactly as written", "do not convert them"], "temporal": ["neither has been changed"], "objective": ["Stream A", "stream B"], "pending": ["confirm with Platform which cap governs"]},
        ["The two caps are expressed in different units.", "They are close but not equal.", "Neither cap has been modified."],
        ["caps are equal", "units were normalised", "cap was changed"],
        ["confirm with Platform which cap governs"],
    ),
    make_fixture(
        "q6-confirm-case-collision",
        "holdout",
        "exact-paths",
        """
[USER] Track this path collision exactly: Docs/Runbook.md is not docs/runbook.md.
[ASSISTANT] Both exist separately on this case-sensitive checkout.
[USER] Docs/Runbook.md is the published one; docs/runbook.md is a stale duplicate.
[USER] Do not delete either path until the duplicate is confirmed unused.
[USER] Next action: grep the site build for references to docs/runbook.md.
""",
        {"files": ["Docs/Runbook.md", "docs/runbook.md"], "decisions": ["published one", "stale duplicate"], "constraints": ["Do not delete either path"], "objective": ["case-sensitive checkout", "site build"], "pending": ["grep the site build for references"]},
        ["The two paths are distinct files.", "One is published and one is a stale duplicate.", "Neither may be deleted yet."],
        ["paths are the same file", "duplicate deleted", "duplicate is unused"],
        ["grep the site build for references"],
        seeded_files={"Docs/Runbook.md": "# Runbook (published)\n", "docs/runbook.md": "# Runbook (stale)\n"},
        expected_files={"Docs/Runbook.md": {"exact": "# Runbook (published)\n"}, "docs/runbook.md": {"exact": "# Runbook (stale)\n"}},
    ),
    make_fixture(
        "q6-confirm-cutover-order",
        "holdout",
        "ordered-next-actions",
        """
[USER] Preserve the cutover order; only the first executable step counts as next.
[ASSISTANT] Order: freeze writes, drain the queue, flip the DNS, then re-enable writes.
[USER] Draining cannot start until writes are frozen, and DNS cannot flip until the queue is empty.
[USER] Nothing has been executed; the maintenance window opens at 02:00.
[USER] Next action: freeze writes at the start of the window.
""",
        {"decisions": ["freeze writes", "drain the queue", "flip the DNS", "re-enable writes"], "temporal": ["Nothing has been executed", "02:00"], "objective": ["cutover order"], "pending": ["freeze writes at the start of the window"]},
        ["The four cutover steps have a strict order.", "Each step gates the next.", "No step has been executed."],
        ["queue drained", "DNS flipped", "cutover started"],
        ["freeze writes at the start of the window"],
    ),
    make_fixture(
        "q6-confirm-unsigned-candidate",
        "holdout",
        "negative-deployment-state",
        """
[USER] Check the release candidate without changing any deployment state.
[ASSISTANT TOOL_USE id=q6h21-a name=exec input="release-check --candidate rc-88"]
[TOOL_RESULT id=q6h21-a] exit=0 build=reproducible signed=false tag=absent promoted=false
[USER] A reproducible build is not a signed one; do not conflate them.
[USER] Nothing was promoted and no tag exists.
[USER] Next action: obtain the release signature for rc-88.
""",
        {"objective": ["rc-88"], "commands": ["build=reproducible", "signed=false", "tag=absent", "promoted=false"], "temporal": ["Nothing was promoted", "no tag exists"], "pending": ["obtain the release signature"]},
        ["The candidate builds reproducibly but is unsigned.", "No tag exists and nothing was promoted.", "Signing precedes promotion."],
        ["candidate signed", "release promoted", "tag exists"],
        ["obtain the release signature"],
    ),
]
ids = [item["id"] for item in fixtures]
assert len(ids) == len(set(ids))
assert sum(item["split"] == "dev" for item in fixtures) == 2
assert sum(item["split"] == "holdout" for item in fixtures) == 21
for item in fixtures:
    assert len(item["recent_messages"]) == 3
    if item["split"] == "holdout":
        anchor_count = sum(len(group) for group in item["exact_anchors"].values())
        assert anchor_count == 8, (item["id"], anchor_count)
        assert len(item["pending_actions"]) == 1

self_contradictions = validate_all(fixtures)
if self_contradictions:
    report = "\n".join(
        f"  {fixture_id}: {error}"
        for fixture_id, errors in sorted(self_contradictions.items())
        for error in errors
    )
    raise SystemExit(f"self-contradictory fixtures:\n{report}")

(ROOT / "fixtures.json").write_text(
    json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n"
)
