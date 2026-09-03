def is_background(event: dict) -> bool:
    if event.get("task_type") == "local_bash":
        return True
    return str(event.get("task_id", "")).startswith("bash-")


def visible_subagents(events: list[dict]) -> list[str]:
    return [event["task_id"] for event in events if not is_background(event)]


def sample_new_event() -> dict:
    return {"task_type": "local_bash", "task_id": "opaque-7"}

