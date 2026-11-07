"""Inch fractions used for glass sizes."""

from __future__ import annotations

from fractions import Fraction


class UnitError(ValueError):
    """A size string is not a multiple of 1/16 inch."""


def parse_inches(value: object) -> Fraction:
    """Parse an inch length into a fraction on a sixteenth-inch grid.

    Accepts integers, ``37 3/4``, ``37-3/4``, ``3/4``, and decimals such as
    ``28.25`` when the value lands on a sixteenth.
    """
    if isinstance(value, bool) or value is None:
        raise UnitError(f"not a length: {value!r}")
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, float):
        result = Fraction(value).limit_denominator(16)
        if abs(float(result) - value) > 1e-9:
            raise UnitError(f"{value} is not a multiple of 1/16 inch")
    else:
        result = _parse_inch_text(str(value))
    if result.denominator > 16 or (result * 16).denominator != 1:
        # Allow any fraction that is an integer number of sixteenths.
        sixteenths = result * 16
        if sixteenths.denominator != 1:
            raise UnitError(f"{value} is not a multiple of 1/16 inch")
    return result


def _parse_inch_text(text: str) -> Fraction:
    cleaned = text.strip().replace('"', "").replace("″", "").replace("”", "").replace("“", "")
    cleaned = cleaned.replace("-", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        raise UnitError("empty length")
    if " " in cleaned:
        whole, frac = cleaned.split(" ", 1)
        if "/" not in frac:
            raise UnitError(f"not a length: {text!r}")
        return Fraction(int(whole)) + Fraction(frac)
    if "/" in cleaned:
        return Fraction(cleaned)
    if "." in cleaned:
        return Fraction(cleaned)
    return Fraction(int(cleaned))


def format_inches(value: Fraction) -> str:
    """Format a length as a mixed number reduced to lowest terms."""
    if value < 0:
        return f"-{format_inches(-value)}"
    whole = value.numerator // value.denominator
    remainder = Fraction(value.numerator % value.denominator, value.denominator)
    if remainder == 0:
        return str(whole)
    frac = f"{remainder.numerator}/{remainder.denominator}"
    if whole == 0:
        return frac
    return f"{whole} {frac}"


def format_quantity(value: Fraction, places: int = 2) -> str:
    """Format a positive rational with a fixed number of decimal places."""
    scale = 10**places
    rounded = (value * scale + Fraction(1, 2)).numerator // (value * scale + Fraction(1, 2)).denominator
    sign = "-" if rounded < 0 else ""
    rounded = abs(rounded)
    whole, frac = divmod(rounded, scale)
    return f"{sign}{whole}.{frac:0{places}d}"
