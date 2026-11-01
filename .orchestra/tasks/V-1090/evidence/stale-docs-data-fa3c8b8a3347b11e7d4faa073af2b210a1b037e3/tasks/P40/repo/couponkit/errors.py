"""The errors of couponkit. Every error is a CouponKitError, so callers can catch them all."""


class CouponKitError(Exception):
    """Base class of all couponkit errors."""


class AmountError(CouponKitError):
    """A money amount is not valid."""


class CartError(CouponKitError):
    """The cart file cannot be read."""


class CouponFileError(CouponKitError):
    """The coupon file cannot be read."""


class UnknownCouponError(CouponKitError):
    """A coupon code is not in the coupon file."""


class SettingsError(CouponKitError):
    """The settings file cannot be read or holds a bad value."""
