"""Finglish to Persian.

Transliteration by sound, which Persian orthography makes lossy: short vowels
are not written, and Finglish cannot say whether a ``t`` is ت or ط.  The rules
handle what they can and a vocabulary arbitrates the rest.

The part that matters most here is not accuracy — it is that this never damages
what is already correct.  It runs only when asked, and steps over code and the
glossary's own output.
"""

import json

import pytest

from mlqvoice.text import build_lexicon, transform
from mlqvoice.text.finglish import (
    convert,
    convert_word,
    exceptions,
    has_latin,
    known_by_sound,
    known_words,
)


@pytest.fixture(scope="module")
def lex():
    return build_lexicon()


@pytest.fixture(scope="module")
def skip(lex):
    return lex.outputs()


class TestConsonants:
    @pytest.mark.parametrize(
        ("finglish", "persian"),
        [
            ("shekar", "شکر"),  # sh
            ("chap", "چپ"),  # ch
            ("kafsh", "کفش"),  # k + sh
            ("barf", "برف"),  # short vowel vanishes
            ("garm", "گرم"),
            ("sard", "سرد"),
        ],
    )
    def test_rules(self, finglish, persian):
        assert convert_word(finglish) == persian


class TestVowels:
    def test_doubled_a_is_the_long_one(self):
        assert convert_word("ketaab") == "کتاب"

    def test_a_single_a_can_still_be_long_if_the_word_is_known(self):
        # The spelling does not say; the vocabulary decides.
        assert convert_word("ketab") == "کتاب"

    def test_a_single_a_stays_short_when_that_is_the_real_word(self):
        assert convert_word("barf") == "برف"

    def test_initial_vowel_gets_an_alef(self):
        assert convert_word("abr") == "ابر"

    def test_final_e_is_the_silent_he(self):
        assert convert_word("bache") == "بچه"

    def test_long_oo(self):
        assert convert_word("goosht") == "گوشت"


class TestArbiter:
    def test_the_vocabulary_settles_letters_finglish_cannot_express(self):
        # "t" could be ت or ط; only the word list knows قطار takes ط.
        assert convert_word("ghatar") == "قطار"

    def test_and_the_z_family(self):
        assert convert_word("gozashtam") == "گذاشتم"

    def test_an_unknown_word_falls_back_to_the_plain_rule(self):
        # Nothing in the vocabulary matches, so the rule's own answer stands
        # rather than some far-fetched candidate.
        assert convert_word("blorgzim") == "بلرگزیم"

    def test_the_vocabulary_is_a_different_file_from_the_phonetic_guard(self):
        # The guard list is a blocklist and costs recall when it grows; this one
        # only helps, so it is allowed to be much bigger.
        from mlqvoice.text.lexicon import builtin_path

        guard = json.loads(builtin_path("fa_common.json").read_text(encoding="utf-8"))["words"]
        assert len(known_words()) > len(guard) * 2

    def test_sound_index_drops_ambiguous_keys(self):
        # Two words that fold to one key would be a coin flip, so neither is used.
        assert all(v for v in known_by_sound().values())


class TestCodeIsUntouched:
    @pytest.mark.parametrize(
        "token",
        [
            "user_id",
            "app.py",
            "getUserName",
            "HTTP/1.1",
            "x=5",
            "foo()",
            "README.md",
            "utf-8",
            "v2",
        ],
    )
    def test_code_shaped_tokens_survive(self, token, skip):
        assert convert(token, skip=skip) == token


class TestGlossaryOutputIsUntouched:
    @pytest.mark.parametrize("term", ["commit", "database", "request", "React", "function"])
    def test_the_glossary_own_words_survive(self, term, skip):
        assert convert(term, skip=skip) == term

    def test_and_this_is_why_the_skip_list_exists(self):
        # Without it the conversion runs and produces nonsense — which is
        # exactly what would happen if this were ever applied automatically.
        assert convert("commit") != "commit"

    def test_a_mixed_sentence_converts_only_the_finglish(self, skip):
        assert convert("in commit ro push kon", skip=skip) == "این commit رو push کن"


class TestSentences:
    @pytest.mark.parametrize(
        ("finglish", "persian"),
        [
            ("salam chetori", "سلام چطوری"),
            ("man ketab ro gozashtam rooye miz", "من کتاب رو گذاشتم روی میز"),
            ("farda miam sherkat", "فردا میام شرکت"),
        ],
    )
    def test_whole_sentences(self, finglish, persian):
        assert convert(finglish) == persian

    def test_persian_input_is_left_alone(self):
        assert convert("سلام چطوری") == "سلام چطوری"

    def test_spacing_is_preserved(self):
        assert convert("salam   chetori") == "سلام   چطوری"


class TestHasLatin:
    def test_detects_something_to_convert(self):
        assert has_latin("salam")
        assert has_latin("سلام salam")

    def test_pure_persian_has_nothing(self):
        assert not has_latin("سلام چطوری")
        assert not has_latin("۱۲۳ ۴۵۶")


class TestExceptions:
    def test_the_table_ships_and_is_not_trivial(self):
        assert len(exceptions()) > 150

    def test_an_irregular_verb_the_rules_cannot_reach(self):
        # خواندم has a silent waw that Finglish simply does not write.
        assert convert_word("khandam") == "خواندم"

    def test_every_exception_value_is_persian(self):
        for finglish, persian in exceptions().items():
            assert not persian.isascii(), f"{finglish} maps to non-Persian {persian!r}"


class TestNeverAutomatic:
    def test_the_speech_pipeline_does_not_transliterate(self, lex):
        """The guarantee: dictating still produces Latin tech terms."""
        assert transform("کامیت کن", lex) == "commit کن"
