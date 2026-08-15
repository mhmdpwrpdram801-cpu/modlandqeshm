"""Jalali dates, for anything a Persian speaker has to read.

The stats file stores ISO dates because they sort, compare and survive a
timezone argument. But an ISO date must never reach the user's eyes: this
project has already been bitten by "2026-08-06" appearing next to "۱۴۰۵/۰۵" in
three different screens, and a date the reader has to convert in their head is
worse than no date.

So: ISO on disk, Jalali on the way out. The conversion is about twenty lines,
which is well under the bar for taking on a dependency.
"""

from __future__ import annotations

from datetime import date

from .text.normalize import to_persian_digits

#: Days elapsed before the first of each Gregorian month, in a non-leap year.
_MONTH_START = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)

MONTH_NAMES = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def to_jalali(value: date) -> tuple[int, int, int]:
    """Gregorian date -> ``(year, month, day)`` in the Jalali calendar."""
    days = (
        365 * (value.year - 1600)
        + (value.year - 1600 + 3) // 4
        - (value.year - 1600 + 99) // 100
        + (value.year - 1600 + 399) // 400
        + _MONTH_START[value.month - 1]
        + value.day
        - 1
    )
    if value.month > 2 and _is_leap(value.year):
        days += 1
    days -= 79  # 1600-03-21 is the Jalali epoch this arithmetic is built around

    cycles, days = divmod(days, 12053)  # a 33-year cycle is exactly 12053 days
    year = 979 + 33 * cycles + 4 * (days // 1461)
    days %= 1461
    if days >= 366:
        year += (days - 1) // 365
        days = (days - 1) % 365
    # The first six months have 31 days, the next five have 30.
    if days < 186:
        month, day = 1 + days // 31, 1 + days % 31
    else:
        month, day = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return year, month, day


def format_jalali(value: date, *, digits: str = "fa") -> str:
    """``۱۴۰۵/۰۵/۲۴`` — the shape used everywhere else in this project."""
    year, month, day = to_jalali(value)
    text = f"{year:04d}/{month:02d}/{day:02d}"
    return to_persian_digits(text) if digits == "fa" else text


def format_iso(iso: str, *, digits: str = "fa") -> str:
    """Same, from a stored ``YYYY-MM-DD`` string.

    An unparseable value is handed back untouched rather than raising: this is
    display code reading a file the user never wrote, and one bad row must not
    take the whole report down.
    """
    try:
        return format_jalali(date.fromisoformat(iso), digits=digits)
    except ValueError:
        return iso
