from src.classifier import sample_new_event, visible_subagents


def test_sample_background_is_hidden():
    assert visible_subagents([sample_new_event()]) == []

