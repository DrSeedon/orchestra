"""Instruction ownership and lossless historical evidence, not prose style checks."""
from pathlib import Path
import hashlib
import subprocess


ROOT = Path(__file__).parents[1]


def test_original_rules_are_preserved_byte_for_byte():
    archive = ROOT / ".orchestra/archive/instructions/2026-09-05-CLAUDE.md"
    # Frozen from 74692c2c before moving the file; works in shallow CI clones too.
    assert hashlib.sha256(subprocess.check_output(["git", "show", "9a1735f1695519a445f393802c2154bd37337e38:.orchestra/archive/instructions/2026-09-05-CLAUDE.md"], cwd=ROOT)).hexdigest() == (
        "298e291c1866285592ca6236a833840fea332c082094d42e4a558faf5c8c1cc7"
    )


def test_both_clients_get_the_same_bounded_rules_and_current_topic_index():
    from scripts.check_instruction_contract import check
    subprocess.run(["git", "ls-files", "--error-unmatch", "AGENTS.md", "CLAUDE.md"], cwd=ROOT, check=True)
    check(ROOT)


def test_historical_source_snapshot_remains_reachable():
    subprocess.run(['git', 'merge-base', '--is-ancestor', '9a1735f1695519a445f393802c2154bd37337e38', 'HEAD'], cwd=ROOT, check=True)
    for path in ['.orchestra/workers/frontend.md', '.orchestra/tasks/239/report.md',
                 '.orchestra/archive/knowledge-20260909/manifest.json']:
        assert subprocess.check_output(['git', 'show', '9a1735f1695519a445f393802c2154bd37337e38:'+path], cwd=ROOT)
