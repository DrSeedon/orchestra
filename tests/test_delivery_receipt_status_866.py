import json

import pytest


@pytest.mark.parametrize(
    ("state", "deferred"),
    [("QUEUED", False), ("WAITING_QUOTA", True)],
)
def test_spawn_receipt_quota_timing_matches_delivery_state(state, deferred):
    from app.mcp_stdio import _delivery_receipt_text

    receipt = _delivery_receipt_text(
        "worker", "luna",
        {
            "worktree_path": "/worktree", "repo_path": "/repo",
            "git_common_dir": "/repo/.git", "branch": "task-866/worker",
        },
        {
            "delivery_id": "delivery-866",
            "delivery_state": state,
            "error": {"details": {"reason": "quota threshold exceeded"}},
            "next_action": {"message": "quota gate is closed"},
        },
    )

    assert f"state={state}" in receipt
    assert ("defer" in receipt.lower()) is deferred


@pytest.mark.parametrize(
    ("state", "deferred"),
    [("QUEUED", False), ("WAITING_QUOTA", True)],
)
def test_send_receipt_quota_timing_matches_delivery_state(state, deferred):
    from app.mcp_stdio import _message_delivery_receipt_text

    receipt = _message_delivery_receipt_text(
        {
            "delivery_id": "delivery-866",
            "acceptance": "ACCEPTED",
            "delivery_state": state,
            "next_action": {
                "code": "WAITING_QUOTA" if deferred else "NONE",
                "message": "quota gate is closed" if deferred else "",
            },
        },
        to="worker",
    )

    assert f"state={state}" in receipt
    assert ("defer" in receipt.lower()) is deferred


@pytest.mark.parametrize(
    ("state", "deferred", "action_code"),
    [("QUEUED", False, "WAIT_FOR_DELIVERY"),
     ("WAITING_QUOTA", True, "WAITING_QUOTA")],
)
def test_retry_initial_delivery_api_receipt_explains_quota_timing(
    state, deferred, action_code,
):
    from app.initial_deliveries import _next_action

    row = {
        "state": state,
        "delivery_id": "delivery-866",
        "worker_name": "worker",
        "message": "task",
        "error_json": json.dumps({
            "code": "WAITING_QUOTA",
            "details": {"reason": "quota threshold exceeded"},
        }) if deferred else None,
    }
    action = _next_action(row)

    assert action["code"] == action_code
    assert ("defer" in action["message"].lower()) is deferred
