
import math
from datetime import date


class InputError(ValueError):
    pass


class NotFoundError(ValueError):
    pass


class ConflictError(ValueError):
    pass


def parse_amount(value):
    if isinstance(value, bool):
        raise InputError("Amount must be numeric")

    try:
        amount = float(value)
    except (TypeError, ValueError) as error:
        raise InputError("Amount must be numeric") from error
    except OverflowError as error:
        raise InputError("Amount exceeds the supported range") from error

    if not math.isfinite(amount):
        raise InputError("Amount must be finite")
    # SQL Server DECIMAL(18,2) allows 16 digits before the decimal point.
    if abs(amount) >= 10**16:
        raise InputError("Amount exceeds the supported range")

    return amount


def validate_amount(value, allow_zero=False):
    amount = parse_amount(value)
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InputError("Invalid amount")

    return amount


def validate_text(value, field, *, nullable=False, max_units=None):
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        suffix = " or null" if nullable else ""
        raise InputError(f"{field} must be a string{suffix}")
    if max_units is not None:
        try:
            units = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError as error:
            raise InputError(f"{field} must contain valid Unicode") from error
        if units > max_units:
            raise InputError(f"{field} exceeds the maximum length of {max_units} UTF-16 code units")
    return value


def validate_name(value, field="name"):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{field.capitalize()} is required")
    return validate_text(value.strip(), field, max_units=255)


def validate_integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise InputError("Expected an integer")

    try:
        number = int(str(value))
    except (TypeError, ValueError) as error:
        raise InputError("Expected an integer") from error

    if not minimum <= number <= maximum:
        raise InputError(f"Value must be between {minimum} and {maximum}")

    return number


def validate_optional_date(value, field):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InputError(f"{field} must be an ISO 8601 date string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InputError(f"{field} must be a valid ISO 8601 date") from error
