import json

import pytest

from mlqvoice.text.lexicon import Entry, Lexicon, build_lexicon, spoken_key
from mlqvoice.text.normalize import ZWNJ
from mlqvoice.text.pipeline import Options, render, transform


@pytest.fixture(scope="module")
def lex():
    return build_lexicon()


def t(text, lex=None, **kw):
    return transform(text, lex, Options(**kw))


class TestGlossary:
    def test_single_term(self, lex):
        assert t("کامیت", lex) == "commit"

    def test_term_inside_a_persian_sentence(self, lex):
        assert t("این تغییر رو کامیت کن", lex) == "این تغییر رو commit کن"

    def test_longest_phrase_wins(self, lex):
        # "پول" on its own is money, not `pull`; only the two-word phrase maps.
        assert t("پول ریکوئست", lex) == "pull request"

    def test_bare_pool_stays_persian_money(self, lex):
        assert t("پول ندارم", lex) == "پول ندارم"

    def test_bare_nod_stays_the_number_ninety(self, lex):
        # "%" hugs the number it follows, so no space — but "نود" stays Persian.
        assert t("نود درصد", lex) == "نود%"

    def test_bare_rast_stays_the_persian_word(self, lex):
        assert t("سمت راست", lex) == "سمت راست"

    def test_zwnj_spelling_matches_the_spaced_one(self, lex):
        assert t(f"ری{ZWNJ}اکت", lex) == "React"
        assert t("ری اکت", lex) == "React"

    def test_arabic_spelling_still_matches(self, lex):
        # Recogniser output with Arabic yeh must still hit the glossary.
        assert t("كوئري", lex) == "query"

    def test_can_be_switched_off(self):
        assert t("کامیت", None, glossary=False) == "کامیت"


class TestPunctuation:
    def test_period_attaches_left(self, lex):
        assert t("سلام دنیا نقطه", lex) == "سلام دنیا."

    def test_comma_then_more_words(self, lex):
        assert t("اول ویرگول دوم", lex) == "اول، دوم"

    def test_brackets_hug_their_content(self, lex):
        assert t("تابع پرانتز باز ایکس پرانتز بسته", lex) == "تابع (ایکس)"

    def test_operator_is_spaced_on_both_sides(self, lex):
        assert t("ایکس مساوی پنج", lex) == "ایکس = پنج"

    def test_underscore_glues_both_sides(self, lex):
        assert t("یوزر آندرلاین آی دی", lex) == "یوزر_آی دی"

    def test_newline(self, lex):
        assert t("اول خط جدید دوم", lex) == "اول\nدوم"

    def test_no_space_leaks_around_a_newline(self, lex):
        assert t("اول نقطه خط جدید دوم", lex) == "اول.\nدوم"

    def test_two_left_symbols_in_a_row(self, lex):
        assert t("ایکس پرانتز بسته نقطه", lex) == "ایکس)."

    def test_can_be_switched_off(self):
        assert t("سلام نقطه", None, punctuation=False) == "سلام نقطه"


class TestCombined:
    def test_a_realistic_dictated_line(self, lex):
        said = "یه فانکشن بساز پرانتز باز پارامتر پرانتز بسته که ریکوئست رو بفرسته نقطه"
        assert t(said, lex) == "یه function بساز (parameter) که request رو بفرسته."

    def test_digits_and_glossary_together(self, lex):
        assert t("پورت ۸۰۸۰ رو روی لوکال هاست باز کن", lex) == "port 8080 رو روی localhost باز کن"

    def test_empty_input(self, lex):
        assert t("", lex) == ""
        assert t("    ", lex) == ""


class TestUserDictionary:
    def test_user_entry_is_added(self, tmp_path):
        f = tmp_path / "dictionary.json"
        f.write_text(json.dumps({"terms": {"kubectl": ["کیوب سی تی ال"]}}), encoding="utf-8")
        lex = build_lexicon(user_file=f)
        assert t("کیوب سی تی ال رو بزن", lex) == "kubectl رو بزن"

    def test_user_entry_overrides_the_builtin(self, tmp_path):
        f = tmp_path / "dictionary.json"
        f.write_text(json.dumps({"terms": {"کامیت": ["کامیت"]}}), encoding="utf-8")
        lex = build_lexicon(user_file=f)
        assert t("کامیت", lex) == "کامیت"

    def test_user_symbols(self, tmp_path):
        f = tmp_path / "dictionary.json"
        f.write_text(
            json.dumps({"symbols": [{"say": ["تیلدا"], "text": "~", "attach": "both"}]}),
            encoding="utf-8",
        )
        lex = build_lexicon(user_file=f)
        assert t("تیلدا اسلش پروژه", lex) == "~/پروژه"

    def test_missing_user_file_is_silent(self, tmp_path):
        lex = build_lexicon(user_file=tmp_path / "nope.json")
        assert t("کامیت", lex) == "commit"

    def test_broken_user_file_raises_rather_than_being_ignored(self, tmp_path):
        f = tmp_path / "dictionary.json"
        f.write_text("{ this is not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            build_lexicon(user_file=f)


class TestLexicon:
    def test_spoken_key_is_zwnj_and_spacing_insensitive(self):
        assert spoken_key(f"ری{ZWNJ}اکت") == spoken_key("ری اکت") == "ریاکت"

    def test_max_phrase_len_tracks_the_longest_entry(self):
        lex = Lexicon()
        assert lex.max_phrase_len == 3  # the floor, so joined entries still match
        lex.add("اچ تی تی پی اس", Entry("HTTPS"))
        assert lex.max_phrase_len == 5

    def test_a_joined_entry_matches_speech_that_came_back_split(self):
        lex = Lexicon()
        lex.add("گیتهاب", Entry("GitHub"))
        assert transform("گیت هاب", lex) == "GitHub"

    def test_empty_phrase_is_ignored(self):
        lex = Lexicon()
        lex.add("   ", Entry("x"))
        assert len(lex) == 0

    def test_bad_attach_kind_is_rejected(self):
        with pytest.raises(ValueError, match="attach"):
            Entry("x", attach="sideways")

    def test_builtin_lexicon_is_not_trivially_small(self, lex):
        # Guards against a data file that silently failed to load.
        assert len(lex) > 200

    def test_no_builtin_spoken_form_is_a_bare_ambiguous_persian_word(self, lex):
        # These are ordinary Persian words; mapping them would corrupt normal
        # sentences. Each may only appear as part of a longer phrase.
        for word in ("پول", "نود", "راست", "گو", "ویو", "تر", "کار", "شارژ"):
            assert lex.get(word) is None, f"{word} must not be a standalone entry"


class TestRender:
    def test_empty(self):
        assert render([]) == ""

    def test_single_word(self):
        assert render([Entry("سلام")]) == "سلام"
