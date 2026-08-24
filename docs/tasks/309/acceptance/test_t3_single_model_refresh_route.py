import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    path = ROOT / "app/routes/system.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "refresh_models_endpoint"]
    routes = [
        d
        for d in ast.walk(tree)
        if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))
        for dec in d.decorator_list
        if isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr == "post"
        and dec.args
        and isinstance(dec.args[0], ast.Constant)
        and dec.args[0].value == "/api/models/refresh"
    ]
    assert len(defs) == 1, f"expected one refresh_models_endpoint, got {len(defs)}"
    assert len(routes) == 1, f"expected one POST /api/models/refresh, got {len(routes)}"


if __name__ == "__main__":
    main()
