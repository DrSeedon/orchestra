"""Instruction ownership and lossless historical evidence, not prose style checks."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]


def test_original_rules_are_preserved_byte_for_byte():
    original = subprocess.check_output(["git", "show", "74692c2c:CLAUDE.md"], cwd=ROOT)
    archive = ROOT / ".orchestra/archive/instructions/2026-09-05-CLAUDE.md"
    assert archive.read_bytes() == original


def test_claude_adapter_resolves_to_the_tracked_codex_rules():
    adapter = (ROOT / "CLAUDE.md").read_text()
    imports = [line[1:] for line in adapter.splitlines() if line.startswith("@")]
    assert len(imports) == 1
    target = ROOT / imports[0]
    assert target.name == "AGENTS.md"
    subprocess.run(["git", "ls-files", "--error-unmatch", target.name], cwd=ROOT, check=True)
    assert target.is_file() and target.stat().st_size > 0
    assert not any(line.startswith("@") for line in target.read_text().splitlines())
