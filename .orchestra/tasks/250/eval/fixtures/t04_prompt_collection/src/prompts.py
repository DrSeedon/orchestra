RULES = [
    "never delete an acceptance test",
    "never weaken an acceptance test",
    "run the named command",
]


def source_clauses() -> list[str]:
    return list(RULES)


def build_prompt(role: str) -> str:
    if role == "worker":
        return "worker executes an already closed ticket"
    return "planner rules:\n" + "\n".join(source_clauses())


def worker_excludes_planner_rules() -> bool:
    worker = build_prompt("worker")
    return all(clause not in worker for clause in source_clauses())

