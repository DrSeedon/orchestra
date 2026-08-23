from src.gateway import default_gateway


def test_three_cards_exist_today():
    assert len(default_gateway().cards()) == 3

