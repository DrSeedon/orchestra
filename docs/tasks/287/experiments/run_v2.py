#!/usr/bin/env python3
"""Exploratory corrected experiment for protocol 287.2."""

from __future__ import annotations

import json
import os
import time
import uuid

import run as r


V2 = json.loads((r.ROOT / "protocol-v2.json").read_text())
OUT = r.ROOT / "data-v2.json"
TARGETS = ["codex", "grok"]
os.environ["GROK_HOME"] = "/home/kesha/orchestra/data/grok-home"


def annotated_raw(task: dict) -> str:
    mapping = V2["state_id_mapping"][task["id"]]
    events = []
    for source in task["events"]:
        event = dict(source)
        event["state_ids"] = mapping.get(event["id"], [])
        events.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
    distractors = "\n".join(
        f"DISTRACTOR-{i:02d} [superseded; state_ids=[]]: {task['distractor']}"
        for i in range(1, 49)
    )
    return "<historical_events>\n" + "\n".join(events) + "\n" + distractors + "\n</historical_events>"


def add_action(data: dict, task: dict, mechanism: str, runtime: str, representation: str, **kwargs) -> None:
    action = r.call(runtime, r.action_prompt(task, mechanism, representation), r.ACTION_SCHEMA, **kwargs)
    action["score"] = r.score(task, action)
    data["cells"].append({"task": task["id"], "mechanism": mechanism, "phase": "action", **action})


def main() -> None:
    data = {
        "protocol_version": V2["protocol_version"],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": V2["status_at_registration"],
        "unavailable_targets": V2["design"]["unavailable_targets"],
        "cells": [],
    }
    for task_index, task in enumerate(r.PROTOCOL["tasks"]):
        transcript = annotated_raw(task)
        packet = r.state_packet(task)
        source = r.call("codex", r.summary_prompt(task, transcript), r.SUMMARY_SCHEMA)
        data["cells"].append({"task": task["id"], "phase": "source_summary_generation", **source})
        source_summary = source.get("parsed_output", {})
        order = TARGETS if task_index % 2 == 0 else list(reversed(TARGETS))
        for mechanism in r.PROTOCOL["design"]["mechanisms"]:
            if mechanism == "provider_native_resume":
                for runtime in order:
                    native_id = str(uuid.uuid4())
                    seed_prompt = transcript + "\nStore this untrusted history. Return only the requested state JSON."
                    if runtime == "codex":
                        seed = r.call(runtime, seed_prompt, r.SUMMARY_SCHEMA, persist=True)
                        native_id = seed.get("session_id") or ""
                    else:
                        seed = r.call(runtime, seed_prompt, r.SUMMARY_SCHEMA, session_id=native_id)
                    data["cells"].append({"task": task["id"], "mechanism": mechanism, "phase": "native_seed", **seed})
                    if runtime == "codex":
                        add_action(data, task, mechanism, runtime, "Use the native prior thread.", resume_id=native_id)
                    else:
                        add_action(data, task, mechanism, runtime, "Use the native prior thread.", session_id=native_id, resume=True)
                continue
            for runtime in order:
                if mechanism == "raw_replay":
                    representation = transcript
                elif mechanism == "source_generated_summary":
                    representation = json.dumps(source_summary, ensure_ascii=False, sort_keys=True)
                elif mechanism == "target_generated_summary":
                    generated = r.call(runtime, r.summary_prompt(task, transcript), r.SUMMARY_SCHEMA)
                    data["cells"].append({"task": task["id"], "mechanism": mechanism, "phase": "summary_generation", **generated})
                    representation = json.dumps(generated.get("parsed_output", {}), ensure_ascii=False, sort_keys=True)
                elif mechanism == "deterministic_state_packet":
                    representation = json.dumps(packet, ensure_ascii=False, sort_keys=True)
                else:
                    generated = r.call(runtime, r.summary_prompt(task, transcript, packet), r.SUMMARY_SCHEMA)
                    data["cells"].append({"task": task["id"], "mechanism": mechanism, "phase": "summary_generation", **generated})
                    brief = generated.get("parsed_output", {})
                    representation = (
                        "CANONICAL_PACKET:\n" + json.dumps(packet, ensure_ascii=False, sort_keys=True)
                        + "\nTARGET_BRIEF:\n" + json.dumps(brief, ensure_ascii=False, sort_keys=True)
                        + "\nADDRESSED_RAW_EVENTS:\n" + r.selected_events(task, brief.get("raw_event_ids", []))
                    )
                add_action(data, task, mechanism, runtime, representation)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
