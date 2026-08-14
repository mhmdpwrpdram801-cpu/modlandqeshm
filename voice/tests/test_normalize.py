from mlqvoice.text.normalize import ZWNJ, apply_zwnj, normalize, strip_zwnj


class TestLetters:
    def test_arabic_kaf_and_yeh_become_persian(self):
        # What Google's fa-IR recogniser hands back is not always Persian-spelled.
        assert normalize("برنامه نويسي كردن") == "برنامه نویسی کردن"

    def test_teh_marbuta_and_hamza_alef(self):
        assert normalize("مدرسة أول") == "مدرسه اول"

    def test_harakat_and_tatweel_are_dropped(self):
        assert normalize("کِتـ__ـاب".replace("__", "")) == "کتاب"


class TestDigits:
    def test_latin_is_the_default_because_this_is_for_code(self):
        assert normalize("پورت ۸۰۸۰") == "پورت 8080"

    def test_arabic_indic_digits_survive_the_harakat_strip(self):
        # Regression: the diacritic range used to cover U+0660..U+0669 and ate these.
        assert normalize("٠١٢٣٤٥٦٧٨٩") == "0123456789"

    def test_persian_mode(self):
        assert normalize("port 8080", digits="fa") == "port ۸۰۸۰"

    def test_keep_mode_leaves_both_alone(self):
        assert normalize("۸ and 8", digits="keep") == "۸ and 8"

    def test_unknown_mode_is_rejected_not_guessed(self):
        try:
            normalize("x", digits="roman")
        except ValueError as exc:
            assert "roman" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestZwnj:
    def test_mi_prefix_binds_to_its_verb(self):
        assert normalize("می روم") == f"می{ZWNJ}روم"

    def test_nemi_prefix(self):
        assert normalize("نمی خواهم") == f"نمی{ZWNJ}خواهم"

    def test_plural_suffix_binds_backwards(self):
        assert normalize("کتاب ها") == f"کتاب{ZWNJ}ها"

    def test_comparative_suffixes(self):
        assert normalize("بزرگ ترین") == f"بزرگ{ZWNJ}ترین"

    def test_short_word_does_not_take_a_suffix(self):
        # "تر" alone is a Persian word (wet); gluing it to every 2-letter token
        # would corrupt real sentences, so the rule needs 3+ letters before it.
        assert normalize("آب تر") == "آب تر"

    def test_stray_zwnj_next_to_a_space_is_cleaned(self):
        assert normalize(f"سلام {ZWNJ} دنیا") == f"سلام{ZWNJ}دنیا"

    def test_doubled_zwnj_collapses(self):
        assert normalize(f"می{ZWNJ}{ZWNJ}روم") == f"می{ZWNJ}روم"

    def test_disabled(self):
        assert normalize("می روم", zwnj=False) == "می روم"

    def test_apply_zwnj_is_idempotent(self):
        once = apply_zwnj("می روم و کتاب ها")
        assert apply_zwnj(once) == once

    def test_strip_zwnj_round_trip(self):
        assert strip_zwnj(normalize("می روم")) == "میروم"


class TestWhitespace:
    def test_runs_collapse_and_edges_trim(self):
        assert normalize("  سلام    دنیا  ") == "سلام دنیا"

    def test_newlines_survive(self):
        assert normalize("سلام  \n   دنیا") == "سلام\nدنیا"

    def test_empty(self):
        assert normalize("   ") == ""
