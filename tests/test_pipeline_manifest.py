"""Routing prose must stay independent of exact registry/manifest model IDs."""

from pathlib import Path

from app import models


def test_routing_prompt_uses_aliases_instead_of_manifest_ids():
    prompt = (Path(__file__).resolve().parents[1] / '.orchestra/pipelines/default/prompts/modules/model-routing.md').read_text()
    for model in models.SELECTABLE_MODEL_SPECS:
        assert model.id not in prompt
    assert all(alias in prompt for alias in ('hubsol', 'hubargon', 'hubsonnet', 'hubluna', 'sol', 'luna'))
