#!/bin/sh
# P4: the real launcher plugin/scripts/te-hook with Codex-shaped payloads, sandboxed: PATH has only python3/git/sh/env
# (no codex/claude => any side call fails closed), HOME/TOKENECONOMIZER_HOME/CODEX_HOME are throwaway dirs.
set -u
R=/tmp/v1143-run/repo; W=$(mktemp -d /tmp/p4-XXXXXX); mkdir -p $W/proj $W/te $W/home $W/codex
export PATH=/tmp/v1143-bin HOME=$W/home TOKENECONOMIZER_HOME=$W/te CODEX_HOME=$W/codex PLUGIN_ROOT=$R/plugin GIT_CONFIG_GLOBAL=/dev/null
git init -q $W/proj; cd $W/proj
hook() { printf '%s' "$1" | $R/plugin/scripts/te-hook --host codex; echo "   (exit=$?)"; }
S=sess-0001; T=turn-1
echo '--- SessionStart'; hook '{"session_id":"'$S'","cwd":"'$W/proj'","hook_event_name":"SessionStart","source":"startup","transcript_path":"'$W'/codex/sessions/rollout-x.jsonl","model":"gpt-x"}'
echo '--- UserPromptSubmit'; hook '{"session_id":"'$S'","cwd":"'$W/proj'","hook_event_name":"UserPromptSubmit","turn_id":"'$T'","prompt":"fix it"}'
echo '--- PostToolUse (Bash, string tool_response, no exit code)'; hook '{"session_id":"'$S'","cwd":"'$W/proj'","hook_event_name":"PostToolUse","turn_id":"'$T'","tool_name":"Bash","tool_input":{"command":"pytest -q"},"tool_response":"E AssertionError\nFAILED t.py::t"}'
echo '--- Stop'; hook '{"session_id":"'$S'","cwd":"'$W/proj'","hook_event_name":"Stop","turn_id":"'$T'","stop_hook_active":false}'
echo '--- SessionEnd (transcript missing)'; hook '{"session_id":"'$S'","cwd":"'$W/proj'","hook_event_name":"SessionEnd","reason":"exit"}'
echo '--- garbage stdin'; hook 'not json'
echo '--- empty stdin'; hook ''
echo '--- TE_DISABLE=1'; TE_DISABLE=1 hook '{"session_id":"x","hook_event_name":"SessionStart","cwd":"'$W/proj'"}'
echo '--- TE_SIDECALL=1 (nested side-call guard)'; TE_SIDECALL=1 hook '{"session_id":"x","hook_event_name":"SessionStart","cwd":"'$W/proj'"}'
echo '--- state tree'; (cd $W/te && find . -type f | sort | head -40); echo '--- files written outside state root in repo:'; (cd $W/proj && git status --short --ignored | head); echo '--- errors.log'; cat $W/te/errors.log 2>/dev/null | head -20
echo '--- config set microskills=envfacts via the te CLI, then SessionStart with a seeded injection.json'
$R/plugin/scripts/te --host codex config set microskills=envfacts 2>&1 | head -5
D=$(dirname "$(find $W/te/repos -name sessions -type d | head -1)"); echo "store dir: ${D#$W/}"
mkdir -p "$D"; printf '{"rendered":"# environment facts learned from earlier sessions in this repository\\n- `python -m pytest` fails here; `/opt/p/bin/python -m pytest` works.\\n","rendered_ids":["f1"]}' > "$D/injection.json"
echo '--- SessionStart (new session) with injection'; hook '{"session_id":"sess-0002","cwd":"'$W/proj'","hook_event_name":"SessionStart","source":"startup"}'
echo '--- SessionStart source=resume (Codex replays start context; plugin should not re-inject)'; hook '{"session_id":"sess-0002","cwd":"'$W/proj'","hook_event_name":"SessionStart","source":"resume"}'
echo "W=$W"
