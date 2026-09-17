"""Exceptions raised by the inventory domain."""


class InventoryError(Exception):
    """Base class for expected inventory errors."""


class ValidationError(InventoryError):
    """Raised when input data is invalid."""


class DuplicateBatchError(InventoryError):
    """Raised when a batch ID is already registered."""


class InsufficientStockError(InventoryError):
    """Raised when a dispensing request cannot be fulfilled."""