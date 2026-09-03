# #508 — Telegram ingress fallback and forwarding metadata

## Result

- The last `@dp.message()` handler now logs every otherwise-unhandled Telegram message. If the message resolves to an Orchestra topic, it sends `[<actual_type>] <JSON>` through the existing `_send_to_agent` batching path.
- aiogram 3.28.2 reports a new `rich_message` as `ContentType.UNKNOWN` but retains the raw field in `Message.model_extra`; the fallback names that field and serializes its value. The same code was probed with the neighboring aiogram 3.30.0 typed `RichMessage` model and emitted the same marker/JSON.
- `_forward_meta` prefers `forward_origin`. User and hidden-user origins remain human-readable; channel origins include title and a public `t.me/<username>/<message_id>` link, or a `t.me/c/...` link when only the `-100...` chat id is available. Deprecated `forward_from`, `forward_sender_name`, and `forward_from_chat` remain fallbacks.
- Rich-message media blocks are not downloaded. Their complete parsed/raw JSON, including every `file_id`, `file_unique_id`, size and dimension, reaches the agent. Downloading nested media would need a separate reservation/grouping contract; treating nested blocks as top-level `Message.photo` would risk reordering or duplicate delivery. Existing top-level photos still take the earlier `F.photo` handler and retain their local path.
- aiogram was not upgraded. The fallback closes this loss on 3.28.2 and remains compatible with 3.30.0, so changing the production dependency would add risk without adding required behavior.

The task description's “exactly two message types” was stale for this branch: before #508 it already had dedicated handlers for voice, video note, photo, document, video, audio, sticker and text. The confirmed defect was the absence of a final fallback for every other type.

## Frozen RED oracle

Final behavioral oracle: `tests/test_tg_ingress_508.py`. The test-only commits precede the production commit for the six new requirements; the later seventh case is a baseline-green compatibility control for ordinary top-level photos.

Exact baseline replay loaded `app/tg_bridge.py` from test-only commit `9eeb362e` without changing the working tree:

```text
uv run python <baseline-module replay>  # pytest -q tests/test_tg_ingress_508.py
FFF.FFF [100%]
6 failed, 1 passed in 1.00s
RC=1
```

The six failures were: rich-message fallback delivery/logging, generic unhandled contact delivery, rich photo-block JSON retention, forwarded rich-message source wiring, modern user origin compatibility, and channel title/link metadata. The passing control was the pre-existing top-level photo download path.

Oracle history:

- `92a01c78` excluded: synthetic block names did not match the known 3.30 schema.
- `b1f6e411` excluded: it asserted Python object identity across aiogram's Bot-context remount, which is not a transport contract.
- `26485c41` and `9eeb362e` are the corrected test-only RED commits; `286a955c` adds only the baseline-green photo compatibility control.

## Verification

```text
uv run pytest -q tests/test_tg_ingress_508.py
7 passed in 5.25s

uv run pytest -q tests/test_tg_ingress_508.py tests/test_tg_bridge.py
200 passed, 1 pre-existing subprocess teardown warning in 13.97s

uv run pytest -q <the other six tests/test_tg*.py files>
25 passed in 18.18s

Combined Telegram total
225 passed; both commands RC=0

uv run python -m py_compile app/tg_bridge.py
RC=0
```

The focused async suite also passed three consecutive runs: `7 passed` after the final compatibility control; before that control, the same six behavioral cases passed three consecutive runs as `6 passed`.

`uv run ruff check ...` could not start because `ruff` is not installed in this environment. `py_compile`, focused pytest, the combined bridge suite, and the full Telegram test set are green.

## Mutation proof

The committed fallback was mutated with an early `return` immediately before `_send_to_agent`, then restored from a one-use backup and `touch`ed before the green repeat.

```text
prod_marker_before=1
mutant_marker_before=0
mutant_marker_during=1
4 failed, 2 passed
mutation_red_rc=1
prod_marker_after=1
mutant_marker_after=0
6 passed
restored_green_rc=0
```

The four failing cases were the two generic fallback routes, rich photo-block delivery, and forwarded rich-message delivery. The two `_forward_meta` unit cases correctly stayed green.

## Review

- Changed consumers: shared Telegram message dispatch and batching (`app/tg_bridge.py`), plus dispatcher-state isolation in `tests/test_tg_bridge.py`.
- Author metadata: `gpt-5.6-sol` / Codex runtime (`list_agents`, 03.09.2026).
- AC: the six baseline-red behaviors above plus the baseline-green top-level photo control; named command `uv run pytest -q tests/test_tg_ingress_508.py` → `7 passed`.
- Route: high-risk message-delivery surface would select Sol, but no separate Sol authorization was provided; `codex-debate` therefore allowed one fresh Luna pass.
- Independence: reviewer metadata is `gpt-5.6-luna`, different from the author model; fresh artifact `docs/tasks/508/codex-review-impl.md` reviewed the committed diff.
- Verdict: ACK, zero findings. Reviewer evidence was the exact command `uv run pytest -q tests/test_tg_ingress_508.py tests/test_tg_bridge.py` → `199 passed` and the verified diff quote `@dp.message()`.
