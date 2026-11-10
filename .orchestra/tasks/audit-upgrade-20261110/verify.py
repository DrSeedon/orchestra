"""Reproducible audit verification; no live providers or production storage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.pop("NOTIFY_SOCKET", None)
os.environ["UV_PROJECT_ENVIRONMENT"] = "/home/kesha/orchestra/.venv"
mode = sys.argv[1]
if mode == "focused":
    patterns = ["test_agentic_compact*.py", "test_session*.py", "test_merge_test_gate*.py",
                "test_harness*.py", "test_models*.py", "test_publication_secrets*.py",
                "test_hub*.py", "test_tool_scoping*.py", "test_core_fixes_v1110.py",
                "test_prompt*1110.py", "test_backend_claude.py", "test_default_pipeline.py",
                "test_prompting.py", "test_local_delegation_prompts.py",
                "test_check_pipeline_manifest.py", "test_source_layout_spawn_v1130.py",
                "test_quota_wait_queue.py", "test_antigravity_runtime.py", "test_antigravity_usage.py",
                "test_runtime_registry.py", "test_model_catalog.py", "test_catalog_api.py",
                "test_audit0901_harness.py", "test_quota_admission_e2e.py", "test_free_worker_pool.py",
                "test_mcp_quota_gate.py", "test_gemini_specialist_v1257.py", "test_backend_grok.py"]
    tests = sorted({str(p) for pattern in patterns for p in Path("tests").glob(pattern)})
    commands = [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m",
                 "not live_probe and not browser", *tests],
                ["/home/kesha/.local/bin/uv", "run", "--frozen", "--no-sync", "python",
                 "scripts/check_instruction_contract.py"],
                [sys.executable, "scripts/check_pipeline_manifest.py", "--check"]]
elif mode == "followup":
    commands = [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 "tests/test_optional_worker_memory_v1069.py", "tests/test_orchestra_backup.py",
                 "tests/test_merge_operations.py::test_real_runner_causes_reach_durable_recovery",
                 "tests/test_agentic_compact_journal_v1110.py", "tests/test_core_fixes_v1110.py",
                 "tests/test_prompt_system_channel_v1110.py", "tests/test_prompt_prefix_and_stack_v1110.py",
                 "tests/test_catalog_api.py", "tests/test_default_pipeline.py", "tests/test_prompting.py",
                 "tests/test_local_delegation_prompts.py", "tests/test_tool_scoping.py"],
                ["/home/kesha/.local/bin/uv", "run", "--frozen", "--no-sync", "python",
                 "scripts/check_instruction_contract.py"],
                [sys.executable, "scripts/check_pipeline_manifest.py", "--check"]]
elif mode == "full":
    commands = [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m",
                 "not live_probe and not browser", "tests/"]]
else:
    raise ValueError(mode)
results=[]
for index, command in enumerate(commands):
    log=OUT/f"{mode}-{index+1}.log"
    print("Starting", mode, index+1, "in", ROOT, flush=True)
    started=time.monotonic()
    with log.open("w") as stream:
        done=subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    tail=log.read_text().splitlines()[-25:]
    result={"command":command,"rc":done.returncode,"seconds":round(time.monotonic()-started,2),
            "log":str(log),"tail":tail}
    results.append(result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
(OUT/f"{mode}-results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
sys.exit(int(any(result["rc"] for result in results)))
