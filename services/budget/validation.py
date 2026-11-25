
import math


class NotFoundError(ValueError):
    pass


class ConflictError(ValueError):
    pass


def validate_amount(value, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError("Amount must be numeric")

    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Amount must be numeric")

    if not math.isfinite(amount):
        raise ValueError("Amount must be finite")

    if amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError("Invalid amount")

    return amount


def validate_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Name is required")

    return value.strip()


def validate_integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError("Expected an integer")

    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise ValueError("Expected an integer")

    if not minimum <= number <= maximum:
        raise ValueError(
            f"Value must be between {minimum} and {maximum}"
        )

    return number
