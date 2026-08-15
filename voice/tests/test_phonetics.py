"""The sound-alike fallback.

Why it exists, measured before it was written: 63% of glossary terms carried
exactly one spelling, and a sweep of same-sounding respellings showed 98% of
them missed.  Every one of those words was already in the dictionary — the
words were not the problem, exact matching was.
"""

import pytest

from mlqvoice.text import build_lexicon, transform
from mlqvoice.text.lexicon import Entry, Lexicon
from mlqvoice.text.phonetics import MIN_KEY_LEN, phonetic_key, phrase_key


@pytest.fixture(scope="module")
def lex():
    return build_lexicon()


class TestFolding:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("کامیت", "کامیط"),  # ت / ط
            ("ریبیس", "ریبیص"),  # س / ص
            ("هاب", "حاب"),  # ه / ح
            ("باقی", "باغی"),  # ق / غ — identical in Persian
            ("آبجکت", "ابجکت"),  # آ / ا
            ("ریکوئست", "ریکوست"),  # hamza dropped
            ("روت", "رووت"),  # doubled letter
            ("ایمپورت", "امپورت"),  # initial ای / ا
        ],
    )
    def test_same_sounding_spellings_share_a_key(self, a, b):
        assert phonetic_key(a) == phonetic_key(b), f"{a} vs {b}"

    def test_genuinely_different_words_do_not(self):
        assert phonetic_key("کامیت") != phonetic_key("کلاینت")

    def test_short_words_get_no_key(self):
        # A two-letter key would collide with half the language.
        assert phonetic_key("ری") == ""
        assert len(phonetic_key("کامیت")) >= MIN_KEY_LEN


class TestPhraseKey:
    def test_length_applies_to_the_whole_phrase_not_each_word(self):
        # Regression: the per-word rule threw away every multi-word term
        # containing a short one, even when the two keys were identical.
        assert phrase_key(["ری", "بیس"]) == phrase_key(["ری", "بیص"]) != ""
        assert phrase_key(["چک", "اوت"]) != ""

    def test_a_phrase_of_only_tiny_words_is_still_refused(self):
        assert phrase_key(["ا"]) == ""


class TestFallbackMatching:
    def test_a_respelling_now_resolves(self, lex):
        assert transform("کامیط کن", lex) == "commit کن"

    def test_multi_word_respelling(self, lex):
        assert transform("چک اوط", lex) == "checkout"

    def test_exact_spelling_still_wins_over_sound(self):
        lex = Lexicon()
        lex.add("کامیت", Entry("exact-one"))
        lex.add("کامیط", Entry("exact-two"))
        # Both are exact entries; neither may be replaced by the other's sound.
        assert transform("کامیت", lex) == "exact-one"
        assert transform("کامیط", lex) == "exact-two"

    def test_unknown_words_are_left_alone(self, lex):
        assert transform("قابلمه", lex) == "قابلمه"


class TestConflictGuard:
    def test_two_terms_that_sound_alike_disable_the_key(self):
        lex = Lexicon()
        lex.add("کامیت", Entry("commit"))
        lex.add("کامیط", Entry("something-else"))
        assert lex.get_by_sound(["کامیط"]) is None
        assert lex.phonetic_conflicts

    def test_but_the_exact_lookups_survive(self):
        lex = Lexicon()
        lex.add("کامیت", Entry("commit"))
        lex.add("کامیط", Entry("something-else"))
        assert lex.get("کامیت").text == "commit"
        assert lex.get("کامیط").text == "something-else"

    def test_the_same_term_under_two_spellings_is_not_a_conflict(self):
        lex = Lexicon()
        lex.add("ریکوئست", Entry("request"))
        lex.add("ریکوست", Entry("request"))
        assert lex.get_by_sound(["ریکوست"]).text == "request"
        assert not lex.phonetic_conflicts


class TestOrdinaryPersianIsSafe:
    def test_face_does_not_become_sort(self, lex):
        # The bug this guard exists for: folding ص onto س made «صورت» a `sort`.
        assert transform("صورت", lex) == "صورت"

    def test_a_word_a_term_deliberately_claims_still_works(self, lex):
        # «درصد» really is how you say "%", so the guard must not block it.
        assert transform("نود درصد", lex) == "نود%"

    @pytest.mark.parametrize(
        "sentence",
        [
            "امروز رفتم مغازه و یه پیراهن آبی خریدم",
            "قیمت این جنس نود هزار تومان است",
            "سمت راست کوچه سومی خانه ماست",
            "صورت حساب رو برام بفرست",
            "هوا سرد شد باید کت بپوشم",
        ],
    )
    def test_plain_persian_passes_through_untouched(self, lex, sentence):
        assert transform(sentence, lex) == sentence

    def test_the_guard_list_ships(self):
        import json

        from mlqvoice.text.lexicon import builtin_path

        data = json.loads(builtin_path("fa_common.json").read_text(encoding="utf-8"))
        assert len(data["words"]) > 300


class TestCoverage:
    def test_the_glossary_grew(self, lex):
        assert len(lex) > 400

    def test_the_sound_index_is_populated(self, lex):
        assert lex.phonetic_size > 300

    def test_no_builtin_spoken_form_is_a_bare_ambiguous_persian_word(self, lex):
        for word in ("پول", "نود", "راست", "گو", "ویو", "تر", "کار", "شارژ", "صورت"):
            assert lex.get(word) is None, f"{word} must not be a standalone entry"

    def test_gaf_and_ghain_stay_apart(self):
        # گ and غ are different sounds; folding them would be over-eager.
        # (My first version of the ق/غ test used this pair by mistake.)
        assert phonetic_key("لاگین") != phonetic_key("لاغین")
