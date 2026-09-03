import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from run_evaluation import expand_transcript, load_fixtures, source_hashes


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
WRITE_LOCK = threading.Lock()


def load_latest(path: Path) -> dict[str, dict]:
    latest = {}
    for line in path.read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            latest[item["job_id"]] = item
    return latest


def load_mapping(source: str = "primary") -> dict[str, dict]:
    return json.loads((RESULTS / f"{source}-blinding-map.json").read_text())


def opaque(parts: list[str], seed: int) -> str:
    return hashlib.sha256("|".join([str(seed), *parts]).encode()).hexdigest()[:16]


def output_schema(fixture: dict, candidate_ids: list[str]) -> dict:
    anchor_ids = [item["id"] for item in fixture["semantic_anchors"]]
    candidate = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string", "enum": candidate_ids},
            "semantic_anchors": {
                "type": "object",
                "properties": {
                    anchor_id: {"type": "boolean"} for anchor_id in anchor_ids
                },
                "required": anchor_ids,
                "additionalProperties": False,
            },
            "unsupported_claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["claim", "reason"],
                    "additionalProperties": False,
                },
            },
            "false_unchanged_file_action_claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["claim", "reason"],
                    "additionalProperties": False,
                },
            },
            "conflict_preserved": {"type": "boolean"},
            "no_transcript_dump": {"type": "boolean"},
        },
        "required": [
            "candidate_id",
            "semantic_anchors",
            "unsupported_claims",
            "false_unchanged_file_action_claims",
            "conflict_preserved",
            "no_transcript_dump",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "fixture_id": {"type": "string", "const": fixture["id"]},
            "candidates": {
                "type": "array",
                "minItems": len(candidate_ids),
                "maxItems": len(candidate_ids),
                "items": candidate,
            },
        },
        "required": ["fixture_id", "candidates"],
        "additionalProperties": False,
    }


def build_prompt(fixture: dict, candidates: list[dict]) -> str:
    source_ledger = {
        "semantic_anchors": fixture["semantic_anchors"],
        "forbidden_claim_examples": fixture["forbidden_claims"],
    }
    rendered = "\n\n".join(
        f'<candidate id="{item["candidate_id"]}">\n'
        f'<measured_workspace_diff>\n{json.dumps(item["workspace_diff"], ensure_ascii=False, indent=2)}\n</measured_workspace_diff>\n'
        f'<handoff>\n{item["summary"]}\n</handoff>\n</candidate>'
        for item in candidates
    )
    return f"""You are one of two independent raters in a blinded context-compaction evaluation. Variant identities, prompt text, and deterministic scores are hidden.

Judge only semantic properties that literal checks cannot safely decide. The transcript plus each candidate's own measured workspace diff are the source of truth. The diff exists for every candidate, including candidates with no changes. A changed path proves only the measured before/after state. An unchanged or absent path never proves a Read, check, commit, deploy, test, or other action. Structured tool events in the transcript are evidence; an unmatched tool-use event has unknown outcome. Put every claim that asserts such an unsupported file action specifically in `false_unchanged_file_action_claims`, even when it also belongs in `unsupported_claims`. Do not flag a negative statement such as "no file was changed" merely because the measured diff is empty.

A summary may paraphrase an anchor only if qualifiers such as provisional/final, negation, ownership, order, time, and uncertainty remain correct. A claim is unsupported only when asserted as fact without transcript, tool, or measured-diff support. Quoting a false idea as rejected, corrected, stale, missing, or uncertain is not an unsupported claim. Do not score exact paths, exact command strings, exact recent wording, secret redaction, or deterministic ledger completeness; separate scorers cover them. `no_transcript_dump` is false only for materially redundant raw log/heartbeat copying, not a bounded evidence ledger.

Return every candidate ID exactly once. Do not rank candidates or infer their author.

<source_transcript>
{expand_transcript(fixture)}
</source_transcript>

<source_ledger>
{json.dumps(source_ledger, ensure_ascii=False, indent=2)}
</source_ledger>

{rendered}
"""


def invoke_claude(prompt: str, schema: dict, cwd: Path, timeout: int) -> dict:
    command = [
        "claude",
        "-p",
        "--safe-mode",
        "--model",
        "claude-sonnet-5",
        "--effort",
        "high",
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timeout": timeout,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed_seconds": time.monotonic() - started,
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_seconds": time.monotonic() - started,
        }
    try:
        outer = json.loads(completed.stdout)
        judgment = json.loads(outer["result"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "parse_error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": time.monotonic() - started,
        }
    return {
        "ok": not outer.get("is_error", False),
        "judgment": judgment,
        "usage": outer.get("usage", {}),
        "model_usage": outer.get("modelUsage", {}),
        "stderr": completed.stderr,
        "elapsed_seconds": time.monotonic() - started,
    }


def invoke_codex(prompt: str, schema: dict, cwd: Path, timeout: int) -> dict:
    schema_path = cwd / "schema.json"
    output_path = cwd / "judgment.json"
    schema_path.write_text(json.dumps(schema))
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "-C",
        str(cwd),
        "-m",
        "gpt-5.6-sol",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timeout": timeout,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed_seconds": time.monotonic() - started,
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_seconds": time.monotonic() - started,
        }
    try:
        judgment = json.loads(output_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "parse_error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": time.monotonic() - started,
        }
    return {
        "ok": True,
        "judgment": judgment,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "elapsed_seconds": time.monotonic() - started,
    }


def build_jobs(judge: str, seed: int, source: str = "primary") -> tuple[list[dict], dict]:
    fixtures = [item for item in load_fixtures() if item["split"] == "holdout"]
    primary = load_latest(RESULTS / f"{source}.jsonl")
    mapping = load_mapping(source)
    by_fixture = {}
    candidate_map = {}
    for job_id, item in primary.items():
        if not item.get("result", {}).get("ok"):
            continue
        candidate_id = opaque(["candidate", judge, job_id], seed)
        candidate_map[candidate_id] = {
            "primary_job_id": job_id,
            "fixture_id": item["fixture_id"],
            "variant": mapping[job_id]["variant"],
            "repetition": item["repetition"],
        }
        before = item.get("files_before", {})
        after = item.get("files_after", {})
        workspace_diff = {
            path: {"before": before.get(path), "after": after.get(path)}
            for path in sorted(set(before) | set(after))
            if before.get(path) != after.get(path)
        }
        by_fixture.setdefault(item["fixture_id"], []).append(
            {
                "candidate_id": candidate_id,
                "summary": item["result"]["summary"],
                "workspace_diff": workspace_diff,
            }
        )
    jobs = []
    # A stage may cover a subset of the corpus (pre-gate uses 3 fixtures), so the
    # expected batch size follows the fixtures actually generated, not the corpus.
    fixtures = [item for item in fixtures if item["id"] in by_fixture]
    for fixture in fixtures:
        candidates = by_fixture.get(fixture["id"], [])
        expected = len(mapping) // len(fixtures)
        if len(candidates) != expected:
            raise RuntimeError(
                f"{fixture['id']}: expected {expected} candidates, found {len(candidates)}"
            )
        random.Random(seed + int(opaque([judge, fixture["id"]], seed), 16)).shuffle(
            candidates
        )
        jobs.append(
            {
                "job_id": opaque(["judge", judge, fixture["id"]], seed),
                "judge": judge,
                "fixture": fixture,
                "candidates": candidates,
            }
        )
    random.Random(seed + (1 if judge == "claude" else 2)).shuffle(jobs)
    return jobs, candidate_map


def run_job(job: dict, timeout: int) -> dict:
    candidate_ids = [item["candidate_id"] for item in job["candidates"]]
    schema = output_schema(job["fixture"], candidate_ids)
    prompt = build_prompt(job["fixture"], job["candidates"])
    with tempfile.TemporaryDirectory(prefix=f"compact-106-q5-judge-{job['job_id']}-") as raw:
        cwd = Path(raw)
        result = (
            invoke_claude(prompt, schema, cwd, timeout)
            if job["judge"] == "claude"
            else invoke_codex(prompt, schema, cwd, timeout)
        )
    return {
        "job_id": job["job_id"],
        "judge": job["judge"],
        "fixture_id": job["fixture"]["id"],
        "candidate_order": candidate_ids,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }


def completed_jobs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        job_id
        for job_id, item in load_latest(path).items()
        if item.get("result", {}).get("ok")
    }


def append(path: Path, payload: dict) -> None:
    with WRITE_LOCK:
        with path.open("a") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()


def diagnostic(result: dict) -> dict | None:
    item = result.get("result", {})
    if item.get("ok"):
        return None
    return {
        key: item.get(key)
        for key in (
            "returncode",
            "runner_error",
            "parse_error",
            "timeout",
            "stdout",
            "stderr",
            "elapsed_seconds",
        )
        if item.get(key) not in (None, "")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("judge", choices=["claude", "codex"])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--source", default="primary")
    args = parser.parse_args()

    jobs, candidate_map = build_jobs(args.judge, args.seed, args.source)
    label = args.judge if args.source == "primary" else f"{args.source}-{args.judge}"
    output = RESULTS / f"judge-{label}.jsonl"
    (RESULTS / f"judge-{label}-blinding-map.json").write_text(
        json.dumps(candidate_map, ensure_ascii=False, indent=2) + "\n"
    )
    if output.exists() and not args.resume:
        raise SystemExit(f"{output} exists; use --resume or archive it explicitly")
    done = completed_jobs(output) if args.resume else set()
    pending = [job for job in jobs if job["job_id"] not in done]
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_jobs = {
            pool.submit(run_job, job, args.timeout): job for job in pending
        }
        for future in concurrent.futures.as_completed(future_jobs):
            job = future_jobs[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "job_id": job["job_id"],
                    "judge": args.judge,
                    "fixture_id": job["fixture"]["id"],
                    "candidate_order": [
                        item["candidate_id"] for item in job["candidates"]
                    ],
                    "result": {
                        "ok": False,
                        "runner_error": f"{type(exc).__name__}: {exc}",
                    },
                }
            append(output, result)
            detail = diagnostic(result)
            failures += detail is not None
            print(
                json.dumps(
                    {
                        "job_id": job["job_id"],
                        "fixture_id": job["fixture"]["id"],
                        "failed_total": failures,
                        "failure_diagnostic": detail,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    observed = len(completed_jobs(output))
    manifest = {
        "judge": args.judge,
        "expected_jobs": len(jobs),
        "observed_jobs": observed,
        "failures_this_invocation": failures,
        "seed": args.seed,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hashes(),
    }
    (RESULTS / f"judge-{label}-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(json.dumps(manifest), flush=True)
    return 0 if observed == len(jobs) and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
