#!/usr/bin/env bash
# Run from the provisioned repository copy. Only public, unauthenticated reads.
set -euo pipefail

v1120_dir=.orchestra/tasks/V-1120/evidence
mkdir -p "$v1120_dir"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$v1120_dir/research-clock.stdout.txt"

set +e
git show main:app/backend_claude.py > "$v1120_dir/git-show-backend-main.stdout.txt" 2> "$v1120_dir/git-show-backend-main.stderr.txt"
v1120_git_status=$?
set -e
printf 'git_show_backend_main_exit=%s\n' "$v1120_git_status" > "$v1120_dir/availability-status.stdout.txt"
if test -d app; then
    printf 'app_directory=present\n' >> "$v1120_dir/availability-status.stdout.txt"
else
    printf 'app_directory=absent\n' >> "$v1120_dir/availability-status.stdout.txt"
fi

curl -fL --max-time 35 -sS 'https://t.me/data_secrets/10237?embed=1&mode=tme' |
    perl -nE 'while (m{https://www\.nodeseek\.com/post-[0-9]+-[0-9]+}g) {say $&} while (m{<time datetime="([^"]+)"}g) {say "post_datetime=$1"}' > "$v1120_dir/telegram-provenance.stdout.txt"

curl -fL --max-time 35 -sS 'https://aicodewith.ai/zh/blog/claude-account-ban-reasons-claude-code-api-key' |
    perl -nE 'while (m{https?[^\s"<>]+(?:status|news)/[0-9]+}g) {say $&}' > "$v1120_dir/x-source-links.stdout.txt"

curl -fL --max-time 35 -sS 'https://api.github.com/repos/anthropics/claude-code/commits?path=CHANGELOG.md&per_page=1' |
    jq '.[0] | {sha: .sha, date: .commit.committer.date, html_url: .html_url}' > "$v1120_dir/changelog-revision.stdout.json"

curl -fL --max-time 35 -sS 'https://raw.githubusercontent.com/anthropics/claude-code/0e1f4789406477380b267a01f3ddd50b0211e5b3/CHANGELOG.md' |
    awk '/^## / {ver=$0} /Fixed being unexpectedly logged out when an older Claude Code build|Fixed a revoked claude.ai login|Fixed a rare login loop where a concurrent credential write|Fixed parallel sessions all dead-ending at 401|Fixed OAuth refresh race after wake-from-sleep|Fixed a rare race where a concurrent credential write could clear|access token expires mid-session/ {print ver "\tline=" NR "\tauth_fix_match=true"}' > "$v1120_dir/changelog-pinned-auth.stdout.txt"

for v1120_issue in 24317 76561 80380 61923; do
    curl -fL --max-time 35 -sS "https://api.github.com/repos/anthropics/claude-code/issues/$v1120_issue" |
        jq '{html_url, title, author: .user.login, created_at, updated_at, state, state_reason}' > "$v1120_dir/issue-$v1120_issue-metadata.stdout.json"
done

curl -fL --max-time 35 -sS 'https://www.rfc-editor.org/rfc/rfc9700.txt' |
    awk '/^4\.14\.2\.  Recommendations/ {p=1} /^4\.15\. / {p=0} p && /Refresh token rotation|revoke refresh tokens automatically|Refresh tokens SHOULD expire/ {print NR ":" $0}' > "$v1120_dir/rfc9700-refresh.stdout.txt"

curl -fL --max-time 35 -sS 'https://www.rfc-editor.org/rfc/rfc6749.txt' |
    awk '/invalid_grant/ {print NR ":" $0}' > "$v1120_dir/rfc6749-invalid-grant.stdout.txt"

rg -n 'claude-agent-sdk' pyproject.toml > "$v1120_dir/orchestra-sdk-pin.stdout.txt"
rg -n 'V-707|V-800|V-919|SDK errors silent|Renew the MultiCode Hub OAuth|Микрокомпакт строить не нужно' CHANGELOG.md > "$v1120_dir/orchestra-auth-context.stdout.txt"

printf 'Evidence collection completed. git show exit: %s; see evidence files.\n' "$v1120_git_status"
