"""Split an amount evenly between people."""
from decimal import Decimal

from .money import TWO_PLACES, round_down


def split_evenly(total: Decimal, people: int) -> list[Decimal]:
    """Split total into one share per person.

    Each share is rounded down to 0.01. The hundredths that are left over go one at
    a time to the first people, so the shares always add up to total. Raises
    ValueError when people is less than 1.
    """
    if people < 1:
        raise ValueError("need at least one person, got {}".format(people))
    base = round_down(total / people)
    shares = [base] * people
    leftover = int((total - base * people) / TWO_PLACES)
    for index in range(leftover):
        shares[index] += TWO_PLACES
    return shares
