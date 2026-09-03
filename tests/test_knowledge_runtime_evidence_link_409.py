from app.ia.runtime import _RuntimeTaskStore


class _Store:
    canonical_head = "task-head-before"

    def __init__(self):
        self.call = None

    def link_evidence_to_task(
        self, task_ref, evidence, *, project_id, expected_head=None
    ):
        self.call = (task_ref, evidence, project_id, expected_head)
        return {"canonical_head": "task-head-after", "added": 1}


def test_runtime_task_store_wires_imported_evidence_link_to_live_owner():
    store = _Store()
    written_heads = []
    runtime = _RuntimeTaskStore(
        store=store,
        legacy_to_canonical={"legacy-orchestra": "orchestra"},
        debt_writer=lambda _debt: None,
        head_writer=written_heads.append,
    )
    evidence = {
        "stable_id": "3b000000-0000-4000-8000-000000000409",
        "task_id": "8b01850f-d6f2-504e-9c1d-390d9e55b5c5",
        "canonical_path": ".orchestra/kb/repo-ops.md",
        "anchor": "1-1",
        "git_commit": "1" * 40,
        "content_sha256": "sha256:" + "1" * 64,
    }

    result = runtime.link_evidence_to_task(
        evidence["task_id"], evidence, project_id="legacy-orchestra"
    )

    assert result["added"] == 1
    assert store.call == (
        evidence["task_id"],
        evidence,
        "orchestra",
        "task-head-before",
    )
    assert written_heads == ["task-head-after"]
