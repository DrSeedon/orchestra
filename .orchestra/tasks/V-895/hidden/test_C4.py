import ast, pathlib
def test_constant():
    import app.bg_jobs as b
    assert b._CRON_COMMAND_TIMEOUT_SECONDS == 600

def test_bg_create_doc_mentions_limit():
    tree = ast.parse(pathlib.Path("app/mcp_stdio.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "bg_create")
    doc = ast.get_docstring(fn)
    assert "600" in doc and "cron_command" in doc
