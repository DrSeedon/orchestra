import json

from app.ia import knowledge
from tests.test_knowledge_import_linking_409 import _setup


def test_import_retry_repairs_record_written_before_archive_index(tmp_path):
    store, _, _, source, registry = _setup(tmp_path)
    root = tmp_path / "knowledge"
    with knowledge.knowledge_service_mode(
        canonical_root=root,
        registry_path=registry,
        task_store=store,
    ):
        first = knowledge.knowledge_api({
            "operation": "import_evidence",
            "detail": "record",
            "payload": {"source": source},
        })
        index_path = root / "archive-index.json"
        index = json.loads(index_path.read_text())
        index["evidence_refs"] = []
        index_path.write_text(json.dumps(index))

        repaired = knowledge.knowledge_api({
            "operation": "import_evidence",
            "detail": "record",
            "payload": {"source": source},
        })
        replayed = knowledge.knowledge_api({
            "operation": "import_evidence",
            "detail": "record",
            "payload": {"source": source},
        })

    assert first["outcome"] == "created"
    assert repaired["outcome"] == "created"
    assert replayed["outcome"] == "noop"
    assert json.loads(index_path.read_text())["evidence_refs"][0]["uri"] == source[
        "canonical_uri"
    ]
