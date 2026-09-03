"""Frozen behavior-level RED oracle for #315 T7 document and prompt cutover."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CONTRACT_PATH = HERE / "fixtures" / "t7_cutover_contract.json"
RECORDS_PATH = HERE / "fixtures" / "t7_cutover_records.json"
INVENTORY_PATH = HERE / "fixtures" / "t7_document_inventory.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _records() -> dict:
    return _json(RECORDS_PATH)


def _inventory() -> dict:
    return _json(INVENTORY_PATH)


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _manifest_head(manifest: dict) -> str:
    body = copy.deepcopy(manifest)
    body.pop("manifest_head", None)
    return "sha256:" + _sha256_bytes(_canonical_bytes(body))


def _load_t7_api() -> SimpleNamespace:
    modules = {}
    for module_name, surface in _contract()["public_api"].items():
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"#315 T7 missing behavior: cannot import {module_name}: {exc}")
        for name in surface.get("callables", []):
            assert callable(getattr(module, name, None)), (
                f"#315 T7 missing behavior: {module_name}.{name} is not callable"
            )
        for name in surface.get("exceptions", []):
            error = getattr(module, name, None)
            assert isinstance(error, type) and issubclass(error, Exception), (
                f"#315 T7 missing behavior: {module_name}.{name} is not an exception"
            )
        modules[module_name.replace(".", "_")] = module
    return SimpleNamespace(**modules)


def _classify_path(path: str) -> str | None:
    if (
        (path.startswith("docs/tasks/") and path.endswith(".md"))
        or (path.startswith("docs/kb/") and path.endswith(".md"))
        or (path.startswith("docs/archive/sessions/") and path.endswith(".md"))
        or path == "TODO.md"
    ):
        return "immutable_evidence_cold_archive"
    if (
        (path.startswith("docs/workers/") and path.endswith(".md"))
        or (path.startswith("pipelines/default/prompts/") and path.endswith(".md"))
        or path in {"CLAUDE.md", "pipelines/default/pipeline.yaml"}
    ):
        return "active_skill_resource_source"
    return None


def _tree_at(commit: str) -> dict[str, str]:
    raw = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "--format=%(objectname)%x09%(path)", commit],
        cwd=ROOT,
    )
    result = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        blob, path = item.split(b"\t", 1)
        result[path.decode("utf-8")] = blob.decode("ascii")
    return result


def _blob_sha256s(blob_ids: list[str]) -> list[tuple[int, str]]:
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    payload = "".join(f"{blob}\n" for blob in blob_ids).encode("ascii")
    output, _ = process.communicate(payload)
    assert process.returncode == 0
    values = []
    offset = 0
    for expected in blob_ids:
        end = output.index(b"\n", offset)
        header = output[offset:end].decode("ascii").split()
        assert header == [expected, "blob", header[2]]
        size = int(header[2])
        start = end + 1
        data = output[start:start + size]
        assert output[start + size:start + size + 1] == b"\n"
        values.append((size, _sha256_bytes(data)))
        offset = start + size + 1
    assert offset == len(output)
    return values


def _normalized_manifest(manifest: dict) -> dict:
    required = {
        "path",
        "source_class",
        "source_commit",
        "git_blob",
        "source_sha256",
        "size",
        "alias",
    }
    entries = []
    for entry in manifest.get("entries", []):
        assert required <= set(entry)
        entries.append({name: entry[name] for name in sorted(required)})
    entries.sort(key=lambda value: value["path"])
    assert entries, "inventory must be nonempty"
    assert len(entries) == len({entry["path"] for entry in entries})
    assert len(entries) == len({entry["alias"] for entry in entries})
    return {
        "schema_version": manifest["schema_version"],
        "project_id": manifest["project_id"],
        "source_commit": manifest["source_commit"],
        "class_counts": manifest["class_counts"],
        "entries": entries,
        "manifest_head": manifest["manifest_head"],
    }


def _materialize_synthetic(tmp_path: Path) -> tuple[Path, dict, dict[str, str]]:
    root = tmp_path / "legacy"
    before = {}
    entries = []
    for document in _records()["synthetic_documents"]:
        path = root / document["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        body = document["content"].encode("utf-8")
        path.write_bytes(body)
        before[document["path"]] = _sha256_bytes(body)
        entries.append({
            "path": document["path"],
            "source_class": document["source_class"],
            "source_commit": "fixture-source-head",
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
            "source_sha256": "sha256:" + _sha256_bytes(body),
            "size": len(body),
            "alias": document["alias"],
        })
    entries.sort(key=lambda value: value["path"])
    class_counts = {}
    for entry in entries:
        class_counts[entry["source_class"]] = class_counts.get(entry["source_class"], 0) + 1
    manifest = {
        "schema_version": 1,
        "project_id": _records()["project_id"],
        "source_commit": "fixture-source-head",
        "classifiers": copy.deepcopy(_inventory()["classifiers"]),
        "class_counts": dict(sorted(class_counts.items())),
        "entries": entries,
    }
    manifest["manifest_head"] = _manifest_head(manifest)
    return root, manifest, before


def _normalized_prompt(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _runtime_prompt_matrix(
    tmp_path: Path,
    *,
    bases: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[tuple[str, str], str]:
    from app.backend_claude import ClaudeBackend
    from app.backend_codex import CodexBackend
    from app.backend_grok import GrokBackend
    from app.harness.prompts import build_system_prompt as build_harness_prompt
    from app.manager import ROLE_SYSTEM_PROMPT

    matrix = _records()["runtime_matrix"]
    results = {}
    for role in matrix["roles"]:
        with (
            patch("app.manager._other_orchestrators_block", return_value=""),
            patch("app.manager._workers_block", return_value=""),
            patch("app.manager.available_models_block", return_value=""),
        ):
            actual_base = ROLE_SYSTEM_PROMPT("default", role, str(tmp_path))
        assert actual_base
        base = (bases or {}).get(role) or actual_base
        claude = ClaudeBackend(
            model="claude-sonnet-5[1m]", cwd=str(tmp_path), system_prompt=base,
        )
        options = claude._make_client().options
        results[("claude", role)] = options.system_prompt["append"]

        codex = CodexBackend(model="gpt-5.6-sol", cwd=str(tmp_path), system_prompt=base)
        results[("codex", role)] = codex.system_prompt

        grok = GrokBackend(model="grok-4.6", cwd=str(tmp_path), system_prompt=base)
        profile = grok._write_agent_profile()
        assert profile is not None and profile.is_file()
        try:
            results[("grok", role)] = profile.read_text(encoding="utf-8")
        finally:
            grok._cleanup_profile()

        results[("harness", role)] = build_harness_prompt(base)
    for runtime, prompt in (overrides or {}).items():
        for role in matrix["roles"]:
            results[(runtime, role)] = prompt
    return results


def _assert_prompt_delivery(prompts: dict[tuple[str, str], str]) -> None:
    matrix = _records()["runtime_matrix"]
    expected = {
        (runtime, role)
        for runtime in matrix["runtimes"]
        for role in matrix["roles"]
    }
    assert set(prompts) == expected
    for key, prompt in prompts.items():
        normalized = _normalized_prompt(prompt)
        assert normalized, f"empty assembled prompt for {key}"
        for anchor in _records()["required_prompt_anchors"]:
            assert _normalized_prompt(anchor) in normalized, (
                f"{key} assembled prompt is missing T7 anchor {anchor!r}"
            )
        for forbidden in _records()["forbidden_legacy_directives"]:
            assert _normalized_prompt(forbidden) not in normalized, (
                f"{key} assembled prompt still contains legacy directive {forbidden!r}"
            )


def _assert_no_human_outputs(root: Path) -> None:
    files = [path for path in root.rglob("*") if path.is_file()]
    assert files, "canonical cutover store is empty"
    forbidden = set(_contract()["forbidden_generated_extensions"])
    offenders = [str(path.relative_to(root)) for path in files if path.suffix.lower() in forbidden]
    assert offenders == [], f"generated human-readable dual truth exists: {offenders}"
    assert {path.suffix.lower() for path in files} <= set(_contract()["canonical_extensions"])


def _asgi_transport(app, calls: list[str]):
    import httpx

    async def call(method, path, **kwargs):
        calls.append(f"{method.upper()} {path}")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t7.test") as client:
            response = await client.request(method, path, json=kwargs.get("json"))
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        if response.status_code >= 400:
            return {"error": payload.get("error", payload), "status": response.status_code}
        return payload

    return call


class _CutoverHarness:
    def __init__(self, tmp_path: Path):
        self.prompts = {
            (runtime, role): "\n".join(_records()["required_prompt_anchors"])
            for runtime in _records()["runtime_matrix"]["runtimes"]
            for role in _records()["runtime_matrix"]["roles"]
        }
        self.gates = copy.deepcopy(_records()["gate_receipts"])
        self.knowledge_calls = []
        self.legacy_calls = []
        self.deleted_projections = []
        self.receipts = []
        self.canonical_failure = False
        self.tmp_path = tmp_path

    def knowledge_request(self, request):
        self.knowledge_calls.append(copy.deepcopy(request))
        if self.canonical_failure:
            raise RuntimeError("canonical knowledge is unavailable")
        operation = request.get("operation")
        payload = request.get("payload") or {}
        if operation == "import_evidence":
            entry = payload.get("entry") or payload
            return {
                "operation": operation,
                "outcome": "created",
                "uri": entry.get("alias"),
                "source_sha256": entry.get("source_sha256"),
                "canonical_head": _records()["heads"]["canonical_head"],
            }
        return {
            "operation": "query",
            "source": "canonical",
            "items": [{
                "uri": payload.get("ref") or request.get("ref"),
                "claim": "canonical typed result",
            }],
            "canonical_head": _records()["heads"]["canonical_head"],
        }

    def prompt_assembler(self, runtime, role):
        return self.prompts[(runtime, role)]

    def projection_probe(self):
        return {
            "gates": copy.deepcopy(self.gates),
            "heads": copy.deepcopy(_records()["heads"]),
        }

    def receipt_writer(self, path, receipt):
        assert Path(path).suffix == ".json"
        assert set(_records()["receipt_required"]) <= set(receipt)
        assert receipt["receipt_status"] == "verified"
        self.receipts.append(copy.deepcopy(receipt))

    def legacy_reader(self, request):
        self.legacy_calls.append(copy.deepcopy(request))
        return copy.deepcopy(_records()["compound_mutants"]["legacy_reader_bypass"])

    def projection_delete(self, target):
        self.deleted_projections.append(target)


@contextmanager
def _cutover_mode(api, tmp_path: Path, root: Path, manifest: dict, harness: _CutoverHarness):
    with api.app_ia_cutover.document_cutover_mode(
        canonical_root=tmp_path / "canonical",
        repository_root=root,
        frozen_inventory=copy.deepcopy(manifest),
        knowledge_request=harness.knowledge_request,
        prompt_assembler=harness.prompt_assembler,
        projection_probe=harness.projection_probe,
        receipt_writer=harness.receipt_writer,
        legacy_reader=harness.legacy_reader,
        projection_delete=harness.projection_delete,
    ):
        yield


def _shadow_request(manifest: dict) -> dict:
    return {
        "operation": "shadow",
        "expected_generation": 1,
        "inventory": copy.deepcopy(manifest),
        "runtime_matrix": copy.deepcopy(_records()["runtime_matrix"]),
    }


def _canonical_request() -> dict:
    return {
        "operation": "canonical",
        "expected_generation": 2,
        "required_gates": copy.deepcopy(_contract()["required_gates"]),
    }


def _assert_receipt(receipt: dict, operation: str) -> None:
    assert set(_records()["receipt_required"]) <= set(receipt)
    assert receipt["receipt_status"] == "verified"
    assert receipt["operation"] == operation
    assert receipt["canonical_head"] == _records()["heads"]["canonical_head"]
    assert receipt["projection_head"] == _records()["heads"]["projection_head"]
    assert receipt["indexed_head"] == _records()["heads"]["indexed_head"]


def test_t7_control_frozen_inventory_and_t1_t6_hashes_are_exact():
    contract = _contract()
    inventory = _inventory()
    records = _records()
    assert _sha256_path(RECORDS_PATH) == contract["records_sha256"]
    assert _sha256_path(INVENTORY_PATH) == contract["inventory_sha256"]
    assert inventory["manifest_head"] == contract["inventory_manifest_head"]
    assert _manifest_head(inventory) == inventory["manifest_head"]
    assert records["source_commit"] == inventory["source_commit"] == contract["source_commit"]
    assert len(inventory["entries"]) == contract["expected_inventory_count"]
    assert inventory["class_counts"] == contract["expected_inventory_class_counts"]
    assert set(inventory["class_counts"]) == set(records["inventory_classes"])
    assert records["expected_denominators"] == {
        "controls": contract["expected_controls"],
        "behavior_nodes": contract["expected_behavior_nodes"],
        "compound_mutants": contract["expected_compound_mutants"],
        "runtime_count": 4,
        "role_count": 5,
        "synthetic_document_count": 8,
    }
    for rel, expected in contract["compatibility_sha256"].items():
        assert _sha256_path(ROOT / rel) == expected, rel

    tree = _tree_at(contract["source_commit"])
    scoped = {path: blob for path, blob in tree.items() if _classify_path(path) is not None}
    entries = inventory["entries"]
    assert {entry["path"]: entry["git_blob"] for entry in entries} == scoped
    for entry, (size, digest) in zip(entries, _blob_sha256s([entry["git_blob"] for entry in entries])):
        assert entry["source_class"] == _classify_path(entry["path"])
        assert entry["size"] == size
        assert entry["source_sha256"] == f"sha256:{digest}"
        assert entry["alias"].startswith("orch://project/orchestra/")


def test_t7_control_real_runtime_and_native_skill_assembly_paths_execute(tmp_path):
    sentinel = "T7_RUNTIME_ASSEMBLY_POSITIVE_SENTINEL"
    bases = {role: f"{sentinel}::{role}" for role in _records()["runtime_matrix"]["roles"]}
    prompts = _runtime_prompt_matrix(tmp_path, bases=bases)
    assert len(prompts) == 20
    assert all(sentinel in prompt for prompt in prompts.values())

    from app.prompting import inject_skills_to_worktree_report

    skill_root = tmp_path / "skill-consumer"
    subprocess.run(["git", "init", "-q", str(skill_root)], check=True)
    source = ROOT / "pipelines/default/prompts/skills/codex-debate.md"
    for home in (".claude", ".codex"):
        result = inject_skills_to_worktree_report(["codex-debate"], str(skill_root), home)
        delivered = skill_root / home / "skills/codex-debate/SKILL.md"
        assert result.written == 1
        assert delivered.read_bytes() == source.read_bytes()


@pytest.mark.asyncio
async def test_t7_control_real_knowledge_mcp_http_owner_path_executes(monkeypatch):
    from fastapi import FastAPI
    import app.mcp_stdio as mcp_stdio
    from app.routes.knowledge import router

    app = FastAPI()
    app.include_router(router)
    calls = []
    monkeypatch.setattr(mcp_stdio, "_api", _asgi_transport(app, calls))
    raw = await mcp_stdio.knowledge(
        operation="read_file",
        detail="summary",
        payload={"path": "docs/kb/repo-ops.md"},
    )
    result = json.loads(raw)
    assert calls == ["POST /api/knowledge"]
    assert result["error"]["code"] == "unsupported_operation"
    tools = await mcp_stdio.mcp.list_tools()
    names = [tool.name for tool in tools]
    assert names and names.count("knowledge") == 1


def test_t7_control_valid_alternate_and_compound_detectors_are_material(tmp_path):
    _, manifest, _ = _materialize_synthetic(tmp_path)
    alternate = copy.deepcopy(manifest)
    alternate["metadata"] = copy.deepcopy(_records()["valid_alternate"]["metadata"])
    alternate["entries"] = [
        {**{name: entry[name] for name in _records()["valid_alternate"]["entry_order"]},
         "git_blob": entry["git_blob"], "safe_extra": True}
        for entry in reversed(alternate["entries"])
    ]
    alternate["manifest_head"] = _manifest_head(alternate)
    assert len(_normalized_manifest(alternate)["entries"]) == 8

    canonical = tmp_path / "detector"
    canonical.mkdir()
    (canonical / "record.json").write_text("{}\n", encoding="utf-8")
    (canonical / "generated.md").write_text("dual truth\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="dual truth"):
        _assert_no_human_outputs(canonical)

    good = "\n".join(_records()["required_prompt_anchors"])
    prompts = {
        (runtime, role): good
        for runtime in _records()["runtime_matrix"]["runtimes"]
        for role in _records()["runtime_matrix"]["roles"]
    }
    prompts[("harness", "worker")] = _records()["compound_mutants"]["stale_runtime_assembly"]["prompt"]
    with pytest.raises(AssertionError, match="assembled prompt"):
        _assert_prompt_delivery(prompts)


def test_t7_inventory_api_reproduces_and_resolves_the_frozen_complete_source_inventory(tmp_path):
    api = _load_t7_api()
    actual = api.scripts_ia_document_inventory.inventory_api({
        "operation": _contract()["inventory_operation"],
        "repository_root": str(ROOT),
        "source_commit": _contract()["source_commit"],
        "classifiers": copy.deepcopy(_inventory()["classifiers"]),
    })
    assert _normalized_manifest(actual) == _normalized_manifest(_inventory())
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, ROOT, actual, harness):
        shadow = api.scripts_ia_migrate_documents.migration_api(_shadow_request(actual))
        assert shadow["inventory_head"] == actual["manifest_head"]
        api.app_ia_cutover.cutover_api(_canonical_request())
        resolved = [
            api.app_ia_cutover.cutover_api({
                "operation": "resolve", "ref": entry["alias"], "detail": "evidence",
            })
            for entry in actual["entries"]
        ]
    assert len(resolved) == _contract()["expected_inventory_count"]
    assert all(value["source"] == "canonical" and value["items"] for value in resolved)
    assert harness.legacy_calls == []
    _assert_no_human_outputs(tmp_path / "canonical")


@pytest.mark.asyncio
async def test_t7_agent_surface_is_one_knowledge_tool_and_legacy_reader_is_absent(monkeypatch):
    from fastapi import FastAPI
    import app.mcp_stdio as mcp_stdio
    import app.ia.knowledge as knowledge_owner
    from app.routes.knowledge import router

    owner_calls = []
    original = knowledge_owner.knowledge_api

    def tracked(request):
        owner_calls.append(request["operation"])
        return original(request)

    monkeypatch.setattr(knowledge_owner, "knowledge_api", tracked)
    app = FastAPI()
    app.include_router(router)
    calls = []
    monkeypatch.setattr(mcp_stdio, "_api", _asgi_transport(app, calls))
    raw = await mcp_stdio.knowledge("read_file", "summary", {"path": "docs/kb/repo-ops.md"})
    result = json.loads(raw)
    assert result["error"]["code"] == "unsupported_operation"
    assert calls == ["POST /api/knowledge"]
    assert owner_calls == ["read_file"]
    tools = await mcp_stdio.mcp.list_tools()
    names = [tool.name for tool in tools]
    assert names.count(_contract()["single_agent_tool"]) == 1
    assert not set(_records()["tool_surface"]["legacy_readers"]) & set(names)


def test_t7_all_runtime_assembled_prompts_and_native_skills_deliver_cutover_contract(tmp_path):
    prompts = _runtime_prompt_matrix(tmp_path)
    from app.prompting import inject_skills_to_worktree_report

    skill_root = tmp_path / "skill-delivery"
    subprocess.run(["git", "init", "-q", str(skill_root)], check=True)
    for home in (".claude", ".codex"):
        result = inject_skills_to_worktree_report(
            ["codex-debate", "orchestra-agents"], str(skill_root), home,
        )
        assert result.written == 2
        delivered = "\n".join(
            (skill_root / home / f"skills/{name}/SKILL.md").read_text(encoding="utf-8")
            for name in ("codex-debate", "orchestra-agents")
        )
        assert "orch://" in delivered and "`knowledge`" in delivered
        for forbidden in _records()["forbidden_legacy_directives"]:
            assert _normalized_prompt(forbidden) not in _normalized_prompt(delivered)
    _assert_prompt_delivery(prompts)


def test_t7_shadow_canonical_resolve_and_rollback_are_byte_safe_idempotent(tmp_path):
    api = _load_t7_api()
    root, manifest, before = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        shadow = api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        retry = api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        assert shadow["active_owner"] == retry["active_owner"] == "legacy"
        assert shadow["shadow_owner"] == retry["shadow_owner"] == "canonical"
        assert shadow["generation"] == retry["generation"] == 2
        assert shadow["receipt"]["receipt_id"] == retry["receipt"]["receipt_id"]
        assert len(harness.receipts) == 1
        _assert_receipt(shadow["receipt"], "shadow")

        canonical = api.app_ia_cutover.cutover_api(_canonical_request())
        assert canonical["active_owner"] == "canonical"
        assert canonical["generation"] == 3
        _assert_receipt(canonical["receipt"], "canonical")
        state = api.app_ia_cutover.cutover_api({"operation": "state"})
        assert state["active_owner"] == "canonical" and state["generation"] == 3

        resolved = [
            api.app_ia_cutover.cutover_api({
                "operation": "resolve", "ref": entry["alias"], "detail": "evidence",
            })
            for entry in manifest["entries"]
        ]
        assert all(value["source"] == "canonical" and value["items"] for value in resolved)
        assert {
            value["items"][0]["uri"] for value in resolved
        } == {entry["alias"] for entry in manifest["entries"]}
        assert harness.legacy_calls == []

        rollback = api.app_ia_cutover.cutover_api({
            "operation": "rollback",
            "expected_generation": 3,
            "target_owner": "legacy",
        })
        assert rollback["active_owner"] == "legacy"
        assert rollback["generation"] == 4
        _assert_receipt(rollback["receipt"], "rollback")

    after = {
        path: _sha256_path(root / path)
        for path in before
    }
    assert after == before
    assert harness.deleted_projections == []
    assert len(harness.receipts) == 3
    _assert_no_human_outputs(tmp_path / "canonical")


def test_t7_valid_alternate_inventory_order_metadata_and_prompt_layout_are_accepted(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    alternate = copy.deepcopy(manifest)
    alternate["metadata"] = copy.deepcopy(_records()["valid_alternate"]["metadata"])
    alternate["entries"].reverse()
    alternate["manifest_head"] = _manifest_head(alternate)
    harness = _CutoverHarness(tmp_path)
    layout = _records()["valid_alternate"]["runtime_layout"]
    harness.prompts = {
        key: f"{layout['prefix']}\n{value}\n{layout['suffix']}"
        for key, value in harness.prompts.items()
    }
    with _cutover_mode(api, tmp_path, root, alternate, harness):
        result = api.scripts_ia_migrate_documents.migration_api(_shadow_request(alternate))
    assert result["generation"] == 2
    assert result["inventory_head"] == alternate["manifest_head"]
    _assert_no_human_outputs(tmp_path / "canonical")


def test_t7_mutant_markdown_and_json_dual_truth_is_rejected(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    mutant = _records()["compound_mutants"]["markdown_json_dual_truth"]
    path = tmp_path / "canonical" / mutant["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mutant["content"], encoding="utf-8")
    with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
        with _cutover_mode(api, tmp_path, root, manifest, harness):
            api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
    assert harness.receipts == []


def test_t7_mutant_source_patch_with_one_stale_runtime_assembly_is_rejected(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    mutant = _records()["compound_mutants"]["stale_runtime_assembly"]
    for role in _records()["runtime_matrix"]["roles"]:
        harness.prompts[(mutant["runtime"], role)] = mutant["prompt"]
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
            api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
    assert harness.receipts == []


def test_t7_mutant_forged_parity_cannot_delete_sqlite_projection(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        mutant = _records()["compound_mutants"]["forged_shadow_parity_sqlite_delete"]
        harness.gates["shadow_parity"]["canonical_normalized_head"] = mutant[
            "canonical_normalized_head"
        ]
        request = _canonical_request()
        request["remove_projection"] = mutant["request_projection_delete"]
        with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
            api.app_ia_cutover.cutover_api(request)
        state = api.app_ia_cutover.cutover_api({"operation": "state"})
    assert state["active_owner"] == "legacy" and state["generation"] == 2
    assert harness.deleted_projections == []


def test_t7_mutant_rewritten_evidence_with_updated_alias_is_rejected(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    forged = copy.deepcopy(manifest)
    mutant = _records()["compound_mutants"]["rewritten_evidence_alias_update"]
    (root / mutant["path"]).write_text(mutant["content"], encoding="utf-8")
    entry = next(value for value in forged["entries"] if value["path"] == mutant["path"])
    body = (root / mutant["path"]).read_bytes()
    entry["source_sha256"] = "sha256:" + _sha256_bytes(body)
    entry["size"] = len(body)
    entry["alias"] = mutant["alias"]
    forged["manifest_head"] = _manifest_head(forged)
    harness = _CutoverHarness(tmp_path)
    with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
        with _cutover_mode(api, tmp_path, root, manifest, harness):
            api.scripts_ia_migrate_documents.migration_api(_shadow_request(forged))
    assert harness.receipts == [] and harness.knowledge_calls == []


def test_t7_mutant_projection_fallback_cannot_hide_canonical_failure(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        api.app_ia_cutover.cutover_api(_canonical_request())
        harness.canonical_failure = True
        mutant = _records()["compound_mutants"]["projection_fallback_canonical_failure"]
        with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
            api.app_ia_cutover.cutover_api({
                "operation": "resolve",
                "ref": manifest["entries"][0]["alias"],
                "detail": "summary",
                "sqlite": mutant["sqlite_claim"],
                "vector": mutant["vector_claim"],
            })
    assert harness.legacy_calls == []


def test_t7_mutant_legacy_reader_cannot_bypass_typed_api(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        api.app_ia_cutover.cutover_api(_canonical_request())
        mutant = _records()["compound_mutants"]["legacy_reader_bypass"]
        with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
            api.app_ia_cutover.cutover_api({
                "operation": "resolve",
                "ref": manifest["entries"][0]["alias"],
                "detail": "evidence",
                "reader": "legacy_file",
                "path": mutant["path"],
            })
    assert harness.legacy_calls == []


def test_t7_mutant_rollback_generation_mismatch_preserves_canonical_owner(tmp_path):
    api = _load_t7_api()
    root, manifest, _ = _materialize_synthetic(tmp_path)
    harness = _CutoverHarness(tmp_path)
    with _cutover_mode(api, tmp_path, root, manifest, harness):
        api.scripts_ia_migrate_documents.migration_api(_shadow_request(manifest))
        api.app_ia_cutover.cutover_api(_canonical_request())
        mutant = _records()["compound_mutants"]["rollback_generation_mismatch"]
        receipt_count = len(harness.receipts)
        with pytest.raises(api.app_ia_cutover.DocumentCutoverError):
            api.app_ia_cutover.cutover_api({
                "operation": "rollback",
                "expected_generation": mutant["expected_generation"],
                "target_owner": "legacy",
            })
        state = api.app_ia_cutover.cutover_api({"operation": "state"})
    assert state["active_owner"] == "canonical" and state["generation"] == 3
    assert len(harness.receipts) == receipt_count
