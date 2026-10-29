#!/usr/bin/env bash
set -euo pipefail
base=.orchestra/tasks/V-1122/evidence
mkdir -p "$base/public-code"
for spec in \
'sentinelx-cloud-core:pyproject.toml' \
'sentinelx-cloud-core:config.example.yaml' \
'sentinelx-cloud-core:config.example.windows.yaml' \
'sentinelx-cloud-core:systemd/sentinelx-core.service' \
'sentinelx-cloud-core:THREAT_MODEL.md' \
'sentinelx-cloud-core:src/sentinelx_core/client.py' \
'sentinelx-cloud-core:src/sentinelx_core/identity.py' \
'sentinelx-cloud-core:src/sentinelx_core/policy.py' \
'sentinelx-cloud-core:src/sentinelx_core/executor_engine.py' \
'sentinelx-cloud-core:src/sentinelx_core/executor.py' \
'sentinelx-cloud-core:src/sentinelx_core/handlers/exec.py' \
'sentinelx-cloud-core:src/sentinelx_core/handlers/script.py' \
'sentinelx-cloud-core:src/sentinelx_core/handlers/edit.py' \
'sentinelx-cloud-core:src/sentinelx_core/handlers/upload.py' \
'sentinelx-cloud-core:src/sentinelx_core/handlers/local_api.py' \
'sentinelx-cloud-core:src/sentinelx_core/local_api.py' \
'sentinelx-cloud-core:src/sentinelx_core/local_api_relay.py' \
'sentinelx-cloud-core:src/sentinelx_core/jobs.py' \
'sentinelx-cloud-core:src/sentinelx_core/pending_results.py' \
'sentinelx-cloud-core:src/sentinelx_core/rotation.py' \
'sentinelx-cloud-core:src/sentinelx_core/local_audit.py' \
'sentinelx-cloud-core:src/sentinelx_core/segment_check.py' \
'sentinelx-cloud-installer:dispatch.sh' \
'sentinelx-cloud-installer:install.sh' \
'sentinelx-cloud-installer:install-macos.sh' \
'sentinelx-cloud-installer:install.ps1' \
'sentinelx-cloud-installer:enroll.py'; do
 repo=${spec%%:*}; path=${spec#*:}
 pin=$(jq -r '.[0].sha' "$base/$repo.commits.json")
 url="https://raw.githubusercontent.com/pensados/$repo/$pin/$path"
 name="$repo--${path//\//__}.txt"
 printf 'SOURCE %s\n' "$url"
 curl -fsSL --max-time 40 "$url" | nl -ba > "$base/public-code/$name"
 sha256sum "$base/public-code/$name" | sed "s#$base/public-code/##"
done
