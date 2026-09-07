"""Check native instruction loading with an otherwise unmentioned canary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
SCRATCH = tempfile.mkdtemp(prefix="orchestra-rule-probe-", dir="/mnt/data")
EXPECTED = "orch-kb-c7e0d4"
(Path(SCRATCH) / "AGENTS.md").write_text(
    (ROOT / "AGENTS.md").read_text() +
    f"\nПроверочный маркер загрузки KNOWLEDGE_LOADER_CANARY: {EXPECTED}.\n")
(Path(SCRATCH) / "CLAUDE.md").write_text((ROOT / "CLAUDE.md").read_text())
PROMPT = "Без инструментов верни только значение KNOWLEDGE_LOADER_CANARY из загруженных проектных инструкций. Если его нет, ответь UNKNOWN."
commands = {
    "codex": ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
              "--skip-git-repo-check", "-C", SCRATCH, "-s", "read-only", "-m", "gpt-6-astra",
              "-c", "project_doc_max_bytes=262144", "--disable", "apps", "--disable", "shell_tool",
              "--disable", "multi_agent", "--json", PROMPT],
    "claude": ["claude", "--print", "--output-format", "json", "--no-session-persistence",
               "--model", "claude-opus-5[1m]", "--tools", "", "--setting-sources", "project",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--", PROMPT],
}
selected = os.environ.get("NATIVE_PROBE_CLIENT", "all")
with (TASK / f"native-probe-{selected}.jsonl").open("x") as output:
    for client, command in commands.items():
        if selected != "all" and client != selected:
            continue
        result = subprocess.run(["timeout", "--kill-after=5s", "90s", *command], cwd=SCRATCH,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        answers = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if client == "claude" and event.get("type") == "result":
                answers.append(event.get("result", ""))
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                answers.append(item.get("text", ""))
        row = {"client": client, "returncode": result.returncode, "answers": answers,
               "canary_loaded": any(a.strip().rstrip('.') == EXPECTED for a in answers),
               "stderr_bytes": len(result.stderr.encode())}
        output.write(json.dumps(row, ensure_ascii=False)+"\n")
        output.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
