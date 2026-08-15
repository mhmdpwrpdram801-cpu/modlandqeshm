"""Counting a dictation as the app actually performs one.

``test_stats.py`` proves the store. What matters here is the one judgement the
app makes on its own: was this dictation *edited*? Get that wrong and the number
the whole feature exists to report is quietly false — and a false measurement is
worse than none, because it gets believed.
"""

from __future__ import annotations

import pytest

from mlqvoice import inject
from mlqvoice.text import stats as usage


@pytest.fixture
def app(make_app, monkeypatch, tmp_path):
    voice = make_app()
    monkeypatch.setattr("mlqvoice.app.stats_file", lambda: tmp_path / "stats.json")
    monkeypatch.setattr(inject, "insert", lambda *a, **k: None)
    return voice


def stored(tmp_path):
    return usage.load(tmp_path / "stats.json")


def dictate(app, heard: str) -> None:
    """One spoken chunk arriving from the recogniser."""
    app.start_recording()
    app._on_result(heard, True)


class TestEditedOrNot:
    def test_inserting_untouched_text_counts_as_clean(self, app, tmp_path):
        dictate(app, "کامیت کن")
        app._insert(app.overlay.text())
        data = stored(tmp_path)
        assert data.dictations == 1
        assert data.edited == 0

    def test_changing_the_text_first_counts_as_edited(self, app, tmp_path):
        dictate(app, "کامیت کن")
        app._insert("چیزِ دیگری کاملاً")
        assert stored(tmp_path).edited == 1

    def test_rewrapping_whitespace_is_not_an_edit(self, app, tmp_path):
        # Otherwise every multi-line dictation would read as a correction and
        # the clean rate would sag for no reason at all.
        dictate(app, "کامیت کن")
        app._insert("  " + app.overlay.text().replace(" ", "  ") + "\n")
        assert stored(tmp_path).edited == 0

    def test_a_one_word_fix_still_counts(self, app, tmp_path):
        dictate(app, "کامیت کن")
        app._insert(app.overlay.text() + " دیگر")
        assert stored(tmp_path).edited == 1


class TestWhatGetsCounted:
    def test_words_are_counted_from_what_was_inserted(self, app, tmp_path):
        dictate(app, "کامیت کن")
        app._insert("یک دو سه چهار")
        assert stored(tmp_path).words == 4

    def test_dictionary_hits_are_recorded(self, app, tmp_path):
        dictate(app, "کامیت کن نقطه")
        app._insert(app.overlay.text())
        assert stored(tmp_path).terms.get("commit") == 1

    def test_interim_guesses_do_not_inflate_the_hit_count(self, app, tmp_path):
        # Chrome rewrites interim text continuously; counting it would report one
        # sentence as a dozen uses of the same entry.
        app.start_recording()
        for _ in range(5):
            app._on_result("کامیت", False)
        app._on_result("کامیت کن", True)
        app._insert(app.overlay.text())
        assert stored(tmp_path).terms.get("commit") == 1

    def test_a_failed_insert_is_not_counted(self, app, tmp_path, monkeypatch):
        # Nothing reached the target window, so nothing was dictated as far as
        # the tally is concerned.
        def boom(*_a, **_k):
            raise inject.InjectError("فوکوس نگرفت")

        monkeypatch.setattr(inject, "insert", boom)
        dictate(app, "کامیت کن")
        app._insert(app.overlay.text())
        assert stored(tmp_path).dictations == 0

    def test_each_session_starts_from_a_clean_slate(self, app, tmp_path):
        dictate(app, "کامیت کن")
        app._insert(app.overlay.text())
        app.overlay.dismiss()
        dictate(app, "مرج کن")
        app._insert(app.overlay.text())
        data = stored(tmp_path)
        assert data.dictations == 2
        # One use each, not one and then two: the hit list is cleared per session.
        assert data.terms == {"commit": 1, "merge": 1}


class TestSwitchedOff:
    def test_nothing_is_written_when_the_setting_is_off(self, make_app, monkeypatch, tmp_path):
        voice = make_app(stats=False)
        monkeypatch.setattr("mlqvoice.app.stats_file", lambda: tmp_path / "stats.json")
        monkeypatch.setattr(inject, "insert", lambda *a, **k: None)
        dictate(voice, "کامیت کن")
        voice._insert(voice.overlay.text())
        assert not (tmp_path / "stats.json").exists()


class TestNeverFatal:
    def test_an_unwritable_file_does_not_lose_the_dictation(self, app, monkeypatch):
        # The text has already reached the target window by this point. Losing
        # the count is nothing; raising here would be everything.
        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(usage, "record", boom)
        dictate(app, "کامیت کن")
        app._insert(app.overlay.text())  # must not raise
