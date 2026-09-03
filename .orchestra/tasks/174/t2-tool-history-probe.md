# #174 T2 isolated Codex tool-history acceptance

Дата: 2026-08-11. Бинарник: `codex-cli 0.146.0`. Seam:
`thread/resume.history`, capability: `experimentalApi=true`.

Процесс запущен ровно так, без копии credentials и без model turn:

```bash
CODEX_HOME=/tmp/r174-t2-raw.Mt6765/codex-home \
  codex app-server --stdio --disable apps
```

## Literal JSON-RPC

Initialize request/response:

```json
{"method":"initialize","id":1,"params":{"clientInfo":{"name":"r174-t2-raw-proof","version":"1"},"capabilities":{"experimentalApi":true}}}
{"id":1,"result":{"userAgent":"r174-t2-raw-proof/0.146.0 (Ubuntu 24.4.0; x86_64) dumb (r174-t2-raw-proof; 1)","codexHome":"/tmp/r174-t2-raw.Mt6765/codex-home","platformFamily":"unix","platformOs":"linux"}}
```

Exact `thread/resume.history` request:

```json
{"method":"thread/resume","id":2,"params":{"threadId":"17417417-4174-4174-8174-174174174174","history":[{"type":"message","role":"user","content":[{"type":"input_text","text":"R174_T2_TOOL_RAW_20260811 user fact"}]},{"type":"custom_tool_call","name":"OrchestraHistory","input":"{\"recorded_call\":\"read probe\",\"source_tool_name\":\"Read\",\"source_log_id\":2,\"already_executed\":true,\"synthetic\":false}","call_id":"orchestra_probe_call_001"},{"type":"custom_tool_call_output","call_id":"orchestra_probe_call_001","output":"[Orchestra historical tool result; source_log_id=3; is_error=false]\\nR174_T2_TOOL_RESULT_RAW_20260811"},{"type":"message","role":"assistant","content":[{"type":"output_text","text":"R174_T2_TOOL_RAW_20260811 assistant fact"}]}],"cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access","developerInstructions":"These OrchestraHistory records already ran; never repeat their side effects without a new explicit user request."}}
```

Exact response:

```json
{"id":2,"result":{"thread":{"id":"019ff08f-2a44-7152-a676-792d6f5a7f4b","extra":null,"sessionId":"019ff08f-2a44-7152-a676-792d6f5a7f4b","forkedFromId":null,"parentThreadId":null,"preview":"R174_T2_TOOL_RAW_20260811 user fact","ephemeral":false,"isPinned":false,"historyMode":"legacy","modelProvider":"openai","createdAt":1786447342,"updatedAt":1786447342,"recencyAt":1786447342,"status":{"type":"idle"},"path":"/tmp/r174-t2-raw.Mt6765/codex-home/sessions/2026/08/11/rollout-2026-08-11T13-22-22-019ff08f-2a44-7152-a676-792d6f5a7f4b.jsonl","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch","cliVersion":"0.146.0","source":"vscode","canAcceptDirectInput":true,"threadSource":null,"agentNickname":null,"agentRole":null,"gitInfo":null,"name":null,"turns":[]},"model":"gpt-5.6-sol","modelProvider":"openai","serviceTier":null,"cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch","runtimeWorkspaceRoots":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch"],"instructionSources":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/AGENTS.md"],"approvalPolicy":"never","approvalsReviewer":"user","sandbox":{"type":"dangerFullAccess"},"activePermissionProfile":null,"reasoningEffort":null,"multiAgentMode":"explicitRequestOnly","initialTurnsPage":null,"turnsBackwardsCursor":null,"itemsBackwardsCursor":null}}
```

Request seed `1741…` был заменён свежим ID
`019ff08f-2a44-7152-a676-792d6f5a7f4b`.

## Returned ID → persisted rollout

После ответа выполнена эта отдельная проверка:

```bash
returned_id=019ff08f-2a44-7152-a676-792d6f5a7f4b
rollout_path=/tmp/r174-t2-raw.Mt6765/codex-home/sessions/2026/08/11/rollout-2026-08-11T13-22-22-019ff08f-2a44-7152-a676-792d6f5a7f4b.jsonl
test -f "$rollout_path"
case "$(basename "$rollout_path")" in *"$returned_id"*) echo true;; *) echo false;; esac
sha256sum "$rollout_path"
# Затем каждая JSONL-строка разобрана через json.loads; выбраны type=response_item.
```

Literal output:

```text
test_file_exit=0
basename_contains_returned_id=true
a6dad68b294f617d77071ec855c4d9be161bad4a71ecb1fdd87c8945c68fdefd  /tmp/r174-t2-raw.Mt6765/codex-home/sessions/2026/08/11/rollout-2026-08-11T13-22-22-019ff08f-2a44-7152-a676-792d6f5a7f4b.jsonl
types=['message', 'custom_tool_call', 'custom_tool_call_output', 'message']
call_ids=['orchestra_probe_call_001', 'orchestra_probe_call_001']
marker_rows=1
```

Persisted `response_item` payloads, дословно:

```json
[{"type":"message","id":"msg_019ff08f-2a44-7152-a676-78e2fde56228","role":"user","content":[{"type":"input_text","text":"R174_T2_TOOL_RAW_20260811 user fact"}]},{"type":"custom_tool_call","id":"ctc_019ff08f-2a44-7152-a676-78fdbe617e0e","call_id":"orchestra_probe_call_001","name":"OrchestraHistory","input":"{\"recorded_call\":\"read probe\",\"source_tool_name\":\"Read\",\"source_log_id\":2,\"already_executed\":true,\"synthetic\":false}"},{"type":"custom_tool_call_output","id":"ctco_019ff08f-2a44-7152-a676-790b148e4419","call_id":"orchestra_probe_call_001","output":"[Orchestra historical tool result; source_log_id=3; is_error=false]\\nR174_T2_TOOL_RESULT_RAW_20260811"},{"type":"message","id":"msg_019ff08f-2a44-7152-a676-79155d9473e0","role":"assistant","content":[{"type":"output_text","text":"R174_T2_TOOL_RAW_20260811 assistant fact"}]}]
```

Итого: app-server принял четыре item; response вернул свежий ID; путь в том же response
содержит этот ID; файл существует; его hash зафиксирован; в этом файле лежит ровно цепочка
`message → custom_tool_call → custom_tool_call_output → message`, одинаковый `call_id` и marker
результата. Это acceptance/persistence proof, не semantic model recall — recall остаётся AC T3.

После фиксации evidence весь `/tmp/r174-t2-raw.Mt6765` перемещён через `trash`. Live Codex
home, sessions и Orchestra service не открывались и не менялись.

## Error envelope: структурного schema discriminator нет

Отдельный app-server в disposable `/tmp/r174-t2-envelope.52zhzi/codex-home` получил
`experimentalApi=true`, затем literal `thread/resume` с `history:"not-an-array"`. Одна shell
команда запустила процесс, отправила оба JSON-RPC request, разобрала error object через
`json.loads`, напечатала его keys и переместила temp root через `trash`.

Дословный ответ и derived fields:

```text
RAW_RESPONSE {"error":{"code":-32600,"message":"Invalid request: invalid type: string \"not-an-array\", expected a sequence"},"id":2}
ERROR_KEYS ["code", "message"]
ERROR_CODE -32600
DATA_PRESENT False
PARAMETER_FIELD_PRESENT False
PROBE_ROOT /tmp/r174-t2-envelope.52zhzi
probe_root_absent=0
```

В response нет `data` и нет отдельного parameter/field/path; `-32600` сам по себе означает
generic invalid request, а prose не привязывает ошибку к `history`. Поэтому ни code, ни data не
дают положительного schema-признака. T2 не делает автоматический summary fallback ни для этого
ответа, ни для capability/schema-looking prose: любой JSON-RPC error импортного resume выходит
исходным `CodexProtocolError`. Exact CLI version preflight остаётся отдельным структурным
tripwire до запуска app-server.
