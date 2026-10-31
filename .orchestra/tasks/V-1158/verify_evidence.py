"""Offline delivery validation, not a canonical publication guard or billing probe."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = {
    '.gitignore', 'REPORT.md', 'CHECKS.md', 'calculate.py', 'calculations.json',
    'source_index.json', 'preservation_manifest.json', 'test_research.py',
    'verify_evidence.py', 'verification.json',
}
# Exact broker-excluded, rebuildable cache metadata from the immutable inventory.
# These four files are not required source evidence and are never read/recreated.
EXCLUDED_CACHE_METADATA = {
    '.pytest_cache/.gitignore': (37, '3ed731b65d06150c138e2dadb0be0697550888a6b47eb8c45ecc9adba8b8e9bd'),
    '.pytest_cache/CACHEDIR.TAG': (191, '37dc88ef9a0abeddbe81053a6dd8fdfb13afb613045ea1eb4a5c815a74a3bde4'),
    '.pytest_cache/README.md': (302, '73fd6fccdd802c419a6b2d983d6c3173b7da97558ac4b589edec2dfe443db9ad'),
    '.pytest_cache/v/cache/nodeids': (1016, 'c8199cb5d4be94e721c8a0be17382661e0224c749e587d8af8d421ddde6a6335'),
}
FORMS = {
    'api_key': r'(?:sk-ant-|sk-proj-|sk-svcacct-|wlo_live_)[A-Za-z0-9_-]{24,}',
    'generic_openai_key': r'sk-[A-Za-z0-9_-]{32,}',
    'github': r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'telegram': r'\b[0-9]{7,12}:[A-Za-z0-9_-]{30,}\b',
    'jwt': r'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b',
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'absolute_host_path': r'/(?:home|mnt|Users)/[^\s"\x27>]+',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_originals(evidence_root, manifest):
    assert len(manifest) == 176 and len({x['path'] for x in manifest}) == 176
    required = []
    excluded = []
    for item in manifest:
        relative = Path(item['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        if '.pytest_cache' in relative.parts:
            expected = EXCLUDED_CACHE_METADATA.get(item['path'])
            assert expected == (item['bytes'], item['sha256']), 'Unexpected cache provenance'
            excluded.append(item)
            continue
        path = evidence_root / relative
        assert path.is_file() and path.stat().st_size == item['bytes'], item['path']
        assert digest(path) == item['sha256'], item['path']
        required.append(item)
    assert {x['path'] for x in excluded} == set(EXCLUDED_CACHE_METADATA)
    assert len(required) == 172
    return {
        'original_inventory_entries': len(manifest),
        'required_non_cache_originals_verified': len(required),
        'required_original_bytes_verified': sum(x['bytes'] for x in required),
        'all_required_original_hashes_match': True,
        'excluded_cache_metadata': excluded,
        'cache_exception': 'Four exact broker-excluded rebuildable caches; metadata only, bodies not read or recreated',
        'receipt_scope': 'Hashes checked at selected evidence root; not an assertion that 176 copies were transported',
    }


def verify(evidence_root):
    private = ROOT / 'private-evidence'
    assert private.is_dir() and not private.is_symlink(), 'Expected task-local plain private folder'
    assert '/private-evidence/' in (ROOT / '.gitignore').read_text().splitlines()
    manifest = json.loads((ROOT / 'preservation_manifest.json').read_text())
    assert manifest == json.loads((private / 'original_inventory.json').read_text())
    originals = verify_originals(evidence_root, manifest)
    index = json.loads((ROOT / 'source_index.json').read_text())
    for item in index:
        relative = Path(item['archive_file']).relative_to('private-evidence/original')
        assert digest(evidence_root / relative) == item['sha256'], item['name']
        assert item['status'] == 200 and item['hash_verified'], item['name']
    broken_links = []
    for name in ('REPORT.md', 'CHECKS.md'):
        for target in re.findall(r'\]\(([^)]+)\)', (ROOT / name).read_text()):
            if '://' not in target and not target.startswith('#') and not (ROOT / target).is_file():
                broken_links.append({'file': name, 'target': target})
    findings = []
    local_markers = (str(ROOT.parents[2]), Path.home().name)
    public_files = []
    for name in sorted(PUBLIC_FILES):
        path = ROOT / name
        assert path.is_file() and not path.is_symlink(), name
        public_files.append(path.name)
        # Regenerated metadata only contains aggregate counts and relative labels.
        if path.name == 'verification.json':
            continue
        content = path.read_text()
        for label, pattern in FORMS.items():
            if re.search(pattern, content):
                findings.append({'file': path.name, 'kind': label})
        if any(marker and marker in content for marker in local_markers):
            findings.append({'file': path.name, 'kind': 'local_identity_literal'})
    assert not broken_links, 'Broken relative public links'
    assert not findings, 'Publication shape/literal scan found prohibited forms; inspect privately'
    result = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Offline archive integrity and delivery only; no fresh billing verification',
        'runner': 'provisioned uv 0.11.28, frozen lock, default .venv',
        **originals,
        'source_body_hashes_match': len(index),
        'http200_non_evidence_stubs': ['anthropic_opus5', 'anthropic_opus48', 'anthropic_sonnet5'],
        'public_files': sorted(public_files),
        'publication_scope': 'Explicit PUBLIC_FILES allowlist only; extra physical files and actual Git index are parent responsibility',
        'local_publication_scan': {'kind': 'task-local forms/literals, NOT canonical guard',
                                   'finding_count': len(findings)},
        'relative_public_links_ok': True,
        'normalized_original_import': 'worker-copy/app/usage_contract.py',
        'full_app_import': False,
        'original_pytest_result': (evidence_root / 'pytest.log').read_text().strip().splitlines()[-1],
        'original_report_sha256': digest(evidence_root / 'REPORT.md'),
        'private_inventory_sha256': digest(private / 'original_inventory.json'),
        'original_inventory_target': 'private-evidence/original_inventory.json',
        'raw_target': 'private-evidence/original',
        'ignore_rule': 'task .gitignore: /private-evidence/; parent must verify Git index',
        'git_head': None,
        'git_head_reason': 'Worker copy has no .git; platform assigns commit on import',
    }
    pytest_rc = private / 'pytest-after-migration.rc'
    pytest_log = private / 'pytest-after-migration.log'
    if pytest_rc.exists() and pytest_log.exists():
        result['migration_pytest_return_code'] = int(pytest_rc.read_text())
        result['migration_pytest_result'] = pytest_log.read_text().strip().splitlines()[-1]
        assert result['migration_pytest_return_code'] == 0, 'Migration tests failed'
    final_rc = private / 'pytest-final.rc'
    final_log = private / 'pytest-final.log'
    if final_rc.exists() and final_log.exists():
        result['final_pytest_return_code'] = int(final_rc.read_text())
        result['final_pytest_result'] = final_log.read_text().strip().splitlines()[-1]
        assert result['final_pytest_return_code'] == 0, 'Final tests failed'
    transport_rc = private / 'pytest-transport.rc'
    transport_log = private / 'pytest-transport.log'
    if transport_rc.exists() and transport_log.exists():
        result['transport_pytest_return_code'] = int(transport_rc.read_text())
        result['transport_pytest_result'] = transport_log.read_text().strip().splitlines()[-1]
        assert result['transport_pytest_return_code'] == 0, 'Transport tests failed'
    (ROOT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, default=ROOT / 'private-evidence/original')
    args = parser.parse_args()
    result = verify(args.evidence_root)
    print(json.dumps({key: result[key] for key in (
        'original_inventory_entries', 'required_non_cache_originals_verified',
        'required_original_bytes_verified', 'source_body_hashes_match',
        'all_required_original_hashes_match', 'relative_public_links_ok', 'local_publication_scan')}))
