"""Jalali conversion.

Not a nicety: this project has already shipped "2026-08-06" next to "۱۴۰۵/۰۵" on
three screens, and the rule that came out of it is that a raw ISO date never
reaches the user. Storage stays ISO; only the way out is converted.
"""

from datetime import date

import pytest

from mlqvoice.dates import format_iso, format_jalali, to_jalali


class TestKnownDates:
    @pytest.mark.parametrize(
        ("gregorian", "jalali"),
        [
            # This project's own record: guidelines/FULLSTACK.md dates version
            # 2026.08.9 as "۲۳ مرداد ۱۴۰۵ (2026-08-14)".
            ((2026, 8, 14), (1405, 5, 23)),
            # Nowruz — the year boundary, where an off-by-one shows up loudest.
            ((2026, 3, 21), (1405, 1, 1)),
            ((2025, 3, 21), (1404, 1, 1)),
            ((2024, 3, 20), (1403, 1, 1)),
            # The day before each is the last of Esfand.
            ((2026, 3, 20), (1404, 12, 29)),
            ((2024, 3, 19), (1402, 12, 29)),
            # Mid-year, both halves of the calendar (31-day and 30-day months).
            ((2026, 1, 1), (1404, 10, 11)),
            ((2026, 6, 22), (1405, 4, 1)),
            ((2026, 9, 23), (1405, 7, 1)),
        ],
    )
    def test_conversion(self, gregorian, jalali):
        assert to_jalali(date(*gregorian)) == jalali


class TestConsistency:
    def test_every_day_of_a_year_maps_to_a_valid_jalali_date(self):
        day = date(2026, 1, 1)
        seen = []
        while day.year == 2026:
            year, month, dom = to_jalali(day)
            assert 1 <= month <= 12, day
            assert 1 <= dom <= 31, day
            assert dom <= (31 if month <= 6 else 30), f"{day} -> {year}/{month}/{dom}"
            seen.append((year, month, dom))
            day = date.fromordinal(day.toordinal() + 1)
        assert len(set(seen)) == len(seen), "دو روزِ میلادی به یک روزِ جلالی افتادند"

    def test_consecutive_days_stay_consecutive(self):
        # An arithmetic slip shows up as a jump or a repeat, not as a bad value.
        first = to_jalali(date(2026, 3, 20))
        second = to_jalali(date(2026, 3, 21))
        assert first == (1404, 12, 29)
        assert second == (1405, 1, 1)


class TestFormatting:
    def test_persian_digits_by_default(self):
        assert format_jalali(date(2026, 8, 14)) == "۱۴۰۵/۰۵/۲۳"

    def test_latin_digits_on_request(self):
        assert format_jalali(date(2026, 8, 14), digits="latin") == "1405/05/23"

    def test_from_a_stored_iso_string(self):
        assert format_iso("2026-08-14") == "۱۴۰۵/۰۵/۲۳"

    def test_a_junk_row_is_shown_as_is_rather_than_crashing_the_report(self):
        # Display code reading a file the user never wrote: one bad row must not
        # take the whole report down.
        assert format_iso("nonsense") == "nonsense"

    def test_no_iso_date_survives_formatting(self):
        # The rule this module exists for.
        assert "-" not in format_iso("2026-08-14")
