# Agent Effort Routing Specification

## Purpose

Define how Orchestra selects reasoning effort per model and safely applies manifest changes to existing agent sessions.

## Requirements

### Requirement: Role effort supports scalar and model-aware forms

The system SHALL accept a role effort as either a scalar level or a mapping keyed by exact model id, runtime name, and optional `default`.

#### Scenario: Existing scalar configuration

- **WHEN** a role uses a scalar effort
- **THEN** the system applies that scalar unchanged

#### Scenario: Model-aware resolution

- **WHEN** a mapping contains an exact model key, a runtime key, and `default`
- **THEN** the system selects exact model, then runtime, then `default`, and otherwise returns no configured value

#### Scenario: Runtime name is also a model alias

- **WHEN** a key such as `codex` or `grok` names both a runtime and a model alias
- **THEN** the system treats that key as the runtime and requires the canonical model id for an exact-model override

### Requirement: Invalid configuration fails according to what is knowable

The system MUST reject an unknown effort level and MUST preserve an unknown model key with an observable warning.

#### Scenario: Misspelled effort level

- **WHEN** a manifest contains an effort level outside the closed supported set
- **THEN** manifest loading fails and no live session changes effort or disconnects

#### Scenario: Model registry is populated later

- **WHEN** a mapping key is not present in the model registry at initial load
- **THEN** the key remains available to match if that model appears later and a warning is emitted

### Requirement: Live sessions reconcile only at a turn boundary

The system SHALL read the current manifest before starting a new turn and apply a changed effort without interrupting an active turn.

#### Scenario: Session is currently running

- **WHEN** a message is injected into an active turn after the manifest changes
- **THEN** the active turn continues on its existing effort and reconciliation waits for the next turn

#### Scenario: Next turn observes a changed effort

- **WHEN** an idle session starts its next turn and the manifest resolves to a different effort
- **THEN** the old backend is disconnected before the new effort is persisted, the backend is rebuilt with the new effort, and the native session id and conversation context are preserved

#### Scenario: No valid replacement exists

- **WHEN** the manifest is unreadable, the role is missing, no mapping entry resolves, or the session has no role or pipeline
- **THEN** the current effort and backend remain unchanged

### Requirement: Manifest reads do not apply a torn snapshot

The system MUST discard and retry a manifest read when file metadata changes during the read.

#### Scenario: Manifest changes between read and stat

- **WHEN** the manifest's modification time or size changes while it is being read
- **THEN** the parsed snapshot is discarded rather than cached or applied to a live session

