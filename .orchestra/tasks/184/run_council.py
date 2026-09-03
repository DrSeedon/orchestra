#!/usr/bin/env python3
"""Прогон матрицы персона × случай × повтор. Пишет сырые выходы и телеметрию в runs/.

Каждый вызов — одноразовая сессия без тулов и без MCP: персона видит только текст случая.
Запускается из пустого каталога, чтобы ни CLAUDE.md, ни AGENTS.md репозитория не подмешивались.
"""
import json
from concurrent.futures import ThreadPoolExecutor
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).parent
RUNS = HERE / "runs"
SANDBOX = pathlib.Path("/tmp/council-sandbox")

OPUS = "claude-opus-5[1m]"
SOL = "gpt-5.6-sol"


def run_claude(persona: str, case: str) -> dict:
    cmd = [
        "claude", "-p", "--model", OPUS, "--output-format", "json",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--tools", "", "--system-prompt", persona, case,
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=SANDBOX, timeout=600)
    if r.returncode != 0:
        return {"error": r.stderr[-500:], "wall": time.time() - t0}
    d = json.loads(r.stdout)
    u = d["usage"]
    return {
        "text": d["result"], "cost": d["total_cost_usd"], "wall": time.time() - t0,
        "in": u["input_tokens"], "cc": u["cache_creation_input_tokens"],
        "cr": u["cache_read_input_tokens"], "out": u["output_tokens"],
    }


def run_sol(persona: str, case: str, tag: str) -> dict:
    # у codex exec нет отдельного системного промпта — персона идёт началом промпта
    last = SANDBOX / f"{tag}.last"
    cmd = [
        "codex", "exec", "--model", SOL, "-s", "read-only", "-C", str(SANDBOX),
        "--skip-git-repo-check", "--ephemeral", "-o", str(last),
        persona + "\n\n---\n\n" + case,
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    txt = last.read_text() if last.exists() else ""
    if not txt.strip():
        return {"error": (r.stderr or r.stdout)[-500:], "wall": time.time() - t0}
    return {"text": txt, "wall": time.time() - t0, "raw_tail": r.stdout[-1500:]}


def main() -> None:
    runtime = sys.argv[1]
    reps = int(sys.argv[2])
    cases = {p.stem: p.read_text() for p in sorted((HERE / "cases").glob("C*.md"))}
    personas = {p.stem: p.read_text() for p in sorted((HERE / "personas").glob("*.md"))}
    SANDBOX.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)

    jobs = [
        (f"{runtime}_{pid}_{cid}_r{rep}", ptext, ctext)
        for rep in range(1, reps + 1)
        for cid, ctext in cases.items()
        for pid, ptext in personas.items()
        if not (RUNS / f"{runtime}_{pid}_{cid}_r{rep}.json").exists()
    ]

    def one(job):
        tag, ptext, ctext = job
        res = run_claude(ptext, ctext) if runtime == "opus" else run_sol(ptext, ctext, tag)
        res["tag"] = tag
        (RUNS / f"{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        mark = "ERR" if "error" in res else f"{res.get('cost', 0):.3f}"
        return f"{tag}  {mark}  {res['wall']:.0f}s"

    with ThreadPoolExecutor(max_workers=4) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)


if __name__ == "__main__":
    main()
