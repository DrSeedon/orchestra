"""Scratch proof for #426; this is not production code."""

import hashlib
import json


def encode(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def old_head(records, task_head, knowledge_head):
    return hashlib.sha256(encode({
        "task_head": task_head,
        "knowledge_head": knowledge_head,
        "evidence": records,
    })).hexdigest()


def evidence_prefix(records):
    return hashlib.sha256(b'{"evidence":' + encode(records) + b',"knowledge_head":')


def cached_head(prefix, task_head, knowledge_head):
    digest = prefix.copy()
    digest.update(encode(knowledge_head))
    digest.update(b',"task_head":')
    digest.update(encode(task_head))
    digest.update(b"}")
    return digest.hexdigest()


def drain(observed, queue):
    refused = 0
    remaining = list(queue)
    while remaining:
        entry = remaining[0]
        if observed == entry["target"]:
            remaining.pop(0)
            continue
        if observed != entry["expected"]:
            refused += 1
            break
        observed = entry["target"]
        remaining.pop(0)
    return observed, remaining, refused


head_equal = []
for count in (0, 2, 1000):
    records = [
        {"project_id": f"p{i % 7}", "stable_id": f"s{i:04d}", "value": i}
        for i in range(count)
    ]
    records.sort(key=lambda item: (item["project_id"], item["stable_id"]))
    head_equal.append(
        old_head(records, "task-B", "knowledge-K")
        == cached_head(evidence_prefix(records), "task-B", "knowledge-K")
    )

entries = [
    {"expected": "P", "target": "A"},
    {"expected": "A", "target": "B"},
]
ordered = drain("P", entries)
out_of_order = drain("P", list(reversed(entries)))
crash_replay = drain("A", entries)

assert head_equal == [True, True, True]
assert ordered == ("B", [], 0)
assert out_of_order[0] == "P" and out_of_order[2] == 1
assert crash_replay == ("B", [], 0)

print("HEAD_PREFIX_EQUAL", head_equal)
print("ORDERED_FINAL", ordered)
print("OUT_OF_ORDER_REFUSED", out_of_order)
print("CRASH_REPLAY_FINAL", crash_replay)
