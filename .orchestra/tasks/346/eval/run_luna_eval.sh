#!/usr/bin/env bash
set -u

if [[ $# -ne 2 ]]; then
  echo "usage: $0 RUN_NAME ARM" >&2
  exit 2
fi

run_name=$1
arm=$2
if [[ ! $run_name =~ ^[a-z0-9-]+$ ]] || [[ ! $arm =~ ^[abc]$ ]]; then
  echo "invalid run/arm" >&2
  exit 2
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../../.." && pwd)
raw_dir="$repo_root/docs/tasks/346/evidence/raw"
eval_dir="$repo_root/docs/tasks/346/eval"
scratch_root=$(sed -n '1p' "$raw_dir/scratch-path.txt")
eval_repo="$scratch_root/luna-$run_name"
project_yml="$raw_dir/serena-generated-project-yml.txt"
prompt="$eval_dir/evaluator-prompt.md"
serena_exe="$scratch_root/venv/bin/serena"

"$eval_dir/prepare_eval_repo.sh" "$eval_repo" "luna-$run_name" "$project_yml" \
  > "$raw_dir/luna-$run_name-setup.txt" 2>&1

common=(
  exec
  --json
  --ephemeral
  --ignore-user-config
  --color never
  -C "$eval_repo"
  -m gpt-5.6-luna
  -c 'model_reasoning_effort="medium"'
  -c 'features.tool_search=true'
  -c 'features.tool_search_always_defer_mcp_tools=false'
  -s danger-full-access
  -
)

extra=()
if [[ $arm == b ]]; then
  unit="task346-eval-${run_name}-serena"
  serena_home="$scratch_root/serena-home-$run_name"
  uv_cache="$scratch_root/uv-cache-$run_name"
  args=$(jq -cn \
    --arg unit "$unit" --arg cwd "$eval_repo" --arg exe "$serena_exe" \
    --arg shome "$serena_home" --arg uvcache "$uv_cache" \
    '["--user","--pipe","--wait","--collect","--quiet",("--unit="+$unit),
      "-p","MemoryMax=1G","-p","CPUQuota=200%","-p","TasksMax=128",
      "-p",("WorkingDirectory="+$cwd),"--","env",("SERENA_HOME="+$shome),
      "SERENA_USAGE_REPORTING=false",("UV_CACHE_DIR="+$uvcache),
      "PATH=/home/maxim/.local/bin:/usr/local/bin:/usr/bin:/bin",$exe,
      "start-mcp-server","--context","codex","--project",$cwd,
      "--enable-web-dashboard","false","--open-web-dashboard","false",
      "--log-level","ERROR","--tool-timeout","120"]')
  extra=(
    -c 'mcp_servers.serena346.command="systemd-run"'
    -c "mcp_servers.serena346.args=$args"
    -c 'mcp_servers.serena346.startup_timeout_sec=120'
    -c 'mcp_servers.serena346.tool_timeout_sec=120'
  )
elif [[ $arm == c ]]; then
  unit="task346-eval-${run_name}-light"
  light_script="$eval_dir/light_codeintel_mcp.py"
  args=$(jq -cn --arg unit "$unit" --arg cwd "$eval_repo" --arg script "$light_script" \
    '["--user","--pipe","--wait","--collect","--quiet",("--unit="+$unit),
      "-p","MemoryMax=128M","-p","CPUQuota=100%","-p","TasksMax=32",
      "-p",("WorkingDirectory="+$cwd),"--","python3",$script]')
  extra=(
    -c 'mcp_servers.light346.command="systemd-run"'
    -c "mcp_servers.light346.args=$args"
    -c 'mcp_servers.light346.startup_timeout_sec=30'
    -c 'mcp_servers.light346.tool_timeout_sec=120'
  )
fi

{
  printf 'run=%s\narm=%s\nrepo=%s\n' "$run_name" "$arm" "$eval_repo"
  printf 'loadavg_start='; cat /proc/loadavg
  printf 'codex_version='; codex --version
  printf 'command_common='; printf '%q ' codex "${common[@]}"; printf '\n'
  printf 'command_extra='; printf '%q ' "${extra[@]}"; printf '\n'
} > "$raw_dir/luna-$run_name-metadata.txt"

set +e
/usr/bin/time -v timeout 720 codex "${common[@]:0:${#common[@]}-1}" "${extra[@]}" - \
  < "$prompt" \
  > "$raw_dir/luna-$run_name.jsonl" \
  2> "$raw_dir/luna-$run_name.stderr"
codex_rc=$?
set -e
{
  printf 'codex_exit=%s\n' "$codex_rc"
  printf 'loadavg_end='; cat /proc/loadavg
} >> "$raw_dir/luna-$run_name-metadata.txt"

cd "$eval_repo"
set +e
{
  printf 'E1_OLD_SYMBOL\n'
  rg -n '\bpace_text\b' app tests
  printf 'E1_OLD_SYMBOL_EXIT=%s\n' "$?"
  printf 'E1_NEW_DEF\n'
  rg -n 'def format_pace_text\b' app/limits_card.py
  printf 'E1_NEW_DEF_EXIT=%s\n' "$?"
  printf 'E1_ALIAS\n'
  rg -n 'from app\.limits_card import format_pace_text as _pace_of' app/tg_bridge.py
  printf 'E1_ALIAS_EXIT=%s\n' "$?"
  printf 'E1_TESTS\n'
  timeout 600 env -u TG_BRIDGE_TOKEN -u INTERNAL_TOKEN -u DASHBOARD_PASSWORD \
    -u DASHBOARD_USERNAME -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
    uv run pytest -q tests/test_limits_card.py \
    tests/test_tg_bridge.py::TestLimitsCommand::test_format_limits_chat_message_includes_consumed_window_and_pace
  printf 'E1_TESTS_EXIT=%s\n' "$?"
  printf 'E2_OLD_SYMBOL\n'
  rg -n '\binject_skills_to_worktree\b' app tests
  printf 'E2_OLD_SYMBOL_EXIT=%s\n' "$?"
  printf 'E2_NEW_DEF\n'
  rg -n 'def install_skills_to_worktree\b' app/prompting.py
  printf 'E2_NEW_DEF_EXIT=%s\n' "$?"
  printf 'E2_REPORT_GUARD\n'
  rg -n '\binject_skills_to_worktree_report\b' app tests
  printf 'E2_REPORT_GUARD_EXIT=%s\n' "$?"
  printf 'E2_TESTS\n'
  timeout 600 env -u TG_BRIDGE_TOKEN -u INTERNAL_TOKEN -u DASHBOARD_PASSWORD \
    -u DASHBOARD_USERNAME -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
    uv run pytest -q tests/test_legacy_pipeline_skills.py tests/test_workspace.py \
    tests/test_manager.py -k 'inject or legacy_empty_pipeline or empty_pipeline_would'
  printf 'E2_TESTS_EXIT=%s\n' "$?"
  printf 'DIFF_CHECK\n'
  git diff --check
  printf 'DIFF_CHECK_EXIT=%s\n' "$?"
  printf 'STATUS\n'
  git status --short
} > "$raw_dir/luna-$run_name-acceptance.txt" 2>&1
set -e

git diff -- app tests > "$raw_dir/luna-$run_name.patch"
git diff --stat -- app tests > "$raw_dir/luna-$run_name-diffstat.txt"

printf 'run=%s arm=%s codex_exit=%s\n' "$run_name" "$arm" "$codex_rc"
grep -E '^(E1|E2|DIFF_CHECK).*=|^[0-9]+ passed|^[0-9]+ failed' "$raw_dir/luna-$run_name-acceptance.txt" || true
