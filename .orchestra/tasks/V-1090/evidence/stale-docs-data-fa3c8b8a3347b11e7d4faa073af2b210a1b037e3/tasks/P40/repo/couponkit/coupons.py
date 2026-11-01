"""The coupon file and the discount of one coupon."""
import json
from dataclasses import dataclass
from decimal import Decimal

from couponkit.errors import AmountError, CouponFileError, UnknownCouponError
from couponkit.money import ZERO, parse_amount, round_amount

KINDS = ("percent", "amount")


@dataclass(frozen=True)
class Coupon:
    """A coupon. ``value`` is a whole percent or an amount, depending on ``kind``."""

    code: str
    kind: str
    value: Decimal
    minimum: Decimal = ZERO


def coupon_from_json(data: dict) -> Coupon:
    """Build a coupon from one entry of the coupon file."""
    if not isinstance(data, dict):
        raise CouponFileError("every coupon must be a JSON object")
    code = str(data.get("code", "")).strip().upper()
    if not code:
        raise CouponFileError("every coupon needs a code")
    kind = data.get("kind")
    if kind not in KINDS:
        raise CouponFileError(f"{code}: kind must be one of {', '.join(KINDS)}")
    try:
        value = parse_amount(str(data.get("value", "")))
        minimum = parse_amount(str(data.get("minimum", "0")))
    except AmountError as error:
        raise CouponFileError(f"{code}: {error}") from None
    if kind == "percent" and (value != value.to_integral_value() or not 1 <= value <= 100):
        raise CouponFileError(f"{code}: a percent must be a whole number from 1 to 100")
    return Coupon(code=code, kind=kind, value=value, minimum=minimum)


def load_coupons(path: str) -> dict[str, Coupon]:
    """Read the coupon file at ``path`` and return the coupons by code."""
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as error:
            raise CouponFileError(f"{path}: not valid JSON ({error.msg})") from None
    if not isinstance(data, dict):
        raise CouponFileError(f"{path}: expected a JSON object")
    coupons = {}
    for entry in data.get("coupons", []):
        coupon = coupon_from_json(entry)
        if coupon.code in coupons:
            raise CouponFileError(f"{path}: coupon {coupon.code} appears twice")
        coupons[coupon.code] = coupon
    return coupons


def find_coupon(coupons: dict[str, Coupon], code: str) -> Coupon:
    """Return the coupon with ``code``; upper and lower case are the same."""
    coupon = coupons.get(code.strip().upper())
    if coupon is None:
        raise UnknownCouponError(f"unknown coupon: {code}")
    return coupon


def coupon_discount(coupon: Coupon, subtotal: Decimal) -> Decimal:
    """Return the discount of ``coupon`` on a cart with ``subtotal``.

    A coupon gives nothing when the subtotal is below its minimum, and never
    more than the subtotal.
    """
    if subtotal < coupon.minimum:
        return ZERO
    if coupon.kind == "percent":
        return round_amount(subtotal * coupon.value / 100)
    return min(coupon.value, subtotal)
