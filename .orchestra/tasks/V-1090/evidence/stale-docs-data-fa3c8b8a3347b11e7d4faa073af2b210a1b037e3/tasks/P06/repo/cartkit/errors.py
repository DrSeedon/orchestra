"""Exception types raised by cartkit."""


class CartError(Exception):
    """Base class for all cartkit errors."""


class InvalidPriceError(CartError):
    """A price string could not be parsed."""


class UnknownProductError(CartError):
    """A SKU is not in the catalog."""


class InvalidQuantityError(CartError):
    """A quantity is zero, negative or above the per-line limit."""


class UnknownRegionError(CartError):
    """No tax or shipping rule exists for a region."""


class EmptyCartError(CartError):
    """Checkout was attempted on a cart without lines."""
