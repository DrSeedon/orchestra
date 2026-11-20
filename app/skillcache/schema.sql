CREATE TABLE IF NOT EXISTS sc_capsule (
    scope TEXT NOT NULL, digest TEXT NOT NULL, skill TEXT NOT NULL, intent TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    deps_json TEXT NOT NULL CHECK(json_valid(deps_json)),
    status TEXT NOT NULL CHECK(status IN ('candidate','active','stale','revoked')),
    created_at INTEGER NOT NULL, PRIMARY KEY(scope,digest)
);
CREATE UNIQUE INDEX IF NOT EXISTS sc_active ON sc_capsule(scope,skill,intent) WHERE status='active';

CREATE TABLE IF NOT EXISTS sc_invocation (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, origin TEXT NOT NULL,
    session_ref TEXT NOT NULL, usage_ref TEXT, skill TEXT NOT NULL,
    eligible INTEGER NOT NULL DEFAULT 0 CHECK(eligible IN (0,1)),
    reason TEXT, UNIQUE(origin,session_ref,usage_ref)
);
CREATE TABLE IF NOT EXISTS sc_event (
    invocation_id TEXT NOT NULL REFERENCES sc_invocation(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, source_ref TEXT NOT NULL,
    PRIMARY KEY(invocation_id,seq), UNIQUE(invocation_id,source_ref)
);
CREATE TABLE IF NOT EXISTS sc_qualification (
    scope TEXT NOT NULL, digest TEXT NOT NULL, case_id TEXT NOT NULL, suite_digest TEXT NOT NULL,
    ok INTEGER NOT NULL CHECK(ok IN (0,1)), evidence_ref TEXT NOT NULL, checked_at INTEGER NOT NULL,
    PRIMARY KEY(scope,digest,suite_digest,case_id),
    FOREIGN KEY(scope,digest) REFERENCES sc_capsule(scope,digest)
);
CREATE TABLE IF NOT EXISTS sc_run (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, digest TEXT NOT NULL, principal TEXT NOT NULL,
    invocation_id TEXT NOT NULL REFERENCES sc_invocation(id), request_key TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL, private_state_ref TEXT, lease_until INTEGER, lease_token TEXT,
    expires_at INTEGER NOT NULL, UNIQUE(scope,principal,request_key),
    FOREIGN KEY(scope,digest) REFERENCES sc_capsule(scope,digest)
);
CREATE TABLE IF NOT EXISTS sc_receipt (
    run_id TEXT NOT NULL REFERENCES sc_run(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL, input_mac TEXT NOT NULL, report_ref TEXT NOT NULL,
    revision INTEGER NOT NULL, PRIMARY KEY(run_id,request_id)
);
