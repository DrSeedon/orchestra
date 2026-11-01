from datetime import date

import pytest

from grantpot.ledger import awarded_total, check_award, remaining, status_lines, totals_by_recipient
from grantpot.models import Award, Fund

FUND = Fund("Arts 2026", 100000)
AWARDS = [
    Award(date(2026, 1, 10), "Choir", 25000),
    Award(date(2026, 2, 3), "Mural", 40000),
    Award(date(2026, 3, 1), "Choir", 5000),
]


def test_awarded_total_and_remaining():
    assert awarded_total(AWARDS) == 70000
    assert remaining(FUND, AWARDS) == 30000
    assert remaining(FUND, []) == 100000


def test_remaining_can_be_negative():
    assert remaining(Fund("Small", 1000), [Award(date(2026, 1, 1), "Choir", 1500)]) == -500


def test_totals_by_recipient_keeps_first_award_order():
    assert totals_by_recipient(AWARDS) == {"Choir": 30000, "Mural": 40000}
    assert list(totals_by_recipient(AWARDS)) == ["Choir", "Mural"]


def test_check_award_accepts_exact_rest():
    check_award(FUND, AWARDS, 30000)


@pytest.mark.parametrize("amount, message", [(0, "more than 0.00"), (30001, "more than the 300.00 left")])
def test_check_award_rejects(amount, message):
    with pytest.raises(ValueError, match=message):
        check_award(FUND, AWARDS, amount)


def test_status_lines():
    assert status_lines(FUND, AWARDS) == [
        "fund: Arts 2026",
        "budget: 1000.00",
        "awarded: 700.00 in 3 awards",
        "remaining: 300.00",
        "  Choir: 300.00",
        "  Mural: 400.00",
    ]
