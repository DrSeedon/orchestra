"""Offline regression checks for research arithmetic and primary-source provenance."""
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path

import pytest

from calculate import MIXES, RATES, calculate, cost, savings

ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = Path(os.environ.get("TASK_V1158_EVIDENCE_ROOT", ROOT / "private-evidence/original"))


def test_advertised_discount_is_not_the_fresh_equal_mix_discount():
    assert cost(RATES['opus5']['wello'], MIXES['fresh50_output50']) == D('2')
    assert cost(RATES['opus5']['official'], MIXES['fresh50_output50']) == D('15')
    assert round(savings(D('2'), D('15')), 2) == D('86.67')
    assert savings(D('2'), D('25')) == D('92')


def test_agent_mix_includes_first_writes_and_does_not_charge_reads_as_fresh():
    mix = MIXES['hypothetical_agent_heavy_cache']
    assert sum(mix) == 1_000_000
    assert cost(RATES['opus5']['wello'], mix) == D('.495')
    assert cost(RATES['opus5']['official'], mix) == D('2.2375')
    assert cost(RATES['sonnet5']['official'], mix) == D('.895')


def test_boundaries_and_more_expensive_models_are_not_hidden():
    assert cost(RATES['opus5']['wello'], (0, 0, 1_000_000, 0)) == D('.2')
    assert cost(RATES['opus5']['wello'], (0, 0, 0, 0)) == 0
    assert savings(D('.815'), D('.325')) < -150
    assert cost(RATES['luna56']['wello'], (1_000_000, 0, 0, 0)) > cost(RATES['luna56']['official'], (1_000_000, 0, 0, 0))
    with pytest.raises(ValueError):
        cost(('2', '2.5', '.2', '2'), (-1, 0, 0, 0))
    with pytest.raises(ValueError):
        savings(D('1'), D('0'))


def test_no_budget_is_invented_and_all_mixes_are_explicit():
    result = calculate()
    assert result['subscription_budget_usd'] is None
    assert result['confidence_interval'] is None
    assert all(sum(mix) == 1_000_000 for mix in MIXES.values())
    max100 = next(x for x in result['plans'] if x['plan'] == 'max100')
    assert max100['conditional_rub_per_million_at_full_advertised_volume'] == '5.225'
    assert max100['hypothetical_opus5_retail_equivalent_usd_if_heavy_cache'] == '1980.000'


def test_saved_calculation_matches_reproduction():
    assert json.loads((ROOT / 'calculations.json').read_text()) == calculate()


def test_primary_rate_rows_support_numeric_inputs():
    wello = (EVIDENCE_ROOT / 'sources/wello_docs.txt').read_text()
    assert 'claude-opus-5 | 1000k | $2.00 / $2.00 | $2.50 / $0.20' in wello
    assert 'claude-sonnet-5 | 1000k | $1.60 / $1.60 | $2.00 / $0.16' in wello
    assert 'glm-5.3-flash | 1000k | $0.38 / $1.25 | $0.47 / $0.08' in wello
    assert 'gpt-6-astra | $10.00 | $50.00 | $1.00 | $12.50 | $25.00' in (EVIDENCE_ROOT / 'sources/openai_pricing.txt').read_text()
    assert 'GLM-5.3-Flash | $0.15 | $0.03 | Limited-time Free | $0.50' in (EVIDENCE_ROOT / 'sources/zai_pricing.txt').read_text()
    assert 'claude-opus-4-8' in (EVIDENCE_ROOT / 'sources/anthropic_opus48_correct.txt').read_text()


def test_documented_cache_conflict_is_material():
    assert D('.38') * D('.1') == D('.038')
    assert D('.08') != D('.038')
    assert D('2.50') * D('.1') == D('.25')
    assert D('1.00') / D('.25') == 4


def test_archive_hashes_and_actual_http_coverage():
    index = json.loads((ROOT / 'source_index.json').read_text())
    assert len(index) >= 30
    for item in index:
        assert item['status'] == 200
        assert item['hash_verified']
        assert hashlib.sha256((EVIDENCE_ROOT / Path(item['archive_file']).relative_to('private-evidence/original')).read_bytes()).hexdigest() == item['sha256']
    assert all('DO NOT CITE' in x['evidence_role'] for x in index if x['name'] in {'anthropic_opus5', 'anthropic_opus48', 'anthropic_sonnet5'})


def test_status_exposes_stale_catalog_and_separate_stable_routes():
    status = json.loads((EVIDENCE_ROOT / 'sources/wello_status_json.html').read_text())
    assert status['models']['gpt-5.6-luna']['blocked'] is True
    assert status['models']['claude-opus-5.5-stable']['availability'] == 'available'
    assert status['models']['claude-opus-5']['availability'] == 'available'
    assert '2026-10-31T' in status['updatedAt']


def test_no_authentication_data_detected_at_publication_boundary():
    from verify_evidence import verify
    audit = verify(EVIDENCE_ROOT)
    assert audit['all_required_original_hashes_match'] is True
    assert audit['required_non_cache_originals_verified'] == 172
    assert audit['original_inventory_entries'] == 176
    assert len(audit['excluded_cache_metadata']) == 4
    assert audit['local_publication_scan']['finding_count'] == 0
    assert audit['relative_public_links_ok'] is True


def test_transport_verification_does_not_read_excluded_cache_bodies(monkeypatch):
    from verify_evidence import verify_originals
    read_bytes = Path.read_bytes

    def without_cache(self):
        assert '.pytest_cache' not in self.parts, 'Cache bodies are not evidence'
        return read_bytes(self)

    monkeypatch.setattr(Path, 'read_bytes', without_cache)
    manifest = json.loads((ROOT / 'preservation_manifest.json').read_text())
    result = verify_originals(EVIDENCE_ROOT, manifest)
    assert result['required_non_cache_originals_verified'] == 172
    assert sum(x['bytes'] for x in result['excluded_cache_metadata']) == 1546


def test_transport_exception_cannot_hide_missing_required_source(monkeypatch):
    from verify_evidence import verify_originals
    is_file = Path.is_file
    missing = EVIDENCE_ROOT / 'sources/wello_docs.html'
    monkeypatch.setattr(Path, 'is_file', lambda path: False if path == missing else is_file(path))
    manifest = json.loads((ROOT / 'preservation_manifest.json').read_text())
    with pytest.raises(AssertionError, match='sources/wello_docs.html'):
        verify_originals(EVIDENCE_ROOT, manifest)


def test_transport_exception_requires_exact_original_cache_metadata():
    from verify_evidence import verify_originals
    for field, value in (('bytes', 0), ('path', '.pytest_cache/unapproved-cache')):
        manifest = json.loads((ROOT / 'preservation_manifest.json').read_text())
        cache = next(x for x in manifest if x['path'] == '.pytest_cache/.gitignore')
        cache[field] = value
        with pytest.raises(AssertionError, match='Unexpected cache provenance'):
            verify_originals(EVIDENCE_ROOT, manifest)
