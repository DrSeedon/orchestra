"""Turn a hub thread's activity timeline into the stream events native backends emit (V-1008).

The hub exposes a paginated, position-ordered list of timeline items (`t3_thread_read`,
view=activity). Items are re-read while they are still running, so the translator keeps one
state per item and emits each event exactly once, in position order: the chat UI, logs and SSE
then render a hub worker with no special casing.
"""

from __future__ import annotations

import json
from typing import Any

from app.events import AgentEvent

DONE = {"completed", "failed", "cancelled", "declined", "interrupted", "rolled_back"}
FAILED = {"failed", "cancelled", "declined", "interrupted", "rolled_back"}
RESULT_LIMIT = 4000
_NOISE_TITLES = {"Workspace ready"}


def _meta(name: str, item_id: str, **extra: Any) -> dict:
    return {"tool_name": name, "short_name": name, "tool_use_id": item_id, **extra}


class HubActivityStream:
    def __init__(self, run_id: str, cursor: int | None = None):
        self.run_id = run_id
        self.cursor = cursor            # afterPosition for the next read; None = from the start
        self._stage: dict[str, int] = {}   # item id -> 1 tool_use emitted, 2 finished
        self._open: dict[str, int] = {}    # item id -> position of an item still running
        self._held: str | None = None      # latest assistant text, not yet known to be the last
        self._max_pos = cursor if cursor is not None else -1

    def feed(self, items: list[dict]) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for item in sorted((it for it in items if it.get("itemId")), key=lambda it: it.get("position", 0)):
            position = int(item.get("position", 0))
            self._max_pos = max(self._max_pos, position)
            if item.get("runId") == self.run_id:
                events.extend(self._item(item))
                finished = item.get("status") in DONE
                if finished:
                    self._open.pop(item["itemId"], None)
                else:
                    self._open[item["itemId"]] = position
        # items still running must be re-read, so the cursor stops just before the oldest one
        floor = min(self._open.values()) - 1 if self._open else self._max_pos
        self.cursor = floor if floor >= 0 else None
        return events

    def finish(self, final_reply: str) -> list[AgentEvent]:
        """Close what the run left open; the final assistant text is returned by the caller."""
        events: list[AgentEvent] = []
        if self._held is not None and self._held.strip() != final_reply.strip():
            events.append(AgentEvent("text", self._held))
        self._held = None
        for item_id, stage in self._stage.items():
            if stage == 1:
                events.append(AgentEvent("tool_result", "(not finished)",
                                         metadata=_meta("hub", item_id, is_error=True)))
                self._stage[item_id] = 2
        return events

    def _flush(self) -> list[AgentEvent]:
        if self._held is None:
            return []
        text, self._held = self._held, None
        return [AgentEvent("text", text)]

    def _item(self, item: dict) -> list[AgentEvent]:
        kind, item_id = item.get("type"), item["itemId"]
        text = item.get("text") or ""
        done = item.get("status") in DONE
        failed = item.get("status") in FAILED
        stage = self._stage.get(item_id, 0)
        if kind == "assistant_message":
            if done and stage == 0 and text.strip():
                self._stage[item_id] = 2
                events = self._flush()
                self._held = text
                return events
            return []
        if kind and ("reason" in kind or "think" in kind):
            if done and stage == 0 and text.strip():
                self._stage[item_id] = 2
                return [AgentEvent("thinking", text)]
            return []
        if kind == "command_execution":
            if item.get("title") in _NOISE_TITLES:
                return []
            head, _, output = text.partition("\n")
            return self._tool(item_id, stage, done, failed, "Bash",
                              head.removeprefix("$ ").strip(), output)
        if kind == "file_change":
            lines = text.split("\n", 1)
            path = lines[0].strip()
            hunk = item.get("diff") or (lines[1].strip() if len(lines) > 1 else "")
            fc_output = str(hunk) if hunk else "изменён файл"
            events = self._tool(item_id, stage, done, failed, "Edit", path, fc_output, raw_input={"file_path": path})
            if done and not failed and stage < 2:
                events.insert(len(events) - 1, AgentEvent("file_change", f"update {path}"))
            return events
        if kind == "dynamic_tool":
            try:
                data = json.loads(text)
            except ValueError:
                data = {}
            name = str(data.get("toolName") or item.get("title") or "tool")
            raw_in = data.get("input") if isinstance(data.get("input"), dict) else None
            args = json.dumps(data.get("input"), ensure_ascii=False) if data.get("input") else ""
            out = data.get("output")
            output = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False) if out else ""
            return self._tool(item_id, stage, done, failed, name, args, output, raw_input=raw_in)
        return []

    def _safe_summary(self, summary: str, limit: int = 300) -> tuple[str, int | None]:
        src_len = len(summary.encode())
        if len(summary) <= limit:
            return summary, None
        try:
            obj = json.loads(summary)
        except ValueError:
            return summary[:limit], src_len
        if isinstance(obj, dict):
            projected = {}
            for k, v in obj.items():
                if isinstance(v, str) and len(v) > 80:
                    projected[k] = v[:80] + "…"
                else:
                    projected[k] = v
            encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) <= limit:
                return encoded, src_len
            return json.dumps({k: ("…" if isinstance(v, str) else v) for k, v in list(projected.items())[:4]}, ensure_ascii=False)[:limit], src_len
        return summary[:limit], src_len

    def _tool(self, item_id: str, stage: int, done: bool, failed: bool, name: str,
              summary: str, output: str, *, raw_input: dict | None = None) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        bounded_summary, src_bytes = self._safe_summary(summary, 300)
        call_meta = _meta(name, item_id)
        if raw_input is not None:
            call_meta["raw_input"] = raw_input
        if src_bytes is not None:
            call_meta["source_bytes"] = src_bytes
        if stage == 0:
            events.extend(self._flush())
            events.append(AgentEvent("tool_use", f"{name}: {bounded_summary}", metadata=call_meta))
            self._stage[item_id] = stage = 1
        elif not done and raw_input is not None:
            events.append(AgentEvent("tool_update", f"{name}: {bounded_summary}", metadata=call_meta))
        if done and stage == 1:
            if failed and (not output.strip() or output.strip() == "applied"):
                output = f"{name} completion failed; no successful result"
            res_text = output or "(no output)"
            res_meta = _meta(name, item_id, is_error=failed)
            if len(res_text) > RESULT_LIMIT:
                res_meta["trunc"] = len(res_text.encode())
                res_text = res_text[:RESULT_LIMIT]
            events.append(AgentEvent("tool_result", res_text, metadata=res_meta))
            self._stage[item_id] = 2
        return events
