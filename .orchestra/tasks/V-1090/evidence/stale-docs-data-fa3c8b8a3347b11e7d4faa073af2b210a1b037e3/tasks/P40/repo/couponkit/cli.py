"""The command line: the total of a cart, with at most one coupon."""
import argparse
import sys
from typing import Optional

from couponkit.cart import cart_subtotal, load_cart
from couponkit.coupons import coupon_discount, find_coupon, load_coupons
from couponkit.errors import CouponKitError
from couponkit.money import ZERO, format_amount
from couponkit.settings import load_settings


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="couponkit")
    parser.add_argument("--settings", help="JSON settings file")
    parser.add_argument("cart", help="cart CSV file")
    parser.add_argument("--coupon", help="coupon code to use")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Show the subtotal, the discount and the total of a cart."""
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        subtotal = cart_subtotal(load_cart(args.cart))
        discount = ZERO
        if args.coupon:
            coupons = load_coupons(settings["coupons_file"])
            discount = coupon_discount(find_coupon(coupons, args.coupon), subtotal)
    except (OSError, CouponKitError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    currency = settings["currency"]
    print(f"subtotal {format_amount(subtotal)} {currency}")
    print(f"discount {format_amount(discount)} {currency}")
    print(f"total {format_amount(subtotal - discount)} {currency}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
