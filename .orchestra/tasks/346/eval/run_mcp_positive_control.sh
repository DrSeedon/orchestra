#!/usr/bin/env bash
set -euo pipefail

arm=${1:-}
if [[ $arm != b && $arm != c ]]; then
  echo "usage: $0 b|c" >&2
  exit 2
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../../.." && pwd)
raw_dir="$repo_root/docs/tasks/346/evidence/raw"
scratch_root=$(sed -n '1p' "$raw_dir/scratch-path.txt")
run="mcp-control-$arm-codemode"
eval_repo="$scratch_root/luna-$run"
"$script_dir/prepare_eval_repo.sh" "$eval_repo" "$run" "$raw_dir/serena-generated-project-yml.txt" \
  > "$raw_dir/luna-$run-setup.txt" 2>&1

extra=()
if [[ $arm == b ]]; then
  unit=task346-mcp-control-b-serena
  args=$(jq -cn --arg unit "$unit" --arg cwd "$eval_repo" \
    --arg exe "$scratch_root/venv/bin/serena" --arg shome "$scratch_root/serena-home-$run" \
    --arg uvcache "$scratch_root/uv-cache-$run" \
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
else
  unit=task346-mcp-control-c-light
  args=$(jq -cn --arg unit "$unit" --arg cwd "$eval_repo" \
    --arg script "$script_dir/light_codeintel_mcp.py" \
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

/usr/bin/time -v timeout 360 codex exec --json --ephemeral --ignore-user-config --color never \
  -C "$eval_repo" -m gpt-5.6-luna -c 'model_reasoning_effort="medium"' \
  -c 'features.code_mode=true' -c 'features.deferred_tool_world_state=true' \
  -c 'features.non_prefixed_mcp_tool_names=true' \
  -s danger-full-access "${extra[@]}" - \
  < "$script_dir/mcp-control-$arm-prompt.txt" \
  > "$raw_dir/luna-$run.jsonl" 2> "$raw_dir/luna-$run.stderr"

jq -c 'select(.type=="item.completed")|.item|{type,name,server,tool,arguments,text}' \
  "$raw_dir/luna-$run.jsonl" > "$raw_dir/luna-$run-items.jsonl"
printf 'control=%s complete\n' "$arm"
