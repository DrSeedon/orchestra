from src.prompts import worker_excludes_planner_rules


def test_helper_says_worker_is_clean():
    assert worker_excludes_planner_rules()

