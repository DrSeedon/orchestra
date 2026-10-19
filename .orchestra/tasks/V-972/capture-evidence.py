"""Record bounded source excerpts and retrieval results verbatim for V-972."""
import json
from pathlib import Path
import subprocess

out = Path('.orchestra/tasks/V-972/raw')
commands = [
    "nl -ba app/manager.py | sed -n '232,294p;405,420p;1513,1538p;1896,1962p'",
    "nl -ba app/session.py | sed -n '1539,1610p;1733,1779p;2148,2167p'",
    "nl -ba app/backend_codex.py | sed -n '713,727p'",
    "nl -ba app/backend_claude.py | sed -n '1125,1158p'",
    "nl -ba app/project_catalog.py | sed -n '1,25p;243,272p'",
    "nl -ba app/routes/tm.py | sed -n '15,25p;223,246p'",
    "nl -ba app/routes/system.py | sed -n '2630,2646p'",
    "nl -ba app/routes/sessions.py | sed -n '1149,1153p'",
    "nl -ba app/routes/sessions.py | sed -n '1873,1884p'",
    "nl -ba app/workspace.py | sed -n '603,639p'",
    "nl -ba app/claude_api_credits.py | sed -n '25,47p'",
    "nl -ba scripts/video_artifact/make.py | sed -n '1260,1264p'",
    "nl -ba app/models.py | sed -n '589,601p;622,631p'",
    "rg -n -F -e 'противореч' -e 'V-971' .orchestra/kb/agent-control.md .orchestra/kb/prompt-engineering.md .orchestra/tasks/V-971/report.md",
    "git diff --stat HEAD main -- .orchestra/pipelines/default/prompts .orchestra/pipelines/default/pipeline.yaml .orchestra/temp-rules.yaml AGENTS.md app/prompting.py app/manager.py app/kb_index.py app/mcp_stdio.py",
    "git ls-files --stage AGENTS.md CLAUDE.md",
]
with (out/'supporting-commands.txt').open('w') as handle:
    for cmd in commands:
        result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
        handle.write(f'$ {cmd}\nEXIT={result.returncode}\nSTDOUT:\n{result.stdout}STDERR:\n{result.stderr}\n')
for path in [Path.home()/'.claude/skills/codex-review/SKILL.md']:
    data = path.read_text()
    (out/'global-codex-review.txt').write_text('\n'.join(f'{i:5}\t{line}' for i,line in enumerate(data.splitlines(),1))+'\n')
print(f'recorded {len(commands)} commands; global codex-review read only, not invoked')
