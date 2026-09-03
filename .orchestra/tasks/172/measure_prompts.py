#!/usr/bin/env python3
"""Reproduce the static prompt-size and exact-duplication measurements for #172.

The script is read-only: it prints TSV sections and does not connect to Orchestra.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from app.mcp_stdio import mcp
from app.backend_codex import ORCHESTRA_FULL_MCP_TOOLS
from app.manager import ROLE_SYSTEM_PROMPT, _roles_catalog_from_manifest
from app.models import available_models_block
from app.pipeline import build_system_prompt, load_pipeline, resolve_role
from app.prompting import _WORKER_MEMORY_BLOCK, refresh_worker_memory, safe_format_prompt


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = "default"
ROLES = ("orchestrator", "sub-orchestrator", "worker", "full-cycle")


def size(text: str) -> tuple[int, int, int]:
    return len(text.encode()), len(text), len(text.splitlines())


def role_files(role_name: str) -> list[Path]:
    role = resolve_role(load_pipeline(PIPELINE), role_name)
    prompt_dir = ROOT / "pipelines" / PIPELINE / "prompts"
    files = [prompt_dir / layer for layer in role.prompt_layers]
    files.extend(prompt_dir / "modules" / f"{module}.md" for module in role.modules)
    return [path for path in files if path.is_file()]


def print_role_sizes() -> None:
    print("[role_sizes]")
    print("role\tbytes\tchars\tlines\tlayers")
    for role_name in ROLES:
        text = build_system_prompt(PIPELINE, role_name)
        byte_count, char_count, line_count = size(text)
        layers = ",".join(path.relative_to(ROOT).as_posix() for path in role_files(role_name))
        print(f"{role_name}\t{byte_count}\t{char_count}\t{line_count}\t{layers}")


def print_file_sizes() -> None:
    paths: set[Path] = set()
    for role_name in ROLES:
        paths.update(role_files(role_name))
    print("\n[prompt_file_sizes]")
    print("path\tbytes\tchars\tlines")
    for path in sorted(paths):
        byte_count, char_count, line_count = size(path.read_text())
        print(f"{path.relative_to(ROOT)}\t{byte_count}\t{char_count}\t{line_count}")


def print_agent_sizes() -> None:
    paths = (
        Path.home() / ".codex" / "AGENTS.md",
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "docs" / "workers" / "prompt-engineer.md",
    )
    print("\n[agent_and_memory_sizes]")
    print("path\tbytes\tchars\tlines")
    for path in paths:
        byte_count, char_count, line_count = size(path.read_text())
        print(f"{path}\t{byte_count}\t{char_count}\t{line_count}")


def print_manager_static_dynamic() -> None:
    print("\n[manager_static_dynamic]")
    print("role\trole_catalog_bytes\tavailable_models_bytes\tcombined_bytes")
    models = available_models_block()
    for role_name in ("orchestrator", "sub-orchestrator"):
        catalog = _roles_catalog_from_manifest(PIPELINE, role_name)
        combined = f"{catalog}\n\n{models}"
        print(
            f"{role_name}\t{len(catalog.encode())}\t{len(models.encode())}\t"
            f"{len(combined.encode())}"
        )


def print_exact_duplicates() -> None:
    print("\n[exact_cross_layer_duplicate_lines]")
    print("role\tredundant_bytes\tduplicate_text\tlocations")
    for role_name in ROLES:
        occurrences: dict[str, list[str]] = defaultdict(list)
        for path in role_files(role_name):
            for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
                line = " ".join(raw_line.split())
                if len(line) >= 48:
                    occurrences[line].append(f"{path.relative_to(ROOT)}:{line_number}")
        rows = []
        for line, locations in occurrences.items():
            distinct_files = {location.rsplit(":", 1)[0] for location in locations}
            if len(distinct_files) < 2:
                continue
            redundant_bytes = len(line.encode()) * (len(locations) - 1)
            rows.append((redundant_bytes, line, locations))
        for redundant_bytes, line, locations in sorted(rows, reverse=True)[:30]:
            print(
                f"{role_name}\t{redundant_bytes}\t"
                f"{json.dumps(line, ensure_ascii=False)}\t{','.join(locations)}"
            )


def print_reload_memory_simulation() -> None:
    """Exercise manager._load_from_db's current prompt-tail reconstruction shape."""
    role_name = "full-cycle"
    worker_name = "prompt-engineer"
    scope = str(ROOT)
    base = safe_format_prompt(
        ROLE_SYSTEM_PROMPT(PIPELINE, role_name),
        worker_name=worker_name,
        orchestrator_name="orchestrator",
        scope=scope,
        branch="task-172",
    )
    memory = (ROOT / "docs" / "workers" / f"{worker_name}.md").read_text().strip()
    block = f"\n\n<worker-memory>\n{memory}\n</worker-memory>"
    old_prompt = base + block
    current_prompt = base + block
    custom_part = old_prompt[len(base) :]
    reloaded = current_prompt + custom_part
    refreshed = refresh_worker_memory(reloaded, worker_name, role_name, scope)
    print("\n[reload_memory_simulation]")
    print("state\tbytes\tworker_memory_blocks")
    for label, prompt in (
        ("spawn", old_prompt),
        ("reload", reloaded),
        ("reload_then_refresh", refreshed),
    ):
        print(f"{label}\t{len(prompt.encode())}\t{len(_WORKER_MEMORY_BLOCK.findall(prompt))}")
    print(f"duplicate_extra_bytes\t{len(refreshed.encode()) - len(old_prompt.encode())}")


async def print_tool_schema_sizes() -> None:
    tools = await mcp.list_tools()
    rows = []
    for tool in tools:
        description = tool.description or ""
        schema = tool.inputSchema or {}
        output_schema = tool.outputSchema or {}
        prompt_core = json.dumps(
            {"name": tool.name, "description": description, "inputSchema": schema},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        transport = json.dumps(
            {
                "name": tool.name,
                "description": description,
                "inputSchema": schema,
                **({"outputSchema": output_schema} if output_schema else {}),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        rows.append(
            (
                tool.name,
                len(description.encode()),
                len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()),
                (
                    len(
                        json.dumps(
                            output_schema,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    )
                    if output_schema
                    else 0
                ),
                len(prompt_core.encode()),
                len(transport.encode()),
            )
        )
    print("\n[orchestra_tool_schemas]")
    enabled = set(ORCHESTRA_FULL_MCP_TOOLS)
    print(
        "name\tcodex_enabled\tdescription_bytes\tinput_schema_bytes\t"
        "output_schema_bytes\tprompt_core_bytes\ttransport_bytes"
    )
    for row in sorted(rows, key=lambda item: item[4], reverse=True):
        print("\t".join(map(str, (row[0], row[0] in enabled, *row[1:]))))
    print(
        "TOTAL_REGISTERED\t-\t"
        + "\t".join(str(sum(row[index] for row in rows)) for index in range(1, 6))
    )
    enabled_rows = [row for row in rows if row[0] in enabled]
    print(
        "TOTAL_CODEX_ENABLED\t-\t"
        + "\t".join(str(sum(row[index] for row in enabled_rows)) for index in range(1, 6))
    )


async def main() -> None:
    print_role_sizes()
    print_file_sizes()
    print_agent_sizes()
    print_manager_static_dynamic()
    print_exact_duplicates()
    print_reload_memory_simulation()
    await print_tool_schema_sizes()


if __name__ == "__main__":
    asyncio.run(main())
