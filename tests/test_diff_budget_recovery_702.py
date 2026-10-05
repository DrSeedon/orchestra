def test_diff_budget_refusal_exposes_parent_escalation_route():
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "large-diff-operation",
        {
            "ok": False,
            "state": "failed",
            "commit_point": "not_reached",
            "target_branch": "main",
            "worker_branch": "task-42/worker",
            "worker_head": "b" * 40,
            "commits_merged": 0,
            "error": "DIFF TOO LARGE: 2001 insertions (limit 2000)",
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "FAILED"
    assert result["next_action"]["code"] == "WAKE_PARENT"
    assert "send_message" in result["next_action"]["message"]
    assert "waive_diff_budget" in result["next_action"]["message"]
