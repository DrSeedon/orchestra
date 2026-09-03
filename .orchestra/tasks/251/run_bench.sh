#!/usr/bin/env bash
set -u

ROOT=$(git rev-parse --show-toplevel)
RAW="$ROOT/docs/tasks/251/raw"
PROMPTS="$ROOT/docs/tasks/251/prompts"
mkdir -p "$RAW" "$ROOT/data/bench-251"

export GROK_HOME="$ROOT/data/grok-home"
export GROK_TELEMETRY_ENABLED=0
export GROK_TELEMETRY_TRACE_UPLOAD=0
export GROK_TELEMETRY_MIXPANEL_ENABLED=0
export GROK_FEEDBACK_ENABLED=0
export GROK_EXTERNAL_OTEL=0
export OTEL_METRICS_EXPORTER=none
export OTEL_LOGS_EXPORTER=none
export OTEL_TRACES_EXPORTER=none
export SENTRY_DSN=
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy

run_one() {
    local task=$1 model=$2 rep=$3
    local stem="$RAW/${task}-${model}-${rep}"
    local started ended rc
    started=$(date +%s%N)
    timeout 180 grok \
        --model "$model" \
        --reasoning-effort high \
        --no-memory \
        --no-plan \
        --always-approve \
        --output-format streaming-json \
        --cwd "$ROOT/data/bench-251" \
        --prompt-file "$PROMPTS/${task}.txt" \
        >"${stem}.jsonl" 2>"${stem}.err"
    rc=$?
    ended=$(date +%s%N)
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$task" "$model" "$rep" "$rc" "$(( (ended-started)/1000000 ))" \
        | tee -a "$RAW/timings.tsv"
}

: >"$RAW/timings.tsv"
for task in A B C; do
    run_one "$task" grok-4.5 1
    run_one "$task" grok-4.6 1
    run_one "$task" grok-4.6 2
    run_one "$task" grok-4.5 2
    run_one "$task" grok-4.5 3
    run_one "$task" grok-4.6 3
done
