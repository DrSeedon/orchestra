"""#407: fan/report rules must reach their role consumers from one owner."""


def test_t4_worker_roles_receive_role_owned_send_message_requirement():
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    anchor = "Every worker completion report MUST be sent with an actual `send_message`"
    worker = build_system_prompt(DEFAULT_PIPELINE, "worker")
    full_cycle = build_system_prompt(DEFAULT_PIPELINE, "full-cycle")
    orchestrator = build_system_prompt(DEFAULT_PIPELINE, "orchestrator")

    assert anchor in worker
    assert anchor in full_cycle
    assert anchor not in orchestrator


def test_t4_spawner_prompts_route_fans_through_one_run_fan_call():
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    orchestrator = build_system_prompt(DEFAULT_PIPELINE, "orchestrator")
    full_cycle = build_system_prompt(DEFAULT_PIPELINE, "full-cycle")
    worker = build_system_prompt(DEFAULT_PIPELINE, "worker")

    assert "`run_fan(tasks=[...])`" in orchestrator
    assert "`run_fan(tasks=[...])`" in full_cycle
    assert "`run_fan(tasks=[...])`" not in worker
    assert "call `open_fan(children=[...])` BEFORE the spawns" not in orchestrator
    assert "call `open_fan(children=[...])` BEFORE the spawns" not in full_cycle
