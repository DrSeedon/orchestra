"""Isolated live probe for resuming one Codex thread under another model."""

import argparse
import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from app.backend_codex import CodexBackend


MARKER = f"R243-{uuid.uuid4()}"
MODELS = ("gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark")


async def run_turn(backend: CodexBackend, prompt: str) -> dict:
    await backend.send(prompt)
    chunks: list[str] = []
    errors: list[str] = []
    events: list[str] = []
    result: dict = {}
    async for event in backend.events():
        events.append(event.type)
        if event.type == "text":
            chunks.append(event.content)
        elif event.type == "error":
            errors.append(event.content)
        elif event.type == "turn_end":
            result = dict(event.metadata)
            break
    result.update(text="\n".join(chunks), errors=errors, events=events)
    return result


async def backend_turn(root: Path, model: str, thread_id: str | None, prompt: str,
                       system_prompt: str) -> tuple[str, dict]:
    os.environ["CODEX_HOME"] = str(root)
    backend = CodexBackend(
        model=model,
        cwd=str(Path.cwd()),
        system_prompt=system_prompt,
        resume_thread_id=thread_id,
        reasoning_effort="low",
    )
    try:
        await asyncio.wait_for(backend.connect(), timeout=60)
        returned_id = backend.session_id
        assert returned_id
        result = await asyncio.wait_for(run_turn(backend, prompt), timeout=180)
        return returned_id, result
    finally:
        await backend.disconnect()


async def main() -> None:
    source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    scratch_parent = Path.home() / ".cache" / "orchestra-probes"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="r243-", dir=scratch_parent))
    seed = scratch / "seed"
    seed.mkdir()
    shutil.copy2(source_home / "auth.json", seed / "auth.json")

    padding = " ".join(f"context-{index:05d}" for index in range(3_000))
    system_prompt = (
        "This is an isolated model-resume canary. Do not call tools. "
        f"Context padding follows: {padding}"
    )
    seed_id, seed_result = await backend_turn(
        seed,
        MODELS[0],
        None,
        f"Store this secret marker from the user message: {MARKER}. "
        "Acknowledge that it is stored without printing it.",
        system_prompt,
    )

    results = {
        "scratch": str(scratch),
        "marker": MARKER,
        "seed": {"requested_id": None, "returned_id": seed_id, **seed_result},
    }
    for model in MODELS:
        root = scratch / model.replace(".", "_")
        shutil.copytree(seed, root)
        returned_id, result = await backend_turn(
            root,
            model,
            seed_id,
            "Return only the secret marker from the prior thread, verbatim.",
            system_prompt,
        )
        results[model] = {
            "requested_id": seed_id,
            "returned_id": returned_id,
            **result,
        }
    print(json.dumps(results, ensure_ascii=False, indent=2))


async def spark_overflow(seed: Path, seed_id: str, marker: str) -> None:
    scratch = seed.parent
    source = scratch / "overflow-sol"
    shutil.copytree(seed, source)
    padding = " ".join(f"context-{index:05d}" for index in range(12_000))
    system_prompt = (
        "This is an isolated model-resume canary. Do not call tools. "
        f"Context padding follows: {padding}"
    )
    overflow = " ".join(f"overflow-{index:06d}" for index in range(15_000))
    returned_id, sol_result = await backend_turn(
        source,
        MODELS[0],
        seed_id,
        "Store this additional context and answer only STORED. " + overflow,
        system_prompt,
    )
    spark_root = scratch / "overflow-spark"
    shutil.copytree(source, spark_root)
    try:
        spark_id, spark_result = await backend_turn(
            spark_root,
            MODELS[2],
            seed_id,
            "Return only the secret marker from the earliest prior context, verbatim.",
            system_prompt,
        )
        spark = {"returned_id": spark_id, **spark_result}
    except Exception as error:
        spark = {"error_type": type(error).__name__, "error": str(error)}
    print(json.dumps({
        "scratch": str(scratch),
        "marker": marker,
        "requested_id": seed_id,
        "sol_overflow": {"returned_id": returned_id, **sol_result},
        "spark_after_overflow": spark,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-root", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument("--marker")
    args = parser.parse_args()
    if args.seed_root:
        if not args.thread_id or not args.marker:
            parser.error("--seed-root requires --thread-id and --marker")
        asyncio.run(spark_overflow(args.seed_root, args.thread_id, args.marker))
    else:
        asyncio.run(main())
