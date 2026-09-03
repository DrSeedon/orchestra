## 1. Model-aware configuration

- [x] 1.1 Add scalar-or-mapping effort schema and deterministic exact-model/runtime/default resolution
- [x] 1.2 Preserve scalar compatibility, runtime-name precedence over aliases, unknown model keys with warning, and fail-closed unknown levels
- [x] 1.3 Apply the Opus-high, Sol-xhigh, Luna-high, default-high map to all four roles

## 2. Live-session reconciliation

- [x] 2.1 Re-read and resolve manifest effort at the next-turn boundary without interrupting a running turn
- [x] 2.2 Disconnect before persisting a changed effort, rebuild the backend, and preserve native session id and context
- [x] 2.3 Leave unchanged, invalid, and legacy sessions untouched when no valid replacement resolves

## 3. Stable manifest reads

- [x] 3.1 Key the cache by path, modification time, and size; re-stat and retry an unstable read
- [x] 3.2 Fail manifest loading on an unknown effort level while keeping current live sessions connected

## 4. Verification

- [x] 4.1 Cover mapping precedence, scalar compatibility, dynamic model registration, and runtime/model alias collisions
- [x] 4.2 Cover next-turn application, mid-turn non-interruption, unchanged and legacy sessions, disconnect failure, and torn-read retry
- [x] 4.3 Run focused pipeline, manager, default-pipeline, and session tests plus targeted mutations

