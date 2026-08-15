"""Learning entries from the user's own corrections.

The one source of dictionary entries that is not a guess: the gap between what
the recogniser said and what the user actually kept.
"""

import json

import pytest

from mlqvoice.text import build_lexicon, transform
from mlqvoice.text.learning import (
    MAX_SPAN,
    Suggestion,
    as_dictionary,
    load,
    merge,
    record,
    save,
    suggest,
)


@pytest.fixture(scope="module")
def lex():
    return build_lexicon()


class TestSuggest:
    def test_a_word_the_dictionary_missed_becomes_a_suggestion(self, lex):
        # "زوستند" is nothing; the user rewrote it as the tool they meant.
        out = suggest("زوستند رو اجرا کن", "zustand رو اجرا کن", lex)
        assert [(s.spoken, s.replacement) for s in out] == [("زوستند", "zustand")]

    def test_a_multi_word_correction(self, lex):
        out = suggest("سرور ساید رندرینگ", "SSR", lex)
        assert out and out[0].replacement == "SSR"

    def test_nothing_is_learned_when_the_user_kept_it_as_is(self, lex):
        assert suggest("کامیت کن", transform("کامیت کن", lex), lex) == []

    def test_a_rule_that_already_does_the_job_is_not_re_suggested(self, lex):
        # The pipeline turns this into exactly what the user inserted, so the
        # difference is not evidence of a missing entry.
        assert suggest("کامیت کن", "commit کن", lex) == []

    def test_a_wrong_existing_rule_is_learnable(self, lex):
        # The user said "روت" and wanted `root`, but the glossary emits `route`.
        out = suggest("روت رو عوض کن", "root رو عوض کن", lex)
        assert [(s.spoken, s.replacement) for s in out] == [("روت", "root")]

    def test_a_whole_rewrite_is_refused(self, lex):
        out = suggest("یک دو سه چهار پنج", "totally different words entirely here", lex)
        assert all(len(s.spoken.split()) <= MAX_SPAN for s in out)

    def test_empty_input(self, lex):
        assert suggest("", "چیزی", lex) == []
        assert suggest("چیزی", "", lex) == []

    def test_pure_punctuation_is_not_a_word(self, lex):
        assert suggest("نقطه", ".", lex) == []


class TestStorage:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "learned.json"
        items = [Suggestion("الف", "alpha", 2), Suggestion("ب", "beta")]
        save(path, items)
        assert sorted(load(path), key=lambda s: s.spoken) == sorted(items, key=lambda s: s.spoken)

    def test_missing_file_is_empty(self, tmp_path):
        assert load(tmp_path / "nope.json") == []

    def test_a_corrupt_file_is_empty_rather_than_fatal(self, tmp_path):
        # Unlike the user's dictionary, nobody typed this file by hand — it must
        # never be the reason the app refuses to start.
        path = tmp_path / "learned.json"
        path.write_text("{ not json at all", encoding="utf-8")
        assert load(path) == []

    def test_rows_missing_fields_are_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "learned.json"
        path.write_text(
            json.dumps({"suggestions": [{"spoken": "الف"}, {"spoken": "ب", "replacement": "b"}]}),
            encoding="utf-8",
        )
        assert [s.replacement for s in load(path)] == ["b"]

    def test_saved_file_is_readable_persian(self, tmp_path):
        path = tmp_path / "learned.json"
        save(path, [Suggestion("کامیت", "commit")])
        assert "\\u" not in path.read_text(encoding="utf-8")


class TestMerge:
    def test_repeats_raise_the_count(self):
        merged = merge([Suggestion("الف", "a")], [Suggestion("الف", "a")])
        assert len(merged) == 1
        assert merged[0].count == 2

    def test_a_different_replacement_is_a_different_suggestion(self):
        merged = merge([Suggestion("الف", "a")], [Suggestion("الف", "b")])
        assert len(merged) == 2

    def test_new_ones_are_kept(self):
        merged = merge([Suggestion("الف", "a")], [Suggestion("ب", "b")])
        assert len(merged) == 2


class TestRecord:
    def test_records_and_counts_across_two_dictations(self, tmp_path, lex):
        path = tmp_path / "learned.json"
        record(path, "زوستند بزن", "zustand بزن", lex)
        record(path, "زوستند رو بردار", "zustand رو بردار", lex)
        stored = load(path)
        assert len(stored) == 1
        assert stored[0].count == 2

    def test_nothing_written_when_there_is_nothing_to_learn(self, tmp_path, lex):
        path = tmp_path / "learned.json"
        assert record(path, "کامیت کن", "commit کن", lex) == 0
        assert not path.exists()


class TestApply:
    def test_shapes_entries_like_the_user_dictionary(self):
        terms = as_dictionary([Suggestion("زوستند", "zustand", 3)])
        assert terms == {"zustand": ["زوستند"]}

    def test_two_spellings_of_one_term_group_together(self):
        terms = as_dictionary([Suggestion("زوستند", "zustand"), Suggestion("زواستند", "zustand")])
        assert sorted(terms["zustand"]) == sorted(["زوستند", "زواستند"])

    def test_min_count_holds_back_one_offs(self):
        items = [Suggestion("الف", "a", 1), Suggestion("ب", "b", 2)]
        assert as_dictionary(items, min_count=2) == {"b": ["ب"]}


class TestEndToEnd:
    def test_a_learned_word_actually_works_afterwards(self, tmp_path, lex):
        """The whole point: correct it once, and the app knows it next time."""
        learned = tmp_path / "learned.json"
        record(learned, "زوستند رو نصب کن", "zustand رو نصب کن", lex)

        dictionary = tmp_path / "dictionary.json"
        dictionary.write_text(
            json.dumps({"terms": as_dictionary(load(learned))}, ensure_ascii=False),
            encoding="utf-8",
        )

        taught = build_lexicon(user_file=dictionary)
        assert transform("زوستند رو نصب کن", taught) == "zustand رو نصب کن"

    def test_a_learned_word_inherits_the_phonetic_layer(self, tmp_path, lex):
        """A taught word must also cover its own respellings, not just the one
        spelling the user happened to correct that day."""
        learned = tmp_path / "learned.json"
        record(learned, "زوستند رو نصب کن", "zustand رو نصب کن", lex)

        dictionary = tmp_path / "dictionary.json"
        dictionary.write_text(
            json.dumps({"terms": as_dictionary(load(learned))}, ensure_ascii=False),
            encoding="utf-8",
        )
        taught = build_lexicon(user_file=dictionary)
        # ص and س are the same sound; the user never typed this spelling.
        assert transform("زوصتند رو نصب کن", taught) == "zustand رو نصب کن"

    def test_learning_never_overrides_a_common_persian_word(self, tmp_path, lex):
        """Even a taught entry may not hijack the sound of an everyday word."""
        dictionary = tmp_path / "dictionary.json"
        dictionary.write_text(
            json.dumps({"terms": {"sort": ["سورت"]}}, ensure_ascii=False), encoding="utf-8"
        )
        taught = build_lexicon(user_file=dictionary)
        assert transform("صورت", taught) == "صورت"
