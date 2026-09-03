"""Add focused regression tests here."""

from src.prompts import build_prompt, source_clauses


def test_source_clauses_reach_planner_and_not_worker():
    clauses = source_clauses()
    assert clauses

    planner = build_prompt("planner")
    worker = build_prompt("worker")
    assert all(clause in planner for clause in clauses)
    assert all(clause not in worker for clause in clauses)
