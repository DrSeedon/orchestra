# #307 upstream publication draft

## Triage decision

Post a comment on openai/codex [#21988](https://github.com/openai/codex/issues/21988), not a new
issue. Our failure is the same app-server response family: one stored thread with seven generated
images becomes a single multi-megabyte turns/resume frame. [#39148](https://github.com/openai/codex/issues/39148)
is corroborating evidence on a different `read_thread` surface. Do not publish without a separate
user command.

Do not propose a pull request. OpenAI's [contribution policy](https://github.com/openai/codex/blob/main/docs/contributing.md)
does not accept external code contributions/PRs and asks contributors to add sanitized reproduction
evidence to an existing issue when one matches.

## Publication-ready comment for #21988

### Linux/stdin-stdout reproduction: default `thread/resume` emits a 23 MB JSONL record

I reproduced the same generated-image frame amplification through the app-server's stdio transport,
where it becomes a connection/recovery failure rather than only a RAM/traffic problem.

Environment:

- `codex-cli 0.149.0`
- Linux `7.0.0-30-generic` x86_64
- `codex app-server --stdio` (newline-delimited JSON-RPC)
- ChatGPT-auth production thread, replayed from a disposable clone without `auth.json`

The stored thread had exactly seven completed `image_generation_end` records. Their serialized
rollout records totaled 22,612,401 bytes; the corresponding paired large tool-output records totaled
22,608,258 bytes. No prompt, path, image bytes, or raw history was retained in the measurement.

Request sequence:

1. `initialize`, request `id=1`
2. `initialized`
3. `thread/resume`, request `id=2`, default parameters (`excludeTurns` absent)

Measured stdout records:

| Record | Bytes |
|---|---:|
| initialize response (`id=1`) | 214 |
| `configWarning` | 500 |
| `remoteControl/status/changed` | 207 |
| `thread/status/changed` | 149 |
| **thread/resume response (`id=2`)** | **23,159,303** |

The oversized record is a response envelope (`id=2`, no `method`), not an item/turn notification.
A client with a bounded 16 MiB line reader cannot parse the envelope or resolve the pending resume
request. Discarding the record is not recovery because this is the only required response.

The existing experimental API is an effective control. With
`initialize.capabilities.experimentalApi=true` and `thread/resume(excludeTurns=true)`, the exact same
thread returned a 5,104-byte `id=2` response (99.978% smaller). It retained the matching thread id,
`status={"type":"idle"}`, preview and runtime/config metadata, and returned `turns=[]`. Without the
initialize capability, 0.149.0 correctly returned `-32600`:
`thread/resume.excludeTurns requires experimentalApi capability`.

This is consistent with the current source comment that `thread/resume` can include large MCP and
image-generation payloads, while response redaction is limited to the two ChatGPT mobile remote
client names:
https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_resume_redaction.rs

Expected behavior:

- Default resume/read responses should not inline unbounded generated-image bytes into one transport
  frame.
- Large binary results should be omitted, externalized, or referenced by saved path/content id.
- The bounded metadata-only resume contract should remain available without reconstructing full turn
  payloads, and clients should be able to negotiate it deterministically.

Related current report: #39148 shows `read_thread` returning multi-megabyte `imageGeneration.result`
despite `includeOutputs:false` and `maxOutputCharsPerItem`.

We mitigated the client side by negotiating `experimentalApi`, using `excludeTurns:true` for stored
native resumes, and treating any lost oversized JSONL record as terminal transport corruption rather
than continuing with unresolved request correlation
([metadata-only resume and typed failure](https://github.com/DrSeedon/orchestra/commit/b11ba9be1a7c54e936be00ebecbc69ca50fcff4f)).
This avoids the crash, but it does not remove the upstream unbounded default response.

### Minimal response-size scanner

Run only against a disposable `CODEX_HOME` containing an image-heavy test thread. It does not start a
model turn and never retains the response payload; it reports envelope id/method and byte length.

```python
import asyncio
import json
import os
import re
import sys


async def main() -> None:
    thread_id = sys.argv[1]
    exclude_turns = "--exclude-turns" in sys.argv[2:]
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server", "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=os.environ.copy(),
    )

    async def send(payload: dict) -> None:
        proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await proc.stdin.drain()

    buffered = b""

    async def next_record() -> tuple[int | None, str | None, int]:
        nonlocal buffered
        size = 0
        prefix = bytearray()
        while True:
            if b"\n" in buffered:
                part, buffered = buffered.split(b"\n", 1)
                size += len(part) + 1
                prefix.extend(part[: max(0, 1024 - len(prefix))])
                text = prefix.decode("utf-8", "replace")
                rid = re.search(r'"id"\s*:\s*(\d+)', text)
                method = re.search(r'"method"\s*:\s*"([^"]+)"', text)
                return (
                    int(rid.group(1)) if rid else None,
                    method.group(1) if method else None,
                    size,
                )
            if buffered:
                size += len(buffered)
                prefix.extend(buffered[: max(0, 1024 - len(prefix))])
                buffered = b""
            buffered = await proc.stdout.read(65536)
            if not buffered:
                raise EOFError("app-server closed stdout")

    capabilities = {"experimentalApi": True} if exclude_turns else {}
    await send({
        "method": "initialize",
        "id": 1,
        "params": {
            "clientInfo": {"name": "resume-size-probe", "title": "probe", "version": "1"},
            "capabilities": capabilities,
        },
    })
    while (await next_record())[0] != 1:
        pass
    await send({"method": "initialized", "params": {}})
    params = {"threadId": thread_id}
    if exclude_turns:
        params["excludeTurns"] = True
    await send({"method": "thread/resume", "id": 2, "params": params})
    while True:
        record_id, method, size = await next_record()
        if record_id == 2:
            print({"id": record_id, "method": method, "bytes": size})
            break
    proc.terminate()
    await proc.wait()


asyncio.run(main())
```

Expected on the measured test thread:

```text
$ CODEX_HOME=/path/to/disposable-copy python resume_size.py THREAD_ID
{'id': 2, 'method': None, 'bytes': 23159303}
$ CODEX_HOME=/path/to/disposable-copy python resume_size.py THREAD_ID --exclude-turns
{'id': 2, 'method': None, 'bytes': 5104}
```

## Publication state

Not published. A separate explicit user command is required before posting this comment.
