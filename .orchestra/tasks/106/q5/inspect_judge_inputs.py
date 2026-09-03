import argparse
import json

from candidates import PRIMARY_VARIANTS
from run_judges import RESULTS, build_jobs, build_prompt


parser = argparse.ArgumentParser()
parser.add_argument("--judge", choices=["claude", "codex"], required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--count", type=int, default=3)
args = parser.parse_args()

jobs, _ = build_jobs(args.judge, args.seed)
selected = jobs[: args.count]
inspection = []
for job in selected:
    prompt = build_prompt(job["fixture"], job["candidates"])
    candidate_count = len(job["candidates"])
    leaked = [name for name in PRIMARY_VARIANTS if name in prompt]
    assert not leaked, leaked
    assert prompt.count("<measured_workspace_diff>") == candidate_count
    assert all(isinstance(item["workspace_diff"], dict) for item in job["candidates"])
    inspection.append(
        {
            "fixture_id": job["fixture"]["id"],
            "candidate_ids": [item["candidate_id"] for item in job["candidates"]],
            "candidate_count": candidate_count,
            "workspace_diff_count": prompt.count("<measured_workspace_diff>"),
            "variant_name_leaks": leaked,
            "prompt": prompt,
        }
    )

output = RESULTS / f"judge-input-inspection-{args.judge}.json"
output.write_text(json.dumps(inspection, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"output": str(output), "jobs": len(inspection), "ok": True}))
