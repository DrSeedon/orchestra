from src.prompts import build_prompt, source_clauses


def test_every_live_source_clause_reaches_only_the_planner():
    clauses = source_clauses()
    assert clauses, "source extraction must be alive"
    planner = build_prompt("planner")
    worker = build_prompt("worker")
    for clause in clauses:
        assert clause in planner
        assert clause not in worker

