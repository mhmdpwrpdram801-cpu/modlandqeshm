"""Usage counting.

The point of this file is a question ``learned.json`` cannot answer: twelve
corrections out of *how many* dictations? Without the denominator the dictionary
can only ever be judged on feel.

The heaviest tests here are not about arithmetic. They are about what must never
end up in the file — because the moment it holds a sentence somebody dictated,
"it never leaves the machine" stops being the whole answer.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice.text import stats as usage


@pytest.fixture
def path(tmp_path):
    return tmp_path / "stats.json"


class TestPrivacy:
    """The promise printed at the bottom of the report, enforced."""

    def test_the_dictated_text_is_not_stored(self, path):
        usage.record(path, words=6, edited=True, terms=["commit"], today="2026-08-15")
        raw = path.read_text(encoding="utf-8")
        assert "commit" in raw  # our own dictionary output — that much is intended
        for spoken in ("سلام", "رمز", "قرارداد"):
            assert spoken not in raw

    def test_only_counts_and_our_own_terms_are_written(self, path):
        usage.record(path, words=6, edited=False, terms=["commit"], today="2026-08-15")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == {"version", "note", "days", "terms"}
        assert set(data["days"]["2026-08-15"]) == {"dictations", "edited", "words", "seconds"}
        assert all(isinstance(v, int) for v in data["days"]["2026-08-15"].values())
        assert all(isinstance(v, int) for v in data["terms"].values())

    def test_the_note_says_so_in_the_file_itself(self, path):
        # Whoever opens this file should not have to take our word from a README.
        usage.record(path, words=1, edited=False, today="2026-08-15")
        assert "هیچ متنی" in json.loads(path.read_text(encoding="utf-8"))["note"]


class TestCounting:
    def test_a_clean_dictation(self, path):
        usage.record(path, words=10, edited=False, today="2026-08-15")
        data = usage.load(path)
        assert (data.dictations, data.edited, data.words) == (1, 0, 10)

    def test_an_edited_one(self, path):
        usage.record(path, words=10, edited=True, today="2026-08-15")
        assert usage.load(path).edited == 1

    def test_totals_add_up_across_days(self, path):
        usage.record(path, words=10, edited=False, today="2026-08-14")
        usage.record(path, words=5, edited=True, today="2026-08-15")
        data = usage.load(path)
        assert (data.dictations, data.edited, data.words) == (2, 1, 15)
        assert len(data.days) == 2

    def test_terms_accumulate(self, path):
        usage.record(path, words=3, edited=False, terms=["commit", "."], today="2026-08-15")
        usage.record(path, words=3, edited=False, terms=["commit"], today="2026-08-15")
        assert usage.load(path).terms == {"commit": 2, ".": 1}

    def test_the_same_term_twice_in_one_dictation_counts_twice(self, path):
        # Saying "commit" twice in a sentence is two uses of the entry.
        usage.record(path, words=4, edited=False, terms=["commit", "commit"], today="2026-08-15")
        assert usage.load(path).terms["commit"] == 2

    def test_negative_seconds_cannot_be_recorded(self, path):
        # A clock that goes backwards must not make the words-per-minute
        # denominator negative and turn the speed into nonsense.
        usage.record(path, words=10, edited=False, seconds=-5, today="2026-08-15")
        assert usage.load(path).seconds == 0


class TestRates:
    def test_clean_rate_is_computed_by_hand_here(self, path):
        for _ in range(8):
            usage.record(path, words=5, edited=False, today="2026-08-15")
        for _ in range(2):
            usage.record(path, words=5, edited=True, today="2026-08-15")
        assert usage.load(path).clean_rate == 0.8

    def test_no_dictations_means_no_rate_rather_than_a_perfect_one(self, path):
        # 0/0 must not read as "100% clean" — that number would get quoted.
        assert usage.load(path).clean_rate is None

    def test_words_per_minute(self, path):
        usage.record(path, words=60, edited=False, seconds=60, today="2026-08-15")
        assert usage.load(path).words_per_minute == 60.0

    def test_no_time_means_no_speed(self, path):
        usage.record(path, words=60, edited=False, seconds=0, today="2026-08-15")
        assert usage.load(path).words_per_minute is None

    def test_top_terms_are_ordered_by_use(self, path):
        usage.record(path, words=1, edited=False, terms=["a", "b", "b", "c", "c", "c"], today="d")
        assert usage.load(path).top_terms(2) == [("c", 3), ("b", 2)]


def _day(n: int) -> str:
    """A sortable run of distinct ISO days, without a calendar to argue with."""
    return f"2026-{1 + n // 28:02d}-{1 + n % 28:02d}"


class TestBounds:
    def test_old_days_fall_off(self, path):
        for n in range(usage.MAX_DAYS + 20):
            usage.record(path, words=1, edited=False, today=_day(n))
        assert len(usage.load(path).days) == usage.MAX_DAYS

    def test_and_it_is_the_oldest_that_go(self, path):
        last = usage.MAX_DAYS + 4
        for n in range(last + 1):
            usage.record(path, words=1, edited=False, today=_day(n))
        days = sorted(usage.load(path).days)
        assert days[-1] == _day(last)
        assert days[0] == _day(last - usage.MAX_DAYS + 1)

    def test_terms_are_capped_keeping_the_most_used(self, path):
        terms = [f"t{n}" for n in range(usage.MAX_TERMS + 50)]
        usage.record(path, words=1, edited=False, terms=[*terms, "hot", "hot"], today="2026-08-15")
        stored = usage.load(path).terms
        assert len(stored) == usage.MAX_TERMS
        assert stored["hot"] == 2  # the busiest entry survives the cull


class TestDamagedFile:
    """Forgiving on purpose: the user never wrote this file by hand."""

    def test_broken_json_reads_as_empty(self, path):
        path.write_text("{ not json", encoding="utf-8")
        assert usage.load(path).dictations == 0

    def test_a_json_array_reads_as_empty(self, path):
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert usage.load(path).dictations == 0

    def test_a_missing_file_reads_as_empty(self, path):
        assert usage.load(path).dictations == 0

    def test_a_junk_row_is_skipped_and_the_rest_survive(self, path):
        path.write_text(
            json.dumps(
                {
                    "days": {
                        "2026-08-14": "nonsense",
                        "2026-08-15": {"dictations": 3, "words": 9},
                    },
                    "terms": {"commit": "many", "merge": 4},
                }
            ),
            encoding="utf-8",
        )
        data = usage.load(path)
        assert data.dictations == 3
        assert data.terms == {"merge": 4}

    def test_recording_over_a_damaged_file_still_works(self, path):
        path.write_text("{ broken", encoding="utf-8")
        usage.record(path, words=4, edited=False, today="2026-08-15")
        assert usage.load(path).dictations == 1
