from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path

from scripts import kb_promote_facts as script


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[dict]]:
    repo = tmp_path / "repo"
    facts_dir = repo / "docs/tasks/kb-extract"
    facts_dir.mkdir(parents=True)
    source = repo / "docs/kb/source.md"
    source.parent.mkdir(parents=True)
    source.write_text("Measured source evidence.\n", encoding="utf-8")
    facts = [
        {
            "statement": f"Canonical statement {index}.",
            "reason": f"Measured reason {index}.",
            "decided_at": None if index == 1 else "2026-08-26",
            "evidence": "Measured source evidence.",
            "source_file": "docs/kb/source.md",
            "source_lines": str(index),
            "status": "rejected" if index == 10 else "current",
            "topic": "проверка идемпотентности",
        }
        for index in range(1, 11)
    ]
    (facts_dir / "part-1.json").write_text(
        json.dumps(facts, ensure_ascii=False), encoding="utf-8"
    )

    canonical = tmp_path / "canonical"
    task_id = "8b01850f-d6f2-504e-9c1d-390d9e55b5c5"
    task = canonical / f"tasks/projects/orchestra/tasks/{task_id}/state.json"
    task.parent.mkdir(parents=True)
    task.write_text(json.dumps({
        "record_type": "task.state",
        "stable_id": task_id,
        "uri": f"orch://project/orchestra/tasks/{task_id}/state",
        "project_id": "orchestra",
        "display_number": 399,
        "title": "Extract docs/tasks/kb-extract/part-1.json",
        "evidence_refs": [],
    }))
    resource = canonical / "evidence/orchestra/resource.json"
    resource.parent.mkdir(parents=True)
    resource.write_text(json.dumps({
        "record_type": "resource",
        "stable_id": "9c3e54c0-3a53-5824-95b1-db920d4c6812",
        "uri": "orch://project/orchestra/resources/9c3e54c0-3a53-5824-95b1-db920d4c6812",
        "project_id": "orchestra",
        "source_path": "docs/kb/source.md",
        "source_sha256": f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}",
        "git_commit": "1" * 40,
    }))
    return repo, facts_dir, canonical, facts


def test_dry_run_is_deterministic_and_second_inventory_has_zero_new(capsys, tmp_path):
    repo, facts_dir, canonical, facts = _fixture(tmp_path)
    arguments = [
        "--facts-dir", str(facts_dir),
        "--source-root", str(repo),
        "--canonical-root", str(canonical),
        "--expected-count", "10",
    ]

    assert script.main(arguments) == 0
    first = capsys.readouterr().out
    assert "loaded=10 status_current=9 status_rejected=1" in first
    assert "ready_to_write=10 already_exists=0 preflight_rejected=0" in first

    ready, rejected = script.preflight(
        script.load_facts(facts_dir),
        repo_root=repo,
        canonical_root=canonical,
        project="orchestra",
        task_map={1: 399},
    )
    assert not rejected and len(ready) == 10
    first_payload = script._fact_payload(ready[0])
    assert first_payload["metadata"]["decided_at"] is None
    assert first_payload["metadata"]["valid_from_basis"] == "extraction_observed_at"
    assert first_payload["valid_from"] == first_payload["observed_at"] == script.EXTRACTED_AT
    bogus = ready[0]
    bogus_path = canonical / (
        f"knowledge/projects/orchestra/topics/{bogus.topic_slug}/"
        f"facts/fact-{bogus.stable_id}/{bogus.stable_id}.json"
    )
    bogus_path.parent.mkdir(parents=True)
    bogus_path.write_text("{}")
    assert script.main(arguments) == 2
    conflict = capsys.readouterr().out
    assert "rejected_reason[existing_canonical_conflict]=1" in conflict
    bogus_path.unlink()

    evidence_refs = []
    archive_entries = []
    for item in ready:
        path = canonical / (
            f"knowledge/projects/orchestra/topics/{item.topic_slug}/"
            f"facts/fact-{item.stable_id}/{item.stable_id}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            **script._fact_payload(item),
            "record_type": "knowledge.fact",
            "project_id": "orchestra",
            "topic_slug": item.topic_slug,
        }))
        source_request = script.import_request(item, repo, "orchestra")
        evidence_uri = source_request["canonical_uri"]
        evidence_refs.append(evidence_uri)
        task_evidence = canonical / (
            f"tasks/projects/orchestra/tasks/{item.task_id}/evidence/{item.evidence_id}.json"
        )
        task_evidence.parent.mkdir(parents=True, exist_ok=True)
        task_evidence.write_text(json.dumps({
            "record_type": "task.evidence",
            "stable_id": item.evidence_id,
            "uri": evidence_uri,
            "task_id": item.task_id,
            "project_id": "orchestra",
            "kind": "immutable-evidence",
            "canonical_path": source_request["path"],
            "anchor": source_request["anchor"],
            "git_commit": source_request["git_commit"],
            "content_sha256": source_request["content_sha256"],
        }))
        knowledge_ref = canonical / (
            f"knowledge/projects/orchestra/evidence/{item.evidence_id}.json"
        )
        knowledge_ref.parent.mkdir(parents=True, exist_ok=True)
        knowledge_ref.write_text(json.dumps({
            "record_type": "knowledge.evidence-ref",
            "stable_id": item.evidence_id,
            "uri": evidence_uri,
            "project_id": "orchestra",
            "source_path": source_request["path"],
            "source_class": source_request["class"],
            "source_sha256": source_request["content_sha256"],
            "git_commit": source_request["git_commit"],
            "anchor": source_request["anchor"],
            "storage": "cold-immutable-reference",
        }))
        archive_entries.append({
            "stable_id": item.evidence_id,
            "uri": evidence_uri,
            "project_id": "orchestra",
            "source_path": source_request["path"],
            "source_sha256": source_request["content_sha256"],
        })
    state_path = next((canonical / "tasks/projects/orchestra/tasks").glob("*/state.json"))
    state = json.loads(state_path.read_text())
    state["evidence_refs"] = sorted(evidence_refs)
    state_path.write_text(json.dumps(state))
    archive = canonical / "knowledge/archive-index.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps({
        "index_version": 1,
        "evidence_refs": sorted(archive_entries, key=lambda item: item["stable_id"]),
    }))

    assert script.main(arguments) == 0
    second = capsys.readouterr().out
    assert "ready_to_write=0 already_exists=10 preflight_rejected=0" in second
    assert [script.stable_fact_id(fact) for fact in facts] == [
        "f2b99462-315c-5c45-8679-a28b860538a9",
        "1631dcca-3097-58db-ae03-cbd82de12d20",
        "f4c9a22f-26a4-50a3-91cc-05b25b622415",
        "fcb9ccd1-51fc-5209-8613-768f74086ee5",
        "929a5ea8-c233-5210-aefa-a551b955d5a7",
        "d107a513-d066-5c8b-bd65-aaf752bc6313",
        "f8e2bb1c-bf28-57e1-ab08-d060218c0f96",
        "13b2a17e-fe7a-5c2a-ab40-30831b392838",
        "c6d9fd51-89b3-52ce-823b-70551b4cdcc5",
        "b8031726-286b-5b0b-8d3a-758874daab7d",
    ]
    archive_payload = json.loads(archive.read_text())
    archive_payload["index_version"] = 2
    archive.write_text(json.dumps(archive_payload))
    assert script.main(arguments) == 2
    wrong_version = capsys.readouterr().out
    assert "rejected_reason[existing_canonical_conflict]=10" in wrong_version
    archive.write_text("not-json")
    assert script.main(arguments) == 2
    malformed = capsys.readouterr().out
    assert "rejected_reason[existing_canonical_conflict]=10" in malformed


def test_preflight_rejects_invalid_import_path_duplicate_id_and_corrupt_task(tmp_path):
    repo, facts_dir, canonical, facts = _fixture(tmp_path)
    task_path = next((canonical / "tasks/projects/orchestra/tasks").glob("*/state.json"))

    bad_resource = canonical / "evidence/orchestra/bad-resource.json"
    bad_resource.write_text(json.dumps({
        "record_type": "resource",
        "project_id": "orchestra",
        "source_path": "docs/kb/source.md",
        "source_sha256": f"sha256:{hashlib.sha256((repo / 'docs/kb/source.md').read_bytes()).hexdigest()}",
        "git_commit": "1" * 40,
    }))
    ready, rejected = script.preflight(
        script.load_facts(facts_dir), repo_root=repo, canonical_root=canonical,
        project="orchestra", task_map={1: 399},
    )
    assert not ready
    assert all("resource_identity_invalid" in reasons for reasons in rejected.values())
    bad_resource.unlink()

    task = json.loads(task_path.read_text())
    task["uri"] = "orch://project/orchestra/tasks/00000000-0000-4000-8000-000000000000"
    task_path.write_text(json.dumps(task))
    ready, rejected = script.preflight(
        script.load_facts(facts_dir), repo_root=repo, canonical_root=canonical,
        project="orchestra", task_map={1: 399},
    )
    assert not ready
    assert all("canonical_task_record_invalid" in reasons for reasons in rejected.values())

    task["uri"] = f"orch://project/orchestra/tasks/{task['stable_id']}/state"
    task_path.write_text(json.dumps(task))
    duplicate = copy.deepcopy(facts[0])
    duplicate["topic"] = "другая тема"
    duplicate["evidence"] = "Conflicting evidence."
    (facts_dir / "part-1.json").write_text(
        json.dumps([*facts, duplicate], ensure_ascii=False), encoding="utf-8"
    )
    ready, rejected = script.preflight(
        script.load_facts(facts_dir), repo_root=repo, canonical_root=canonical,
        project="orchestra", task_map={1: 399},
    )
    assert len(ready) == 9
    assert sum("duplicate_stable_id" in reasons for reasons in rejected.values()) == 2

    invalid = copy.deepcopy(facts)
    invalid[0]["source_file"] = "README.md"
    (repo / "README.md").write_text("Measured source evidence.\n")
    resource_path = canonical / "evidence/orchestra/root-resource.json"
    resource_path.write_text(json.dumps({
        "record_type": "resource",
        "stable_id": "8c3e54c0-3a53-5824-95b1-db920d4c6812",
        "uri": "orch://project/orchestra/resources/8c3e54c0-3a53-5824-95b1-db920d4c6812",
        "project_id": "orchestra",
        "source_path": "README.md",
        "source_sha256": f"sha256:{hashlib.sha256((repo / 'README.md').read_bytes()).hexdigest()}",
        "git_commit": "1" * 40,
    }))
    (facts_dir / "part-1.json").write_text(
        json.dumps(invalid, ensure_ascii=False), encoding="utf-8"
    )
    _, rejected = script.preflight(
        script.load_facts(facts_dir), repo_root=repo, canonical_root=canonical,
        project="orchestra", task_map={1: 399},
    )
    assert any(
        reason.startswith("invalid_fact_payload:PromotionValidationError:")
        for reason in next(
            reasons for identity, reasons in rejected.items() if identity.startswith("part-1:1:")
        )
    )


def test_apply_exit_gate_requires_every_ready_fact_to_be_canonical(
    capsys, monkeypatch, tmp_path
):
    repo, facts_dir, canonical, _ = _fixture(tmp_path)

    class FakeKnowledgeClient:
        def __init__(self, **_kwargs):
            self.fact = None

        def call(self, operation, *, detail, payload):
            if operation == "import_evidence":
                return {"outcome": "created"}
            if operation == "promote":
                self.fact = payload["request"]["fact"]
                return {"outcome": "created"}
            assert operation == "query" and detail == "record"
            return {"items": [self.fact]}

    monkeypatch.setattr(script, "KnowledgeClient", FakeKnowledgeClient)
    result = script.main([
        "--apply",
        "--limit", "1",
        "--facts-dir", str(facts_dir),
        "--source-root", str(repo),
        "--canonical-root", str(canonical),
    ])

    assert result == 1
    output = capsys.readouterr().out
    assert "failed=0" in output
    assert "canonical_batch_facts=0" in output
    assert "canonical_batch_complete=0" in output
