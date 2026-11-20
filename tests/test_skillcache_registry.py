from copy import deepcopy

import pytest

from app import db
from app.skillcache.abi import Rejected, check_manifest
from app.skillcache.fixtures import SyntheticSources, cases
from app.skillcache.pilots import MANIFESTS, catalog
from app.skillcache.qualifier import qualify
from app.skillcache.registry import PrivateStore, Registry, SkillSource
from app.skillcache.runner import Access, Runner


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "offline.sqlite"
    db.init_db(path)
    db.init_db(path)
    skill = tmp_path / "SKILL.md"
    skill.write_text("fixture")
    script = tmp_path / "dependency.py"
    script.write_text("# fixture")
    schemas = {"tools": {"inputSchema": {"type": "object"}, "outputSchema": {"type": "string"}}}
    abi = catalog({("test", name): SkillSource(skill, (script,)) for name in MANIFESTS},
                  {("test", name): schemas for name in MANIFESTS})
    return Registry(lambda: db._conn(path), abi), PrivateStore(tmp_path / "private"), skill, script, schemas


def start(manifest, bindings, request_id="start"):
    return {"action": "run", "skill": manifest["skill"], "intent": manifest["intent"],
            "request_id": request_id, "bindings": bindings}


def resume(report, bindings, request_id="continue"):
    return {"action": "continue", "run_id": report["run_id"], "revision": report["revision"],
            "request_id": request_id, "bindings": bindings}


def _runner(setup, name, *, source_factory=SyntheticSources, invocation="turn-one", grant_revision="v1"):
    registry, store, *_ = setup
    probe = cases(name)[0]
    return Runner(registry, store, b"a" * 32, lambda: Access(
        "test", "session", invocation, frozenset({name}), {name: probe["workspace"]},
        source_factory(probe), grant_revision=grant_revision,
    ))


@pytest.mark.parametrize("name", MANIFESTS)
def test_pilot_qualification_and_execution(setup, name):
    registry, *_ = setup
    manifest = MANIFESTS[name]
    version = qualify(registry, "test", manifest)
    with registry.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert dict(conn.execute(
            "SELECT case_id, ok FROM sc_qualification WHERE digest=?", (version,),
        ).fetchall()) == {"baseline": 1, "counterexample": 1, "reject_stale": 1}
    case = cases(name)[0]
    runner = _runner(setup, name)
    request = start(manifest, case["bindings"])
    report = runner.handle(request)
    assert runner.handle(request) == report
    if name == "kesha-mail":
        assert report["status"] == "your_steps"
        assert report["steps"][0]["in"]["evidence"]["value"][0]["preview"] == "Synthetic content"
        followup = resume(report, case["answer"])
        report = runner.handle(followup)
        assert runner.handle(followup) == report
        assert runner.handle({**followup, "bindings": {"prioritize": {"digest": []}}}) == {"status": "conflict"}
        assert runner.handle(request)["status"] == "your_steps"
    assert report["status"] == "complete"
    if name == "direct-reports":
        report["result"]["totals"].pop("checksum")
    assert report["result"] == case["expected"]


@pytest.mark.parametrize("dependency", ("skill", "script", "schema"))
def test_dependency_edit_invalidates_lookup_and_continue(setup, dependency):
    registry, _, skill, script, schemas = setup
    name = "kesha-mail"
    manifest = MANIFESTS[name]
    version = qualify(registry, "test", manifest)
    runner = _runner(setup, name)
    report = runner.handle(start(manifest, {}))
    assert report["status"] == "needs_bindings"
    if dependency == "skill":
        skill.write_text("changed")
    elif dependency == "script":
        script.write_text("# changed")
    else:
        schemas["tools"]["outputSchema"] = {"type": "integer"}
    assert runner.handle(resume(report, cases(name)[0]["bindings"])) == {"status": "stale"}
    assert registry.lookup("test", name, manifest["intent"]) is None
    with registry.connect() as conn:
        assert conn.execute("SELECT status FROM sc_capsule WHERE digest=?", (version,)).fetchone()[0] == "stale"


def test_literal_and_manifest_secret_rejection(setup):
    registry, *_ = setup
    manifest = deepcopy(MANIFESTS["kesha-mail"])
    manifest["bindings"]["window"]["value"] = {"start": "2025-01-01", "end": "2025-01-01"}
    with pytest.raises(Rejected):
        check_manifest(manifest, registry.catalog)
    manifest = deepcopy(MANIFESTS["kesha-mail"])
    manifest["steps"][0]["in"]["window"] = "2025-01-01"
    with pytest.raises(Rejected):
        check_manifest(manifest, registry.catalog)
    manifest = deepcopy(MANIFESTS["kesha-mail"])
    manifest["steps"][2]["instruction"] = "Check private-user@example.com"
    with pytest.raises(Rejected, match="publication scan"):
        qualify(registry, "test", manifest)
    manifest["steps"][2]["instruction"] = "Use an invented mailbox name"
    with pytest.raises(Rejected, match="no reviewed qualification suite"):
        qualify(registry, "test", manifest)


def test_step_level_deopt_never_skips_postconditions(setup):
    registry, *_ = setup
    name = "kesha-mail"
    manifest = MANIFESTS[name]
    qualify(registry, "test", manifest)
    fixture = cases(name)[0]

    class Broken(SyntheticSources):
        def mail(self, window, accounts):
            raise OSError("synthetic private error")

    runner = _runner(setup, name, source_factory=Broken)
    failure = runner.handle(start(manifest, fixture["bindings"]))
    assert failure["status"] == "program_failed"
    assert failure["step"] == "collect"
    assert "synthetic private error" not in str(failure)
    report = runner.handle(resume(failure, {"collect": {"batch": fixture["read"]}}, "recover"))
    assert report["status"] == "your_steps"
    failed_verification = runner.handle(resume(report, fixture["answer"]))
    assert failed_verification["status"] == "verification_failed"


def test_run_is_bound_to_turn_and_grant(setup):
    registry, *_ = setup
    manifest = MANIFESTS["kesha-mail"]
    qualify(registry, "test", manifest)
    runner = _runner(setup, "kesha-mail")
    pending = runner.handle(start(manifest, {}))
    request = resume(pending, cases("kesha-mail")[0]["bindings"])
    assert _runner(setup, "kesha-mail", invocation="turn-two").handle(request) == {"status": "revoked"}
    assert _runner(setup, "kesha-mail", grant_revision="v2").handle(request) == {"status": "revoked"}
    assert runner.handle(request)["status"] == "your_steps"



def test_recover_one_failed_transform_and_finish(setup):
    from dataclasses import replace

    registry, *_ = setup
    name = "kesha-mail"
    manifest = MANIFESTS[name]
    qualify(registry, "test", manifest)
    case = cases(name)[0]
    key = "mail.normalize@1"

    def broken_transform(inputs, source):
        raise OSError("synthetic failure")

    ops = {**registry.catalog.operations, key: replace(registry.catalog.operations[key], execute=broken_transform)}
    registry.catalog = replace(registry.catalog, operations=ops)
    runner = _runner(setup, name)
    report = runner.handle(start(manifest, case["bindings"]))
    assert report["status"] == "program_failed" and report["step"] == "normalize"
    evidence = [{"id": "synthetic-a", "subject": "Synthetic subject", "preview": "Synthetic content"}]
    report = runner.handle(resume(report, {"normalize": {"evidence": evidence}}, "recover"))
    assert report["status"] == "your_steps"
    report = runner.handle(resume(report, case["answer"]))
    assert report["status"] == "complete" and report["result"] == case["expected"]
