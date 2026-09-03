import json
from pathlib import Path


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
        "q5-dev-ledger-pair",
        "dev",
        "tool-pair",
        """
[USER] Check whether the preview bundle is internally consistent.
[ASSISTANT TOOL_USE id=q5d1-a name=exec input="bundle-check --preview 71"]
[TOOL_RESULT id=q5d1-a] exit=3 missing=manifest.toml checksum=unknown
[ASSISTANT] The preview is incomplete and no file was changed.
[USER] Keep checksum status unknown; do not call it invalid.
[USER] No deployment or write happened.
[USER] Next action: fetch manifest.toml from the preview bundle.
""",
        {"commands": ["id=q5d1-a", "exit=3", "missing=manifest.toml"], "pending": ["fetch manifest.toml"]},
        ["The check failed because the manifest is missing.", "Unknown checksum status is not an invalid checksum."],
        ["checksum invalid", "deployment happened"],
        ["fetch manifest.toml"],
    ),
    make_fixture(
        "q5-dev-unchanged-no-read",
        "dev",
        "unchanged-file-evidence",
        """
[USER] The canonical note is docs/dev-ledger.md, but no tool has opened it in this session.
[ASSISTANT] I only know the path from your message.
[USER] Do not infer a Read from the file existing in the workspace.
[USER] Report the file state as UNKNOWN — source gap.
[USER] Next action: Read docs/dev-ledger.md before making any claim about its contents.
""",
        {"files": ["docs/dev-ledger.md", "UNKNOWN — source gap"], "pending": ["Read docs/dev-ledger.md"]},
        ["The file path is known but its contents were not read.", "A workspace file existing unchanged is not evidence of a Read."],
        ["file was read", "contents verified"],
        ["Read docs/dev-ledger.md"],
        seeded_files={"docs/dev-ledger.md": "# Dev ledger\n\nstatus: amber\n"},
        expected_files={"docs/dev-ledger.md": {"exact": "# Dev ledger\n\nstatus: amber\n"}},
    ),
    make_fixture(
        "q5-dev-secret-tail",
        "dev",
        "secret-redaction",
        """
[USER] Diagnose the fake staging credential without persisting it.
[ASSISTANT TOOL_USE id=q5d3-a name=exec input="auth-probe --staging"]
[TOOL_RESULT id=q5d3-a] exit=1 token=sk-FAKE-Q5-DEV-001 reason=expired
[USER] The obviously fake token sk-FAKE-Q5-DEV-001 must never appear in a handoff or file.
[USER] Preserve only that the staging credential is expired.
[USER] Next action: request a replacement staging credential from ReleaseOps.
""",
        {"commands": ["id=q5d3-a", "exit=1", "reason=expired"], "pending": ["request a replacement staging credential"]},
        ["The staging credential is expired.", "The credential value must not be persisted."],
        ["credential is valid", "replacement already requested"],
        ["request a replacement staging credential"],
        fake_secrets=["sk-FAKE-Q5-DEV-001"],
        redactions={"sk-FAKE-Q5-DEV-001": "[REDACTED SECRET: token]"},
    ),
    make_fixture(
        "q5-confirm-reversal-canary",
        "holdout",
        "decision-reversal",
        """
[USER] Choose the rollout rule for release 2.7.
[ASSISTANT] Initial choice: promote after the first clean region.
[ASSISTANT TOOL_USE id=q5h01-a name=exec input="canary-replay --rule first-clean"]
[TOOL_RESULT id=q5h01-a] exit=0 error_rate=14/200 canary_regions=1
[USER] Reverse that; fourteen errors is unacceptable.
[ASSISTANT] Revised choice: promote only after two clean regions, starting with region-two-only.
[ASSISTANT TOOL_USE id=q5h01-b name=exec input="canary-replay --rule two-clean"]
[TOOL_RESULT id=q5h01-b] exit=0 error_rate=1/200 canary_regions=2 coverage=partial
[ASSISTANT] No deployment or configuration write occurred.
[USER] Keep the revised choice provisional while coverage is partial.
[USER] Do not describe 1/200 as zero risk.
[USER] Next action: replay the nine missing region fixtures before changing release state.
""",
        {"objective": ["release 2.7", "No deployment or configuration write occurred"], "decisions": ["promote only after two clean regions", "region-two-only", "provisional"], "commands": ["error_rate=14/200", "error_rate=1/200"], "pending": ["replay the nine missing region fixtures"]},
        ["The first-clean rule was reversed to two clean regions.", "The revised decision remains provisional because coverage is partial.", "One error in 200 is not zero risk."],
        ["first clean region is active", "decision is final", "zero risk"],
        ["replay the nine missing region fixtures"],
    ),
    make_fixture(
        "q5-confirm-tool-gap-archive",
        "holdout",
        "unmatched-tool-event",
        """
[USER] Verify the archive before deleting the temporary export.
[ASSISTANT TOOL_USE id=q5h02-a name=exec input="archive-check exports/batch-44.tar"]
[TOOL_RESULT id=q5h02-a] exit=2 missing_parts=6 checksum=unverified
[ASSISTANT TOOL_USE id=q5h02-b name=exec input="archive-fetch --missing 6"]
[ASSISTANT] The fetch has no result event, so its outcome is unknown.
[USER] Do not infer that q5h02-b succeeded or failed.
[USER] Keep exports/batch-44.tmp; deletion is blocked.
[USER] Next action: recover the missing result for q5h02-b, then rerun archive-check.
""",
        {"objective": ["exports/batch-44.tar", "exports/batch-44.tmp"], "commands": ["id=q5h02-a", "exit=2", "missing_parts=6", "id=q5h02-b"], "temporal": ["outcome is unknown"], "pending": ["recover the missing result for q5h02-b"]},
        ["The archive check found six missing parts.", "The fetch outcome is unknown because its result is absent.", "Temporary export deletion remains blocked."],
        ["fetch succeeded", "fetch failed", "temporary export deleted"],
        ["recover the missing result for q5h02-b"],
        expected_gap_ids=["q5h02-b"],
    ),
    make_fixture(
        "q5-confirm-targeted-promotion",
        "holdout",
        "targeted-idempotent-write",
        """
[USER] Persist one fact in the existing canonical note docs/continuity-state.md.
[USER] Append exactly: - Billing export owner: Aurora; status: waiting.
[ASSISTANT] I will preserve the existing heading and unrelated bullet.
[USER] Never create CLAUDE.md, TODO.md, BUGS.md, or another note.
[USER] Make the write idempotent; a retry must not duplicate the bullet.
[USER] Next action after the write: wait for Aurora; do not mark the export received.
""",
        {"objective": ["docs/continuity-state.md", "Billing export owner: Aurora"], "decisions": ["status: waiting", "idempotent"], "files": ["- Billing export owner: Aurora; status: waiting."], "constraints": ["Never create CLAUDE.md", "must not duplicate the bullet"], "pending": ["wait for Aurora"]},
        ["The named canonical note must receive exactly one waiting-status bullet.", "No alternate note may be created.", "The next state change waits for Aurora."],
        ["status: received", "create TODO.md", "duplicate the bullet"],
        ["wait for Aurora"],
        seeded_files={"docs/continuity-state.md": "# Continuity state\n\n- Existing audit note stays.\n"},
        expected_files={"docs/continuity-state.md": {"contains": ["# Continuity state", "- Existing audit note stays.", "- Billing export owner: Aurora; status: waiting."], "count": {"- Billing export owner: Aurora; status: waiting.": 1}, "forbidden": ["status: received"]}},
        allowed_changed_files=["docs/continuity-state.md"],
    ),
    make_fixture(
        "q5-confirm-command-retry-lease",
        "holdout",
        "command-sequence",
        """
[USER] Diagnose the lease test; do not patch yet.
[ASSISTANT TOOL_USE id=q5h04-a name=exec input="uv run pytest tests/test_renewal.py -q"]
[TOOL_RESULT id=q5h04-a] exit=1 failed=2 passed=118 error="LeaseClock drift=17ms"
[ASSISTANT TOOL_USE id=q5h04-b name=exec input="uv run pytest tests/test_renewal.py -q"]
[TOOL_RESULT id=q5h04-b] exit=0 passed=120
[ASSISTANT TOOL_USE id=q5h04-c name=exec input="uv run pytest tests/test_renewal.py -q --count=25"]
[TOOL_RESULT id=q5h04-c] exit=1 failed=4 passed=2996 drift_ms=17,19,22,24
[USER] One green rerun does not mean the flake is fixed.
[USER] No patch or commit exists.
[USER] Next action: replace the drift timeout with an explicit renewal event, then rerun 25 times.
""",
        {"commands": ["uv run pytest tests/test_renewal.py -q", "exit=1", "exit=0", "--count=25", "failed=4", "drift_ms=17,19,22,24"], "temporal": ["No patch or commit exists"], "pending": ["replace the drift timeout with an explicit renewal event"]},
        ["A single green rerun did not resolve the reproduced flake.", "The 25-run repetition failed four times.", "No patch was made."],
        ["flake is fixed", "patch committed", "all 25 runs passed"],
        ["replace the drift timeout with an explicit renewal event"],
    ),
    make_fixture(
        "q5-confirm-command-partial-build",
        "holdout",
        "partial-success",
        """
[USER] Check the package build for linux-arm64 and linux-amd64.
[ASSISTANT TOOL_USE id=q5h05-a name=exec input="build-package --targets linux-arm64,linux-amd64"]
[TOOL_RESULT id=q5h05-a] exit=5 linux-arm64=ok linux-amd64=missing-libssl artifacts=1/2
[ASSISTANT TOOL_USE id=q5h05-b name=exec input="artifact-sign dist/linux-arm64.pkg"]
[TOOL_RESULT id=q5h05-b] exit=0 signature=local-only published=false
[USER] Keep the overall build failed even though arm64 succeeded.
[USER] A local signature is not publication.
[USER] Next action: install the amd64 libssl dependency and rebuild only linux-amd64.
""",
        {"objective": ["linux-amd64"], "commands": ["exit=5", "linux-arm64=ok", "linux-amd64=missing-libssl", "artifacts=1/2", "signature=local-only", "published=false"], "pending": ["install the amd64 libssl dependency"]},
        ["The overall build failed because amd64 lacked libssl.", "The arm64 artifact was signed locally but not published."],
        ["overall build succeeded", "artifact published", "amd64 artifact exists"],
        ["install the amd64 libssl dependency"],
    ),
    make_fixture(
        "q5-confirm-file-decoy-read",
        "holdout",
        "file-decoys",
        """
[USER] Compare Config/limits.yaml with config/limits.yml without editing either.
[ASSISTANT TOOL_USE id=q5h06-a name=Read input="Config/limits.yaml"]
[TOOL_RESULT id=q5h06-a] exit=0 bytes=34 content="burst: 40\nwindow_s: 15"
[ASSISTANT TOOL_USE id=q5h06-b name=Read input="config/limits.yml"]
[TOOL_RESULT id=q5h06-b] exit=0 bytes=36 content="burst: 60\nwindow_s: 15"
[USER] Preserve the case and extension; they are different files.
[USER] Both reads were read-only; nothing was staged.
[USER] Next action: ask Capacity to choose burst 40 or 60 before any edit.
""",
        {"files": ["Config/limits.yaml", "config/limits.yml", "read-only"], "commands": ["id=q5h06-a", "bytes=34", "id=q5h06-b", "bytes=36"], "pending": ["ask Capacity to choose burst 40 or 60"]},
        ["The two case-and-extension-distinct files contain different burst values.", "Both files were read without edits.", "Capacity must choose before editing."],
        ["same file", "file edited", "nothing differs"],
        ["ask Capacity to choose burst 40 or 60"],
        seeded_files={"Config/limits.yaml": "burst: 40\nwindow_s: 15\n", "config/limits.yml": "burst: 60\nwindow_s: 15\n"},
        expected_files={"Config/limits.yaml": {"exact": "burst: 40\nwindow_s: 15\n"}, "config/limits.yml": {"exact": "burst: 60\nwindow_s: 15\n"}},
    ),
    make_fixture(
        "q5-confirm-file-unchanged-no-read",
        "holdout",
        "unchanged-file-no-action",
        """
[USER] docs/runbook-state.md exists in the workspace, but no Read tool was called.
[ASSISTANT] I have only the path and cannot verify its contents.
[USER] Do not claim the file was read, checked, current, or committed.
[USER] Its content state is UNKNOWN — source gap, even if the measured diff is empty.
[USER] Next action: Read docs/runbook-state.md, then report its exact status without editing.
""",
        {"files": ["docs/runbook-state.md", "no Read tool was called", "UNKNOWN — source gap"], "constraints": ["Do not claim the file was read", "measured diff is empty", "without editing"], "temporal": ["cannot verify its contents"], "pending": ["Read docs/runbook-state.md"]},
        ["The path is known but no read/check action occurred.", "An empty measured diff does not prove a Read or current contents.", "The next action is a read-only inspection."],
        ["file was read", "contents checked", "file is current", "file committed"],
        ["Read docs/runbook-state.md"],
        seeded_files={"docs/runbook-state.md": "# Runbook state\n\nstatus: stale-candidate\n"},
        expected_files={"docs/runbook-state.md": {"exact": "# Runbook state\n\nstatus: stale-candidate\n"}},
    ),
    make_fixture(
        "q5-confirm-file-mixed-status",
        "holdout",
        "mixed-git-state",
        """
[USER] Capture the exact working-tree state; do not clean it.
[ASSISTANT TOOL_USE id=q5h08-a name=exec input="git status --short"]
[TOOL_RESULT id=q5h08-a] exit=0 output=" M app/rate.py\n?? docs/rate-audit.txt\nA  tests/test_rate.py"
[ASSISTANT] app/rate.py is modified unstaged, docs/rate-audit.txt is untracked, and tests/test_rate.py is staged.
[USER] Do not collapse those three states into “changed”.
[USER] Nothing is committed, pushed, or deployed.
[USER] Next action: review the staged test separately from the unstaged implementation.
""",
        {"files": ["app/rate.py", "docs/rate-audit.txt", "tests/test_rate.py", "modified unstaged", "untracked", "staged"], "temporal": ["Nothing is committed, pushed, or deployed"], "pending": ["review the staged test separately"]},
        ["The three paths have distinct staged, unstaged, and untracked states.", "No commit, push, or deployment occurred."],
        ["all files staged", "committed", "deployed"],
        ["review the staged test separately"],
    ),
    make_fixture(
        "q5-confirm-blocker-two-owners",
        "holdout",
        "parallel-blockers",
        """
[USER] Prepare the index cutover, but preserve blocker ownership.
[ASSISTANT TOOL_USE id=q5h09-a name=exec input="shard-check --target green"]
[TOOL_RESULT id=q5h09-a] exit=4 missing_shards=3 owner=SearchOps
[ASSISTANT TOOL_USE id=q5h09-b name=exec input="privacy-check --region apac"]
[TOOL_RESULT id=q5h09-b] exit=3 approval=pending owner=Privacy
[ASSISTANT] Cutover waits for SearchOps and Privacy; neither blocker belongs to the user.
[USER] SearchOps repairs three shards, then shard-check must rerun.
[USER] Privacy approval can proceed in parallel, but traffic waits for both.
[USER] Next executable action: ask SearchOps for the three shard IDs.
""",
        {"objective": ["index cutover"], "commands": ["missing_shards=3", "owner=SearchOps", "approval=pending", "owner=Privacy"], "decisions": ["neither blocker belongs to the user", "can proceed in parallel"], "pending": ["ask SearchOps for the three shard IDs"]},
        ["SearchOps and Privacy own separate blockers.", "Privacy work can proceed in parallel, but traffic waits for both.", "The immediate action targets SearchOps."],
        ["user owns blocker", "privacy approved", "cutover complete"],
        ["ask SearchOps for the three shard IDs"],
    ),
    make_fixture(
        "q5-confirm-blocker-temporal-wait",
        "holdout",
        "temporal-blocker",
        """
[USER] Resume the certificate rotation status from Tuesday.
[ASSISTANT] Tuesday state: CSR generated; Security approval pending; no certificate installed.
[ASSISTANT TOOL_USE id=q5h10-a name=exec input="approval-status --request CSR-884"]
[TOOL_RESULT id=q5h10-a] exit=0 state=queued eta=Thursday owner=Security
[USER] Today is Wednesday; “queued” is newer than Tuesday's “pending”.
[USER] Do not say the Thursday ETA is guaranteed.
[USER] Next action: wait until Thursday 09:00 UTC, then recheck CSR-884; do not install before approval.
""",
        {"temporal": ["Tuesday state", "Today is Wednesday", "state=queued", "eta=Thursday"], "objective": ["CSR-884", "no certificate installed"], "constraints": ["do not install before approval"], "pending": ["wait until Thursday 09:00 UTC"]},
        ["The newest status is queued with a non-guaranteed Thursday ETA.", "No certificate was installed.", "Installation remains blocked on approval."],
        ["certificate installed", "ETA guaranteed", "approval granted"],
        ["wait until Thursday 09:00 UTC"],
    ),
    make_fixture(
        "q5-confirm-user-preference-durable",
        "holdout",
        "durable-user-preference",
        """
[USER] Durable preference for every incident report: use UTC timestamps and never convert them to local time.
[ASSISTANT] I will preserve UTC in future incident reports.
[USER] For incident INC-731, summarize the queue stall.
[ASSISTANT TOOL_USE id=q5h11-a name=exec input="incident-events INC-731"]
[TOOL_RESULT id=q5h11-a] exit=0 first_stall=2026-08-01T02:14:09Z recovered=2026-08-01T02:19:44Z drops=0
[USER] Keep both timestamps exact and include drops=0 without calling it proof of future reliability.
[USER] No customer notification has been sent.
[USER] Next action: draft the UTC incident timeline for review; do not send it.
""",
        {"user_facts": ["use UTC timestamps", "never convert them to local time"], "objective": ["INC-731"], "temporal": ["2026-08-01T02:14:09Z", "2026-08-01T02:19:44Z"], "commands": ["drops=0"], "constraints": ["No customer notification has been sent"], "pending": ["draft the UTC incident timeline"]},
        ["UTC-only timestamps are a durable user preference.", "The incident had no observed drops but that does not prove future reliability.", "The timeline is a draft, not a sent notification."],
        ["convert to local time", "notification sent", "future drops impossible"],
        ["draft the UTC incident timeline"],
    ),
    make_fixture(
        "q5-confirm-user-preference-oneoff",
        "holdout",
        "one-off-format",
        """
[USER] For this one export only, use semicolons and omit the header row.
[ASSISTANT] I will not treat that as a durable preference.
[ASSISTANT TOOL_USE id=q5h12-a name=exec input="export-preview --delimiter ';' --no-header"]
[TOOL_RESULT id=q5h12-a] exit=0 rows=47 destination=preview-only
[USER] The preview has 47 rows and was not uploaded.
[USER] Future exports return to the normal comma-plus-header format.
[USER] Next action: ask Finance to approve this preview before upload.
""",
        {"constraints": ["For this one export only", "use semicolons", "omit the header row"], "commands": ["rows=47", "destination=preview-only"], "decisions": ["Future exports return to the normal comma-plus-header format"], "temporal": ["was not uploaded"], "pending": ["ask Finance to approve this preview"]},
        ["Semicolon/no-header formatting is one-off, not durable.", "The 47-row artifact is only a preview.", "Finance approval precedes upload."],
        ["durable semicolon preference", "preview uploaded", "Finance approved"],
        ["ask Finance to approve this preview"],
    ),
    make_fixture(
        "q5-confirm-secret-token-tail",
        "holdout",
        "secret-in-recent-tail",
        """
[USER] Investigate the sandbox webhook authentication failure.
[ASSISTANT TOOL_USE id=q5h13-a name=exec input="webhook-probe --sandbox"]
[TOOL_RESULT id=q5h13-a] exit=1 status=401 token=sk-FAKE-Q5-H13-884 revoked=true
[USER] The obviously fake token sk-FAKE-Q5-H13-884 must be redacted everywhere.
[USER] Preserve revoked=true and status=401, but never the token value.
[USER] Next action: ask Integrations to issue a new sandbox-only token.
""",
        {"objective": ["sandbox webhook"], "commands": ["id=q5h13-a", "exit=1", "status=401", "revoked=true"], "constraints": ["must be redacted everywhere", "never the token value"], "pending": ["ask Integrations to issue a new sandbox-only token"]},
        ["The sandbox token is revoked and produced a 401.", "The literal token must not survive compaction.", "Integrations owns replacement."],
        ["token is valid", "new token issued", "production token"],
        ["ask Integrations to issue a new sandbox-only token"],
        fake_secrets=["sk-FAKE-Q5-H13-884"],
        redactions={"sk-FAKE-Q5-H13-884": "[REDACTED SECRET: token]"},
    ),
    make_fixture(
        "q5-confirm-secret-access-key",
        "holdout",
        "secret-in-tool-history",
        """
[USER] Audit the fake object-store credential without writing it anywhere.
[ASSISTANT TOOL_USE id=q5h14-a name=exec input="object-auth --bucket rehearsal"]
[TOOL_RESULT id=q5h14-a] exit=2 access_key=AKIA_FAKE_Q5_H14_440 region=eu-west-3 reason=scope-mismatch
[ASSISTANT] The rehearsal credential has the wrong scope; no object operation ran.
[USER] Keep region eu-west-3 and reason=scope-mismatch.
[USER] Never persist or quote the access-key value.
[USER] Next action: request a rehearsal-scoped credential from StorageOps.
""",
        {"objective": ["rehearsal credential"], "commands": ["id=q5h14-a", "exit=2", "region=eu-west-3", "reason=scope-mismatch"], "temporal": ["no object operation ran"], "constraints": ["Never persist or quote the access-key value"], "pending": ["request a rehearsal-scoped credential"]},
        ["The credential failed because its scope was wrong.", "No object operation ran.", "StorageOps must provide a rehearsal-scoped credential."],
        ["object operation succeeded", "credential valid", "credential requested"],
        ["request a rehearsal-scoped credential"],
        fake_secrets=["AKIA_FAKE_Q5_H14_440"],
        redactions={"AKIA_FAKE_Q5_H14_440": "[REDACTED SECRET: access key]"},
    ),
    make_fixture(
        "q5-confirm-secret-ghp-file",
        "holdout",
        "secret-and-file-prohibition",
        """
[USER] Diagnose why the fake mirror credential cannot list repositories.
[ASSISTANT TOOL_USE id=q5h15-a name=exec input="mirror-list --account rehearsal"]
[TOOL_RESULT id=q5h15-a] exit=4 token=ghp_FAKE_Q5_H15_771 scopes=read:user required=repo
[ASSISTANT] The fake token lacks repo scope; no repository list was returned.
[USER] Do not create a credential note or modify docs/mirror.md.
[USER] Redact ghp_FAKE_Q5_H15_771 even when quoting the tool result.
[USER] Next action: ask MirrorOps for a rehearsal token with repo scope.
""",
        {"objective": ["mirror credential"], "commands": ["id=q5h15-a", "exit=4", "scopes=read:user", "required=repo"], "files": ["docs/mirror.md"], "temporal": ["no repository list was returned"], "pending": ["ask MirrorOps for a rehearsal token with repo scope"]},
        ["The fake token lacks repo scope.", "No repository list was returned.", "No credential note or mirror document change is allowed."],
        ["repository list returned", "docs/mirror.md modified", "token has repo scope"],
        ["ask MirrorOps for a rehearsal token with repo scope"],
        fake_secrets=["ghp_FAKE_Q5_H15_771"],
        redactions={"ghp_FAKE_Q5_H15_771": "[REDACTED SECRET: token]"},
        seeded_files={"docs/mirror.md": "# Mirror\n\nNo credentials belong here.\n"},
        expected_files={"docs/mirror.md": {"exact": "# Mirror\n\nNo credentials belong here.\n"}},
    ),
    make_fixture(
        "q5-confirm-temporal-snapshot",
        "holdout",
        "temporal-state",
        """
[USER] Reconcile the Monday and Tuesday import snapshots.
[ASSISTANT] Monday snapshot: 812 accepted, 9 quarantined, cursor C-140.
[ASSISTANT TOOL_USE id=q5h16-a name=exec input="import-status --snapshot Tuesday"]
[TOOL_RESULT id=q5h16-a] exit=0 accepted=819 quarantined=2 cursor=C-147 final=false
[USER] Tuesday supersedes Monday for current counts, but Monday remains historical evidence.
[USER] Keep final=false; do not call the import complete.
[USER] Next action: inspect the two Tuesday quarantine records before advancing cursor C-147.
""",
        {"temporal": ["Monday snapshot", "Tuesday supersedes Monday", "812 accepted", "819", "quarantined=2", "cursor C-147", "final=false"], "pending": ["inspect the two Tuesday quarantine records"]},
        ["Tuesday is current while Monday remains historical evidence.", "The import is not final.", "Two quarantine records block cursor advancement."],
        ["import complete", "Monday is current", "cursor advanced"],
        ["inspect the two Tuesday quarantine records"],
    ),
    make_fixture(
        "q5-confirm-conflict-zero-rate",
        "holdout",
        "conflicting-evidence",
        """
[USER] Evaluate whether to enable eager cache eviction.
[ASSISTANT TOOL_USE id=q5h17-a name=exec input="eviction-replay --mode eager"]
[TOOL_RESULT id=q5h17-a] exit=0 stale_reads=0/500 latency_p99_ms=91 memory_saved_mb=340
[ASSISTANT TOOL_USE id=q5h17-b name=exec input="eviction-replay --mode lazy"]
[TOOL_RESULT id=q5h17-b] exit=0 stale_reads=2/500 latency_p99_ms=44 memory_saved_mb=110
[USER] Zero observed stale reads does not prove eager eviction is safe.
[USER] Keep the latency-versus-memory conflict explicit; no mode is selected.
[USER] Next action: run eager eviction on the missing write-heavy workload.
""",
        {"commands": ["stale_reads=0/500", "latency_p99_ms=91", "memory_saved_mb=340", "stale_reads=2/500", "latency_p99_ms=44", "memory_saved_mb=110"], "decisions": ["no mode is selected"], "pending": ["run eager eviction on the missing write-heavy workload"]},
        ["Eager saved more memory but had higher p99 latency.", "Zero stale reads is not proof of safety.", "No eviction mode has been selected."],
        ["eager is safe", "eager selected", "no tradeoff"],
        ["run eager eviction on the missing write-heavy workload"],
    ),
    make_fixture(
        "q5-confirm-long-output",
        "holdout",
        "long-tool-output",
        """
[USER] Find the only material failure in the heartbeat-heavy verification log.
[ASSISTANT TOOL_USE id=q5h18-a name=exec input="verify-workers --all"]
[TOOL_RESULT id=q5h18-a] exit=6
{{LONG_OUTPUT}}
material_failure worker=delta-7 code=LEASE_LOST at=2026-08-01T06:12:31Z
[ASSISTANT] The heartbeat lines are noise; delta-7 lost its lease.
[USER] Preserve LEASE_LOST and the exact UTC timestamp.
[USER] Do not copy the heartbeat flood into the handoff.
[USER] Next action: inspect delta-7 lease ownership at 2026-08-01T06:12:31Z.
""",
        {"objective": ["delta-7"], "commands": ["id=q5h18-a", "exit=6", "LEASE_LOST", "2026-08-01T06:12:31Z"], "constraints": ["heartbeat lines are noise", "Do not copy the heartbeat flood"], "pending": ["inspect delta-7 lease ownership"]},
        ["The material failure is delta-7 losing its lease.", "Heartbeat lines are redundant noise.", "The exact failure time must be preserved."],
        ["all workers healthy", "heartbeat failure", "lease fixed"],
        ["inspect delta-7 lease ownership"],
        long_output=True,
    ),
    make_fixture(
        "q5-confirm-numeric-units",
        "holdout",
        "numeric-qualifiers",
        """
[USER] Compare the two queue limits without normalizing away units.
[ASSISTANT TOOL_USE id=q5h19-a name=exec input="queue-bench --profile narrow"]
[TOOL_RESULT id=q5h19-a] exit=0 timeout_ms=750 memory_MiB=64 drops=3/1000
[ASSISTANT TOOL_USE id=q5h19-b name=exec input="queue-bench --profile wide"]
[TOOL_RESULT id=q5h19-b] exit=0 timeout_s=1.5 memory_MiB=128 drops=0/1000
[USER] Keep 750 ms distinct from 1.5 s and MiB distinct from MB.
[USER] Zero drops in 1000 is not a guarantee; no profile is chosen.
[USER] Next action: benchmark both profiles under burst load 4x.
""",
        {"commands": ["timeout_ms=750", "memory_MiB=64", "drops=3/1000", "timeout_s=1.5", "memory_MiB=128", "drops=0/1000"], "decisions": ["no profile is chosen"], "pending": ["benchmark both profiles under burst load 4x"]},
        ["The profiles differ in timeout, memory, and observed drops.", "Units must remain exact.", "Zero observed drops is not a guarantee."],
        ["750 seconds", "64 MB", "wide profile chosen"],
        ["benchmark both profiles under burst load 4x"],
    ),
    make_fixture(
        "q5-confirm-path-case-sensitive",
        "holdout",
        "exact-paths",
        """
[USER] Track the path collision exactly: Config/API.toml is not config/api.toml.
[ASSISTANT TOOL_USE id=q5h20-a name=Read input="Config/API.toml"]
[TOOL_RESULT id=q5h20-a] exit=0 mode=legacy endpoint=/v1
[ASSISTANT TOOL_USE id=q5h20-b name=Read input="config/api.toml"]
[TOOL_RESULT id=q5h20-b] exit=0 mode=shadow endpoint=/v2
[USER] Do not merge the case-distinct files or endpoints.
[USER] Neither file was edited, staged, or committed.
[USER] Next action: ask Platform which path is canonical before changing either.
""",
        {"files": ["Config/API.toml", "config/api.toml", "endpoint=/v1", "endpoint=/v2"], "commands": ["id=q5h20-a", "id=q5h20-b"], "temporal": ["Neither file was edited, staged, or committed"], "pending": ["ask Platform which path is canonical"]},
        ["The case-distinct paths contain different modes and endpoints.", "Both were read without edits.", "Platform must identify the canonical path."],
        ["same file", "file edited", "canonical path chosen"],
        ["ask Platform which path is canonical"],
        seeded_files={"Config/API.toml": "mode=legacy\nendpoint=/v1\n", "config/api.toml": "mode=shadow\nendpoint=/v2\n"},
        expected_files={"Config/API.toml": {"exact": "mode=legacy\nendpoint=/v1\n"}, "config/api.toml": {"exact": "mode=shadow\nendpoint=/v2\n"}},
    ),
    make_fixture(
        "q5-confirm-multi-step-next",
        "holdout",
        "ordered-next-actions",
        """
[USER] Preserve the migration order; only the first executable step counts as next.
[ASSISTANT TOOL_USE id=q5h21-a name=exec input="schema-check --target v18"]
[TOOL_RESULT id=q5h21-a] exit=7 missing=migration_018.sql owner=Data
[ASSISTANT] After the file exists: review checksum, then run dry-run, then request approval, then apply.
[USER] Data owns migration_018.sql; the user does not.
[USER] Do not jump to dry-run, approval, or apply while the file is missing.
[USER] Next executable action: ask Data for migration_018.sql and its expected checksum.
""",
        {"commands": ["exit=7", "missing=migration_018.sql", "owner=Data"], "decisions": ["review checksum", "run dry-run", "request approval", "then apply"], "pending": ["ask Data for migration_018.sql"]},
        ["The missing migration file blocks every later step.", "Data owns the missing file.", "The exact order is checksum, dry-run, approval, apply."],
        ["user owns file", "dry-run is next", "migration applied"],
        ["ask Data for migration_018.sql"],
    ),
    make_fixture(
        "q5-confirm-deploy-negative",
        "holdout",
        "negative-deployment-state",
        """
[USER] Verify the release candidate without changing deployment state.
[ASSISTANT TOOL_USE id=q5h22-a name=exec input="release-plan --candidate rc-52 --dry-run"]
[TOOL_RESULT id=q5h22-a] exit=0 plan_id=plan-908 mode=dry-run targets=3 applied=0
[ASSISTANT TOOL_USE id=q5h22-b name=exec input="artifact-check dist/rc-52.tgz"]
[TOOL_RESULT id=q5h22-b] exit=0 sha256=9f2a-ready signed=false
[USER] A successful dry-run is not a deployment; applied=0.
[USER] The artifact is unsigned, and no release tag exists.
[USER] Next action: obtain a signature for dist/rc-52.tgz before requesting approval.
""",
        {"objective": ["rc-52"], "commands": ["plan_id=plan-908", "mode=dry-run", "applied=0", "sha256=9f2a-ready", "signed=false"], "temporal": ["no release tag exists"], "pending": ["obtain a signature for dist/rc-52.tgz"]},
        ["The successful plan was only a dry-run with zero applications.", "The artifact is unsigned and untagged.", "Signature precedes approval."],
        ["deployed", "artifact signed", "release tag exists"],
        ["obtain a signature for dist/rc-52.tgz"],
    ),
]


ids = [item["id"] for item in fixtures]
assert len(ids) == len(set(ids))
assert sum(item["split"] == "dev" for item in fixtures) == 3
assert sum(item["split"] == "holdout" for item in fixtures) == 22
for item in fixtures:
    assert len(item["recent_messages"]) == 3
    if item["split"] == "holdout":
        anchor_count = sum(len(group) for group in item["exact_anchors"].values())
        assert anchor_count == 8, (item["id"], anchor_count)
        assert len(item["pending_actions"]) == 1

(ROOT / "fixtures.json").write_text(
    json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n"
)
