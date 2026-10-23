"""Temporary production mutants; always restore the source before returning."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
source = root / "app/hub_workspace.py"
original = source.read_text()
plain_start = original.index('    repository = _git_out(root, "rev-parse", "--is-inside-work-tree")',
                             original.index("def capture_inputs("))
plain_end = original.index("    if state.manifest:", plain_start)
mutations = [
    ("remove non-Git support", original[:plain_start] + original[plain_end:],
     "tests/test_hub_inputs_v1063.py::test_plain_upload_freezes_no_exemptions_even_after_git_init"),
    ("grant non-Git manifest allowances",
     original.replace("            state.input_manifest = {}", "            state.input_manifest = dict(manifest)"),
     "tests/test_hub_inputs_v1063.py::test_plain_upload_freezes_no_exemptions_even_after_git_init"),
    ("treat broken Git metadata as a plain directory",
     original.replace('if not any(os.path.lexists(parent / ".git") for parent in (resolved, *resolved.parents)):',
                      "if True:"),
     "tests/test_hub_inputs_v1063.py::test_broken_git_metadata_is_not_a_plain_upload"),
]
try:
    for name, mutant, test in mutations:
        assert mutant != original
        source.write_text(mutant)
        for cache in (root / "app/__pycache__").glob("hub_workspace.*.pyc"):
            cache.unlink()
        command = ["uv", "run", "--frozen", "python", "-m", "pytest", test, "-q", "--tb=short"]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=90)
        print(f"MUTATION: {name}\n$ {' '.join(command)}\n{result.stdout}{result.stderr}", flush=True)
        assert result.returncode == 1, f"mutant was not killed: {name}"
        assert "AssertionError" in result.stdout or "HubWorkspaceError" in result.stdout
        assert "ERROR collecting" not in result.stdout
        assert "ImportError" not in result.stdout + result.stderr
finally:
    source.write_text(original)
    for cache in (root / "app/__pycache__").glob("hub_workspace.*.pyc"):
        cache.unlink()
print("All three mutants killed; production source restored.")
