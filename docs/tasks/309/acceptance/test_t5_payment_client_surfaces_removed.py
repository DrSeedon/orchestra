import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def main() -> None:
    assert not {"payment_receive", "payment_status"} & _function_names(ROOT / "app/mcp_stdio.py")
    route_src = (ROOT / "app/routes/tm.py").read_text(encoding="utf-8")
    for marker in ("TmPaymentReceive", "/payments", "_resolve_client_id", "tm_payment_"):
        assert marker not in route_src, f"payment/client HTTP surface remains: {marker}"
    tm_src = (ROOT / "app/tm.py").read_text(encoding="utf-8")
    for marker in ("receive_payment", "get_payment_status", "api_receive_payment", "api_payment_status", "tm_clients", "tm_payments"):
        assert marker not in tm_src, f"payment/client service code remains: {marker}"
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    for marker in ("payment_receive", "payment_status", "/api/tm/payments", "paid_rub", "debt_rub"):
        assert marker not in js, f"payment/client UI marker remains: {marker}"
    prompt = (ROOT / "pipelines/default/prompts/modules/task-management.md").read_text(encoding="utf-8")
    for marker in ("payment_receive", "payment_status"):
        assert marker not in prompt, f"payment prompt anchor remains: {marker}"


if __name__ == "__main__":
    main()
